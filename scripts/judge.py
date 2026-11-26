#!/usr/bin/env python3
"""Judge one version of a replay ticket. `--help` gives the two tests and the files the judge reads and writes."""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
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
# Output that is not UTF-8, such as a diff of a Latin-1 file, is kept with its odd bytes written as \xe9.
TEXT = {"encoding": "utf-8", "errors": "backslashreplace"}

# The fixed lines, as the help and the reviewer's prompt give them and as read_answer reads them.
ANSWERS = ("met", "not met", "cannot tell")
LINES = f"""\
R<n>: {' | '.join(ANSWERS)}
F<n>: <file>:<line>: <what is wrong> Evidence: <evidence>"""
# Each form the evidence may take, as shown and as read; every form but "none" proves its finding.
FORMS = (("breaks R<n>: <how the line breaks requirement n>", r"breaks R[1-9]\d*: \S.*"),
         ("fails: <what to give or do> -> <what goes wrong then>", r"fails: \S.*? -> \S.*"),
         ("fails R<n>: <what to give or do> -> <what goes wrong then>", r"fails R[1-9]\d*: \S.*? -> \S.*"),
         ("none", "none"))
EVIDENCE = "\n".join(shown for shown, _ in FORMS)
PROOF = re.compile("|".join(read for shown, read in FORMS if shown != "none"))
RULES = """\
Give one R line for each requirement, in order, and one F line for each
finding, numbered F1, F2 and on. <file> may hold a colon: it ends at the first
colon that is followed by a line number and a colon. "breaks" names the
requirement that the line at <file>:<line> breaks. "fails" shows the finding
failing: what to give the change or do with it, and what goes wrong then.
Write "none" when you can show neither. A finding names a requirement by its
R<n> in <what is wrong> or right after "breaks" or "fails". An R<n> later in
the evidence, such as a label in what to give, names none. A finding with
"breaks" or "fails" names each requirement it is about, and names no other; a
finding with "none" names no requirement. A finding is proven when its evidence is "breaks" or
"fails", and each "cannot tell" counts as a proven finding. A requirement that
is not met needs a proven finding that names it. The review passes when no
finding is proven, so with every requirement met and nothing wrong the answer
is the R lines alone."""
REQUIREMENT_LINE = re.compile(rf"R([1-9]\d*): ({'|'.join(ANSWERS)})")
FINDING_LINE = re.compile(r"F([1-9]\d*): (\S.*?):([1-9]\d*): (\S.*?) Evidence: (.+)")
NAMED = re.compile(r"\bR([1-9]\d*)\b")
VERSION_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


def indented(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


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
setup command, where it has one, and then its check command, each with sh,
both read from repos.json as the draw reads them. It passes when the check
exits 0. A step that runs for more than {draw.CHECK_TIMEOUT // 60} minutes is stopped and fails.

Test 2: one requirements review, headless on Claude Code, on Opus at medium
effort. The reviewer is given the ticket's title and body, its requirements
and the diff from the version's starting commit: from the merge base of the
commit before the merged PR and the version's commit. It starts in a folder
outside any git repo that holds the version's files as committed and no git
history, so it sees no branch name, commit message or author, and it can read
those files but change nothing. The requirements are the list the draw stored
in the ticket's entry of the replay set, numbered R1, R2 and on in the order
written. python3 scripts/draw.py --help says which lists the draw reads. An
entry without that list, a list of strings each with text, stops the judge
with an error before any checkout. The reviewer answers in fixed lines only:

{indented(LINES)}

where the evidence is one of:

{indented(EVIDENCE)}

{RULES}

Test 2 passes when the review passes. An answer with any other line, or that
breaks these rules, gives no verdict, as does a review that fails or runs for
more than {REVIEW_TIMEOUT // 60} minutes.

The version is right first time when both tests pass. The judge checks that
the version's commit and its tree are the same after the review as before it.

Every file is in the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver). The judge reads replay-set-<n>.json, the set that
holds the ticket, project-labels.json and repos.json, and writes:

  verdicts.jsonl        One JSON line per ticket and version, replaced when
                        the version is judged again: label, ticket, version,
                        commit, base_commit, judged_at, check {{passed,
                        reason, output}}, review {{passed, reason,
                        requirements, findings, proven, lines, prompt}} and
                        right_first_time: true, false, or null for no
                        verdict. Paths are relative to the machine directory.
  judged/<label>-<ticket>-<version>/<attempt>/
                        check.txt, the output of setup and check; prompt.txt,
                        what the reviewer was given; review.txt, the
                        review's answer as it came. The line on record
                        names the three files of its own attempt. Once a
                        new line is written the judge tries to remove the
                        folder of the attempt it replaced; a folder no
                        line names can stay behind after an interrupt or
                        a failed removal.
  judge-work/           Clones and checkouts, removed when the judge ends.

Exit 0: a verdict was recorded. Exit 1: an error; nothing was recorded, and
the line and files of an earlier attempt stay as they were. Exit 2: bad usage.
Exit {EXIT_NO_VERDICT}: the review gave no verdict, recorded as null."""

PROMPT = f"""\
Review a change against the requirements of the ticket it was written for.

The working folder holds the files as they are after the change. Read them as you need. You cannot run commands \
or change files.

<ticket>
{{title}}

{{body}}
</ticket>

The requirements, numbered in the order the ticket gives them:

{{requirements}}

The change, as a diff from the commit it started from:

<diff>
{{diff}}</diff>

Answer with these lines and nothing else: no heading, no code fence, no other text.

{LINES}

where the evidence is one of:

{EVIDENCE}

{RULES}
"""


class JudgeError(Exception):
    """Ends the judge with exit 1 and nothing recorded."""


class Checkout(draw.Draw):
    """The draw's repo list, clean checkout and run of setup and check, in the judge's own work folder."""

    def __init__(self, state: Path, work: Path) -> None:
        self.state, self.work = state, work


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, **TEXT)


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
    """The label's repo in repos.json as it is now, read by the draw's own reader, which keeps the last of two entries
    for one repo and refuses a list it cannot use."""
    repo = read_json(state / "project-labels.json").get(label)
    try:
        entry = Checkout(state, state).repos().get(str(repo).lower())
    except draw.DrawError as error:
        raise JudgeError(str(error))
    if not repo or not entry:
        raise JudgeError(f"project {label} has no repo in repos.json.")
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
    """Every file of the commit's tree, byte for byte as committed, in `folder`, with no git history.

    The blobs are read from the tree, so no attribute changes or leaves out a file. A link that leads out
    of the folder is left out, as is a submodule, which has no files in the tree."""
    def run(*args: str, given: bytes = b"") -> bytes:
        done = subprocess.run(["git", "-C", str(clone), *args], input=given, capture_output=True)
        if done.returncode:
            raise JudgeError(f"git {args[0]} failed: {done.stderr.decode(**TEXT).strip()}")
        return done.stdout
    files = []  # (mode, object, path)
    for record in run("ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if record:
            info, path = record.split(b"\t", 1)
            mode, kind, name = info.split()
            if kind == b"blob":
                files.append((mode, name, os.fsdecode(path)))
    batch, at, links = run("cat-file", "--batch", given=b"".join(name + b"\n" for _, name, _ in files)), 0, []
    for mode, _, path in files:
        header = batch.index(b"\n", at)
        size = int(batch[at:header].split()[2])
        content, at = batch[header + 1:header + 1 + size], header + 2 + size
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == b"120000":
            links.append((target, os.fsdecode(content)))
        else:
            target.write_bytes(content)
            target.chmod(0o755 if mode == b"100755" else 0o644)
    root = folder.resolve()
    for link, to in links:  # made last, so no file is written through one
        if (link.parent / to).resolve().is_relative_to(root):
            link.symlink_to(to)


def read_answer(text: str, count: int) -> dict | None:
    """The review's fixed lines read, or None when the answer is not in them or the rules of --help cannot score it."""
    answers: dict[str, str] = {}
    findings: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if found := REQUIREMENT_LINE.fullmatch(line):
            if int(found.group(1)) != len(answers) + 1:
                return None
            answers[f"R{found.group(1)}"] = found.group(2)
        elif found := FINDING_LINE.fullmatch(line):
            evidence = found.group(5).strip()
            # The evidence names a requirement only in its head, the part before its first colon.
            named = sorted({int(number) for number in NAMED.findall(f"{found.group(4)} {evidence.split(':', 1)[0]}")})
            if int(found.group(1)) != len(findings) + 1 or not (
                    evidence == "none" and not named or PROOF.fullmatch(evidence)):
                return None
            findings.append({"finding": f"F{found.group(1)}", "file": found.group(2), "line": int(found.group(3)),
                             "what": found.group(4).strip(), "evidence": evidence,
                             "requirements": [f"R{number}" for number in named], "proven": evidence != "none"})
        else:
            return None
    named = {requirement for finding in findings for requirement in finding["requirements"]}
    shown = {requirement for finding in findings if finding["proven"] for requirement in finding["requirements"]}
    if len(answers) != count or not named <= set(answers) or any(
            answer == "not met" and requirement not in shown for requirement, answer in answers.items()):
        return None
    proven = sum(finding["proven"] for finding in findings) + sum(answer == "cannot tell" for answer in answers.values())
    return {"requirements": answers, "findings": findings, "proven": proven, "passed": proven == 0}


def review(prompt: str, folder: Path) -> tuple[str, str | None]:
    """Run the review in `folder`: the answer as it came, and why it gives no verdict when it fails."""
    try:
        done = subprocess.run(CLAUDE, input=prompt, cwd=folder, capture_output=True, timeout=REVIEW_TIMEOUT, **TEXT)
    except subprocess.TimeoutExpired:
        return "", f"the review ran for more than {REVIEW_TIMEOUT} seconds"
    try:
        result = json.loads(done.stdout)
    except ValueError:
        result = None
    if isinstance(result, list):  # with "verbose" on in the user's settings the JSON is every message, the result last
        result = next((message for message in reversed(result)
                       if isinstance(message, dict) and message.get("type") == "result"), None)
    if not isinstance(result, dict) or result.get("type") != "result":
        result = None
    text = result.get("result") if result else None
    reason = (f"the review session failed with exit {done.returncode}" if done.returncode
              else "the review session gave no result" if not isinstance(text, str)
              else "the review session ended in an error" if result.get("is_error") else None)
    if reason:
        return f"{done.stdout}{done.stderr}".rstrip("\n") + f"\nclaude exit {done.returncode}\n", reason
    return text, None


def attempt(state: Path, label: str, number: int, version: str, commit: str | None, source: Path | None,
            entry: dict, repo: dict, required: list[str], saved: Path) -> dict:
    """Run both tests, keep their files in `saved`, and give the verdict's line."""
    (state / "judge-work").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=state / "judge-work"))  # its name says nothing of the version
    try:
        clone = work / "clone"
        if source is None:
            cloned = subprocess.run(["gh", "repo", "clone", repo["repo"], str(clone)], capture_output=True, **TEXT)
            commit = entry["ready_commit"]
        else:
            cloned = subprocess.run(["git", "clone", "--quiet", "--no-checkout", str(source), str(clone)],
                                    capture_output=True, **TEXT)
        if cloned.returncode:
            raise JudgeError(f"the version's repo cannot be cloned: {cloned.stderr.strip()}")
        commit = fetch(clone, commit)
        base = fetch(clone, entry["base_commit"])
        trees = {place: tree_of(commit, place) for place in (clone, source) if place}

        failed = Checkout(state, work).run_check({"label": label, "ticket": number, "repo": repo}, clone, commit,
                                                 saved / "check.txt")

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

    def path(name: str) -> str:
        return str((saved / name).relative_to(state))
    return {"label": label, "ticket": number, "version": version, "commit": commit, "base_commit": entry["base_commit"],
            "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "check": {"passed": failed is None, "reason": failed, "output": path("check.txt")},
            "review": {"passed": None if reading is None else reading["passed"], "reason": reason,
                       **({"requirements": None, "findings": None, "proven": None} if reading is None else
                          {key: reading[key] for key in ("requirements", "findings", "proven")}),
                       "lines": path("review.txt"), "prompt": path("prompt.txt")},
            "right_first_time": None if reading is None else failed is None and reading["passed"]}


def ledger(state: Path) -> list[dict]:
    path = state / "verdicts.jsonl"
    return [json.loads(text) for text in (path.read_text().splitlines() if path.is_file() else []) if text.strip()]


def folder_of(state: Path, line: dict) -> Path:
    return (state / str(line.get("check", {}).get("output", ""))).parent


def publish(state: Path, record: dict, saved: Path) -> list[Path]:
    """Put the verdict's line in verdicts.jsonl in place of the version's earlier one, and give the attempt
    folders that line named, for the caller to remove."""
    key = (record["label"], record["ticket"], record["version"])
    with open(state / "verdicts.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = ledger(state)
        earlier = [line for line in lines if (line.get("label"), line.get("ticket"), line.get("version")) == key]
        scan.write_private(state / "verdicts.jsonl", "".join(json.dumps(line) + "\n" for line in [*(
            line for line in lines if line not in earlier), record]))
    folders = [folder_of(state, line) for line in earlier]
    return [folder for folder in folders if folder.parent == saved.parent and folder != saved]


def judge(label: str, number: int, version: str, commit: str | None, source: Path | None) -> int:
    state = scan.state_dir()
    entry = find_ticket(state, label, number)
    required = entry.get("requirements")
    if not (isinstance(required, list) and required
            and all(isinstance(text, str) and text.strip() for text in required)):
        raise JudgeError(f"the set entry of ticket {label}-{number} holds no requirements: a list of strings, each "
                         "with text, as the draw writes it.")
    repo = repo_entry(state, label)
    # Each attempt keeps its files apart, so one that fails leaves the files of the line on record as they were.
    versions = state / "judged" / f"{label}-{number}-{version}"
    versions.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(dir=versions, prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")))
    try:
        record = attempt(state, label, number, version, commit, source, entry, repo, required, saved)
        replaced = publish(state, record, saved)
    except BaseException:
        # Only an attempt that no line names is taken back: an interrupt can land after the line is written.
        if all(folder_of(state, line) != saved for line in ledger(state)):
            shutil.rmtree(saved, ignore_errors=True)
        raise
    for folder in replaced:  # once the new line is written; an interrupt here leaves only an unnamed folder
        shutil.rmtree(folder, ignore_errors=True)

    check, lines = state / record["check"]["output"], state / record["review"]["lines"]
    failed = record["check"]["reason"]
    print(f"Test 1, the check: {'passed' if failed is None else 'failed, ' + failed}. Output in {check}.")
    if record["right_first_time"] is None:
        print(f"Test 2, the review: no verdict, {record['review']['reason']}. Answer in {lines}.")
        print(f"No verdict for {label}-{number} {version}.")
        return EXIT_NO_VERDICT
    print(f"Test 2, the review: {'passed' if record['review']['passed'] else 'failed'}. Answer in {lines}.")
    print(f"{label}-{number} {version} is {'right' if record['right_first_time'] else 'not right'} first time.")
    return 0


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(HELP)
        return 0
    found = re.fullmatch(rf"({draw.LABEL.pattern})-([1-9]\d*)", argv[0]) if argv else None
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
