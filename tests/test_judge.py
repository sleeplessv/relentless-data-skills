"""Exercise scripts/judge.py at its command line against a world the tests build.

Each test builds its own world in a temporary folder: a bare git repo that a
stand-in `gh` clones, a replay's clone beside it, a replay set and a repo list
in a machine directory of its own, and a stand-in `claude`, first on PATH, that
records how it was started and prints a saved review answer. No test touches
the network, the real machine directory or a real session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REPO = "example-org/alpha"
CHECK = "test -e .setup-done && test ! -e broken"
SETUP = "touch .setup-done"
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
# Records each argument on a line of its own, the prompt it reads, its working folder and what that folder
# holds; tries to change the folder; then prints the saved answer as Claude Code's JSON result.
CLAUDE = r"""#!/bin/sh
printf '%s\n' "$@" > "$CLAUDE_ARGS"
cat > "$CLAUDE_PROMPT"
pwd > "$CLAUDE_CWD"
if git rev-parse --git-dir > /dev/null 2>&1; then echo inside > "$CLAUDE_GIT"; else echo outside > "$CLAUDE_GIT"; fi
ls -A > "$CLAUDE_FILES"
echo "the reviewer wrote this" > app.txt
rm -f counter
if [ -n "$CLAUDE_STDERR" ]; then echo "$CLAUDE_STDERR" >&2; fi
cat "$CLAUDE_ANSWER"
exit "${CLAUDE_EXIT:-0}"
"""


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True, capture_output=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


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
        self.base = commit(work, "Start", owner, {"counter": "1\n", "report.txt": "rows\n"})
        git(work, "checkout", "-q", "-b", "ticket-7-the-branch")
        # Generation one's commit first marked ready still holds `broken`; the fix after ready removes it.
        self.ready = commit(work, "Branch work for ticket 7", gen_one, {"report.txt": "rows\ntotal\n", "broken": "x\n"})
        self.fixed = commit(work, "Fix after ready", gen_one, {"broken": None})
        git(work, "checkout", "-q", "main")
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
                         "body": BODY, "base_commit": self.base, "ready_commit": self.ready, "model": "test-model",
                         "pr": 8, "session": "s-1", "log": "logs/s-1.jsonl", "check_output": "checks/A-7.txt"}]}))
        self.answer("R1: met\nR2: met\nR3: met\n")

    def answer(self, text: str, exit: int = 0, raw: str | None = None) -> None:
        """The stand-in's next answer: `text` as the result of Claude Code's JSON, or `raw` printed as it is."""
        result = {"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": "s-r"}
        (self.root / "answer").write_text(json.dumps(result) if raw is None else raw)
        self.exit = exit

    def judge(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
        env.update({"HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(self.state),
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.records / "gh"),
                    "GH_REMOTES": str(self.remotes), "CLAUDE_ANSWER": str(self.root / "answer"),
                    "CLAUDE_EXIT": str(self.exit), **{f"CLAUDE_{name.upper()}": str(self.records / name)
                                                      for name in ("args", "prompt", "cwd", "git", "files")}})
        return subprocess.run([sys.executable, str(SCRIPTS / "judge.py"), *args], cwd=self.root / "cwd", env=env,
                              text=True, capture_output=True)

    def record(self, name: str) -> str:
        return (self.records / name).read_text()

    def verdicts(self) -> list[dict]:
        return [json.loads(line) for line in (self.state / "verdicts.jsonl").read_text().splitlines()]


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
        self.assertEqual(verdict["check"], {"passed": True, "reason": None, "output": "judged/A-7-zeta/check.txt"})
        self.assertEqual(verdict["review"], {
            "passed": True, "reason": None, "requirements": {"R1": "met", "R2": "met", "R3": "met"}, "findings": [],
            "proven": 0, "lines": "judged/A-7-zeta/review.txt"})
        self.assertIs(verdict["right_first_time"], True)
        self.assertEqual(result.stdout.splitlines()[1:], [
            f"Test 2, the review: passed. Answer in {self.world.state / 'judged/A-7-zeta/review.txt'}.",
            "A-7 zeta is right first time."])
        self.assertEqual((self.world.state / "judged/A-7-zeta/review.txt").read_text(), "R1: met\nR2: met\nR3: met\n")
        self.assertFalse((self.world.records / "gh").exists())  # its repo is on this machine; GitHub is not asked
        self.assertEqual(list((self.world.state / "judge-work").iterdir()), [])

    def test_the_review_starts_headless_on_opus_at_medium_effort_with_read_tools_only(self) -> None:
        self.world.judge("A-7", "generation-one")
        self.assertEqual(self.world.record("args").splitlines(), [
            "-p", "--model", "opus", "--effort", "medium", "--output-format", "json", "--safe-mode",
            "--strict-mcp-config", "--tools", "Read,Grep,Glob", "--permission-prompts", "none",
            "--no-session-persistence"])

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
                self.assertEqual(prompt, (self.world.state / f"judged/A-7-{version}/prompt.txt").read_text())
                seen = prompt + self.world.record("args") + self.world.record("cwd") + self.world.record("files")
                for secret in (*SECRETS, version, self.world.ready, self.world.replay, "A-7"):
                    self.assertNotIn(secret, seen)
                self.assertEqual(self.world.record("git"), "outside\n")
                self.assertNotIn(".git", self.world.record("files").split())

    def test_the_diff_for_generation_one_runs_from_where_its_branch_started(self) -> None:
        self.world.judge("A-7", "generation-one")
        prompt = self.world.record("prompt")
        self.assertIn("+++ b/broken\n", prompt)
        self.assertNotIn("Squash", prompt)

    def test_the_review_lines_decide_test_two(self) -> None:
        cases = {  # answer: (test 2 passed, proven findings, right first time)
            "R1: met\nR2: met\nR3: met": (True, 0, True),
            "R1: met\n\nR2: met\nR3: met\nF1: report.txt:2: Wording. Evidence: none": (True, 0, True),
            "R1: met\nR2: not met\nR3: met\nF1: report.txt:2: No blank rows. Evidence: R2 needs blank rows; "
            "report.txt:2 counts none.": (False, 1, False),
            "R1: met\nR2: not met\nR3: met": (False, 0, False),
            "R1: met\nR2: cannot tell\nR3: met": (False, 1, False),
            "R1: met\nR2: met\nR3: met\nF1: report.txt:1: Breaks the count. Evidence: wc -l prints 3.": (False, 1, False),
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
        self.world.answer("R1: met\nR2: met\nR3: met\nF1: docs/a b.md:12: Says 3. Evidence: R1 needs the total.")
        self.world.judge("A-7", "generation-one")
        self.assertEqual(self.world.verdicts()[0]["review"]["findings"], [
            {"finding": "F1", "file": "docs/a b.md", "line": 12, "what": "Says 3.", "evidence": "R1 needs the total.",
             "proven": True}])

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
                self.assertEqual((self.world.state / "judged/A-7-generation-one/review.txt").read_text(), answer)

    def test_a_review_session_that_fails_gives_no_verdict(self) -> None:
        cases = [("R1: met\nR2: met\nR3: met", 1, None, "the review session failed with exit 1"),
                 (None, 0, json.dumps({"type": "result", "is_error": True, "result": "R1: met\nR2: met\nR3: met"}),
                  "the review session ended in an error"),
                 (None, 0, "not JSON", "the review session gave no result"),
                 (None, 0, json.dumps([{"type": "system", "subtype": "init"}]), "the review session gave no result")]
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
        self.assertEqual((self.world.state / "judged/A-7-generation-one/review.txt").read_text(),
                         "R1: met\nR2: met\nR3: met")

    def test_the_review_changes_neither_the_version_nor_its_repo(self) -> None:
        clone = self.world.replay_clone
        before = (git(clone, "rev-parse", "HEAD"), git(clone, "rev-parse", f"{self.world.replay}^{{tree}}"),
                  git(clone, "status", "--porcelain"), (clone / "counter").read_text())
        self.world.judge("A-7", "direct", "--commit", self.world.replay, "--from", str(clone))
        # The stand-in wrote app.txt and removed counter in its working folder, which is a copy.
        self.assertEqual(self.world.record("files").split(), ["counter", "report.txt"])
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


if __name__ == "__main__":
    unittest.main()
