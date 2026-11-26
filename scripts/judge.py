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
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # importing the siblings would otherwise write scripts/__pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
import draw  # noqa: E402  (a sibling script, not an installed package)
import scan  # noqa: E402

GENERATION_ONE = "generation-one"
EXIT_NO_VERDICT = 3
REVIEW_TIMEOUT = draw.CHECK_TIMEOUT
# Set to a true value such as 1 (not empty, 0, false or off), it stops Claude Code 2.1.332 writing the session's log.
NO_LOG = "CLAUDE_CODE_SKIP_PROMPT_HISTORY"
REVIEWED = ("review.txt", "session.jsonl")  # what a review leaves in its attempt's folder
# One requirements review on the strong class, headless, that can read the version's files and change nothing.
# --safe-mode loads no CLAUDE.md, skill, plugin, hook, MCP server or auto memory; --tools leaves only the
# read tools; --permission-prompts none denies whatever would ask.
CLAUDE = ["claude", "-p", "--model", "opus", "--effort", "medium", "--output-format", "json", "--safe-mode",
          "--strict-mcp-config", "--tools", "Read,Grep,Glob", "--permission-prompts", "none"]
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
finding, numbered F1, F2 and on. "breaks" names the requirement that the line
at <file>:<line> breaks. "fails" shows the finding failing: what to give the
change or do with it, and what goes wrong then. Write "none" when you can show
neither. A finding with "breaks" or "fails" names each requirement, R<n>, that
its line holds after <file>:<line>, and names no other; a finding with "none"
names no requirement. A finding is proven when its evidence is "breaks" or
"fails", and each "cannot tell" counts as a proven finding. A requirement that
is not met needs a proven finding that names it. The review passes when no
finding is proven, so with every requirement met and nothing wrong the answer
is the R lines alone."""
REQUIREMENT_LINE = re.compile(rf"R([1-9]\d*): ({'|'.join(ANSWERS)})")
FINDING_LINE = re.compile(r"F([1-9]\d*): ([^\s:][^:]*):([1-9]\d*): (\S.*?) Evidence: (.+)")
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
breaks these rules, gives no verdict, as does a review that fails, runs for
more than {REVIEW_TIMEOUT // 60} minutes or leaves no session log.

The version is right first time when both tests pass. The judge checks that
the version's commit and its tree are the same after the review as before it.

Every file is in the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver). The judge reads replay-set-<n>.json, the set that
holds the ticket, project-labels.json and repos.json, and writes:

  verdicts.jsonl        One JSON line per ticket and version, replaced when
                        the version is judged again: label, ticket, version,
                        commit, base_commit, judged_at, check {{passed,
                        reason, output}}, review {{passed, reason,
                        requirements, findings, proven, lines, prompt, log}}
                        and right_first_time: true, false, or null for no
                        verdict. Paths are relative to the machine directory;
                        log is null when the session left no log.
  judged/<label>-<ticket>-<version>/<attempt>/
                        check.txt, the output of setup and check; prompt.txt,
                        what the reviewer was given; review.txt, the
                        review's answer as it came; session.jsonl, the
                        review session's log, with session/ beside it when
                        Claude Code keeps a folder for the session. The judge
                        starts the review with --session-id, and without
                        {NO_LOG}, which can stop the
                        log being written. When the session ends, the judge
                        moves its log and folder here from
                        $CLAUDE_CONFIG_DIR/projects (default ~/.claude; a
                        relative one is read from where the judge was
                        started, and an empty one is an error).
                        session.jsonl and each file in session/ are mode
                        0600. The line on record names the files of its
                        own attempt. Once a new line is written the judge
                        tries to remove the folder of the attempt it
                        replaced, its log included; when that fails or is
                        interrupted, the folder stays and no line names it.
  judge-work/           Clones and checkouts, removed when the judge ends.

Exit 0: a verdict was recorded. Exit 1: an error. Until a new line is
written, the line and files of the version's earlier attempt stay as they
were. On an error or an interrupt the judge removes its own attempt's folder
when no line names it and it holds neither review.txt nor session.jsonl;
otherwise the folder stays. When copying or removing the log fails, the
error names where it still is. Exit 2: bad usage.
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
            named = sorted({int(number) for number in NAMED.findall(f"{found.group(4)} {evidence}")})
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


def review(prompt: str, folder: Path, session: str, config: Path) -> tuple[str, str | None]:
    """Run the review in `folder` as session `session`, with `config` as its Claude Code folder when the caller set
    one: the answer as it came, and why it gives no verdict when it fails."""
    env = {key: value for key, value in os.environ.items() if key != NO_LOG}
    if "CLAUDE_CONFIG_DIR" in env:
        env["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        done = subprocess.run([*CLAUDE, "--session-id", session], input=prompt, cwd=folder, capture_output=True,
                              timeout=REVIEW_TIMEOUT, env=env, **TEXT)
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


def private_copy(source: str | Path, target: str | Path) -> None:
    """Copy a file's bytes to `target`, a file only its owner can read, which then holds all of them or is absent."""
    try:
        with open(source, "rb") as found, os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
                                                    "wb") as kept:
            os.fchmod(kept.fileno(), 0o600)  # whatever the umask
            shutil.copyfileobj(found, kept)
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise


def keep_log(session: str, saved: Path, config: Path) -> Path | None:
    """The session's log as kept in `saved`, or None when the session left none under `config`."""
    log = next((path for path in config.glob(f"projects/*/{session}.jsonl") if path.is_file()), None)
    if log is None:
        return None
    try:
        private_copy(log, saved / "session.jsonl")
        if log.with_suffix("").is_dir():
            shutil.copytree(log.with_suffix(""), saved / "session", copy_function=private_copy)
            shutil.rmtree(log.with_suffix(""))
        log.unlink()
    except OSError as error:
        raise JudgeError(f"the review session's log could not be kept; it is still at {log}.") from error
    try:
        log.parent.rmdir()  # the folder Claude Code made for the review's working folder, once empty
    except OSError:
        pass
    return saved / "session.jsonl"


def attempt(state: Path, label: str, number: int, version: str, commit: str | None, source: Path | None,
            entry: dict, repo: dict, required: list[str], saved: Path, config: Path) -> dict:
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
        session = str(uuid.uuid4())
        try:
            answer, reason = review(prompt, folder, session, config)
            scan.write_private(saved / "review.txt", answer)
        finally:  # on an interrupt too
            log = keep_log(session, saved, config)
        reason = reason or (None if log else "the review session left no log")
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
                       "lines": path("review.txt"), "prompt": path("prompt.txt"),
                       "log": str(log.relative_to(state)) if log else None},
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
    value = os.environ.get("CLAUDE_CONFIG_DIR")
    if value == "":  # Claude Code 2.1.332 would write the log in the review's folder
        raise JudgeError("CLAUDE_CONFIG_DIR is set and empty: unset it, or name the Claude Code folder.")
    # The session runs in the review's folder, so it is handed the folder the judge looks in, whole.
    config = scan.config_dir() if value is None else Path(os.path.abspath(value))
    # Each attempt keeps its files apart, so one that fails leaves the files of the line on record as they were.
    versions = state / "judged" / f"{label}-{number}-{version}"
    versions.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(dir=versions, prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")))
    try:
        record = attempt(state, label, number, version, commit, source, entry, repo, required, saved, config)
        replaced = publish(state, record, saved)
    except BaseException:
        # Around publish too: an interrupt can land after it has written the line that names this attempt.
        if not any((saved / name).exists() for name in REVIEWED) and all(
                folder_of(state, line) != saved for line in ledger(state)):
            shutil.rmtree(saved, ignore_errors=True)
        raise
    for folder in replaced:  # only once the new line is written
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
