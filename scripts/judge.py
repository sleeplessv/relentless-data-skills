#!/usr/bin/env python3
"""Judge one version of a replay ticket. `--help` gives the two tests and the files the judge reads and writes."""
from __future__ import annotations

import fcntl
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # importing the siblings would otherwise write scripts/__pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
import draw  # noqa: E402  (a sibling script, not an installed package)
import scan  # noqa: E402

GENERATION_ONE = "generation-one"
EXIT_NO_VERDICT = 3
REVIEW_TIMEOUT = draw.CHECK_TIMEOUT
# One requirements review on the strong class, headless, that can read the version's files and change nothing.
# --safe-mode loads no CLAUDE.md, skill, plugin, hook, MCP server or auto memory; --tools leaves only the
# read tools; --permission-prompts none denies whatever would ask; no session log is kept.
CLAUDE = ["claude", "-p", "--model", "opus", "--effort", "medium", "--output-format", "json", "--safe-mode",
          "--strict-mcp-config", "--tools", "Read,Grep,Glob", "--permission-prompts", "none",
          "--no-session-persistence"]
ANSWERS = ("met", "not met", "cannot tell")
REQUIREMENT_LINE = re.compile(r"R([1-9]\d*): (met|not met|cannot tell)")
FINDING_LINE = re.compile(r"F([1-9]\d*): ([^\s:][^:]*):([1-9]\d*): (.*?) ?Evidence: (.*)")
VERSION_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")

HELP = f"""\
Judge one version of a replay ticket by the two tests every version gets.

Usage: python3 scripts/judge.py <label>-<ticket> {GENERATION_ONE}
       python3 scripts/judge.py <label>-<ticket> <version> --commit <commit> --from <repo>

A version is a name and a commit. {GENERATION_ONE} is the commit first marked ready
that the replay set records for the ticket, read from the repo on GitHub. Any
other name is a version the caller made, such as a replay: its commit is read
from <repo>, a git repo on this machine that holds it, such as the replay's
clone. A name is lower-case letters, digits and . _ -.

Test 1: in a clean checkout of the version's commit the judge runs the repo's
setup command, where it has one, and then its check command, each with sh. It
passes when the check exits 0. A step that runs for more than {draw.CHECK_TIMEOUT // 60} minutes
is stopped and fails.

Test 2: one requirements review, headless on Claude Code, on Opus at medium
effort. The reviewer is given the ticket's title and body, its requirements
and the diff from the version's starting commit: from the merge base of the
commit before the merged PR and the version's commit. It starts in a folder
outside any git repo that holds the version's files and no git history, so it
sees no branch name, commit message or author, and it can read those files
but change nothing. The requirements are the items under "## Acceptance
criteria", "## Acceptance" or "## Done when", numbered R1, R2 and on in the
order written. The reviewer answers in fixed lines only:

  R<n>: met | not met | cannot tell
  F<n>: <file>:<line>: <what is wrong> Evidence: <evidence>

A finding is proven unless its evidence is "none". Test 2 passes when every
requirement is met and no finding is proven: "not met" and "cannot tell" fail
it. An answer with any other line, or without one line for each requirement,
gives no verdict, as does a review that fails or runs for more than
{REVIEW_TIMEOUT // 60} minutes.

The version is right first time when both tests pass. The judge checks that
the version's commit and its tree are the same after the review as before it.

Every file is in the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver). The judge reads replay-set-<n>.json, the set that
holds the ticket, project-labels.json and repos.json, and writes:

  verdicts.jsonl        One JSON line per ticket and version, replaced when
                        the version is judged again: label, ticket, version,
                        commit, base_commit, judged_at, check {{passed,
                        reason, output}}, review {{passed, reason,
                        requirements, findings, proven, lines}} and
                        right_first_time: true, false, or null for no
                        verdict. Paths are relative to the machine directory.
  judged/<label>-<ticket>-<version>/
                        check.txt, the output of setup and check; prompt.txt,
                        what the reviewer was given; review.txt, the
                        review's answer as it came.
  judge-work/           Clones and checkouts, removed when the judge ends.

Exit 0: a verdict was recorded. Exit 1: an error; nothing was recorded. Exit 2:
bad usage. Exit {EXIT_NO_VERDICT}: the review gave no verdict, recorded as null."""

PROMPT = """\
Review a change against the requirements of the ticket it was written for.

The working folder holds the files as they are after the change. Read them as you need. You cannot run commands \
or change files.

<ticket>
{title}

{body}
</ticket>

The requirements, numbered in the order the ticket gives them:

{requirements}

The change, as a diff from the commit it started from:

<diff>
{diff}</diff>

Answer with these lines and nothing else: no heading, no code fence, no other text.

- One line for each requirement, in order: `R<n>: met`, `R<n>: not met` or `R<n>: cannot tell`.
- One line for each finding, numbered F1, F2 and on: `F<n>: <file>:<line>: <what is wrong> Evidence: <evidence>`. \
The evidence shows the finding failing, or names the line and the requirement it breaks. Write `Evidence: none` \
when you have neither.
- Give a finding for each requirement that is not met.
- With every requirement met and nothing wrong, the answer is the requirement lines alone.
"""


class JudgeError(Exception):
    """Ends the judge with exit 1 and nothing recorded."""


class Checkout(draw.Draw):
    """The draw's clean checkout and its run of setup and check, in the judge's own work folder."""

    def __init__(self, work: Path) -> None:
        self.work = work


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(cwd), *args], text=True, capture_output=True)


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        raise JudgeError(f"{path} cannot be read as JSON.")


def find_ticket(state: Path, label: str, number: int) -> dict:
    for path in sorted(state.glob("replay-set-*.json")):
        for entry in read_json(path).get("tickets", []):
            if (entry.get("label"), entry.get("ticket")) == (label, number):
                return entry
    raise JudgeError(f"no replay set in {state} holds ticket {label}-{number}.")


def repo_entry(state: Path, label: str) -> dict:
    repo = read_json(state / "project-labels.json").get(label)
    entry = next((entry for entry in read_json(state / "repos.json")
                  if isinstance(entry, dict) and str(entry.get("repo", "")).lower() == str(repo).lower()), None)
    if not repo or not entry or not entry.get("check"):
        raise JudgeError(f"project {label} has no repo with a check command in repos.json.")
    return entry


def tree_of(commit: str, repo: Path) -> str:
    found = git("rev-parse", "--verify", "--quiet", f"{commit}^{{tree}}", cwd=repo)
    return found.stdout.strip()


def fetch(clone: Path, commit: str) -> str:
    """The commit's full name in the clone, fetched from origin when the clone lacks it."""
    for attempt in range(2):
        found = git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}", cwd=clone).stdout.strip()
        if found:
            return found
        if not attempt:
            git("fetch", "--quiet", "origin", commit, cwd=clone)
    raise JudgeError(f"commit {commit} is not in the version's repo.")


def export(clone: Path, commit: str, folder: Path) -> None:
    """The commit's files, with no git history, in `folder`."""
    archive = subprocess.run(["git", "-C", str(clone), "archive", "--format=tar", commit], capture_output=True)
    if archive.returncode:
        raise JudgeError(f"git archive failed: {archive.stderr.decode(errors='replace').strip()}")

    def keep(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
        try:  # a link that leads out of the folder is left out
            return tarfile.data_filter(member, path)
        except tarfile.FilterError:
            return None
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(folder, filter=keep)


def read_answer(text: str, count: int) -> dict | None:
    """The review's fixed lines read, or None when the answer is not in them."""
    answers: dict[str, str] = {}
    findings: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if found := REQUIREMENT_LINE.fullmatch(line):
            number = int(found.group(1))
            if number > count or f"R{number}" in answers or number != len(answers) + 1:
                return None
            answers[f"R{number}"] = found.group(2)
        elif found := FINDING_LINE.fullmatch(line):
            if int(found.group(1)) != len(findings) + 1:
                return None
            evidence = found.group(5).strip()
            findings.append({"finding": f"F{found.group(1)}", "file": found.group(2), "line": int(found.group(3)),
                             "what": found.group(4).strip(), "evidence": evidence,
                             "proven": evidence.rstrip(".").strip().lower() != "none"})
        else:
            return None
    if len(answers) != count:
        return None
    proven = sum(finding["proven"] for finding in findings) + sum(answer == "cannot tell" for answer in answers.values())
    return {"requirements": answers, "findings": findings, "proven": proven,
            "passed": proven == 0 and all(answer == "met" for answer in answers.values())}


def review(prompt: str, folder: Path) -> tuple[str, str | None]:
    """Run the review in `folder`: the answer as it came, and why it gives no verdict when it fails."""
    try:
        done = subprocess.run(CLAUDE, input=prompt, cwd=folder, text=True, capture_output=True,
                              timeout=REVIEW_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "", f"the review ran for more than {REVIEW_TIMEOUT} seconds"
    try:
        result = json.loads(done.stdout)
    except ValueError:
        result = None
    if isinstance(result, list):  # with "verbose" on in the user's settings the JSON is every message, the result last
        result = next((message for message in reversed(result)
                       if isinstance(message, dict) and message.get("type") == "result"), None)
    text = result.get("result") if isinstance(result, dict) else None
    reason = (f"the review session failed with exit {done.returncode}" if done.returncode
              else "the review session gave no result" if not isinstance(text, str)
              else "the review session ended in an error" if result.get("is_error") else None)
    if reason:
        return f"{done.stdout}{done.stderr}".rstrip("\n") + f"\nclaude exit {done.returncode}\n", reason
    return text, None


def judge(label: str, number: int, version: str, commit: str | None, source: Path | None) -> int:
    state = scan.state_dir()
    entry = find_ticket(state, label, number)
    repo = repo_entry(state, label)
    required = draw.requirements(entry.get("body"))
    if not required:
        raise JudgeError(f"ticket {label}-{number} has no requirements under the headings of --help.")
    saved = state / "judged" / f"{label}-{number}-{version}"
    saved.mkdir(parents=True, exist_ok=True)
    (state / "judge-work").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=state / "judge-work"))  # its name says nothing of the version
    try:
        clone = work / "clone"
        if source is None:
            cloned = subprocess.run(["gh", "repo", "clone", repo["repo"], str(clone)], text=True, capture_output=True)
            commit = entry["ready_commit"]
        else:
            cloned = subprocess.run(["git", "clone", "--quiet", "--no-checkout", str(source), str(clone)], text=True,
                                    capture_output=True)
        if cloned.returncode:
            raise JudgeError(f"the version's repo cannot be cloned: {cloned.stderr.strip()}")
        commit = fetch(clone, commit)
        base = fetch(clone, entry["base_commit"])
        trees = {place: tree_of(commit, place) for place in (clone, source) if place}

        check = saved / "check.txt"
        failed = Checkout(work).run_check({"label": label, "ticket": number, "repo": repo}, clone, commit, check)

        diff = git("-c", "core.quotepath=off", "diff", "--no-color", "--no-ext-diff", "--no-textconv",
                   f"{base}...{commit}", cwd=clone)
        if diff.returncode:
            raise JudgeError(f"git diff failed: {diff.stderr.strip()}")
        folder = work / "review"
        folder.mkdir()
        if git("rev-parse", "--is-inside-work-tree", cwd=folder).returncode == 0:
            raise JudgeError(f"{folder} is inside a git repo, whose branch and commits Claude Code would read.")
        export(clone, commit, folder)
        prompt = PROMPT.format(title=entry.get("title", ""), body=(entry.get("body") or "").strip(), diff=diff.stdout,
                               requirements="\n".join(f"R{at}: {text}" for at, text in enumerate(required, 1)))
        scan.write_private(saved / "prompt.txt", prompt)
        answer, reason = review(prompt, folder)
        scan.write_private(saved / "review.txt", answer)
        reading = None if reason else read_answer(answer, len(required))
        if reading is None and not reason:
            reason = "the answer is not in the fixed lines"
        if {place: tree_of(commit, place) for place in trees} != trees:
            raise JudgeError("the version's commit or its tree changed during the review.")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    right = None if reading is None else (failed is None and reading["passed"])
    record = {"label": label, "ticket": number, "version": version, "commit": commit, "base_commit": entry["base_commit"],
              "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "check": {"passed": failed is None, "reason": failed, "output": str(check.relative_to(state))},
              "review": {"passed": None if reading is None else reading["passed"], "reason": reason,
                         **({"requirements": None, "findings": None, "proven": None} if reading is None else
                            {key: reading[key] for key in ("requirements", "findings", "proven")}),
                         "lines": str((saved / "review.txt").relative_to(state))},
              "right_first_time": right}
    with open(state / "verdicts.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = state / "verdicts.jsonl"
        kept = [text for text in (path.read_text().splitlines() if path.is_file() else []) if text.strip()
                and (lambda old: (old.get("label"), old.get("ticket"), old.get("version")))(json.loads(text))
                != (label, number, version)]
        scan.write_private(path, "".join(text + "\n" for text in [*kept, json.dumps(record)]))
    print(f"Test 1, the check: {'passed' if failed is None else 'failed, ' + failed}. Output in {check}.")
    if reading is None:
        print(f"Test 2, the review: no verdict, {reason}. Answer in {saved / 'review.txt'}.")
        print(f"No verdict for {label}-{number} {version}.")
        return EXIT_NO_VERDICT
    print(f"Test 2, the review: {'passed' if reading['passed'] else 'failed'}. "
          f"Answer in {saved / 'review.txt'}.")
    print(f"{label}-{number} {version} is {'right' if right else 'not right'} first time.")
    return 0


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(HELP)
        return 0
    found = re.fullmatch(r"([A-Z]+)-([1-9]\d*)", argv[0]) if argv else None
    options = dict(zip(argv[2::2], argv[3::2]))
    usable = found and len(argv) >= 2 and VERSION_NAME.fullmatch(argv[1]) and (
        (argv[1] == GENERATION_ONE and len(argv) == 2)
        or (argv[1] != GENERATION_ONE and len(argv) == 6 and set(options) == {"--commit", "--from"}))
    if not usable:
        print(HELP, file=sys.stderr)
        return 2
    try:
        source = Path(options["--from"]).expanduser().absolute() if "--from" in options else None
        return judge(found.group(1), int(found.group(2)), argv[1], options.get("--commit"), source)
    except JudgeError as error:
        print(f"judge: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
