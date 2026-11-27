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

import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
REPO = "example-org/alpha"
MODEL = "claude-test-model-1"
TITLE = "Print the total"
BODY = "## Acceptance criteria\n\n- [ ] The report prints the total."

GH = r"""#!/bin/sh
printf '%s\n' "$*" >> "$GH_LOG"
# GitHub reads a repo's name in any case; the remotes here are named in lower case.
name=$(printf '%s' "${3#*/}" | tr '[:upper:]' '[:lower:]')
if [ "$1 $2" = "repo clone" ]; then exec git clone -q "$GH_REMOTES/$name.git" "$4"; fi
echo "stand-in gh: no answer for $*" >&2
exit 1
"""

# The stand-in for Claude Code. It records each start (arguments, working folder, the
# prompt on standard input, the environment and whether setup had run) as one JSON line
# in $STANDIN_STARTS. With STANDIN_NO_SANDBOX set it does what Claude Code does when the
# sandbox cannot start and sandbox.failIfUnavailable is set: it prints an error and
# exits 1 before the session starts, writing no log. Otherwise it writes the session's
# log under $CLAUDE_CONFIG_DIR/projects/, loads the skill STANDIN_SKILL names, writes
# replayed.txt in its working folder and exits with STANDIN_EXIT (default 0). Other knobs
# make the session misbehave: STANDIN_LOG set to "none" writes no log, to "bad" writes a
# line that is not JSON, to "huge" gives the response a token count of 4,300 digits, to "no-usage" leaves out the response that holds token counts;
# STANDIN_TRAP names a file that a post-commit hook and a required clean filter, which
# the session leaves in the clone, would create if anything ran them. STANDIN_TRACK set
# replaces replayed.txt with the file it names, which the repo's .gitignore matches when it
# ends in .lock: the session adds it to git with -f and commits it. The other knobs still act alongside it.
# STANDIN_INDEX_DENY set leaves the clone's index file with mode 000, as a session can; STANDIN_INDEX_BAD
# leaves it holding four bytes; STANDIN_GIT_DENY makes .git unsearchable; STANDIN_SPLIT splits the index
# after the tracked file is added; STANDIN_PREPARE runs a shell command in the clone as the session ends.
# STANDIN_WATCH names a file holding a process id; the start record says whether that process
# is running. STANDIN_HOLD names a file the session creates before it waits for a signal.
CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
prompt = sys.stdin.read()
cwd = Path.cwd()
with open(os.environ["STANDIN_STARTS"], "a") as starts:
    watch, alive = os.environ.get("STANDIN_WATCH"), None
    if watch:
        try:
            os.kill(int(Path(watch).read_text()), 0)
            alive = True
        except ProcessLookupError:
            alive = False
    starts.write(json.dumps({"args": args, "cwd": str(cwd), "prompt": prompt, "env": dict(os.environ),
                             "setup_done": (cwd / ".setup-done").exists(), "watched_alive": alive}) + "\n")
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
call = os.environ.get("STANDIN_SKILL_CALL")  # a Skill call by this name loads STANDIN_SKILL's folder
if os.environ.get("STANDIN_SKILL") and call:
    lines += [{**base, "type": "assistant", "uuid": "c1", "timestamp": "2026-01-05T10:00:20.000Z", "message": {
                   "role": "assistant", "content": [
                       {"type": "tool_use", "id": "toolu_skill", "name": "Skill", "input": {"skill": call}}]}},
              {**base, "type": "user", "uuid": "c2", "timestamp": "2026-01-05T10:00:25.000Z", "message": {
                   "role": "user", "content": [
                       {"type": "tool_result", "tool_use_id": "toolu_skill", "content": "Launching skill"}]}}]
if os.environ.get("STANDIN_SKILL"):
    lines.append({**base, "type": "user", "uuid": "u2", "timestamp": "2026-01-05T10:00:30.000Z", "isMeta": True,
                  **({"sourceToolUseID": "toolu_skill"} if call else {}),
                  "message": {"role": "user", "content": [{"type": "text", "text":
                      "Base directory for this skill: /skills/" + os.environ["STANDIN_SKILL"] + "\n\n# Body"}]}})
if os.environ.get("STANDIN_LOG") != "no-usage":
    lines.append({**base, "type": "assistant", "uuid": "a1", "timestamp": "2026-01-05T10:02:00.000Z",
                  "message": {"model": args[args.index("--model") + 1], "id": "msg_1", "type": "message",
                              "role": "assistant", "content": [{"type": "text", "text": "Done."}],
                              "usage": {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 30,
                                        "cache_read_input_tokens": 40}}})
text = "".join(json.dumps(line) + "\n" for line in lines)
if os.environ.get("STANDIN_LOG") == "huge":  # a token count at Python's limit for converting an integer to text
    text = text.replace('"input_tokens": 10,', '"input_tokens": ' + "9" * 4300 + ",")
if os.environ.get("STANDIN_LOG") != "none":
    (folder / (session + ".jsonl")).write_text("not json\n" + text if os.environ.get("STANDIN_LOG") == "bad" else text)
if os.environ.get("STANDIN_TRACK"):
    tracked = os.environ["STANDIN_TRACK"]
    (cwd / tracked).write_text("pinned\n")
    subprocess.run(["git", "add", "-f", tracked], check=True)
    subprocess.run(["git", "commit", "-q", "-m", "pin"], check=True)
    if os.environ.get("STANDIN_SPLIT"):
        subprocess.run(["git", "update-index", "--split-index"], check=True)
else:
    (cwd / "replayed.txt").write_text("the replay's change\n")
if os.environ.get("STANDIN_TRAP"):
    # The marker's path stays in the environment, quoted where the scripts use it, so no path is written into a command.
    for name, word in (("hooks/post-commit", "hook"), ("trap-filter", "filter")):
        script = cwd / ".git" / name
        script.write_text(f'#!/bin/sh\necho {word} >> "$STANDIN_TRAP"\nexec cat\n')
        script.chmod(0o755)
    (cwd / ".gitattributes").write_text("* filter=trap\n")
    with open(cwd / ".git" / "config", "a") as config:  # git runs a filter in the working tree's top folder
        config.write('[filter "trap"]\n\tclean = .git/trap-filter\n\trequired = true\n')
if os.environ.get("STANDIN_INDEX_DENY"):
    (cwd / ".git" / "index").chmod(0)
if os.environ.get("STANDIN_INDEX_BAD"):
    (cwd / ".git" / "index").write_bytes(b"DIRC")
if os.environ.get("STANDIN_PREPARE"):
    subprocess.run(os.environ["STANDIN_PREPARE"], shell=True, check=True)
if os.environ.get("STANDIN_GIT_DENY"):
    (cwd / ".git").chmod(0)
if os.environ.get("STANDIN_HOLD"):
    import time
    Path(os.environ["STANDIN_HOLD"]).write_text("holding\n")
    time.sleep(60)
sys.exit(int(os.environ.get("STANDIN_EXIT", "0")))
'''


# What the replay inherits when a Claude Code session runs it: that session's own variables, a login
# token the replayed session needs, and a GitHub token it must not have.
PARENT = {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_SESSION_ID": "parent-session",
          "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_PID": "1", "CLAUDE_CODE_OAUTH_TOKEN": "login-token",
          "GH_TOKEN": "github-token", "GITHUB_TOKEN": "github-token"}
CACHES = (".cache/uv", ".cache/pip", "Library/Caches/pip", ".npm")


def process_state(pid: int) -> str:
    """"running", "zombie" (killed and not yet reaped) or "gone". An AssertionError when ps cannot say."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "gone"
    ps = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    state = ps.stdout.strip()
    if ps.returncode == 0 and state:
        return "zombie" if state.startswith("Z") else "running"
    if ps.returncode == 1 and not state:  # ps found no such process; it was reaped after the kill above, or not
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "gone"
    raise AssertionError(f"ps cannot say whether process {pid} runs: exit {ps.returncode}, {ps.stdout!r}, "
                         f"{ps.stderr!r}")


def wait_blocking(process: subprocess.Popen, timeout: float) -> None:
    """Wait for `process` in one blocking call, which returns as it exits; a timed wait polls, and can return up to
    50 ms after. A timer kills the process after `timeout` seconds, which then fails the caller."""
    fired: list[bool] = []
    timer = threading.Timer(timeout, lambda: (fired.append(True), process.kill()))
    timer.start()
    try:
        process.wait()
    finally:
        timer.cancel()
    if fired:
        raise subprocess.TimeoutExpired(process.args, timeout)


def run_to_exit(args: list[str], at_exit: Callable[[], None] | None = None, **options: object
                ) -> subprocess.CompletedProcess[str]:
    """`args` run to the end, with its output in files rather than pipes, so it is known to have exited as soon as
    wait() returns, however long another process holds its output open. `at_exit` is called then, before any output
    is read."""
    with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
        process = subprocess.Popen(args, text=True, stdout=out, stderr=err, **options)
        wait_blocking(process, 120)
        if at_exit:
            at_exit()
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(args, process.returncode, out.read(), err.read())


def run_git(*args: str, cwd: Path, env: dict[str, str]) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, text=True,
                          capture_output=True).stdout.strip()


class World:
    """A real repo with one merged change, a machine directory naming its ticket, and the stand-ins."""

    def __init__(self, root: Path, branch: str = "main") -> None:
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
        # Every git the tests start with git_env() reads this file as its global settings, and no system settings.
        # The environments of the replay's own git steps and of the session point git at neither. Its default branch name differs from the repo's, as a user's can.
        self.gitconfig = root / "gitconfig"
        self.gitconfig.write_text("[init]\n\tdefaultBranch = trunk\n[user]\n\tname = t\n\temail = t@example.com\n")
        work = root / "work"
        work.mkdir()
        self.git("init", "-q", "-b", branch, cwd=work)
        (work / "README.md").write_text("A report.\n")
        (work / ".gitignore").write_text("*.lock\n")
        self.git("add", ".", cwd=work)
        self.git("commit", "-q", "-m", "start", cwd=work)
        self.base = self.git("rev-parse", "HEAD", cwd=work)
        (work / "total.py").write_text("print(42)\n")
        self.git("add", ".", cwd=work)
        self.git("commit", "-q", "-m", "the merged change", cwd=work)
        self.merged = self.git("rev-parse", "HEAD", cwd=work)
        self.bare = self.remotes / "alpha.git"
        self.git("clone", "-q", "--bare", str(work), str(self.bare), cwd=root)
        shutil.rmtree(work)
        entry = {"label": "A", "ticket": 7, "bucket": "0-50", "size": 1, "title": TITLE, "body": BODY,
                 "base_commit": self.base, "ready_commit": self.merged, "model": MODEL, "pr": 507,
                 "session": "00000000-0000-4000-8000-000000000007", "log": "logs/x.jsonl",
                 "check_output": "checks/A-7.txt"}
        self.write("replay-set-1.json", {"set": 1, "seed": 1, "drawn_at": "2026-01-05T00:00:00+00:00",
                                         "tickets": [entry], "set_aside": []})
        self.write("project-labels.json", {"A": REPO})
        self.write("repos.json", [{"repo": REPO, "check": "true", "setup": "touch .setup-done"}])

    def git(self, *args: str, cwd: Path) -> str:
        return run_git(*args, cwd=cwd, env=self.git_env())

    def git_env(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        return {**env, "HOME": str(self.home), "GIT_CONFIG_GLOBAL": str(self.gitconfig), "GIT_CONFIG_NOSYSTEM": "1"}

    def write(self, name: str, data: object) -> None:
        (self.state / name).write_text(json.dumps(data))

    def env(self, **extra: str) -> dict[str, str]:
        env = {key: value for key, value in self.git_env().items()
               if not key.startswith(("CLAUDE", "STANDIN_", "GH_", "GITHUB_"))}
        env.update(PATH=f"{self.bin}{os.pathsep}{env['PATH']}", DELIVER_STATE_DIR=str(self.state),
                   CLAUDE_CONFIG_DIR=str(self.config), GH_LOG=str(self.gh_log), GH_REMOTES=str(self.remotes),
                   STANDIN_STARTS=str(self.starts), TMPDIR=str(self.root), **PARENT)
        return {**env, **extra}

    def replay(self, *args: str, unset: tuple[str, ...] = (), at_exit: Callable[[], None] | None = None,
               **extra: str) -> subprocess.CompletedProcess[str]:
        """Run the replay in env(**extra), less the variables unset names; `at_exit` is called as it exits."""
        env = {key: value for key, value in self.env(**extra).items() if key not in unset}
        return run_to_exit([sys.executable, str(SCRIPTS / "replay.py"), *args], at_exit, cwd=self.root, env=env)

    def clear(self) -> None:
        """Remove the clone and the version's repo, for a subtest that replays the same ticket again."""
        shutil.rmtree(self.clone, ignore_errors=True)
        shutil.rmtree(self.store, ignore_errors=True)

    @property
    def clone(self) -> Path:
        return self.state / "replays" / "A-7-direct"

    @property
    def store(self) -> Path:
        return self.state / "replays" / "A-7-direct.git"

    def jsonl(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []

    def starts_made(self) -> list[dict]:
        return self.jsonl(self.starts)

    def versions(self) -> list[dict]:
        return self.jsonl(self.state / "versions.jsonl")

    def rows(self) -> list[dict]:
        return self.jsonl(self.state / "scan-rows.jsonl")

    def names(self, commit: str) -> list[bytes]:
        """The paths of a commit in the version's repo, exactly as git holds them."""
        listed = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", commit], cwd=self.store,
                                env=self.git_env(), check=True, capture_output=True).stdout
        return [name for name in listed.split(b"\0") if name]

    def start(self, *args: str, **extra: str) -> subprocess.Popen[str]:
        """The replay, running, for a test that signals it. A background job starts with SIGINT ignored, and
        Python then raises no KeyboardInterrupt, so the replay gets Python's handler back first."""
        launcher = ("import runpy, signal, sys\nsignal.signal(signal.SIGINT, signal.default_int_handler)\n"
                    "sys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')")
        return subprocess.Popen([sys.executable, "-c", launcher, str(SCRIPTS / "replay.py"), *args], cwd=self.root,
                                env=self.env(**extra), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class ReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.world = World(self.root_of(temp))
        self.git = self.world.git

    @staticmethod
    def root_of(temp: tempfile.TemporaryDirectory, name: str = "a world") -> Path:
        """The world's folder, named with a space by default so that a shell string built from a path must quote it."""
        root = Path(temp.name).resolve() / name
        root.mkdir()
        return root

    def replay(self, *args: str, unset: tuple[str, ...] = (), at_exit: Callable[[], None] | None = None,
               **extra: str) -> subprocess.CompletedProcess[str]:
        """Run the replay, then hold every session it started to the whole confinement."""
        result = self.world.replay(*args, unset=unset, at_exit=at_exit, **extra)
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
                "filesystem": {"denyRead": [str(home)], "allowRead": [clone, *caches], "allowWrite": caches},
                "network": {"allowedDomains": ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"],
                            "strictAllowlist": True, "allowLocalBinding": True,
                            "allowUnixSockets": [f"/tmp/claude-{os.getuid()}", f"/private/tmp/claude-{os.getuid()}"]},
            },
            # The web tools are not commands, so the sandbox's network list does not bind them.
            "permissions": {"blockReadsOutsideWorkingDirectories": True, "blockWritesOutsideWorkingDirectories": True,
                            "deny": ["WebFetch", "WebSearch"]},
            "disableClaudeAiConnectors": True,
            "disableAllHooks": True,
        })
        env = start["env"]
        self.assertEqual(sorted(key for key in env if key.startswith("CLAUDE")),
                         ["CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"])
        self.assertTrue(Path(env["CLAUDE_CONFIG_DIR"]).is_absolute())
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "login-token")
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertEqual(env["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")

    def session(self) -> str:
        [start] = self.world.starts_made()
        return start["args"][start["args"].index("--session-id") + 1]

    def test_the_version_is_cut_at_the_commit_before_the_merged_pr_with_no_later_history(self) -> None:
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        store, clone = self.world.store, self.world.clone
        self.assertEqual(self.git("rev-parse", f"{version['commit']}^", cwd=store), self.world.base)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=clone), self.world.base)
        for repo in (store, clone, clone / ".git" / "replay-origin.git"):
            with self.subTest(repo=repo.name):
                self.assertNotIn(self.world.merged, self.git("rev-list", "--all", cwd=repo).split())
                missing = subprocess.run(["git", "cat-file", "-e", self.world.merged], cwd=repo, capture_output=True,
                                         env=self.world.git_env())
                self.assertNotEqual(missing.returncode, 0)

    def test_the_clone_fetches_from_a_copy_inside_it_and_nothing_is_pushed_to_the_real_repo(self) -> None:
        refs = self.git("for-each-ref", cwd=self.world.bare)
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        clone = self.world.clone
        self.assertEqual(self.git("remote", cwd=clone), "origin")
        self.assertEqual(self.git("remote", "get-url", "origin", cwd=clone), str(clone / ".git" / "replay-origin.git"))
        self.git("fetch", "-q", "origin", "main", cwd=clone)
        # The default branch keeps its name, though git's default here is trunk, so origin/main and
        # origin/HEAD are where the ticket's author found them.
        self.assertEqual(self.git("branch", "--show-current", cwd=clone), "main")
        self.assertEqual(self.git("rev-parse", "origin/main", cwd=clone), self.world.base)
        self.assertEqual(self.git("rev-parse", "origin/HEAD", cwd=clone), self.world.base)
        self.assertEqual(self.git("for-each-ref", cwd=self.world.bare), refs)
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

    def test_the_sets_and_repo_list_are_read_as_the_draw_reads_them(self) -> None:
        stale = json.loads((self.world.state / "replay-set-1.json").read_text())
        stale["tickets"][0]["title"] = "A stale title"
        self.world.write("replay-set-0-backup.json", stale)
        # The draw keeps the last of two entries that differ only in case.
        self.world.write("repos.json", [{"repo": REPO, "check": "true", "setup": "exit 9"},
                                        {"repo": REPO.upper(), "check": "true", "setup": "touch .setup-done"}])
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        [start] = self.world.starts_made()
        self.assertEqual(start["prompt"], f"{TITLE}\n\n{BODY}")
        self.assertTrue(start["setup_done"])

    def test_a_failed_setup_starts_no_session_and_keeps_nothing(self) -> None:
        self.world.write("repos.json", [{"repo": REPO, "check": "true", "setup": "exit 4"}])
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines()[-1], "replay: the setup command exited 4; no session started.")
        self.assertEqual(self.world.starts_made(), [])
        self.assertFalse(self.world.clone.exists())
        self.assertFalse(self.world.store.exists())
        self.assertEqual(self.world.versions(), [])

    def test_a_sandbox_that_cannot_start_records_no_version(self) -> None:
        result = self.replay("A", "7", STANDIN_NO_SANDBOX="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines()[-1], "replay: claude exited 1, left no session log and changed "
                                                         "nothing, so no session started.")
        self.assertEqual(len(self.world.starts_made()), 1)
        self.assertEqual(self.world.versions(), [])
        self.assertEqual(self.world.rows(), [])
        self.assertFalse(self.world.clone.exists())
        self.assertFalse(self.world.store.exists())

    def test_the_working_tree_is_committed_and_recorded_as_the_direct_version_with_the_exit_status(self) -> None:
        result = self.replay("A", "7", STANDIN_EXIT="3")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        commit, store = version["commit"], self.world.store
        self.assertEqual(self.git("rev-parse", "refs/replay/direct", cwd=store), commit)
        self.assertEqual(self.git("show", f"{commit}:replayed.txt", cwd=store), "the replay's change")
        self.assertEqual(self.git("show", f"{commit}:.setup-done", cwd=store), "")
        self.assertEqual(version, {
            "label": "A", "ticket": 7, "version": "direct", "commit": commit, "repo": "replays/A-7-direct.git",
            "base_commit": self.world.base, "clone": "replays/A-7-direct", "exit_status": 3,
            "session": self.session(), "skills": [], "not_direct": False})
        self.assertEqual((self.world.state / "versions.jsonl").stat().st_mode & 0o777, 0o600)
        self.assertEqual(result.stdout, f"Recorded A-7 direct at {commit}: session exit 3.\n")

    def test_nothing_the_session_left_in_the_clone_s_git_folder_runs_when_the_version_is_committed(self) -> None:
        trap = self.world.root / "trap.txt"
        result = self.replay("A", "7", STANDIN_TRAP=str(trap))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(trap.exists(), trap.read_text() if trap.exists() else "")
        [version] = self.world.versions()
        self.assertEqual(self.git("show", f"{version['commit']}:replayed.txt", cwd=self.world.store),
                         "the replay's change")
        # The control: git run the ordinary way in the clone does fire the filter and the hook.
        env = {**self.world.git_env(), "STANDIN_TRAP": str(trap)}
        for args in (("add", "-A"), ("commit", "-q", "-m", "control")):
            subprocess.run(["git", *args], cwd=self.world.clone, env=env, check=True, capture_output=True)
        self.assertEqual(set(trap.read_text().split()), {"filter", "hook"})

    def test_a_session_that_ran_without_a_log_found_is_still_recorded(self) -> None:
        result = self.replay("A", "7", STANDIN_LOG="none", STANDIN_EXIT="2")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual((version["exit_status"], version["skills"], version["not_direct"]), (2, None, True))
        self.assertEqual(self.git("show", f"{version['commit']}:replayed.txt", cwd=self.world.store),
                         "the replay's change")
        self.assertEqual(result.stdout, f"Recorded A-7 direct at {version['commit']}: session exit 2, "
                                        "skills unknown, marked not direct.\n")
        [row] = self.world.rows()
        self.assertEqual((row["session"], row["skills"], row["total_tokens"]), (self.session(), None, None))

    def test_a_log_that_cannot_be_scanned_still_records_the_version(self) -> None:
        result = self.replay("A", "7", STANDIN_LOG="bad")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual((version["exit_status"], version["skills"], version["not_direct"]), (0, None, True))
        session = self.session()
        [row] = self.world.rows()
        self.assertEqual((row["session"], row["skills"], row["total_tokens"]), (session, None, None))
        log = next(self.world.config.glob(f"projects/*/{session}.jsonl"))
        self.assertEqual(result.stderr, f"replay: the session's log could not be scanned ({log}:1: not a JSON line); "
                                        "its row is left blank.\n")

    def test_a_relative_claude_config_dir_still_finds_the_session_s_log(self) -> None:
        result = self.replay("A", "7", CLAUDE_CONFIG_DIR=os.path.relpath(self.world.config, self.world.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual(version["skills"], [])
        self.assertEqual(len(self.world.rows()), 1)

    def test_a_file_the_session_added_to_git_past_an_ignore_rule_is_in_the_version(self) -> None:
        # With no log, the tracked file is also what tells a session that ran from a refused start.
        result = self.replay("A", "7", STANDIN_TRACK="skills.lock", STANDIN_LOG="none")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual(self.git("show", f"{version['commit']}:skills.lock", cwd=self.world.store), "pinned")

    BASE_FILES = [b".gitignore", b".setup-done", b"README.md"]

    def assert_version_holds(self, result: subprocess.CompletedProcess[str], name: bytes) -> None:
        """The replay exited 0 with nothing on standard error, and its version holds the base's files and `name`."""
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        [version] = self.world.versions()
        self.assertEqual(self.world.names(version["commit"]), [*self.BASE_FILES, name])

    def test_a_tracked_file_whose_name_holds_a_carriage_return_is_in_the_version_under_that_name(self) -> None:
        name = "a\rb.lock"
        self.assert_version_holds(self.replay("A", "7", STANDIN_TRACK=name), name.encode())

    def test_a_tracked_file_with_a_non_ascii_name_is_in_the_version_when_the_locale_is_not_utf_8(self) -> None:
        name = "café.lock"
        self.assert_version_holds(self.replay("A", "7", STANDIN_TRACK=name, LC_ALL="C", PYTHONUTF8="0"),
                                  name.encode())

    def test_a_tracked_file_whose_name_is_not_utf_8_is_in_the_version_under_its_bytes(self) -> None:
        name = b"caf\xe9.lock"
        probe = self.world.root / os.fsdecode(name)
        try:
            probe.write_bytes(b"")
        except OSError:
            self.skipTest("this file system refuses a name that is not UTF-8")
        probe.unlink()
        self.assert_version_holds(self.replay("A", "7", STANDIN_TRACK=os.fsdecode(name)), name)

    def assert_index_refused(self, result: subprocess.CompletedProcess[str], why: str, kept: bool = True,
                             shown: str | None = None) -> None:
        """One line and nothing recorded. What the replay made is kept when the session had run, and removed when
        the index was refused before the session. `shown` is the index's path as the line gives it, where the
        replay's locale shows it otherwise than this test's."""
        shown = shown or repr(str(self.world.clone / ".git" / "index"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: the clone's index {shown} cannot be read ({why}).\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.world.versions(), [])
        self.assertEqual(self.world.rows(), [])
        if kept:
            self.assertTrue(self.world.clone.is_dir())
            self.assertTrue(self.world.store.is_dir())
            self.assertEqual(sorted(path.name for path in self.world.store.glob("replay-*")), ["replay-index"])
        else:
            self.assertEqual(self.world.starts_made(), [])
            self.assertFalse(self.world.clone.exists())
            self.assertFalse(self.world.store.exists())

    @staticmethod
    def refused(attempt: Callable[[], object]) -> bool:
        """Whether `attempt`, made on the fixture, fails with a permission error. The mode bits a test sets do not
        decide it: root, or an access control list, can grant what they deny."""
        try:
            attempt()
        except PermissionError:
            return True
        return False

    def skip_unless_refused(self, attempt: Callable[[], object]) -> None:
        if not self.refused(attempt):
            self.skipTest("this user is granted what the mode bits deny, so no permission error can be asserted")

    def test_a_clone_index_that_cannot_be_read_ends_in_one_line_and_records_nothing(self) -> None:
        result = self.replay("A", "7", STANDIN_INDEX_DENY="1")
        self.skip_unless_refused((self.world.clone / ".git" / "index").read_bytes)
        self.assert_index_refused(result, "Permission denied")

    def test_a_clone_index_git_cannot_list_ends_in_one_line_and_records_nothing(self) -> None:
        self.assert_index_refused(self.replay("A", "7", STANDIN_INDEX_BAD="1"), "git ls-files exited 128")

    def test_a_git_folder_that_cannot_be_searched_ends_in_one_line_and_records_nothing(self) -> None:
        self.addCleanup(lambda: self.world.clone.joinpath(".git").chmod(0o755))
        result = self.replay("A", "7", STANDIN_GIT_DENY="1")
        self.skip_unless_refused(lambda: os.lstat(self.world.clone / ".git" / "index"))
        self.assert_index_refused(result, "Permission denied")

    def test_an_index_that_is_unreadable_before_the_session_removes_what_the_replay_made(self) -> None:
        # setup makes the index unreadable, then tells whether this user is refused a read of it.
        readable = self.world.root / "readable"
        self.world.write("repos.json", [{"repo": REPO, "check": "true", "setup":
                                         f"chmod 000 .git/index && {{ ! cat .git/index >/dev/null 2>&1 || "
                                         f"touch {shlex.quote(str(readable))}; }}"}])
        result = self.replay("A", "7")
        if readable.exists():
            self.skipTest("this user is granted what the mode bits deny, so no permission error can be asserted")
        self.assert_index_refused(result, "Permission denied", kept=False)

    def test_an_index_path_with_a_newline_in_it_still_gives_one_line(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.world = World(self.root_of(temp, "a\nworld"))
        result = self.replay("A", "7", STANDIN_INDEX_BAD="1")
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        self.assertIn("\\n", result.stderr)

    def test_a_split_index_is_read_with_its_shared_index(self) -> None:
        self.assert_version_holds(self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_SPLIT="1"), b"dep.lock")
        self.assertEqual(sorted(path.name for path in self.world.store.glob("replay-*")), ["replay-index"])
        self.assertEqual(list(self.world.store.glob("sharedindex.*")), [])

    def native_listing(self) -> subprocess.CompletedProcess[bytes]:
        """Native git's `ls-files -z` in the clone, under the test's own git settings."""
        return subprocess.run(["git", "ls-files", "-z"], cwd=self.world.clone, env=self.world.git_env(),
                              capture_output=True)

    def assert_git_lists(self, name: bytes) -> None:
        native = self.native_listing()
        self.assertEqual((native.returncode, native.stderr), (0, b""))
        self.assertIn(name + b"\0", native.stdout)

    def test_a_split_index_in_a_git_folder_that_can_be_searched_but_not_read_is_listed_as_git_lists_it(self) -> None:
        git_folder = self.world.clone / ".git"
        self.addCleanup(lambda: git_folder.chmod(0o755) if git_folder.exists() else None)
        result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_SPLIT="1", STANDIN_PREPARE="chmod 111 .git")
        self.skip_unless_refused(lambda: os.listdir(git_folder))
        self.assert_git_lists(b"dep.lock")
        self.assert_version_holds(result, b"dep.lock")

    def test_a_split_index_whose_named_shared_index_is_missing_ends_in_one_line_though_another_is_there(self) -> None:
        # The shared index is renamed, so a file of that shape with the right bytes is in .git/, under a name the
        # index does not give. Native git looks for the named one only, and fails.
        other = "sharedindex." + "0" * 40
        result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_SPLIT="1",
                             STANDIN_PREPARE=f'for f in .git/sharedindex.*; do mv "$f" .git/{other}; done')
        self.assert_index_refused(result, "git ls-files exited 128")
        self.assertEqual([path.name for path in (self.world.clone / ".git").glob("sharedindex.*")], [other])
        self.assertNotEqual(self.native_listing().returncode, 0)

    # Rewrites the index in the working folder as git reads it and does not write it, then writes the checksum again.
    # "last" moves the link extension after the others; "twice" puts a link extension naming another base before it,
    # and git takes the last; "strip" gives the first entry of a version 4 index a strip count, which git ignores.
    DOCTOR = ("import hashlib, pathlib, sys\n"
              "git = pathlib.Path('.git')\n"
              "[shared] = git.glob('sharedindex.*')\n"
              "data = (git / 'index').read_bytes()[:-20]\n"
              "start = data.index(bytes.fromhex(shared.name[12:])) - 8\n"
              "assert data[start:start + 4] == b'link'\n"
              "end = start + 8 + int.from_bytes(data[start + 4:start + 8])\n"
              "if sys.argv[1] == 'last':\n"
              "    data = data[:start] + data[end:] + data[start:end]\n"
              "elif sys.argv[1] == 'twice':\n"
              "    data = data[:start] + b'link' + (20).to_bytes(4) + bytes([17] * 20) + data[start:]\n"
              "else:\n"
              "    assert data[4:8] == (4).to_bytes(4) and data[74] == 0\n"
              "    data = data[:74] + b'\\1' + data[75:]\n"
              "(git / 'index').write_bytes(data + hashlib.sha1(data).digest())\n")

    def test_the_shared_index_is_found_in_each_index_layout_git_reads(self) -> None:
        # After the split, each preparation leaves entries in the split index for the replay to step over before the
        # link extension: version 2, version 3 with an extended flag, version 4 with its compressed names (newer reuses
        # the name new), and names too long for an entry's flags, in versions 2 and 4; then three indexes git reads and
        # does not write. Each name added by --cacheinfo is in the index and not in the clone.
        doctor = self.world.root / "doctor.py"
        doctor.write_text(self.DOCTOR)
        git = "git -c splitIndex.maxPercentChange=100"
        added = f"echo new > new && {git} add new && {git} update-index --add --cacheinfo 100644,$(git hash-object new)"
        v2 = f"{git} update-index --split-index"
        v4 = f"{git} update-index --index-version 4 && {v2}"
        doctored = f"{shlex.quote(sys.executable)} {shlex.quote(str(doctor))}"
        layouts = {
            "version 2": (2, f"{v2} && {added},newer"),
            "version 3": (3, f"{v2} && {added},newer && {git} update-index --skip-worktree .gitignore"),
            "version 4": (4, f"{v4} && {added},newer"),
            "version 2, a long name": (2, f"{v2} && {added},{'L' * 4200}"),
            "version 4, a long name": (4, f"{v4} && {added},{'L' * 4200}"),
            "version 2, the link extension last": (2, f"{v2} && {added},newer && {doctored} last"),
            "version 2, a link extension before the last": (2, f"{v2} && {added},newer && {doctored} twice"),
            "version 4, a strip count on the first entry": (4, f"{v4} && {added},newer && {doctored} strip"),
        }
        for layout, (index_version, prepare) in layouts.items():
            with self.subTest(layout=layout):
                self.world.clear()
                result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE=prepare)
                data = (self.world.clone / ".git" / "index").read_bytes()
                self.assertEqual(int.from_bytes(data[4:8]), index_version)
                self.assertGreater(int.from_bytes(data[8:12]), 0)
                [shared] = (self.world.clone / ".git").glob("sharedindex.*")
                self.assertIn(b"link\0\0\0", data)
                self.assertIn(bytes.fromhex(shared.name[12:]), data)
                self.assert_git_lists(b"dep.lock")
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                [version] = self.world.versions()
                self.assertEqual(self.world.names(version["commit"]), [*self.BASE_FILES, b"dep.lock", b"new"])

    def test_a_shared_index_of_the_same_name_in_the_version_s_repo_is_neither_read_nor_touched(self) -> None:
        # The session puts a file named as the shared index in the version's repo: a valid copy, which must not stand
        # in for the clone's own copy once that is removed, or other bytes, which must be left as they are. The
        # refusal comes first, as it records nothing.
        for removed in (True, False):
            with self.subTest(clone_copy_removed=removed):
                self.world.clear()
                prepare = ("cp .git/sharedindex.* ../A-7-direct.git/ && rm .git/sharedindex.*" if removed else
                           "for f in .git/sharedindex.*; do echo session > \"../A-7-direct.git/${f#.git/}\"; done")
                result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_SPLIT="1", STANDIN_PREPARE=prepare)
                if removed:
                    self.assert_index_refused(result, "git ls-files exited 128")
                    self.assertEqual(list((self.world.clone / ".git").glob("sharedindex.*")), [])
                else:
                    self.assert_version_holds(result, b"dep.lock")
                    [clone_copy] = (self.world.clone / ".git").glob("sharedindex.*")
                    self.assertEqual((self.world.store / clone_copy.name).read_bytes(), b"session\n")
                self.assertEqual(len(list(self.world.store.glob("sharedindex.*"))), 1)

    def test_a_stale_alternates_entry_does_not_stop_an_index_git_lists(self) -> None:
        # The clone's alternates file names a folder that does not exist. Native git says so on standard error,
        # lists the index and exits 0; so must the replay: for a plain index, for a sparse one whose tree the clone
        # holds or a folder its alternates file names, with the objects folder searchable only, and with the
        # alternates file under objects/Info, which git finds on a file system that ignores case.
        stale = "echo ../nowhere/objects >> .git/objects/info/alternates"
        restored = "mkdir pins && echo pinned > pins/dep.lock"
        tree = 't=$(git rev-parse HEAD:pins) && rm ".git/objects/$(echo $t | cut -c1-2)/$(echo $t | cut -c3-)"'
        borrowed = self.world.state / "replays" / "borrowed"
        objects = self.world.clone / ".git" / "objects"
        self.addCleanup(lambda: objects.chmod(0o755) if objects.exists() else None)
        for kind, prepare, name in (
                ("plain", stale, "dep.lock"),
                ("sparse", f"{self.SPARSE} && {stale} && {restored}", "pins/dep.lock"),
                ("sparse, its tree borrowed", f"{self.SPARSE} && git clone -q --bare . ../borrowed && {tree} && "
                                              f"echo ../../../borrowed/objects > .git/objects/info/alternates && "
                                              f"{stale} && {restored}", "pins/dep.lock"),
                ("Info", f"mv .git/objects/info .git/objects/moved && mv .git/objects/moved .git/objects/Info && "
                         f"echo ../nowhere/objects > .git/objects/Info/alternates", "dep.lock"),
                ("objects searchable only", f"{stale} && chmod 111 .git/objects", "dep.lock")):
            with self.subTest(index=kind):
                self.world.clear()
                shutil.rmtree(borrowed, ignore_errors=True)
                result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE=prepare)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                [version] = self.world.versions()
                self.assertIn(name.encode(), self.world.names(version["commit"]))
                native = subprocess.run(["git", "ls-files", "-z"], cwd=self.world.clone, env=self.world.git_env(),
                                        capture_output=True)
                self.assertEqual(native.returncode, 0)
                self.assertIn(name.encode() + b"\0", native.stdout)
                if kind != "Info":  # a file system that keeps case finds no alternates file there
                    self.assertIn(b"nowhere", native.stderr)
                objects.chmod(0o755)

    def test_a_missing_index_means_no_paths(self) -> None:
        for prepare in ("rm .git/index", "mv .git ../real-git && ln -s ../real-git .git && rm ../real-git/index"):
            with self.subTest(prepare=prepare):
                self.world.clear()
                shutil.rmtree(self.world.state / "replays" / "real-git", ignore_errors=True)
                result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE=prepare)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                [version] = self.world.versions()
                self.assertEqual(self.world.names(version["commit"]), self.BASE_FILES)

    def test_an_index_that_is_not_one_regular_file_git_can_list_is_refused_not_read_as_empty(self) -> None:
        # The session first tracks and commits an ignored file. Each preparation then truncates, replaces or breaks
        # the index, so most of the resulting indexes list nothing at all.
        index = self.world.clone / ".git" / "index"
        states = {
            "a zero-byte file": (": > .git/index", "git ls-files exited 128"),
            # A user granted the read whatever the mode bits say, as root is, gets git's refusal of the zero bytes.
            "a zero-byte file of mode 000": (": > .git/index && chmod 000 .git/index", None),
            "a folder": ("rm .git/index && mkdir .git/index", "not a regular file"),
            "a link to an index": ("mv .git/index .git/other && ln -s other .git/index", "not a regular file"),
            "a git file naming another folder": ("mv .git ../moved && echo 'gitdir: ../moved' > .git",
                                                 "Not a directory"),
            "a git folder that is a link to nothing": ("rm -rf .git && ln -s gone .git", "No such file or directory"),
            "a split index whose shared index is gone": (
                "git update-index --split-index && rm .git/sharedindex.*", "git ls-files exited 128"),
        }
        for state, (prepare, why) in states.items():
            with self.subTest(state=state):
                self.world.clear()
                shutil.rmtree(self.world.state / "replays" / "moved", ignore_errors=True)
                result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE=prepare)
                if why is None:
                    why = "Permission denied" if self.refused(index.read_bytes) else "git ls-files exited 128"
                self.assert_index_refused(result, why)

    def test_a_shared_index_the_clone_no_longer_uses_does_not_stop_the_replay(self) -> None:
        # Git leaves the retired shared index of a split index that was turned off; it may be unreadable, and a name
        # of that shape may be a link to anywhere, here into a folder that cannot be searched. A step that fails
        # makes the stand-in exit 1, which the recorded exit status shows.
        locked = self.world.state / "replays" / "locked"
        self.addCleanup(lambda: locked.chmod(0o755) if locked.exists() else None)
        retire = "git update-index --split-index && git update-index --no-split-index"
        for retired, prepare in (
                ("unreadable", f"{retire} && chmod 000 .git/sharedindex.*"),
                ("a link into a folder that cannot be searched",
                 f"{retire} && mkdir ../locked && : > ../locked/shared && "
                 "ln -s ../../locked/shared .git/sharedindex.0000000000000000000000000000000000000000 && "
                 "chmod 000 ../locked")):
            with self.subTest(retired=retired):
                if locked.exists():
                    locked.chmod(0o755)
                    shutil.rmtree(locked)
                self.world.clear()
                result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE=prepare)
                self.assert_version_holds(result, b"dep.lock")
                self.assertEqual(self.world.versions()[0]["exit_status"], 0)
                shared = list((self.world.clone / ".git").glob("sharedindex.*"))
                self.assertEqual(len(shared), 2 if locked.exists() else 1)

    def test_a_private_git_folder_git_cannot_make_under_a_non_ascii_path_in_the_c_locale_ends_in_one_line(self) -> None:
        # git's message names the private folder, whose path is not ASCII; the C locale cannot decode it.
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.world = World(self.root_of(temp, "café world"))
        stand_in = self.world.root / "git-bin"
        stand_in.mkdir()
        (stand_in / "git").write_text(
            '#!/bin/sh\nif [ "$1 $2 $3" = "init -q --bare" ]; then case "$4" in */replays/tmp*)\n'
            '  echo "fatal: cannot copy templates to $4" >&2; exit 128;; esac; fi\n'
            f'exec {shlex.quote(shutil.which("git"))} "$@"\n')
        (stand_in / "git").chmod(0o755)
        result = self.world.replay("A", "7", LC_ALL="C", PYTHONUTF8="0",
                                   PATH=f"{stand_in}{os.pathsep}{self.world.env()['PATH']}")
        # The index's path as the replay's own Python shows it under that locale.
        shown = subprocess.run([sys.executable, "-c", "import os, sys; sys.stderr.write(repr(os.path.join("
                                "os.environ['DELIVER_STATE_DIR'], 'replays', 'A-7-direct', '.git', 'index')))"],
                               env=self.world.env(LC_ALL="C", PYTHONUTF8="0"), capture_output=True, text=True).stderr
        self.assert_index_refused(result, "git init exited 128", kept=False, shown=shown)

    # Fails the nth call of subprocess.run whose arguments hold sys.argv[1], as `how` says.
    FAIL_NTH_RUN = ("real, calls, word, nth = subprocess.run, [], sys.argv[1], int(sys.argv[2])\n"
                    "def run(args, *rest, **options):\n"
                    "    if word in args:\n"
                    "        calls.append(1)\n"
                    "        if len(calls) == nth:\n"
                    "            {how}\n"
                    "    return real(args, *rest, **options)\n"
                    "subprocess.run = run")

    def test_a_listing_that_cannot_start_after_the_session_ends_in_one_line_and_keeps_both(self) -> None:
        body = self.FAIL_NTH_RUN.format(how="raise OSError(24, 'Too many open files')")
        self.assert_index_refused(self.patched_replay(body, "ls-files", "2"), "Too many open files")

    def test_a_listing_that_cannot_start_before_the_session_ends_in_one_line_and_removes_both(self) -> None:
        body = self.FAIL_NTH_RUN.format(how="raise OSError(24, 'Too many open files')")
        self.assert_index_refused(self.patched_replay(body, "ls-files", "1"), "Too many open files", kept=False)

    def test_a_private_folder_for_the_index_that_cannot_be_made_ends_in_one_line_and_keeps_both(self) -> None:
        # cut() makes the first temporary folder and the first git init; each listing makes one more of each, so the
        # third of either belongs to the listing after the session.
        no_space = ("import tempfile\nreal, calls = tempfile.mkdtemp, []\n"
                    "def full(*args, **options):\n"
                    "    calls.append(1)\n"
                    "    if len(calls) == 3:\n"
                    "        raise OSError(28, 'No space left on device')\n"
                    "    return real(*args, **options)\n"
                    "tempfile.mkdtemp = full")
        init_fails = self.FAIL_NTH_RUN.format(how="return subprocess.CompletedProcess(args, 7, '', '')")
        for failure, body, argv, why in (("no space", no_space, (), "No space left on device"),
                                          ("git init exits 7", init_fails, ("init", "3"), "git init exited 7")):
            with self.subTest(failure=failure):
                self.world.clear()
                self.assert_index_refused(self.patched_replay(body, *argv), why)

    def test_a_folder_of_replays_the_session_made_read_only_ends_in_one_line_and_keeps_both(self) -> None:
        replays = self.world.clone.parent
        self.addCleanup(lambda: replays.chmod(0o755))
        result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE="chmod 500 ..")
        refused = self.refused(lambda: tempfile.TemporaryDirectory(dir=replays).cleanup())
        replays.chmod(0o755)
        if not refused:
            self.skipTest("this user is granted what the mode bits deny, so no permission error can be asserted")
        self.assert_index_refused(result, "Permission denied")

    # The session moves the ignored tracked file into a new folder, commits, and turns on a sparse index whose cone
    # leaves that folder out; the index then holds the folder as one entry, a tree only the clone has.
    SPARSE = ("mkdir pins && git mv dep.lock pins/ && git commit -q -m move && "
              "git sparse-checkout set --sparse-index elsewhere && git ls-files --sparse | grep -qx pins/")

    def test_a_sparse_index_keeps_a_tracked_file_under_a_folder_the_session_made(self) -> None:
        # The file is written back after the sparse index is made, so it is in the working tree.
        prepare = f"{self.SPARSE} && mkdir pins && echo pinned > pins/dep.lock"
        result = self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE=prepare)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        [version] = self.world.versions()
        self.assertEqual(version["exit_status"], 0)
        self.assertIn(b"pins/dep.lock", self.world.names(version["commit"]))

    def test_a_sparse_index_whose_tree_cannot_be_read_is_refused_not_read_as_fewer_paths(self) -> None:
        # Git expands the sparse folder entry from its tree and exits 0 when that tree is gone.
        prepare = (f"{self.SPARSE} && "
                   't=$(git rev-parse HEAD:pins) && rm ".git/objects/$(echo $t | cut -c1-2)/$(echo $t | cut -c3-)" && '
                   "mkdir pins && echo pinned > pins/dep.lock")
        self.assert_index_refused(self.replay("A", "7", STANDIN_TRACK="dep.lock", STANDIN_PREPARE=prepare),
                                  "git ls-files reported an error")

    def test_a_folder_at_the_name_the_old_copy_used_does_not_stop_the_replay(self) -> None:
        self.world.write("repos.json", [{"repo": REPO, "check": "true",
                                         "setup": "touch .setup-done && mkdir ../A-7-direct.git/replay-clone-index"}])
        result = self.replay("A", "7")
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_a_row_that_cannot_be_written_ends_in_one_line_that_names_the_scan_command(self) -> None:
        (self.world.state / "scan-rows.lock").mkdir()
        result = self.replay("A", "7")
        [version] = self.world.versions()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: A-7 direct is recorded at {version['commit']} without its row "
                                        f"(Is a directory). Write the row with: python3 scripts/scan.py "
                                        f"{self.session()}\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.world.rows(), [])
        self.assertTrue(self.world.clone.is_dir())
        self.assertTrue(self.world.store.is_dir())

    def test_a_row_the_writer_cannot_serialise_ends_in_the_same_one_line(self) -> None:
        result = self.replay("A", "7", STANDIN_LOG="huge", PYTHONINTMAXSTRDIGITS="4300")
        [version] = self.world.versions()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: A-7 direct is recorded at {version['commit']} without its row "
                                        f"(ValueError). Write the row with: python3 scripts/scan.py {self.session()}\n")
        self.assertEqual(self.world.rows(), [])

    def test_a_warning_before_a_failed_row_write_is_not_printed(self) -> None:
        (self.world.state / "scan-rows.jsonl.partial").mkdir()  # the writer warns about the next line, then fails
        (self.world.state / "scan-rows.jsonl").write_text("[]\n")
        result = self.replay("A", "7", STANDIN_LOG="bad")  # the scan would warn that the row is left blank
        [version] = self.world.versions()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: A-7 direct is recorded at {version['commit']} without its row "
                                        f"(Is a directory). Write the row with: python3 scripts/scan.py "
                                        f"{self.session()}\n")

    def test_the_warnings_of_a_row_that_is_written_are_printed(self) -> None:
        (self.world.state / "scan-rows.jsonl").write_text("[]\n")
        result = self.replay("A", "7", STANDIN_LOG="bad")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = next(self.world.config.glob(f"projects/*/{self.session()}.jsonl"))
        self.assertEqual(result.stderr, f"replay: the session's log could not be scanned ({log}:1: not a JSON line); "
                                        f"its row is left blank.\n{self.world.state / 'scan-rows.jsonl'}:1: "
                                        "not a JSON object, kept as it is\n")

    def watch_setup(self, tail: str = "") -> Path:
        """A setup command that starts a process outliving it, whose pid it writes to the returned file."""
        watch = self.world.root / "watched.pid"
        self.world.write("repos.json", [{"repo": REPO, "check": "true", "setup":
                                         f"touch .setup-done && {{ sleep 60 </dev/null >/dev/null 2>&1 & "
                                         f'echo $! > "$STANDIN_WATCH"; }}{tail}'}])
        return watch

    @staticmethod
    def watched_pid(watch: Path) -> int:
        return int(watch.read_text().strip())

    def assert_gone(self, watch: Path) -> None:
        """Called as soon as the replay has exited: the process setup started is gone, or killed and not yet reaped."""
        pid = self.watched_pid(watch)
        if process_state(pid) == "running":
            os.kill(pid, signal.SIGKILL)
            self.fail(f"the process setup started, {pid}, is still running")

    def test_what_setup_starts_runs_through_the_session_and_is_gone_when_the_replay_has_exited(self) -> None:
        watch = self.watch_setup()
        result = self.replay("A", "7", STANDIN_WATCH=str(watch), at_exit=lambda: self.assert_gone(watch))
        self.assertEqual(result.returncode, 0, result.stderr)
        [start] = self.world.starts_made()
        self.assertIs(start["watched_alive"], True)

    def test_the_exit_check_fails_for_a_process_that_outlives_the_replay(self) -> None:
        # A process that starts its own session leaves setup's group, so the replay does not stop it.
        watch = self.world.root / "watched.pid"
        escape = (f"{shlex.quote(sys.executable)} -c 'import os, time; os.setsid(); "
                  'open(os.environ["STANDIN_WATCH"], "w").write(str(os.getpid())); time.sleep(60)\'')
        self.world.write("repos.json", [{"repo": REPO, "check": "true", "setup":
                                         f"touch .setup-done && {{ {escape} </dev/null >/dev/null 2>&1 & }} && "
                                         'until [ -s "$STANDIN_WATCH" ]; do sleep 0.1; done'}])
        with self.assertRaisesRegex(AssertionError, "is still running"):
            self.replay("A", "7", STANDIN_WATCH=str(watch), at_exit=lambda: self.assert_gone(watch))
        self.assertIn(process_state(self.watched_pid(watch)), ("gone", "zombie"))

    def test_what_setup_starts_is_gone_when_the_setup_fails_or_the_session_s_start_is_refused(self) -> None:
        for tail, extra, message in (
                (" && exit 4", {}, "replay: the setup command exited 4; no session started."),
                ("", {"STANDIN_NO_SANDBOX": "1"}, "replay: claude exited 1, left no session log and changed "
                                                  "nothing, so no session started.")):
            with self.subTest(tail=tail, extra=extra):
                watch = self.watch_setup(tail)
                result = self.replay("A", "7", STANDIN_WATCH=str(watch), at_exit=lambda: self.assert_gone(watch),
                                     **extra)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr.splitlines()[-1], message)  # the stand-in's own error comes before

    def test_what_setup_starts_is_gone_when_the_replay_is_interrupted_during_setup_or_the_session(self) -> None:
        for number in (signal.SIGINT, signal.SIGTERM):
            for where in ("setup", "session"):
                with self.subTest(signal=number.name, where=where):
                    self.world.clear()
                    holding = self.world.root / "holding"
                    holding.unlink(missing_ok=True)
                    watch = self.watch_setup(f" && touch {shlex.quote(str(holding))} && sleep 60" if where == "setup" else "")
                    extra = {"STANDIN_HOLD": str(holding)} if where == "session" else {}
                    replay = self.world.start("A", "7", STANDIN_WATCH=str(watch), **extra)
                    self.addCleanup(replay.kill)
                    for _ in range(400):
                        if holding.exists() or replay.poll() is not None:
                            break
                        time.sleep(0.05)
                    self.assertTrue(holding.exists())
                    replay.send_signal(number)
                    wait_blocking(replay, 60)  # its output is small enough to wait in the pipe
                    self.assert_gone(watch)
                    _, stderr = replay.communicate()
                    self.assertNotEqual(replay.returncode, 0)
                    if number == signal.SIGTERM:
                        self.assertEqual((replay.returncode, stderr), (128 + signal.SIGTERM, "replay: stopped by SIGTERM.\n"))

    def patched_replay(self, body: str, *argv: str) -> subprocess.CompletedProcess[str]:
        """The replay's main(), run in a process that first runs `body` to patch it, with `argv` as that process's
        arguments, the module imports and the setup watch set up. The process setup started is gone when this
        returns."""
        watch = self.watch_setup()
        code = (f"import os, signal, subprocess, sys, time\nsys.path[:0] = [{str(SCRIPTS)!r}, {str(TESTS)!r}]\n"
                f"import replay, scan\n{body}\nsys.exit(replay.main(['A', '7']))\n")
        try:
            return run_to_exit([sys.executable, "-c", code, *argv], lambda: self.assert_gone(watch),
                               cwd=self.world.root, env=self.world.env(STANDIN_WATCH=str(watch)))
        except BaseException as failure:  # this invocation failed: do not leave its process behind
            if watch.exists():
                try:
                    os.kill(self.watched_pid(watch), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception as error:
                    failure.add_note(f"the process setup started may still run: {error!r}")
            raise

    def test_a_run_that_fails_names_a_process_it_could_not_kill(self) -> None:
        # The run fails, and the kill of the watched process then fails for another reason than its being gone.
        (self.world.root / "watched.pid").write_text("4242\n")
        for kill, note in ((ProcessLookupError(), None), (PermissionError("denied"), "may still run")):
            with self.subTest(kill=type(kill).__name__):
                with (mock.patch(f"{__name__}.run_to_exit", side_effect=RuntimeError("the run failed")),
                      mock.patch.object(os, "kill", side_effect=kill) as killed):
                    with self.assertRaisesRegex(RuntimeError, "the run failed") as raised:
                        self.patched_replay("")
                killed.assert_called_once_with(4242, signal.SIGKILL)
                notes = getattr(raised.exception, "__notes__", [])
                if note:
                    self.assertEqual(len(notes), 1)
                    self.assertIn(note, notes[0])
                else:
                    self.assertEqual(notes, [])

    def test_the_group_setup_started_is_stopped_whichever_call_after_it_is_interrupted(self) -> None:
        # The invariant: once setup has run, no exit of the replay leaves a process of its group running.
        # Each call the replay makes between setup and its end takes a Ctrl-C in turn.
        points = (("replay", "snapshot", 1), ("replay", "command", 1), ("replay", "environment", 1),
                  ("scan", "resolve", 1), ("replay", "snapshot", 2), ("scan", "scan", 1), ("replay", "record", 1),
                  ("scan", "write_row", 1))
        body = ("module, name, nth = {'replay': replay, 'scan': scan}[sys.argv[1]], sys.argv[2], int(sys.argv[3])\n"
                "real, calls = getattr(module, name), []\n"
                "def interrupted(*args, **options):\n"
                "    calls.append(1)\n"
                "    if len(calls) == nth:\n"
                "        raise KeyboardInterrupt\n"
                "    return real(*args, **options)\n"
                "setattr(module, name, interrupted)")
        for module, name, nth in points:
            with self.subTest(call=f"{module}.{name} #{nth}"):
                self.world.clear()
                result = self.patched_replay(body, module, name, str(nth))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("KeyboardInterrupt", result.stderr)

    SNAPSHOT_WATCH = ("from test_replay import process_state\n"
                      "stopped, real = [], replay.SetupGroup.stop\n"
                      "def stop(self):\n"
                      "    real(self)\n"
                      "    stopped.append(1)\n"
                      "replay.SetupGroup.stop = stop\n"
                      "snapshots, snapshot = [], replay.snapshot\n"
                      "def watched(*args, **options):\n"
                      "    snapshots.append(1)\n"
                      "    if len(snapshots) == 2:  # the working tree is about to be written for the commit\n"
                      "        state = process_state(int(open(os.environ['STANDIN_WATCH']).read()))\n"
                      "        print(f'process {state} at the second snapshot')\n"
                      "        print('group stopped' if stopped else 'group not stopped')\n"
                      "    return snapshot(*args, **options)\n"
                      "replay.snapshot = watched")

    def test_what_setup_started_is_gone_when_the_working_tree_is_committed(self) -> None:
        # The second snapshot writes the tree that the commit, after it returns, records. As it is entered, before
        # any wait, the process must already be killed (gone, or a zombie not yet reaped) and the group stopped.
        # That the process is gone once the replay has exited is checked apart.
        result = self.patched_replay(self.SNAPSHOT_WATCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        state, group = result.stdout.splitlines()[:2]
        self.assertIn(state, ("process gone at the second snapshot", "process zombie at the second snapshot"))
        self.assertEqual(group, "group stopped")

    def test_the_process_check_fails_when_ps_cannot_say(self) -> None:
        # A running process this test owns, and stand-ins for ps that give no state.
        sleeper = subprocess.Popen(["sleep", "60"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        fake = self.world.root / "ps-bin"
        fake.mkdir()
        for code in (1, 2):
            with self.subTest(ps_exit=code):
                (fake / "ps").write_text(f"#!/bin/sh\nexit {code}\n")
                (fake / "ps").chmod(0o755)
                with mock.patch.dict(os.environ, PATH=f"{fake}{os.pathsep}{os.environ['PATH']}"):
                    with self.assertRaises(AssertionError):
                        process_state(sleeper.pid)
        self.assertEqual(process_state(sleeper.pid), "running")

    def test_a_sigterm_as_the_stop_begins_still_stops_what_setup_started(self) -> None:
        # The first SIGTERM-blocking call is the one that makes the group; the second opens stop().
        body = ("real, blocks = signal.pthread_sigmask, []\n"
                "def mask(how, signals):\n"
                "    if how == signal.SIG_BLOCK:\n"
                "        blocks.append(1)\n"
                "        if len(blocks) == 2:\n"
                "            os.kill(os.getpid(), signal.SIGTERM)\n"
                "    return real(how, signals)\n"
                "signal.pthread_sigmask = mask")
        result = self.patched_replay(body)
        self.assertEqual((result.returncode, result.stderr), (128 + signal.SIGTERM, "replay: stopped by SIGTERM.\n"))

    def test_a_signal_just_before_either_call_of_stop_still_stops_what_setup_started(self) -> None:
        # The signal comes as replay() calls stop() after the session, and again as it calls stop() in the handler of
        # what that first signal raised. A handler's own call of stop() is not signalled.
        body = ("signal.signal(signal.SIGINT, signal.default_int_handler)\n"
                "number, real = getattr(signal, sys.argv[1]), replay.SetupGroup.stop\n"
                "def stop(self):\n"
                "    if sys._getframe(1).f_code.co_name == 'replay':\n"
                "        print('signalled before stop()', flush=True)\n"
                "        os.kill(os.getpid(), number)\n"
                "    real(self)\n"
                "replay.SetupGroup.stop = stop")
        for name in ("SIGTERM", "SIGINT"):
            with self.subTest(signal=name):
                self.world.clear()
                result = self.patched_replay(body, name)
                self.assertEqual(result.stdout.splitlines(), ["signalled before stop()"] * 2)
                if name == "SIGTERM":
                    self.assertEqual((result.returncode, result.stderr),
                                     (128 + signal.SIGTERM, "replay: stopped by SIGTERM.\n"))
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(result.stderr.endswith("KeyboardInterrupt\n"), result.stderr)

    def test_an_untouched_file_keeps_its_base_bytes_with_core_autocrlf_in_the_operator_s_settings(self) -> None:
        with open(self.world.gitconfig, "a") as config:
            config.write("[core]\n\tautocrlf = true\n")
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        changed = self.git("diff", "--name-only", self.world.base, version["commit"], cwd=self.world.store)
        self.assertEqual(changed.split(), [".setup-done", "replayed.txt"])

    def test_no_file_of_the_version_s_repo_is_shared_with_the_clone(self) -> None:
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)

        def identities(folder: Path) -> set[tuple[int, int]]:
            return {(path.stat().st_dev, path.stat().st_ino) for path in folder.rglob("*") if path.is_file()}
        self.assertEqual(identities(self.world.store) & identities(self.world.clone), set())

    def test_a_label_key_that_is_not_an_object_is_an_error(self) -> None:
        self.world.write("project-labels.json", [])
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "replay: project A is not in both project-labels.json and repos.json.\n")

    def test_the_session_s_git_skips_the_caller_s_default_git_files_and_commits_in_the_clone(self) -> None:
        # Settings, an ignore rule and an attribute held only in the files git looks up by default under HOME and
        # XDG_CONFIG_HOME, and in the file the caller's GIT_CONFIG_GLOBAL names. The sandbox hides the home folder,
        # so a session's git must not look them up, whether the caller sets GIT_CONFIG_GLOBAL or not.
        home = self.world.home
        xdg = home / ".config"
        (xdg / "git").mkdir(parents=True)
        (xdg / "git" / "ignore").write_text("notes.txt\n")
        (xdg / "git" / "attributes").write_text("* caller-attribute\n")
        (xdg / "git" / "config").write_text("[replay]\n\txdg = caller\n")
        (home / ".gitconfig").write_text("[replay]\n\thome = caller\n")
        with open(self.world.gitconfig, "a") as config:
            config.write("[replay]\n\tglobal = caller\n")
        for unset in (("GIT_CONFIG_GLOBAL",), ()):
            self.world.clear()
            result = self.replay("A", "7", XDG_CONFIG_HOME=str(xdg), unset=unset)
            self.assertEqual(result.returncode, 0, result.stderr)
            env = self.world.starts_made()[-1]["env"]

            def session_git(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(["git", *args], cwd=self.world.clone, env=env, text=True, capture_output=True)
            for key in ("replay.home", "replay.xdg", "replay.global"):
                with self.subTest(unset=unset, key=key):
                    self.assertEqual(session_git("config", "--get", key).returncode, 1)
            (self.world.clone / "notes.txt").write_text("a note\n")
            with self.subTest(unset=unset, check="ignore and attributes"):
                self.assertEqual(session_git("status", "--porcelain", "--", "notes.txt").stdout, "?? notes.txt\n")
                self.assertEqual(session_git("check-attr", "caller-attribute", "notes.txt").stdout,
                                 "notes.txt: caller-attribute: unspecified\n")
            for args in (("status",), ("add", "notes.txt"), ("commit", "-q", "-m", "a note"),
                         ("fetch", "-q", "origin")):
                with self.subTest(unset=unset, args=args):
                    done = session_git(*args)
                    self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_the_session_is_scanned_into_a_row(self) -> None:
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        [row] = self.world.rows()
        self.assertEqual(row["session"], self.world.versions()[0]["session"])
        self.assertEqual(row["model"], MODEL)
        self.assertEqual(row["total_tokens"], 100)

    def test_a_session_that_loaded_a_skill_of_either_generation_is_marked_not_direct(self) -> None:
        for skill, marked in (("implement-ticket", True), ("deliver", True), ("squad", True), ("tdd", False)):
            with self.subTest(skill=skill):
                self.world.clear()
                result = self.replay("A", "7", STANDIN_SKILL=skill)
                self.assertEqual(result.returncode, 0, result.stderr)
                [version] = self.world.versions()
                self.assertEqual(version["skills"], [skill])
                self.assertEqual(version["not_direct"], marked)
                if marked:
                    self.assertTrue(result.stdout.endswith(": session exit 0, marked not direct.\n"), result.stdout)

    def test_a_session_that_loaded_a_generation_one_skill_through_a_prefixed_call_is_marked_not_direct(self) -> None:
        result = self.replay("A", "7", STANDIN_SKILL="implement-ticket-folder",
                             STANDIN_SKILL_CALL="example-plugin:implement-ticket")

        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual(version, {
            "label": "A", "ticket": 7, "version": "direct", "commit": version["commit"],
            "repo": "replays/A-7-direct.git", "base_commit": self.world.base, "clone": "replays/A-7-direct",
            "exit_status": 0, "session": self.session(), "skills": ["implement-ticket"], "not_direct": True})
        self.assertEqual(result.stdout,
                         f"Recorded A-7 direct at {version['commit']}: session exit 0, marked not direct.\n")
        self.assertEqual([row["skills"] for row in self.world.rows()], [["implement-ticket"]])

    def test_a_session_whose_skills_the_scan_cannot_tell_is_marked_not_direct(self) -> None:
        result = self.replay("A", "7", STANDIN_SKILL="tdd", STANDIN_LOG="no-usage")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual((version["skills"], version["not_direct"]), (None, True))

    def test_a_ticket_another_replay_holds_is_refused_and_left_as_it_is(self) -> None:
        self.world.clone.parent.mkdir()
        self.world.clone.mkdir()
        (self.world.clone / "theirs.txt").write_text("another replay's\n")
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: {self.world.clone} is already in place. "
                                        f"Remove it and {self.world.store} to replay the ticket again.\n")
        self.assertEqual(self.world.starts_made(), [])
        self.assertEqual((self.world.clone / "theirs.txt").read_text(), "another replay's\n")

    def test_a_version_repo_already_in_place_is_refused_and_left_as_it_is(self) -> None:
        self.world.store.mkdir(parents=True)
        (self.world.store / "theirs.txt").write_text("kept\n")
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: {self.world.store} is already in place. "
                                        f"Remove it and {self.world.clone} to replay the ticket again.\n")
        self.assertEqual(self.world.starts_made(), [])
        self.assertEqual((self.world.store / "theirs.txt").read_text(), "kept\n")
        self.assertFalse(self.world.clone.exists())

    def test_replaying_again_after_removing_the_clone_and_repo_replaces_the_record(self) -> None:
        self.assertEqual(self.replay("A", "7").returncode, 0)
        shutil.rmtree(self.world.clone)
        shutil.rmtree(self.world.store)
        self.assertEqual(self.replay("A", "7").returncode, 0)
        [version] = self.world.versions()
        self.assertEqual(version["commit"], self.git("rev-parse", "refs/replay/direct", cwd=self.world.store))
        self.assertEqual(len(self.world.rows()), 2)

    def test_the_version_is_recorded_beside_a_default_branch_named_under_it(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.world = World(self.root_of(temp), branch="direct/release")
        self.git = self.world.git
        result = self.replay("A", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual(self.git("rev-parse", "refs/replay/direct", cwd=self.world.store), version["commit"])
        self.assertEqual(self.git("rev-parse", "origin/HEAD", cwd=self.world.clone), self.world.base)

    def test_a_ticket_in_no_replay_set_is_an_error(self) -> None:
        result = self.replay("A", "9")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: no replay set in {self.world.state} holds project A ticket 9.\n")
        self.assertFalse(self.world.gh_log.exists())

    # Each rule the help states, as one whole sentence of the section it is in, with the section's first and next
    # headings.
    RUNS, COMMITS, EXITS = ("2. Runs", "3. Starts"), ("4. Commits", "5. Scans"), ("Exit 0:", None)
    HELP_RULES = (
        (*RUNS, "Runs the repo's setup command from repos.json, where it has one, with sh in the clone, in a process "
                "group made for the replay."),
        (*RUNS, "What setup starts runs on through the session."),
        (*RUNS, "It is stopped once the session has ended, before step 4 commits the working tree, and on every other "
                "way the replay ends: a setup that fails, a start that is refused, an error, Ctrl-C or SIGTERM."),
        (*RUNS, "SIGKILL to the replay leaves it running, and a process that starts its own group or session is not "
                "followed."),
        (*COMMITS, "The replay reads each name in the index as the bytes git holds it, in any locale."),
        (*COMMITS, f"The replay's own git commands, gh's aside, set GIT_CONFIG_NOSYSTEM to 1 and GIT_CONFIG_GLOBAL to "
                   f"{os.devnull}, which switch off git's default lookups of the system config file and of the user "
                   "config files (~/.gitconfig and $XDG_CONFIG_HOME/git/config); a config file that a repo's own "
                   "config names with include.path is still read."),
        (*COMMITS, "The version's repo records the tree."),
        (*COMMITS, "A private repo, made beside it for this step, lists a copy of the clone's index and reads objects "
                   "from the clone's .git/objects and from the folders its alternates file names that exist."),
        (*EXITS, "A clone index that is not a regular file, or that the replay cannot copy or list with git, ends the "
                 "replay with one line on standard error and nothing recorded."),
        (*EXITS, "A listing that exits 0 but writes to standard error, as git does when it cannot read such a tree, "
                 "counts as one git cannot list."),
        (*EXITS, "A row that cannot be written, after the version was recorded, ends it with one line on standard "
                 "error that says the version is recorded without its row and names the command that writes the row "
                 "from the session's log, python3 scripts/scan.py SESSION; the version's line stays in "
                 "versions.jsonl, and the scan's own warnings are printed only when the row is written."),
    )
    # The conditions and outcomes inside those sentences; the check must fail when any one is dropped.
    HELP_PHRASES = (
        "in a process group made for the replay", "runs on through the session", "once the session has ended",
        "before step 4 commits the working tree", "on every other way the replay ends", "a setup that fails",
        "a start that is refused", "an error", "Ctrl-C", "or SIGTERM", "SIGKILL to the replay", "leaves it running",
        "is not followed", "as the bytes git holds it", "in any locale", "is still read", "records the tree",
        "lists a copy of the clone's index", "that exist", "not a regular file", "cannot copy or list with git",
        "with one line on standard error and nothing recorded", "exits 0 but writes to standard error",
        "counts as one git cannot list", "A row that cannot be written", "after the version was recorded",
        "says the version is recorded without its row", "python3 scripts/scan.py SESSION",
        "the version's line stays in versions.jsonl")
    # Rewordings that reverse a condition or an outcome; the check must fail for each.
    REVERSED = (
        ("on every other way the replay ends", "except when the replay ends through"),
        ("before step 4 commits", "after step 4 commits"),
        ("leaves it running", "stops it"),
        ("is not followed", "is followed"),
        ("is still read", "is not read"),
        ("A clone index that is not a regular file", "A clone index that is a regular file"),
        ("cannot copy or list with git", "can copy or list with git"),
        ("and nothing recorded", "and the version recorded"),
        ("counts as one git cannot list", "never counts as one git cannot list"),
        ("A row that cannot be written", "A row that was written successfully"),
        ("ends it with one line on standard error", "never ends it with one line on standard error"),
        ("after the version was recorded", "except after the version was recorded"),
    )

    def assert_help_states(self, text: str) -> None:
        """The help, whitespace joined: each rule, whole, as one sentence of its section."""
        self.assertNotIn("no user or system config file", text)
        for start, end, rule in self.HELP_RULES:
            self.assertEqual(text.count(start), 1, start)
            section = text[text.index(start):text.index(end) if end else None]
            self.assertIn(rule, re.split(r"(?<=\.)\s+(?=[A-Z0-9])", section.strip()))

    def test_the_help_check_fails_when_a_rule_is_dropped_or_reversed(self) -> None:
        text = " ".join(self.world.replay("--help").stdout.split())
        self.assert_help_states(text)
        for _, _, rule in self.HELP_RULES:
            with self.subTest(dropped=rule[:40]):
                with self.assertRaises(AssertionError):
                    self.assert_help_states(text.replace(rule, ""))
        for phrase in self.HELP_PHRASES:
            with self.subTest(dropped=phrase):
                self.assertEqual(sum(rule.count(phrase) for _, _, rule in self.HELP_RULES), 1)
                with self.assertRaises(AssertionError):
                    self.assert_help_states(text.replace(phrase, "", 1))
        for old, new in self.REVERSED:
            with self.subTest(reversed=old):
                self.assertEqual(text.count(old), 1)
                with self.assertRaises(AssertionError):
                    self.assert_help_states(text.replace(old, new))

    def test_bad_usage_exits_2_and_help_exits_0(self) -> None:
        for args in ((), ("A",), ("A", "seven"), ("A", "7", "8"), ("--model", "7")):
            with self.subTest(args=args):
                result = self.replay(*args)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.startswith("Rerun one ticket of the replay set"), result.stderr)
        result = self.replay("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage: python3 scripts/replay.py LABEL TICKET", result.stdout)
        self.assertIn(f"For git, its environment sets GIT_CONFIG_GLOBAL to {os.devnull} and GIT_CONFIG_NOSYSTEM to 1, "
                      f"sets core.excludesFile and core.attributesFile to {os.devnull} through GIT_CONFIG_COUNT, and "
                      "carries no other GIT_* variable of the caller's. These settings replace git's default lookups of "
                      "the system config file, of ~/.gitconfig, and of the config, ignore and attributes files under "
                      "$XDG_CONFIG_HOME/git/ (~/.config/git/ when XDG_CONFIG_HOME is unset).",
                      " ".join(result.stdout.split()))
        self.assertIn("network only to pypi.org, files.pythonhosted.org, registry.npmjs.org; local port binding; "
                      "Unix sockets only in the sandbox's temporary folder, /tmp/claude-<uid> and its spelling "
                      "/private/tmp/claude-<uid>, and in no other folder;", " ".join(result.stdout.split()))
        self.assert_help_states(" ".join(result.stdout.split()))
        self.assertFalse(self.world.starts.exists())


if __name__ == "__main__":
    unittest.main()
