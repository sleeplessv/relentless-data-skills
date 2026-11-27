"""Exercise scripts/judge.py at its command line against a world the tests build.

Each test builds its own world in a temporary folder: a bare git repo that a
stand-in `gh` clones, a replay's clone beside it, a replay set and a repo list
in a machine directory of its own, and a stand-in `claude`, first on PATH, that
records how it was started and prints a saved review answer. No test touches
the network, the real machine directory or a real session.
"""
from __future__ import annotations

import errno
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REPO = "example-org/alpha"
CHECK = "test -e .setup-done && test ! -e broken"
SETUP = "touch .setup-done"
# The fixtures' git reads no global or system config, so a developer's signing program never starts.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
# Words that name generation one's version or the replay's: none may reach the reviewer.
SECRETS = ("ticket-7-the-branch", "Branch work for ticket 7", "Fix after ready", "Gen One Author",
           "gen-one@example.com", "Replay commit message", "Replay Author", "replay@example.com")
BODY = """## What to build

The report prints the total.

## Acceptance criteria

- [ ] The report prints the total.
- [x] The total counts every row,
  blank rows included.

## Notes

- Not a requirement.

## Done when

1. The help names the total.
"""
REQUIREMENTS = ["The report prints the total.", "The total counts every row, blank rows included.",
                "The help names the total."]

# Records each call and clones the bare repo for `repo clone`; any other call fails.
GH = r"""#!/bin/sh
printf '%s\n' "$*" >> "$GH_LOG"
[ "$1 $2" = "repo clone" ] || { echo "stand-in gh: no answer for $*" >&2; exit 1; }
exec git clone -q "$GH_REMOTES/$3.git" "$4"
"""
# Records each argument on a line of its own, the prompt it reads, its working folder, what that folder holds
# and a copy of it, links and modes kept; tries to change the folder, and removes $CLAUDE_BREAK when it is set.
# Given --session-id, it writes the session's log where Claude Code writes it, under $CLAUDE_CONFIG_DIR/projects
# (default ~/.claude; a relative or empty one read from its working folder) in a folder named for its working folder:
# the bytes of the file $CLAUDE_LOG names, then a line with the session's id; with $CLAUDE_LOG_FOLDER set, a folder
# beside the log as well. It writes no log when $CLAUDE_LOG is empty or when given --no-session-persistence. It
# records what it was given as CLAUDE_CONFIG_DIR and CLAUDE_CODE_SKIP_PROMPT_HISTORY, <unset> for a key it was not
# given. With $CLAUDE_SLEEP set it then sleeps that many seconds; it prints the saved answer as Claude Code's JSON
# result.
CLAUDE = r"""#!/bin/sh
printf '%s\n' "$@" > "$CLAUDE_ARGS"
cat > "$CLAUDE_PROMPT"
pwd > "$CLAUDE_CWD"
if git rev-parse --git-dir > /dev/null 2>&1; then echo inside > "$CLAUDE_GIT"; else echo outside > "$CLAUDE_GIT"; fi
ls -A > "$CLAUDE_FILES"
rm -rf "$CLAUDE_COPY" && cp -pRP . "$CLAUDE_COPY"
if [ -n "$CLAUDE_BREAK" ]; then rm -rf "$CLAUDE_BREAK"; fi
echo "the reviewer wrote this" > app.txt
rm -f counter
printf '%s\n' "${CLAUDE_CONFIG_DIR-<unset>}" > "$CLAUDE_CONFIG"
printf '%s\n' "${CLAUDE_CODE_SKIP_PROMPT_HISTORY-<unset>}" > "$CLAUDE_SWITCH"
session= previous=
for arg in "$@"; do
  [ "$previous" = --session-id ] && session=$arg
  [ "$arg" = --no-session-persistence ] && session= && break
  previous=$arg
done
if [ -n "$session" ] && [ -n "$CLAUDE_LOG" ]; then
  config=${CLAUDE_CONFIG_DIR-$HOME/.claude}
  project="${config:+$config/}projects/$(pwd | sed 's/[^A-Za-z0-9]/-/g')"
  mkdir -p "$project"
  { cat "$CLAUDE_LOG"; printf '{"sessionId":"%s"}\n' "$session"; } > "$project/$session.jsonl"
  if [ -n "$CLAUDE_LOG_FOLDER" ]; then
    mkdir -p "$project/$session/tool-results" && printf 'a large result\n' > "$project/$session/tool-results/r1.txt"
  fi
fi
if [ -n "$CLAUDE_SLEEP" ]; then exec sleep "$CLAUDE_SLEEP"; fi
if [ -n "$CLAUDE_STDERR" ]; then echo "$CLAUDE_STDERR" >&2; fi
cat "$CLAUDE_ANSWER"
exit "${CLAUDE_EXIT:-0}"
"""
# A line of the stand-in's session log that appears nowhere else.
MARKER = '{"type":"user","message":"log marker 5c1e"}\n'


def ExitStack_of(*managers):
    """One context manager that enters each of `managers` in turn."""
    stack = ExitStack()
    for manager in managers:
        stack.enter_context(manager)
    return stack


def module():
    """scripts/judge.py, imported without writing scripts/__pycache__ into the checkout."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    with mock.patch.object(sys, "dont_write_bytecode", True):
        return importlib.import_module("judge")


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True, capture_output=True,
                          env={**os.environ, **GIT_ENV, **(env or {})}).stdout.strip()


def commit(cwd: Path, message: str, author: tuple[str, str], files: dict[str, str | None]) -> str:
    for name, text in files.items():
        if text is None:
            (cwd / name).unlink()
        else:
            (cwd / name).write_text(text)
    git(cwd, "add", "-A")
    name, email = author
    git(cwd, "commit", "-q", "-m", message, env={
        "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email})
    return git(cwd, "rev-parse", "HEAD")


class World:
    """A repo with one finished ticket, its replay, and the machine directory that names them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.bin = root / "bin"
        self.remotes = root / "remotes"
        self.records = root / "records"
        for folder in (self.state, self.bin, self.records, root / "home", root / "cwd"):
            folder.mkdir(parents=True)
        for name, text in (("gh", GH), ("claude", CLAUDE)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        work = root / "build"
        work.mkdir()
        git(work, "init", "-q", "-b", "main")
        owner = ("Main Author", "main@example.com")
        gen_one = ("Gen One Author", "gen-one@example.com")
        # Attributes that git archive would act on: a $Format$ stamp it would fill in and a file it would leave out.
        # A link inside the folder is kept; one that leads out of it is not. run.sh is executable.
        (work / "inside-link").symlink_to("report.txt")
        (work / "outside-link").symlink_to("../../outside")
        (work / "run.sh").write_text("#!/bin/sh\necho run\n")
        (work / "run.sh").chmod(0o755)
        commit(work, "Start", owner, {
            "counter": "1\n", "report.txt": "rows\n", "stamp.txt": "$Format:%an %s$\n", "hidden.txt": "kept\n",
            ".gitattributes": "stamp.txt export-subst\nhidden.txt export-ignore\n"})
        git(work, "checkout", "-q", "-b", "ticket-7-the-branch")
        # Generation one's commit first marked ready still holds `broken`; the fix after ready removes it.
        self.ready = commit(work, "Branch work for ticket 7", gen_one, {"report.txt": "rows\ntotal\n", "broken": "x\n"})
        self.fixed = commit(work, "Fix after ready", gen_one, {"broken": None})
        git(work, "checkout", "-q", "main")
        # main moved on after the branch started: the commit before the merged PR is not where the branch began.
        self.base = commit(work, "Main-only change", owner, {"notes.txt": "main only\n"})
        self.merged = commit(work, "Squash of ticket 7", owner, {"report.txt": "rows\ntotal\n"})
        bare = self.remotes / f"{REPO}.git"
        bare.parent.mkdir(parents=True)
        git(root, "init", "-q", "--bare", str(bare))
        git(work, "push", "-q", str(bare), "main", f"{self.fixed}:refs/pull/8/head")
        git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
        # The replay's clone: the commit before the merged PR, then the replay's own commit, with HEAD on it.
        self.replay_clone = root / "replays" / "A-7-direct"
        self.replay_clone.parent.mkdir()
        git(root, "clone", "-q", str(bare), str(self.replay_clone))
        git(self.replay_clone, "checkout", "-q", "--detach", self.base)
        self.replay = commit(self.replay_clone, "Replay commit message", ("Replay Author", "replay@example.com"),
                             {"report.txt": "rows\ntotal from replay\n"})
        (self.state / "repos.json").write_text(json.dumps([{"repo": REPO, "check": CHECK, "setup": SETUP}]))
        (self.state / "project-labels.json").write_text(json.dumps({"A": REPO}))
        (self.state / "replay-set-1.json").write_text(json.dumps({
            "set": 1, "seed": 4, "drawn_at": "2026-01-05T10:00:00+00:00", "set_aside": [],
            "tickets": [{"label": "A", "ticket": 7, "bucket": "0-50", "size": 3, "title": "Print the total",
                         "body": BODY, "requirements": REQUIREMENTS, "base_commit": self.base,
                         "ready_commit": self.ready, "model": "test-model",
                         "pr": 8, "session": "s-1", "log": "logs/s-1.jsonl", "check_output": "checks/A-7.txt"}]}))
        self.answer("R1: met\nR2: met\nR3: met\n")
        self.breaking = ""
        self.log = root / "log"  # the bytes the stand-in's session log starts with; None for no log
        self.log.write_text(MARKER)
        self.log_folder = self.sleep = ""
        self.config = str(root / "claude")  # CLAUDE_CONFIG_DIR as the judge is given it; None for unset
        self.no_log: str | None = None  # CLAUDE_CODE_SKIP_PROMPT_HISTORY as the judge is given it; None for unset
        self.stderr = ""  # what the last judge_here printed on standard error

    def answer(self, text: str, exit: int = 0, raw: str | None = None) -> None:
        """The stand-in's next answer: `text` as the result of Claude Code's JSON, or `raw` printed as it is."""
        result = {"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": "s-r"}
        (self.root / "answer").write_text(json.dumps(result) if raw is None else raw)
        self.exit = exit

    def env(self) -> dict[str, str]:
        """What the judge runs with: the caller's environment, with the stand-ins first on PATH, a scratch home and
        machine directory, CLAUDE_CONFIG_DIR and CLAUDE_CODE_SKIP_PROMPT_HISTORY as this world sets them, and the
        stand-ins' controls."""
        environ = {key: value for key, value in os.environ.items() if key not in (
            "PYTHONDONTWRITEBYTECODE", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_SKIP_PROMPT_HISTORY", "CLAUDE_STDERR")}
        return {**environ, **({} if self.config is None else {"CLAUDE_CONFIG_DIR": self.config}),
                **({} if self.no_log is None else {"CLAUDE_CODE_SKIP_PROMPT_HISTORY": self.no_log}),
                "HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(self.state),
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.records / "gh"),
                "GH_REMOTES": str(self.remotes), "CLAUDE_ANSWER": str(self.root / "answer"),
                "CLAUDE_EXIT": str(self.exit), "CLAUDE_BREAK": self.breaking,
                "CLAUDE_LOG": str(self.log or ""), "CLAUDE_LOG_FOLDER": self.log_folder, "CLAUDE_SLEEP": self.sleep,
                **{f"CLAUDE_{name.upper()}": str(self.records / name)
                   for name in ("args", "prompt", "cwd", "git", "files", "copy", "config", "switch")}}

    def judge(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPTS / "judge.py"), *args], cwd=self.root / "cwd",
                              env=self.env(), text=True, capture_output=True)

    def judge_here(self, args: list[str], *patches) -> int:
        """Run the judge in this process, from the same folder and with the same environment as `judge`, with
        `patches` applied to its module: its exit code, or what it raised. Its standard error is kept in `stderr`."""
        judge = module()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, self.env(), clear=True))
            for patch in patches:
                stack.enter_context(patch(judge))
            stack.enter_context(redirect_stdout(StringIO()))
            self.stderr = ""
            errors = stack.enter_context(redirect_stderr(StringIO()))
            stack.callback(lambda: setattr(self, "stderr", errors.getvalue()))
            here = os.getcwd()
            os.chdir(self.root / "cwd")
            stack.callback(os.chdir, here)
            return judge.main(args)

    def written(self) -> bytes:
        """The bytes the stand-in wrote as its last session's log."""
        session = self.record("args").splitlines()
        return self.log.read_bytes() + b'{"sessionId":"%s"}\n' % session[session.index("--session-id") + 1].encode()

    def record(self, name: str) -> str:
        return (self.records / name).read_text()

    def verdicts(self) -> list[dict]:
        return [json.loads(line) for line in (self.state / "verdicts.jsonl").read_text().splitlines()]

    def saved(self, path: str) -> str:
        """A file a verdict names, by its path relative to the machine directory."""
        return (self.state / path).read_text()

    def files(self) -> dict[str, str]:
        """Every file the judge saved for its verdicts, by path."""
        return {str(path.relative_to(self.state)): path.read_text()
                for path in sorted((self.state / "judged").rglob("*")) if path.is_file()}

    def version(self, message: str, files: dict[str, bytes]) -> tuple[Path, str]:
        """A clone of the replay's clone with one more commit on the replay: its folder and the commit."""
        clone = self.root / f"version-{len(list(self.root.glob('version-*')))}"
        git(self.root, "clone", "-q", str(self.replay_clone), str(clone))
        git(clone, "checkout", "-q", "--detach", self.replay)
        for name, data in files.items():
            (clone / name).write_bytes(data)
        return clone, commit(clone, message, ("Replay Author", "replay@example.com"), {})


class TestJudge(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name).resolve())

    def test_generation_one_is_judged_at_its_commit_first_marked_ready(self) -> None:
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        [verdict] = self.world.verdicts()
        self.assertEqual((verdict["version"], verdict["commit"]), ("generation-one", self.world.ready))
        # The fix made after ready does not count: the ready commit still holds `broken`, so the check fails.
        self.assertIs(verdict["check"]["passed"], False)
        self.assertIs(verdict["right_first_time"], False)
        output = (self.world.state / verdict["check"]["output"]).read_text()
        self.assertEqual(output, f"$ {SETUP}\n\nsetup exit 0\n$ {CHECK}\n\ncheck exit 1\n")

    def test_a_version_it_has_not_seen_is_judged_from_its_own_repo(self) -> None:
        result = self.world.judge("A-7", "zeta", "--commit", self.world.replay[:12], "--from", str(self.world.replay_clone))
        self.assertEqual(result.returncode, 0, result.stderr)
        [verdict] = self.world.verdicts()
        self.assertEqual((verdict["label"], verdict["ticket"], verdict["version"], verdict["commit"]),
                         ("A", 7, "zeta", self.world.replay))
        folder = verdict["check"]["output"].removesuffix("/check.txt")
        self.assertRegex(folder, r"\Ajudged/A-7-zeta/\d{8}T\d{6}Z-[^/]+\Z")
        self.assertEqual(verdict["check"], {"passed": True, "reason": None, "output": f"{folder}/check.txt"})
        self.assertEqual(verdict["review"], {
            "passed": True, "reason": None, "requirements": {"R1": "met", "R2": "met", "R3": "met"}, "findings": [],
            "proven": 0, "lines": f"{folder}/review.txt", "prompt": f"{folder}/prompt.txt",
            "log": f"{folder}/session.jsonl"})
        self.assertIs(verdict["right_first_time"], True)
        self.assertEqual(result.stdout.splitlines(), [
            f"Test 1, the check: passed. Output in {self.world.state / folder / 'check.txt'}.",
            f"Test 2, the review: passed. Answer in {self.world.state / folder / 'review.txt'}.",
            "A-7 zeta is right first time."])
        self.assertEqual(self.world.saved(f"{folder}/review.txt"), "R1: met\nR2: met\nR3: met\n")
        self.assertFalse((self.world.records / "gh").exists())  # its repo is on this machine; GitHub is not asked
        self.assertEqual(list((self.world.state / "judge-work").iterdir()), [])

    def test_the_review_session_s_log_is_kept_with_its_attempt_and_named_by_its_line(self) -> None:
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        [verdict] = self.world.verdicts()
        folder = verdict["check"]["output"].removesuffix("/check.txt")
        self.assertEqual(verdict["review"]["log"], f"{folder}/session.jsonl")
        log = self.world.state / verdict["review"]["log"]
        self.assertEqual(log.read_bytes(), self.world.written())
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)

    def test_every_review_that_ran_keeps_its_log(self) -> None:
        cases = [("R1: met\nR2: met\nR3: met", 0, 0, None),
                 ("R1: met\nR2: not met\nR3: met", 0, 3, "the answer is not in the fixed lines"),
                 ("R1: met\nR2: met\nR3: met", 1, 3, "the review session failed with exit 1")]
        for answer, exit, code, reason in cases:
            with self.subTest(reason=reason):
                self.world.answer(answer, exit)
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, code, result.stderr)
                [verdict] = self.world.verdicts()
                self.assertEqual(verdict["review"]["reason"], reason)
                folder = verdict["check"]["output"].removesuffix("/check.txt")
                self.assertEqual(verdict["review"]["log"], f"{folder}/session.jsonl")
                self.assertEqual((self.world.state / verdict["review"]["log"]).read_bytes(), self.world.written())

    def test_a_review_with_no_log_gives_no_verdict(self) -> None:
        self.world.log = None
        for exit, reason in ((0, "the review session left no log"), (1, "the review session failed with exit 1")):
            with self.subTest(exit=exit):
                self.world.answer("R1: met\nR2: met\nR3: met", exit)
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 3, result.stderr)
                [verdict] = self.world.verdicts()
                self.assertEqual((verdict["right_first_time"], verdict["review"]["passed"],
                                  verdict["review"]["reason"], verdict["review"]["log"]), (None, None, reason, None))
                folder = (self.world.state / verdict["check"]["output"]).parent
                self.assertEqual(sorted(path.name for path in folder.iterdir()),
                                 ["check.txt", "prompt.txt", "review.txt"])
                self.assertEqual(result.stdout.splitlines()[1:], [
                    f"Test 2, the review: no verdict, {reason}. Answer in {folder / 'review.txt'}.",
                    "No verdict for A-7 generation-one."])

    def test_a_review_stopped_at_its_timeout_keeps_its_partial_log(self) -> None:
        self.world.sleep = "60"  # the stand-in writes its log, then outlasts the timeout
        code = self.world.judge_here(["A-7", "generation-one"],
                                     lambda judge: mock.patch.object(judge, "REVIEW_TIMEOUT", 2))
        self.assertEqual(code, 3)
        [verdict] = self.world.verdicts()
        self.assertEqual(verdict["review"]["reason"], "the review ran for more than 2 seconds")
        folder = verdict["check"]["output"].removesuffix("/check.txt")
        self.assertEqual(verdict["review"]["log"], f"{folder}/session.jsonl")
        self.assertEqual((self.world.state / verdict["review"]["log"]).read_bytes(), self.world.written())

    def test_the_kept_log_is_the_bytes_the_session_wrote(self) -> None:
        self.world.log.write_bytes(b"caf\xe9 \xff\xfe not UTF-8\n" + bytes(range(256)) * 4096)  # and 1 MiB more
        self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
        [verdict] = self.world.verdicts()
        self.assertEqual((self.world.state / verdict["review"]["log"]).read_bytes(), self.world.written())

    def test_the_log_s_folder_is_kept_beside_it(self) -> None:
        self.world.log_folder = "1"
        self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
        [verdict] = self.world.verdicts()
        folder = (self.world.state / verdict["review"]["log"]).with_suffix("")
        kept = folder / "tool-results" / "r1.txt"
        self.assertEqual([path for path in folder.rglob("*") if path.is_file()], [kept])
        self.assertEqual(kept.read_text(), "a large result\n")
        self.assertEqual(stat.S_IMODE(kept.stat().st_mode), 0o600)

    def test_each_kept_file_gets_its_name_only_once_whole(self) -> None:
        self.world.log_folder = "1"
        copying, seen = shutil.copyfileobj, {}

        def copy(found, kept, *args):  # writes 8 bytes, then looks for the file's final name, then writes the rest
            kept.write(found.read(8))
            kept.flush()
            name = Path(found.name).name
            final = "session.jsonl" if name.endswith(".jsonl") else f"session/tool-results/{name}"
            seen[final] = [str(path.relative_to(self.world.state)) for path in
                           self.world.state.glob(f"judged/*/*/{final}")]
            return copying(found, kept, *args)
        code = self.world.judge_here(["A-7", "generation-one"],
                                     lambda judge: mock.patch.object(judge.shutil, "copyfileobj", copy))
        self.assertEqual(code, 0, self.world.stderr)
        self.assertEqual(seen, {"session.jsonl": [], "session/tool-results/r1.txt": []})
        [verdict] = self.world.verdicts()
        folder = (self.world.state / verdict["review"]["log"]).parent
        self.assertEqual(sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()),
                         ["check.txt", "prompt.txt", "review.txt", "session.jsonl", "session/tool-results/r1.txt"])
        self.assertEqual((folder / "session.jsonl").read_bytes(), self.world.written())
        self.assertEqual((folder / "session/tool-results/r1.txt").read_bytes(), b"a large result\n")
        for kept in (folder / "session.jsonl", folder / "session/tool-results/r1.txt"):
            self.assertEqual(stat.S_IMODE(kept.stat().st_mode), 0o600)

    def test_the_review_s_log_is_moved_out_of_claude_code_s_projects(self) -> None:
        self.world.log_folder = "1"
        projects = Path(self.world.config) / "projects"
        self.assertFalse(projects.exists())
        self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
        self.assertEqual(list(projects.iterdir()), [])  # the stand-in made a folder here for the session

    def test_a_claude_code_folder_that_is_empty_relative_or_has_a_dot_dot_part_is_an_error_before_any_checkout(
            self) -> None:
        before = sorted(self.world.state.rglob("*"))
        for config in ("", "claude-config", str(self.world.root / "missing" / ".." / "claude")):
            with self.subTest(config=config):
                self.world.config = config
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "judge: CLAUDE_CONFIG_DIR must be unset or an absolute path with no "
                                                ".. part.\n")
                self.assertFalse((self.world.records / "gh").exists())  # no checkout
                self.assertFalse((self.world.records / "config").exists())  # no session started
                self.assertEqual(sorted(self.world.state.rglob("*")), before)  # nothing written

    def test_the_session_is_handed_the_claude_code_folder_as_the_caller_set_it(self) -> None:
        claude = str(self.world.root / "claude")
        # (CLAUDE_CONFIG_DIR as given, where the log is written, what the session is handed)
        for config, folder, seen in ((None, self.world.root / "home" / ".claude", "<unset>"),
                                     (claude, Path(claude), claude), (f"{claude}/", Path(claude), f"{claude}/")):
            with self.subTest(config=config):
                self.world.config = config
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.world.record("config"), f"{seen}\n")  # what the session was given
                [verdict] = self.world.verdicts()
                self.assertEqual((self.world.state / verdict["review"]["log"]).read_bytes(), self.world.written())
                self.assertEqual([path for path in (folder / "projects").rglob("*") if not path.is_dir()], [])

    def test_the_switch_that_stops_the_log_is_not_handed_to_the_review(self) -> None:
        self.world.no_log = "1"
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.world.record("switch"), "<unset>\n")
        [verdict] = self.world.verdicts()
        self.assertEqual((self.world.state / verdict["review"]["log"]).read_bytes(), self.world.written())

    def test_a_run_for_another_version_or_ticket_leaves_the_first_log_as_it_was(self) -> None:
        path = self.world.state / "replay-set-1.json"
        listed = json.loads(path.read_text())
        listed["tickets"].append({**listed["tickets"][0], "ticket": 8})
        path.write_text(json.dumps(listed))
        self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
        [first] = self.world.verdicts()
        log = self.world.state / first["review"]["log"]
        written = log.read_bytes()
        self.assertEqual(written, self.world.written())
        direct = ("--commit", self.world.replay, "--from", str(self.world.replay_clone))
        for args in (("A-7", "direct", *direct), ("A-8", "generation-one"), ("A-7", "direct", *direct)):
            with self.subTest(args=args[:2]):
                self.assertEqual(self.world.judge(*args).returncode, 0)
                self.assertEqual(log.read_bytes(), written)
                self.assertEqual(self.world.verdicts()[0]["review"]["log"], first["review"]["log"])
        self.assertEqual(len({verdict["review"]["log"] for verdict in self.world.verdicts()}), 3)

    def test_nothing_of_the_log_is_printed_or_written_to_the_line(self) -> None:
        for answer, exit, code in (("R1: met\nR2: met\nR3: met", 0, 0), ("Not the lines.", 0, 3),
                                   ("R1: met\nR2: met\nR3: met", 1, 3)):
            with self.subTest(answer=answer, exit=exit):
                self.world.answer(answer, exit)
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn(MARKER.encode(), (self.world.state / self.world.verdicts()[0]["review"]["log"]).read_bytes())
                for seen in (result.stdout, result.stderr, (self.world.state / "verdicts.jsonl").read_text()):
                    self.assertNotIn("log marker 5c1e", seen)

    def test_the_help_says_where_the_session_log_is_kept(self) -> None:
        help_text = self.world.judge("--help").stdout
        kept = "session.jsonl, the review session's log"
        self.assertEqual(" ".join(help_text.split()).count(kept), 1)
        # The files part, one entry per heading: only the attempt's folder names the log, with where it comes from,
        # the source path whole, and its mode.
        files = help_text.split(" and writes:\n\n", 1)[1].split("\n\nExit 0:", 1)[0]
        entries = [" ".join(entry.split()) for entry in re.split(r"\n(?=  \S)", "\n" + files) if entry.strip()]
        [entry] = [entry for entry in entries if "session.jsonl" in entry]
        self.assertTrue(entry.startswith("judged/<label>-<ticket>-<version>/<attempt>/ "), entry)
        for fact in (kept, "moves its log and folder here from $CLAUDE_CONFIG_DIR/projects (default ~/.claude;",
                     "session.jsonl and each file in session/ are mode 0600."):
            self.assertIn(fact, entry)
        self.assertNotIn("no session log is kept", (SCRIPTS / "judge.py").read_text())

    def test_the_review_starts_headless_on_opus_at_medium_effort_with_read_tools_only(self) -> None:
        self.world.judge("A-7", "generation-one")
        *args, session = self.world.record("args").splitlines()
        self.assertEqual(args, [
            "-p", "--model", "opus", "--effort", "medium", "--output-format", "json", "--safe-mode",
            "--strict-mcp-config", "--tools", "Read,Grep,Glob", "--permission-prompts", "none", "--session-id"])
        self.assertRegex(session, r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")

    def test_the_reviewer_is_given_the_ticket_and_the_diff_and_nothing_that_names_the_version(self) -> None:
        for version, args in (("generation-one", ()),
                              ("direct", ("--commit", self.world.replay, "--from", str(self.world.replay_clone)))):
            with self.subTest(version=version):
                self.assertEqual(self.world.judge("A-7", version, *args).returncode, 0)
                prompt = self.world.record("prompt")
                self.assertIn("<ticket>\nPrint the total\n\n" + BODY.strip() + "\n</ticket>\n", prompt)
                self.assertIn("".join(f"R{at}: {text}\n" for at, text in enumerate(REQUIREMENTS, 1)), prompt)
                added = "+total\n" if version == "generation-one" else "+total from replay\n"
                self.assertIn(f" rows\n{added}", prompt)
                [verdict] = [verdict for verdict in self.world.verdicts() if verdict["version"] == version]
                self.assertEqual(prompt, self.world.saved(verdict["review"]["prompt"]))
                seen = prompt + "".join(self.world.record(name) for name in ("args", "cwd", "files"))
                seen += (self.world.records / "copy" / "stamp.txt").read_text()
                for secret in (*SECRETS, version, self.world.ready, self.world.replay, "A-7"):
                    self.assertNotIn(secret, seen)
                self.assertEqual(self.world.record("git"), "outside\n")
                self.assertNotIn(".git", self.world.record("files").split())

    def test_the_reviewer_reads_every_committed_file_as_committed(self) -> None:
        self.world.judge("A-7", "direct", "--commit", self.world.replay, "--from", str(self.world.replay_clone))
        copy, clone = self.world.records / "copy", self.world.replay_clone
        tree = {}  # path: (mode, the blob's bytes) for each file of the version's commit
        for record in git(clone, "ls-tree", "-r", self.world.replay).splitlines():
            info, path = record.split("\t")
            mode, _, blob = info.split()
            tree[path] = (mode, subprocess.run(["git", "-C", str(clone), "cat-file", "blob", blob], check=True,
                                               capture_output=True, env={**os.environ, **GIT_ENV}).stdout)
        # Every file but the link that leads out of the folder, and nothing else.
        self.assertEqual(sorted(path.name for path in copy.iterdir()), sorted(set(tree) - {"outside-link"}))
        for path, (mode, data) in tree.items():
            if path == "outside-link":
                continue
            with self.subTest(path=path):
                if mode == "120000":
                    self.assertEqual(os.readlink(copy / path), data.decode())
                else:
                    self.assertFalse((copy / path).is_symlink())
                    self.assertEqual((copy / path).read_bytes(), data)
                    self.assertEqual(os.access(copy / path, os.X_OK), mode == "100755")
        self.assertEqual(tree["stamp.txt"][1], b"$Format:%an %s$\n")
        self.assertEqual(tree["run.sh"][0], "100755")

    def test_a_link_that_leads_inside_through_a_later_link_reaches_the_reviewer(self) -> None:
        clone = self.world.root / "linked"
        git(self.world.root, "clone", "-q", str(self.world.replay_clone), str(clone))
        git(clone, "checkout", "-q", "--detach", self.world.replay)
        (clone / "sub" / "deep").mkdir(parents=True)
        (clone / "sub" / "deep" / "kept.txt").write_text("deep\n")
        # z-link sorts after the links that go through it. Read as a plain folder, z-link/../.. is outside the copy;
        # through the link it is the copy's root.
        (clone / "z-link").symlink_to("sub/deep")
        (clone / "a-link").symlink_to("z-link/../../report.txt")
        (clone / "b-link").symlink_to("z-link/../../../outside")
        linked = commit(clone, "Links", ("Replay Author", "replay@example.com"), {})
        result = self.world.judge("A-7", "direct", "--commit", linked, "--from", str(clone))
        self.assertEqual(result.returncode, 0, result.stderr)
        copy = self.world.records / "copy"
        self.assertEqual({name: os.readlink(copy / name) for name in ("a-link", "z-link")},
                         {"a-link": "z-link/../../report.txt", "z-link": "sub/deep"})
        self.assertEqual((copy / "a-link").read_text(), "rows\ntotal from replay\n")
        for gone in ("b-link", "outside-link"):
            self.assertFalse((copy / gone).is_symlink(), gone)

    def set_requirements(self, *value: object) -> None:
        """Give the set entry `value` as its requirements, or no requirements field when no value is given."""
        path = self.world.state / "replay-set-1.json"
        listed = json.loads(path.read_text())
        listed["tickets"][0].pop("requirements", None)
        if value:
            listed["tickets"][0]["requirements"] = value[0]
        path.write_text(json.dumps(listed))

    def test_the_requirements_are_the_set_entry_s_list_numbered_in_order(self) -> None:
        # The body still lists three; the entry's list, which the draw wrote, is what the reviewer is given.
        self.set_requirements(["Only this one.", "And this,\nwhich wraps."])
        self.world.answer("R1: met\nR2: met")
        self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
        prompt = self.world.record("prompt")
        requirements = prompt.split("the ticket gives them:\n\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(requirements.splitlines(), ["R1: Only this one.", "R2: And this,", "which wraps."])
        self.assertIn("<ticket>\nPrint the total\n\n" + BODY.strip() + "\n</ticket>\n", prompt)

    def test_an_entry_without_a_list_of_requirements_each_with_text_is_an_error_before_any_checkout(self) -> None:
        for value in ((), ([],), (["One.", 3],), ([""],), (["One.", " \n"],), ("One.",), (3,), (None,),
                      ({"R1": "One."},)):
            with self.subTest(value=value):
                self.set_requirements(*value)
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "judge: the set entry of ticket A-7 holds no requirements: a list "
                                                "of strings, each with text, as the draw writes it.\n")
                self.assertFalse((self.world.records / "gh").exists())
                self.assertFalse((self.world.records / "args").exists())
                self.assertFalse((self.world.state / "verdicts.jsonl").exists())
                self.assertFalse((self.world.state / "judged").exists())

    def test_a_list_the_draw_stores_passes_the_judge_s_check_and_keeps_its_unicode(self) -> None:
        # The draw's command line stores a ticket's list, the test copies that list into the judge's entry A-7, and
        # the judge's command line passes it and numbers its items with their text as stored. An item left with only
        # white space that is not a space, such as a no-break space, is one the draw refuses.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        self.addCleanup(sys.path.remove, str(Path(__file__).resolve().parent))
        drawing = importlib.import_module("test_draw")
        for criteria, stored in (("## Acceptance\n\n- [ ]  Keep the space.\n- [x]  Save.",
                                  [" Keep the space.", " Save."]),
                                 ("## Acceptance\n\n- [ ]  \n- Save.", None)):
            with self.subTest(criteria=criteria):
                folder = tempfile.TemporaryDirectory()
                self.addCleanup(folder.cleanup)
                draw = drawing.World(Path(folder.name), drawing.full_pool(criteria=criteria))
                result = draw.draw()
                if stored is None:
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertIn("Refused 36 tickets of the listed repos: a list under a criteria heading that the "
                                  "draw cannot read with certainty keeps each out of the pool.", result.stdout)
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                [entry, *_] = draw.set_file()["tickets"]
                self.assertEqual(entry["requirements"], stored)
                self.set_requirements(entry["requirements"])
                self.world.answer("R1: met\nR2: met")
                self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
                self.assertIn("R1:  Keep the space.\nR2:  Save.\n", self.world.record("prompt"))

    def test_the_help_points_to_the_draw_for_the_list_and_states_no_grammar(self) -> None:
        help_text = " ".join(self.world.judge("--help").stdout.split())
        self.assertIn(" The requirements are the list the draw stored in the ticket's entry of the replay set, "
                      "numbered R1, R2 and on in the order written. python3 scripts/draw.py --help says which "
                      "lists the draw reads. ", help_text)
        for gone in ("a marker numbered other than 1 right after a line of text", "with certainty",
                     "each with its text on its marker line", "stops the judge with an error that names the line"):
            self.assertNotIn(gone, help_text)

    def test_an_interrupt_after_the_line_is_written_keeps_the_files_it_names(self) -> None:
        version = ("A-7", "direct", "--commit", self.world.replay, "--from", str(self.world.replay_clone))
        self.world.judge(*version)
        [earlier] = self.world.verdicts()
        earlier_folder = (self.world.state / earlier["check"]["output"]).parent
        removing = shutil.rmtree

        def interrupted(path, *args, **kwargs):
            if Path(path) == earlier_folder:
                raise KeyboardInterrupt
            return removing(path, *args, **kwargs)
        with self.assertRaises(KeyboardInterrupt):
            self.world.judge_here(list(version), lambda judge: mock.patch.object(judge.shutil, "rmtree", interrupted))
        [line] = self.world.verdicts()
        self.assertNotEqual(line["judged_at"] + line["check"]["output"], earlier["judged_at"] + earlier["check"]["output"])
        for path in (line["check"]["output"], line["review"]["lines"], line["review"]["prompt"]):
            self.assertTrue((self.world.state / path).is_file(), path)
        self.assertEqual((self.world.state / line["review"]["log"]).read_bytes(), self.world.written())

    def test_the_diff_for_generation_one_runs_from_where_its_branch_started(self) -> None:
        self.world.judge("A-7", "generation-one")
        diff = self.world.record("prompt").split("<diff>\n", 1)[1].split("</diff>", 1)[0]
        # From the commit before the merged PR, the diff would also take back main's later notes.txt.
        self.assertEqual(re.findall(r"^diff --git a/(\S+)", diff, re.M), ["broken", "report.txt"])
        self.assertNotIn("main only", diff)

    def test_the_review_lines_decide_test_two(self) -> None:
        cases = {  # answer: (test 2 passed, proven findings, right first time)
            "R1: met\nR2: met\nR3: met": (True, 0, True),
            "R1: met\n\nR2: met\nR3: met\nF1: report.txt:2: Wording. Evidence: none": (True, 0, True),
            "R1: met\nR2: not met\nR3: met\nF1: report.txt:2: R2 skips blank rows. Evidence: fails: a file with "
            "one blank row -> the total is one short.": (False, 1, False),
            "R1: met\nR2: not met\nR3: met\nF1: report.txt:2: No blank rows. Evidence: breaks R2: it counts "
            "rows with text only.": (False, 1, False),
            "R1: met\nR2: not met\nR3: met\nF1: report.txt:2: Blank rows. Evidence: fails R2: a file with one "
            "blank row -> the total is one short.": (False, 1, False),
            "R1: met\nR2: cannot tell\nR3: met": (False, 1, False),
            "R1: met\nR2: met\nR3: met\nF1: report.txt:1: Counts the header. Evidence: fails: a file of two rows "
            "-> the total is 3.": (False, 1, False),
        }
        for answer, (passed, proven, right) in cases.items():
            with self.subTest(answer=answer):
                self.world.answer(answer)
                result = self.world.judge("A-7", "direct", "--commit", self.world.replay, "--from",
                                          str(self.world.replay_clone))
                self.assertEqual(result.returncode, 0, result.stderr)
                [verdict] = self.world.verdicts()
                self.assertEqual((verdict["review"]["passed"], verdict["review"]["proven"], verdict["right_first_time"]),
                                 (passed, proven, right))
                self.assertEqual(result.stdout.splitlines()[-1],
                                 f"A-7 direct is {'right' if right else 'not right'} first time.")

    def test_a_finding_line_is_read_into_its_parts(self) -> None:
        self.world.answer("R1: not met\nR2: met\nR3: met\nF1: docs/a b.md:12: Says 3. Evidence: breaks R1: it prints "
                          "no total.\nF2: report.txt:1: Terse. Evidence: none")
        self.world.judge("A-7", "generation-one")
        self.assertEqual(self.world.verdicts()[0]["review"]["findings"], [
            {"finding": "F1", "file": "docs/a b.md", "line": 12, "what": "Says 3.",
             "evidence": "breaks R1: it prints no total.", "requirements": ["R1"], "proven": True},
            {"finding": "F2", "file": "report.txt", "line": 1, "what": "Terse.", "evidence": "none",
             "requirements": [], "proven": False}])

    def test_a_finding_in_a_file_whose_name_holds_a_colon_is_read(self) -> None:
        self.world.answer("R1: not met\nR2: met\nR3: met\nF1: jobs/report:daily.sql:17: wrong join Evidence: breaks "
                          "R1: drops rows")
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.world.verdicts()[0]["review"]["findings"], [
            {"finding": "F1", "file": "jobs/report:daily.sql", "line": 17, "what": "wrong join",
             "evidence": "breaks R1: drops rows", "requirements": ["R1"], "proven": True}])

    def test_a_file_name_ends_at_its_first_line_number_even_when_the_rest_then_does_not_fit(self) -> None:
        for finding in ("F1: jobs/x:2:y:17: wrong join Evidence: breaks R1: drops rows",
                        "F1: app.py:17:  R42 at helper.py:3: wrong total Evidence: fails R1: two rows -> none"):
            with self.subTest(finding=finding):
                self.world.answer(f"R1: not met\nR2: met\nR3: met\n{finding}")
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 3, result.stderr)
                [verdict] = self.world.verdicts()
                self.assertEqual((verdict["right_first_time"], verdict["review"]["reason"]),
                                 (None, "the answer is not in the fixed lines"))

    def test_a_label_like_r42_in_the_evidence_names_no_requirement(self) -> None:
        self.set_requirements(["The report prints the total."])
        self.world.answer("R1: not met\nF1: report.txt:2: wrong total Evidence: fails R1: give the row labelled R42 "
                          "-> the total is wrong")
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        [verdict] = self.world.verdicts()
        self.assertEqual((verdict["review"]["requirements"], verdict["review"]["passed"]), ({"R1": "not met"}, False))
        self.assertEqual(verdict["review"]["findings"], [
            {"finding": "F1", "file": "report.txt", "line": 2, "what": "wrong total",
             "evidence": "fails R1: give the row labelled R42 -> the total is wrong", "requirements": ["R1"],
             "proven": True}])

    def test_the_help_says_where_a_file_name_ends_and_which_r_n_name_a_requirement(self) -> None:
        # The prompt gives the same rules: test_the_help_and_the_prompt_state_the_same_rules.
        help_text = " ".join(self.world.judge("--help").stdout.split())
        for sentence in ("<file> may hold a colon: it ends at the first colon that is followed by digits and a colon. "
                         "Those digits are <line>, a line number from 1 with no leading zero.",
                         'A finding names a requirement by its R<n> in <what is wrong> or right after "breaks" or '
                         '"fails". An R<n> later in the evidence, such as a label in what to give, names none.'):
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, help_text)

    def test_a_finding_names_each_requirement_its_line_holds(self) -> None:
        self.world.answer("R1: not met\nR2: met\nR3: not met\nF1: report.txt:1: R1 and R3 lack the total; R2D2 is "
                          "no word. Evidence: fails: a two-row file -> printed no total.")
        self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
        [finding] = self.world.verdicts()[0]["review"]["findings"]
        self.assertEqual((finding["requirements"], finding["proven"]), (["R1", "R3"], True))

    def test_the_help_and_the_prompt_state_the_same_rules(self) -> None:
        self.world.judge("A-7", "generation-one")
        help_text = self.world.judge("--help").stdout
        rules = help_text.split("\n  none\n\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("cannot tell", " ".join(rules.split()))
        self.assertIn("F1, F2", rules)
        self.assertIn(" ".join(rules.split()), " ".join(self.world.record("prompt").split()))

    def test_an_answer_outside_the_fixed_lines_gives_no_verdict(self) -> None:
        cases = {
            "```\nR1: met\nR2: met\nR3: met\n```": "the answer is not in the fixed lines",
            "All three are met.\nR1: met\nR2: met\nR3: met": "the answer is not in the fixed lines",
            "R1: met\nR2: met": "the answer is not in the fixed lines",
            "R1: met\nR3: met\nR2: met": "the answer is not in the fixed lines",
            "R1: met\nR2: met\nR3: met\nR4: met": "the answer is not in the fixed lines",
            "R1: Met\nR2: met\nR3: met": "the answer is not in the fixed lines",
            "R1: met\nR2: met\nR3: met\nF1: report.txt: no line. Evidence: x": "the answer is not in the fixed lines",
            "R1: met\nR2: met\nR3: met\nF2: report.txt:1: Skips F1. Evidence: none": "the answer is not in the fixed lines",
            "": "the answer is not in the fixed lines",
            # A finding with no text saying what is wrong.
            "R1: met\nR2: met\nR3: met\nF1: report.txt:1: Evidence: none": "the answer is not in the fixed lines",
            # Evidence in none of the forms.
            "R1: met\nR2: met\nR3: met\nF1: report.txt:1: Odd. Evidence: Maybe.": "the answer is not in the fixed lines",
            "R1: met\nR2: met\nR3: met\nF1: report.txt:1: Odd. Evidence: fails: a blank row": "the answer is not in "
            "the fixed lines",
            # A requirement not met with no proven finding that names it.
            "R1: met\nR2: not met\nR3: met": "the answer is not in the fixed lines",
            "R1: met\nR2: not met\nR3: met\nF1: report.txt:2: No blank rows. Evidence: none": "the answer is not in "
            "the fixed lines",
            "R1: met\nR2: not met\nR3: met\nF1: report.txt:2: No total. Evidence: breaks R1: no total.": "the answer is "
            "not in the fixed lines",
            "R1: met\nR2: met\nR3: met\nF1: report.txt:2: Wording. Evidence: none.": "the answer is not in the "
            "fixed lines",
            # A finding that names a requirement and proves nothing: neither a breach nor a passing remark.
            "R1: met\nR2: met\nR3: met\nF1: report.txt:1: This line violates R1 by printing just the rows and "
            "omitting the total. Evidence: none": "the answer is not in the fixed lines",
            "R1: met\nR2: not met\nR3: met\nF1: report.txt:2: R2 skips blank rows. Evidence: none": "the answer is "
            "not in the fixed lines",
            # A finding that names a requirement the ticket does not have.
            "R1: met\nR2: met\nR3: met\nF1: report.txt:2: R4 is short. Evidence: fails: one row -> no total.": "the "
            "answer is not in the fixed lines",
            "R1: met\nR2: met\nR3: met\nF1: report.txt:2: Extra. Evidence: breaks R4: no such.": "the answer is not in "
            "the fixed lines",
            # A requirement not met whose label is only in the body of the evidence, as a row label, is not shown.
            "R1: not met\nR2: met\nR3: met\nF1: report.txt:2: total missing Evidence: fails: give the R1 row -> "
            "zero": "the answer is not in the fixed lines",
        }
        for answer, reason in cases.items():
            with self.subTest(answer=answer):
                self.world.answer(answer)
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 3, result.stderr)
                [verdict] = self.world.verdicts()
                self.assertEqual((verdict["right_first_time"], verdict["review"]["passed"], verdict["review"]["reason"]),
                                 (None, None, reason))
                self.assertEqual(result.stdout.splitlines()[-1], "No verdict for A-7 generation-one.")
                self.assertEqual(self.world.saved(verdict["review"]["lines"]), answer)

    def test_a_review_session_that_fails_gives_no_verdict(self) -> None:
        cases = [("R1: met\nR2: met\nR3: met", 1, None, "the review session failed with exit 1"),
                 (None, 0, json.dumps({"type": "result", "is_error": True, "result": "R1: met\nR2: met\nR3: met"}),
                  "the review session ended in an error"),
                 (None, 0, "not JSON", "the review session gave no result"),
                 (None, 0, json.dumps([{"type": "system", "subtype": "init"}]), "the review session gave no result"),
                 (None, 0, json.dumps({"type": "assistant", "result": "R1: met\nR2: met\nR3: met"}),
                  "the review session gave no result")]
        for text, exit, raw, reason in cases:
            with self.subTest(exit=exit, raw=raw):
                self.world.answer(text or "", exit, raw)
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 3, result.stderr)
                [verdict] = self.world.verdicts()
                self.assertIsNone(verdict["right_first_time"])
                self.assertEqual(verdict["review"]["reason"], reason)

    def test_the_result_is_read_from_every_message_when_settings_make_the_output_verbose(self) -> None:
        # With "verbose" on in the user's settings, --output-format json prints the list of messages, the result last.
        self.world.answer("", 0, json.dumps([
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "R1: not met"}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "R1: met\nR2: met\nR3: met"}]))
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.world.verdicts()[0]["review"]["requirements"], {"R1": "met", "R2": "met", "R3": "met"})
        self.assertEqual(self.world.saved(self.world.verdicts()[0]["review"]["lines"]), "R1: met\nR2: met\nR3: met")

    def test_the_review_changes_neither_the_version_nor_its_repo(self) -> None:
        clone = self.world.replay_clone
        before = (git(clone, "rev-parse", "HEAD"), git(clone, "rev-parse", f"{self.world.replay}^{{tree}}"),
                  git(clone, "status", "--porcelain"), (clone / "counter").read_text())
        self.world.judge("A-7", "direct", "--commit", self.world.replay, "--from", str(clone))
        # The stand-in wrote app.txt and removed counter in its working folder, which is a copy.
        self.assertIn("counter", self.world.record("files").split())
        after = (git(clone, "rev-parse", "HEAD"), git(clone, "rev-parse", f"{self.world.replay}^{{tree}}"),
                 git(clone, "status", "--porcelain"), (clone / "counter").read_text())
        self.assertEqual(after, before)

    def test_judging_a_version_again_replaces_its_verdict(self) -> None:
        self.world.judge("A-7", "generation-one")
        self.world.judge("A-7", "direct", "--commit", self.world.replay, "--from", str(self.world.replay_clone))
        self.world.answer("R1: met\nR2: cannot tell\nR3: met")
        self.world.judge("A-7", "generation-one")
        verdicts = self.world.verdicts()
        self.assertEqual([(verdict["version"], verdict["review"]["passed"]) for verdict in verdicts],
                         [("direct", True), ("generation-one", False)])
        # Only the files the two lines name are kept: the replaced attempt's log goes with its folder.
        self.assertEqual(list(self.world.files()), sorted(
            path for verdict in verdicts for path in (verdict["check"]["output"], verdict["review"]["lines"],
                                                      verdict["review"]["prompt"], verdict["review"]["log"])))

    def test_a_failed_attempt_leaves_the_earlier_verdict_and_its_files_as_they_were(self) -> None:
        self.assertEqual(self.world.judge("A-7", "direct", "--commit", self.world.replay, "--from",
                                          str(self.world.replay_clone)).returncode, 0)
        verdicts, files = self.world.verdicts(), self.world.files()
        # A second attempt whose check fails, and whose repo is taken away during its review.
        clone, broken = self.world.version("Break it", {"broken": b"x\n"})
        self.world.breaking = str(clone / ".git")
        result = self.world.judge("A-7", "direct", "--commit", broken, "--from", str(clone))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "judge: the version's commit or its tree changed during the review.\n")
        self.assertEqual(self.world.verdicts(), verdicts)
        [folder] = self.unnamed()  # the second attempt, kept with the log of its review
        self.assertEqual(self.outside(folder), files)
        self.assertEqual((folder / "session.jsonl").read_bytes(), self.world.written())

    def outside(self, *folders: Path) -> dict[str, str]:
        """Every file the judge saved, by path, but those in `folders`."""
        return {path: text for path, text in self.world.files().items()
                if not any((self.world.state / path).is_relative_to(folder) for folder in folders)}

    def unnamed(self) -> list[Path]:
        """The attempts' folders that no line names."""
        named = {(self.world.state / line["check"]["output"]).parent for line in
                 (self.world.verdicts() if (self.world.state / "verdicts.jsonl").exists() else [])}
        return [folder for folder in sorted((self.world.state / "judged").glob("*/*")) if folder not in named]

    def test_an_error_or_interrupt_after_the_review_started_keeps_its_answer_and_log(self) -> None:
        version = ["A-7", "direct", "--commit", self.world.replay, "--from", str(self.world.replay_clone)]
        self.assertEqual(self.world.judge(*version).returncode, 0)
        verdicts, files = self.world.verdicts(), self.world.files()
        self.world.log_folder = "1"
        running, removing, copying = subprocess.run, shutil.rmtree, shutil.copyfileobj
        config = Path(self.world.config)

        def stopped(args, *rest, **kwargs):  # the session is interrupted after it has written its log
            if args[0] != "claude":
                return running(args, *rest, **kwargs)
            try:
                return running(args, *rest, **{**kwargs, "timeout": 2})
            except subprocess.TimeoutExpired:
                raise KeyboardInterrupt

        def ended(judge):  # an interrupt as soon as the session has ended, before its answer is written
            review = judge.review

            def interrupted(*args):
                review(*args)
                raise KeyboardInterrupt
            return mock.patch.object(judge, "review", interrupted)

        def unremoved(path, *args, **kwargs):  # an interrupt as the judge removes what Claude Code wrote
            if Path(path).is_relative_to(config):
                raise KeyboardInterrupt
            return removing(path, *args, **kwargs)

        def denied(path, *args, **kwargs):  # the judge may not remove what Claude Code wrote
            if Path(path).is_relative_to(config):
                raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
            return removing(path, *args, **kwargs)

        def full(suffix):  # the disk fills after 8 bytes of the copy of a file whose name ends in `suffix`
            def copy(found, kept, *args):
                if not found.name.endswith(suffix):
                    return copying(found, kept, *args)
                kept.write(found.read(8))
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
            return lambda judge: mock.patch.object(judge.shutil, "copyfileobj", copy)
        run = ["check.txt", "prompt.txt"]
        answered = [*run, "review.txt"]
        logged = ["session.jsonl", "session/tool-results/r1.txt"]
        # How the judge ends once the session has started: (patch, its exit code or what it raises, the files left in
        # the attempt's folder or None for no folder, whether the log is still where Claude Code wrote it).
        cases = {
            "the session interrupted": (lambda judge: mock.patch.object(judge.subprocess, "run", stopped),
                                        KeyboardInterrupt, [*run, *logged], False),
            "an interrupt as the session ends": (ended, KeyboardInterrupt, [*run, *logged], False),
            "an interrupt as the session ends and before the log is copied": (
                lambda judge: ExitStack_of(ended(judge), mock.patch.object(
                    judge.shutil, "copyfileobj", side_effect=KeyboardInterrupt)), KeyboardInterrupt, None, True),
            "a full disk as the log is copied": (full(".jsonl"), 1, answered, True),
            "a full disk as the log's folder is copied": (full("r1.txt"), 1, [*answered, "session.jsonl"], True),
            "a denied removal of the source": (lambda judge: mock.patch.object(judge.shutil, "rmtree", denied), 1,
                                               [*answered, *logged], True),
            "an interrupt as the source is removed": (
                lambda judge: mock.patch.object(judge.shutil, "rmtree", unremoved), KeyboardInterrupt,
                [*answered, *logged], True),
            "a failed publish": (lambda judge: mock.patch.object(judge, "publish", side_effect=OSError("no space")),
                                 OSError, [*answered, *logged], False),
        }
        for case, (patch, ending, left, source_left) in cases.items():
            for folder in self.unnamed():  # what the case before left
                shutil.rmtree(folder)
            shutil.rmtree(config / "projects", ignore_errors=True)
            with self.subTest(case=case):
                self.world.sleep = "60" if case == "the session interrupted" else ""
                if isinstance(ending, int):
                    self.assertEqual(self.world.judge_here(version, patch), ending)
                else:
                    with self.assertRaises(ending):
                        self.world.judge_here(version, patch)
                [source] = [*config.glob("projects/*/*.jsonl")] or [None]
                folders = self.unnamed()
                if ending == 1 and case == "a denied removal of the source":
                    self.assertEqual(self.world.stderr, f"judge: the review session's log is kept whole in "
                                                        f"{folders[0]}; its original in {source.parent} could not be "
                                                        "removed.\n")
                elif ending == 1:
                    self.assertEqual(self.world.stderr,
                                     f"judge: the review session's log could not be copied; it is still at {source}.\n")
                self.assertEqual(self.world.verdicts(), verdicts)
                self.assertEqual(self.outside(*folders), files)
                self.assertEqual([sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())
                                  for folder in folders], [] if left is None else [sorted(left)])
                for folder in folders:  # each file kept is whole
                    if (folder / "review.txt").exists():
                        self.assertEqual((folder / "review.txt").read_bytes(), b"R1: met\nR2: met\nR3: met\n")
                    if (folder / "session.jsonl").exists():
                        self.assertEqual((folder / "session.jsonl").read_bytes(), self.world.written())
                    for kept in folder.glob("session/*/*"):
                        self.assertEqual(kept.read_bytes(), b"a large result\n")
                self.assertEqual(source is not None, source_left)
                if source_left:  # the log and its folder where Claude Code wrote them, whole
                    self.assertEqual(source.read_bytes(), self.world.written())
                    self.assertEqual({str(path.relative_to(source.with_suffix(""))): path.is_file() and path.read_bytes()
                                      for path in source.with_suffix("").rglob("*")},
                                     {"tool-results": False, "tool-results/r1.txt": b"a large result\n"})
        help_text = " ".join(self.world.judge("--help").stdout.split())
        for sentence in ("On an error or an interrupt the judge tries to remove its own attempt's folder when no line "
                         "names it and it holds neither review.txt nor session.jsonl; otherwise the folder stays.",
                         "When an error, not an interrupt, stops the judge as it copies the log or removes it from "
                         "$CLAUDE_CONFIG_DIR/projects, the error says where the whole log is."):
            self.assertEqual(help_text.count(sentence), 1)

    def test_a_text_file_that_is_not_utf8_reaches_the_reviewer(self) -> None:
        clone, legacy = self.world.version("Latin-1 notes", {"legacy.txt": b"caf\xe9\n"})
        result = self.world.judge("A-7", "direct", "--commit", legacy, "--from", str(clone))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("+++ b/legacy.txt\n@@ -0,0 +1 @@\n+caf\\xe9\n", self.world.record("prompt"))

    def test_the_check_is_the_one_the_draw_reads_from_the_repo_list(self) -> None:
        # Two entries for one repo: the draw keeps the last, so the judge runs the last one's check too.
        (self.world.state / "repos.json").write_text(json.dumps([
            {"repo": REPO, "check": "false"}, {"repo": REPO.upper(), "check": CHECK, "setup": SETUP}]))
        self.world.judge("A-7", "direct", "--commit", self.world.replay, "--from", str(self.world.replay_clone))
        [verdict] = self.world.verdicts()
        self.assertEqual(self.world.saved(verdict["check"]["output"]),
                         f"$ {SETUP}\n\nsetup exit 0\n$ {CHECK}\n\ncheck exit 0\n")

    def test_a_repo_list_the_draw_refuses_is_an_error(self) -> None:
        path = self.world.state / "repos.json"
        path.write_text(json.dumps([{"repo": REPO, "check": "   "}]))
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f'judge: {path} must be a list of {{"repo": "owner/name", "check": "...", '
                                        '"setup": "..."} objects, with setup optional.\n')
        self.assertFalse((self.world.state / "verdicts.jsonl").exists())

    def test_a_ledger_line_that_is_not_json_is_an_error_before_any_checkout(self) -> None:
        path = self.world.state / "verdicts.jsonl"
        path.write_text('{"label": "A", "ticket": 7, "version": "direct"}\n\nnot json\n')
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"judge: {path} line 3 cannot be read as a JSON object.\n")
        self.assertFalse((self.world.records / "gh").exists())
        self.assertFalse((self.world.records / "args").exists())
        self.assertFalse((self.world.state / "judged").exists())
        self.assertFalse((self.world.state / "judge-work").exists())
        self.assertEqual(path.read_text(), '{"label": "A", "ticket": 7, "version": "direct"}\n\nnot json\n')

    def test_a_ledger_that_breaks_during_the_review_is_one_error_and_the_reviewed_attempt_stays(self) -> None:
        self.assertEqual(self.world.judge("A-7", "generation-one").returncode, 0)
        verdicts, files = self.world.verdicts(), self.world.files()
        # The stand-in adds a line that is not JSON to the ledger before it answers.
        path = self.world.state / "verdicts.jsonl"
        stand_in = self.world.bin / "claude"
        shebang, rest = stand_in.read_text().split("\n", 1)
        stand_in.write_text(f"{shebang}\necho 'not json' >> \"$DELIVER_STATE_DIR/verdicts.jsonl\"\n{rest}")
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"judge: {path} line 2 cannot be read as a JSON object.\n")
        self.assertTrue((self.world.records / "args").exists())
        [line, broken] = path.read_text().splitlines()
        self.assertEqual(([json.loads(line)], broken), (verdicts, "not json"))
        # The files of the line on record are as they were; the attempt's folder stays with its answer and log.
        [earlier] = [(self.world.state / line["check"]["output"]).parent for line in verdicts]
        [folder] = [folder for folder in earlier.parent.iterdir() if folder != earlier]
        self.assertEqual(self.outside(folder), files)
        self.assertTrue((folder / "review.txt").is_file() and (folder / "session.jsonl").is_file())

    def test_a_ledger_saved_with_a_byte_order_mark_or_as_utf16_is_an_error_before_any_checkout(self) -> None:
        path = self.world.state / "verdicts.jsonl"
        for encoding in ("utf-8-sig", "utf-16"):
            with self.subTest(encoding=encoding):
                path.write_text('{"label": "A", "ticket": 7, "version": "direct"}\n', encoding=encoding)
                result = self.world.judge("A-7", "generation-one")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, f"judge: {path} line 1 cannot be read as a JSON object.\n")
                self.assertFalse((self.world.records / "gh").exists())
                self.assertFalse((self.world.state / "judged").exists())

    def test_a_ledger_line_of_unicode_spaces_is_blank(self) -> None:
        (self.world.state / "verdicts.jsonl").write_text('{"label": "A", "ticket": 9, "version": "direct"}\n'
                                                         ' 　 \n')
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([(line["ticket"], line["version"]) for line in self.world.verdicts()],
                         [(9, "direct"), (7, "generation-one")])

    def test_a_ledger_line_that_names_no_attempt_folder_is_replaced(self) -> None:
        (self.world.state / "verdicts.jsonl").write_text('{"label": "A", "ticket": 7, "version": "generation-one", '
                                                         '"check": null}\n')
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        [verdict] = self.world.verdicts()
        self.assertTrue((self.world.state / verdict["check"]["output"]).is_file())
        self.assertEqual(len(list((self.world.state / "judged" / "A-7-generation-one").iterdir())), 1)

    def test_a_ledger_that_breaks_during_the_review_after_a_line_with_no_check_is_one_error(self) -> None:
        # The stand-in writes a line whose check is null, then one that is not JSON, before it answers.
        path = self.world.state / "verdicts.jsonl"
        stand_in = self.world.bin / "claude"
        shebang, rest = stand_in.read_text().split("\n", 1)
        stand_in.write_text(f"{shebang}\nprintf '%s\\nbad\\n' '{{\"check\": null}}' > \"$DELIVER_STATE_DIR/"
                            f"verdicts.jsonl\"\n{rest}")
        result = self.world.judge("A-7", "generation-one")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"judge: {path} line 2 cannot be read as a JSON object.\n")
        self.assertEqual(path.read_text(), '{"check": null}\nbad\n')
        [folder] = (self.world.state / "judged" / "A-7-generation-one").iterdir()  # it holds a review, so it stays
        self.assertTrue((folder / "review.txt").is_file() and (folder / "session.jsonl").is_file())

    def test_a_ledger_that_breaks_before_an_interrupted_review_names_no_attempt(self) -> None:
        # The stand-in writes a line whose check is null, then one that is not JSON, and is interrupted before it
        # answers or leaves a log: the attempt's folder holds no review, and no line the judge can read names it.
        path = self.world.state / "verdicts.jsonl"
        stand_in = self.world.bin / "claude"
        shebang, rest = stand_in.read_text().split("\n", 1)
        stand_in.write_text(f"{shebang}\nprintf '%s\\nbad\\n' '{{\"check\": null}}' > \"$DELIVER_STATE_DIR/"
                            f"verdicts.jsonl\"\n{rest}")
        self.world.log, self.world.sleep = None, "60"
        running = subprocess.run

        def stopped(args, *rest, **kwargs):
            if args[0] != "claude":
                return running(args, *rest, **kwargs)
            try:
                return running(args, *rest, **{**kwargs, "timeout": 2})
            except subprocess.TimeoutExpired:
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.world.judge_here(["A-7", "generation-one"], lambda judge: mock.patch.object(judge.subprocess, "run",
                                                                                            stopped))
        self.assertEqual(self.world.stderr, "")
        self.assertEqual(path.read_text(), '{"check": null}\nbad\n')
        self.assertEqual(list((self.world.state / "judged" / "A-7-generation-one").iterdir()), [])

    def test_bad_usage_exits_2_with_the_help(self) -> None:
        for args in ([], ["A-7"], ["a-7", "generation-one"], ["A-07", "generation-one"], ["A-7", "Direct"],
                     ["A-7", "direct"], ["A-7", "direct", "--commit", "abc"],
                     ["A-7", "direct", "--commit", "abc", "--commit", "abc"],
                     ["A-7", "generation-one", "--commit", "abc", "--from", "."]):
            with self.subTest(args=args):
                result = self.world.judge(*args)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.startswith("Judge one version of a replay ticket by the two tests "
                                                         "every version gets.\n"))
        self.assertFalse((self.world.state / "verdicts.jsonl").exists())

    def test_a_ticket_in_no_set_is_an_error(self) -> None:
        result = self.world.judge("A-9", "generation-one")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"judge: no replay set in {self.world.state} holds ticket A-9.\n")
        self.assertFalse((self.world.state / "verdicts.jsonl").exists())

    def test_a_commit_its_repo_lacks_is_an_error(self) -> None:
        result = self.world.judge("A-7", "direct", "--commit", "f" * 40, "--from", str(self.world.replay_clone))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"judge: commit {'f' * 40} is not in the version's repo.\n")
        self.assertFalse((self.world.state / "verdicts.jsonl").exists())
        self.assertEqual(self.unnamed(), [])  # an error before the review takes the attempt's folder back


if __name__ == "__main__":
    unittest.main()
