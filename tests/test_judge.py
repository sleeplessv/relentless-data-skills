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


if __name__ == "__main__":
    unittest.main()
