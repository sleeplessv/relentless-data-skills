"""Exercise scripts/replay.py at its command line against a world the tests build.

Each test builds its own world in a temporary folder: a bare git repo standing in
for the real one, whose last commit is the merged change; a machine directory
holding a hand-written replay set, repo list and label key; a stand-in `gh`,
first on PATH, that clones the bare repo and records every call; and a stand-in
`claude`, first on PATH, that records how it was started, writes a session log
in the shape of Claude Code's and makes a change in its working folder. HOME,
the machine directory and the Claude config directory all point inside the
folder, so no test starts a real session, touches the network, or reads the
real machine directory or a real session log.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REPO = "example-org/alpha"
MODEL = "claude-test-model-1"
TITLE = "Print the total"
BODY = "## Acceptance criteria\n\n- [ ] The report prints the total."

GH = r"""#!/bin/sh
printf '%s\n' "$*" >> "$GH_LOG"
if [ "$1 $2" = "repo clone" ]; then exec git clone -q "$GH_REMOTES/${3#*/}.git" "$4"; fi
echo "stand-in gh: no answer for $*" >&2
exit 1
"""

# The stand-in for Claude Code. It records each start (arguments, working folder, the
# prompt on standard input, the environment and whether setup had run) as one JSON line
# in $STANDIN_STARTS. With STANDIN_NO_SANDBOX set it does what Claude Code does when the
# sandbox cannot start and sandbox.failIfUnavailable is set: it prints an error and
# exits 1 before the session starts, writing no log. Otherwise it writes the session's
# log under $CLAUDE_CONFIG_DIR/projects/, loads the skill STANDIN_SKILL names, writes
# replayed.txt in its working folder and exits with STANDIN_EXIT (default 0).
CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
prompt = sys.stdin.read()
cwd = Path.cwd()
with open(os.environ["STANDIN_STARTS"], "a") as starts:
    starts.write(json.dumps({"args": args, "cwd": str(cwd), "prompt": prompt, "env": dict(os.environ),
                             "setup_done": (cwd / ".setup-done").exists()}) + "\n")
settings = json.loads(args[args.index("--settings") + 1]) if "--settings" in args else {}
if os.environ.get("STANDIN_NO_SANDBOX") and (settings.get("sandbox") or {}).get("failIfUnavailable"):
    print("Error: sandbox required but unavailable", file=sys.stderr)
    sys.exit(1)
session = args[args.index("--session-id") + 1]
folder = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / str(cwd).replace("/", "-")
folder.mkdir(parents=True, exist_ok=True)
base = {"sessionId": session, "cwd": str(cwd), "version": "2.1.332", "userType": "external"}
lines = [{**base, "type": "user", "uuid": "u1", "timestamp": "2026-01-05T10:00:00.000Z",
          "message": {"role": "user", "content": prompt}}]
if os.environ.get("STANDIN_SKILL"):
    lines.append({**base, "type": "user", "uuid": "u2", "timestamp": "2026-01-05T10:00:30.000Z", "isMeta": True,
                  "message": {"role": "user", "content": [{"type": "text", "text":
                      "Base directory for this skill: /skills/" + os.environ["STANDIN_SKILL"] + "\n\n# Body"}]}})
lines.append({**base, "type": "assistant", "uuid": "a1", "timestamp": "2026-01-05T10:02:00.000Z",
              "message": {"model": args[args.index("--model") + 1], "id": "msg_1", "type": "message",
                          "role": "assistant", "content": [{"type": "text", "text": "Done."}],
                          "usage": {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 30,
                                    "cache_read_input_tokens": 40}}})
(folder / (session + ".jsonl")).write_text("".join(json.dumps(line) + "\n" for line in lines))
(cwd / "replayed.txt").write_text("the replay's change\n")
sys.exit(int(os.environ.get("STANDIN_EXIT", "0")))
'''


# What the replay inherits when a Claude Code session runs it: that session's own variables, a login
# token the replayed session needs, and a GitHub token it must not have.
PARENT = {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_SESSION_ID": "parent-session",
          "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_PID": "1", "CLAUDE_CODE_OAUTH_TOKEN": "login-token",
          "GH_TOKEN": "github-token", "GITHUB_TOKEN": "github-token"}
CACHES = (".cache/uv", ".cache/pip", "Library/Caches/pip", ".npm")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


class World:
    """A real repo with one merged change, a machine directory naming its ticket, and the stand-ins."""

    def __init__(self, root: Path, setup: str = "touch .setup-done") -> None:
        self.root = root
        self.home = root / "home"
        self.state = self.home / ".local" / "state" / "deliver"
        self.config = self.home / ".claude"
        self.bin = root / "bin"
        self.remotes = root / "remotes"
        for folder in (self.state, self.config, self.bin, self.remotes):
            folder.mkdir(parents=True)
        self.gh_log = root / "gh.log"
        self.starts = root / "starts.jsonl"
        for name, text in (("gh", GH), ("claude", CLAUDE)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        work = root / "work"
        work.mkdir()
        git("init", "-q", "-b", "main", cwd=work)
        (work / "README.md").write_text("A report.\n")
        git("add", ".", cwd=work)
        git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "start", cwd=work)
        self.base = git("rev-parse", "HEAD", cwd=work)
        (work / "total.py").write_text("print(42)\n")
        git("add", ".", cwd=work)
        git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "the merged change", cwd=work)
        self.merged = git("rev-parse", "HEAD", cwd=work)
        self.bare = self.remotes / "alpha.git"
        git("clone", "-q", "--bare", str(work), str(self.bare), cwd=root)
        shutil.rmtree(work)
        entry = {"label": "A", "ticket": 7, "bucket": "0-50", "size": 1, "title": TITLE, "body": BODY,
                 "base_commit": self.base, "ready_commit": self.merged, "model": MODEL, "pr": 507,
                 "session": "00000000-0000-4000-8000-000000000007", "log": "logs/x.jsonl",
                 "check_output": "checks/A-7.txt"}
        self.write("replay-set-1.json", {"set": 1, "seed": 1, "drawn_at": "2026-01-05T00:00:00+00:00",
                                         "tickets": [entry], "set_aside": []})
        self.write("project-labels.json", {"A": REPO})
        self.write("repos.json", [{"repo": REPO, "check": "true", **({"setup": setup} if setup else {})}])

    def write(self, name: str, data: object) -> None:
        (self.state / name).write_text(json.dumps(data))

    def env(self, **extra: str) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("CLAUDE", "STANDIN_", "GH_", "GITHUB_"))}
        env.update(PATH=f"{self.bin}{os.pathsep}{env['PATH']}", HOME=str(self.home), DELIVER_STATE_DIR=str(self.state),
                   CLAUDE_CONFIG_DIR=str(self.config), GH_LOG=str(self.gh_log), GH_REMOTES=str(self.remotes),
                   STANDIN_STARTS=str(self.starts), TMPDIR=str(self.root), **PARENT, **extra)
        return env

    def replay(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPTS / "replay.py"), *args], cwd=self.root,
                              env=self.env(**extra), text=True, capture_output=True, timeout=120)

    @property
    def clone(self) -> Path:
        return self.state / "replays" / "A-7-direct"

    @property
    def remote(self) -> Path:
        return self.state / "replays" / "A-7-direct.git"

    def starts_made(self) -> list[dict]:
        return [json.loads(line) for line in self.starts.read_text().splitlines()] if self.starts.is_file() else []

    def versions(self) -> list[dict]:
        path = self.state / "versions.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []

    def rows(self) -> list[dict]:
        path = self.state / "scan-rows.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


class ReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.world = World(Path(temp.name).resolve())

    def replay(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        """Run the replay, then hold every session it started to the whole confinement."""
        result = self.world.replay(*args, **extra)
        for start in self.world.starts_made():
            self.assert_confined(start)
        return result

    def assert_confined(self, start: dict) -> None:
        clone, home, args = str(self.world.clone), self.world.home, start["args"]
        self.assertEqual(start["cwd"], clone)
        self.assertEqual(args[0], "-p")

        def value(flag: str) -> str:
            self.assertEqual(args.count(flag), 1, flag)
            return args[args.index(flag) + 1]
        self.assertEqual(value("--permission-mode"), "bypassPermissions")
        self.assertEqual(value("--setting-sources"), "project,local")
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(json.loads(value("--mcp-config")), {"mcpServers": {}})
        caches = [str(home / cache) for cache in CACHES]
        self.assertEqual(json.loads(value("--settings")), {
            "sandbox": {
                "enabled": True,
                "failIfUnavailable": True,
                "allowUnsandboxedCommands": False,
                "excludedCommands": [],
                # The clone's remote is let back in too, so `git fetch origin` works in the sandbox.
                "filesystem": {"denyRead": [str(home)], "allowRead": [clone, str(self.world.remote), *caches],
                               "allowWrite": caches},
                "network": {"allowedDomains": ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"],
                            "strictAllowlist": True},
            },
            "permissions": {"blockReadsOutsideWorkingDirectories": True, "blockWritesOutsideWorkingDirectories": True},
            "disableClaudeAiConnectors": True,
            "disableAllHooks": True,
        })
        env = start["env"]
        self.assertEqual(sorted(key for key in env if key.startswith("CLAUDE")),
                         ["CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"])
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "login-token")
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertEqual(env["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")

    def test_the_clone_is_cut_at_the_commit_before_the_merged_pr_with_no_later_history(self) -> None:
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        clone = self.world.clone
        self.assertEqual(git("rev-parse", "HEAD^", cwd=clone), self.world.base)
        every = git("rev-list", "--all", cwd=clone).split()
        self.assertNotIn(self.world.merged, every)
        missing = subprocess.run(["git", "cat-file", "-e", self.world.merged], cwd=clone, capture_output=True)
        self.assertNotEqual(missing.returncode, 0)

    def test_the_clone_has_only_the_local_copy_as_remote_and_nothing_is_pushed_to_the_real_repo(self) -> None:
        refs = git("for-each-ref", cwd=self.world.bare)
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git("remote", cwd=self.world.clone), "origin")
        self.assertEqual(git("remote", "get-url", "origin", cwd=self.world.clone), str(self.world.remote))
        # The default branch keeps its name, so origin/main is where the ticket's author found it.
        self.assertEqual(git("branch", "--show-current", cwd=self.world.clone), "main")
        self.assertEqual(git("rev-parse", "origin/main", cwd=self.world.clone), self.world.base)
        self.assertNotIn(self.world.merged, git("rev-list", "--all", cwd=self.world.remote).split())
        self.assertEqual(git("for-each-ref", cwd=self.world.bare), refs)
        calls = self.world.gh_log.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith(f"repo clone {REPO} "), calls[0])

    def test_one_session_starts_in_the_clone_after_setup_with_the_ticket_text_as_its_whole_prompt(self) -> None:
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        [start] = self.world.starts_made()
        self.assertTrue(start["setup_done"])
        self.assertEqual(start["prompt"], f"{TITLE}\n\n{BODY}")
        self.assertEqual(start["args"][start["args"].index("--model") + 1], MODEL)

    def test_a_failed_setup_starts_no_session_and_keeps_nothing(self) -> None:
        self.world.write("repos.json", [{"repo": REPO, "check": "true", "setup": "exit 4"}])
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines()[-1], "replay: the setup command exited 4; no session started.")
        self.assertEqual(self.world.starts_made(), [])
        self.assertFalse(self.world.clone.exists())
        self.assertFalse(self.world.remote.exists())
        self.assertEqual(self.world.versions(), [])

    def test_a_sandbox_that_cannot_start_records_no_version(self) -> None:
        result = self.replay("A", "7", STANDIN_NO_SANDBOX="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines()[-1],
                         "replay: claude exited 1 and left no session log, so no session started.")
        self.assertEqual(len(self.world.starts_made()), 1)
        self.assertEqual(self.world.versions(), [])
        self.assertEqual(self.world.rows(), [])
        self.assertFalse(self.world.clone.exists())
        self.assertFalse(self.world.remote.exists())

    def test_the_clone_is_committed_and_recorded_as_the_direct_version_with_the_session_exit_status(self) -> None:
        result = self.replay("A", "7", STANDIN_EXIT="3")
        self.assertEqual(result.returncode, 0, result.stderr)
        [start] = self.world.starts_made()
        session = start["args"][start["args"].index("--session-id") + 1]
        clone = self.world.clone
        commit = git("rev-parse", "HEAD", cwd=clone)
        self.assertEqual(git("status", "--porcelain", cwd=clone), "")
        self.assertEqual(git("show", "HEAD:replayed.txt", cwd=clone), "the replay's change")
        self.assertEqual(self.world.versions(), [{
            "label": "A", "ticket": 7, "version": "direct", "commit": commit, "base_commit": self.world.base,
            "clone": "replays/A-7-direct", "exit_status": 3, "session": session, "skills": [], "not_direct": False}])
        self.assertEqual((self.world.state / "versions.jsonl").stat().st_mode & 0o777, 0o600)
        self.assertEqual(result.stdout, f"Recorded A-7 direct at {commit}: session exit 3.\n")

    def test_the_session_is_scanned_into_a_row(self) -> None:
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        [row] = self.world.rows()
        self.assertEqual(row["session"], self.world.versions()[0]["session"])
        self.assertEqual(row["model"], MODEL)
        self.assertEqual(row["total_tokens"], 100)

    def test_a_session_that_loaded_a_skill_of_either_generation_is_marked_not_direct(self) -> None:
        for skill, marked in (("implement-ticket", True), ("deliver", True), ("fan-out", True), ("tdd", False)):
            with self.subTest(skill=skill):
                shutil.rmtree(self.world.clone, ignore_errors=True)
                shutil.rmtree(self.world.remote, ignore_errors=True)
                result = self.replay("A", "7", STANDIN_SKILL=skill)
                self.assertEqual(result.returncode, 0, result.stderr)
                [version] = self.world.versions()
                self.assertEqual(version["skills"], [skill])
                self.assertEqual(version["not_direct"], marked)
                if marked:
                    self.assertTrue(result.stdout.endswith(": session exit 0, marked not direct.\n"), result.stdout)

    def test_a_clone_already_in_place_is_refused_and_starts_no_session(self) -> None:
        self.assertEqual(self.replay("A", "7").returncode, 0)
        commit = git("rev-parse", "HEAD", cwd=self.world.clone)
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: {self.world.clone} or {self.world.remote} is already in place. "
                                        "Remove both to replay the ticket again.\n")
        self.assertEqual(len(self.world.starts_made()), 1)
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.world.clone), commit)

    def test_replaying_again_after_removing_the_clone_replaces_the_record(self) -> None:
        self.assertEqual(self.replay("A", "7").returncode, 0)
        shutil.rmtree(self.world.clone)
        shutil.rmtree(self.world.remote)
        self.assertEqual(self.replay("A", "7").returncode, 0)
        [version] = self.world.versions()
        self.assertEqual(version["commit"], git("rev-parse", "HEAD", cwd=self.world.clone))
        self.assertEqual(len(self.world.rows()), 2)

    def test_a_ticket_in_no_replay_set_is_an_error(self) -> None:
        result = self.replay("A", "9")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: no replay set in {self.world.state} holds project A ticket 9.\n")
        self.assertFalse(self.world.gh_log.exists())

    def test_bad_usage_exits_2_and_help_exits_0(self) -> None:
        for args in ((), ("A",), ("A", "seven"), ("A", "7", "8"), ("--model", "7")):
            with self.subTest(args=args):
                result = self.replay(*args)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.startswith("Rerun one ticket of the replay set"), result.stderr)
        result = self.replay("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage: python3 scripts/replay.py LABEL TICKET", result.stdout)
        self.assertFalse(self.world.starts.exists())


if __name__ == "__main__":
    unittest.main()
