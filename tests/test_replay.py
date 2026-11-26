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
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
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
# line that is not JSON, to "no-usage" leaves out the response that holds token counts;
# STANDIN_TRAP names a file that a post-commit hook and a required clean filter, which
# the session leaves in the clone, would create if anything ran them. STANDIN_TRACK set
# replaces replayed.txt with the file it names, which the repo's .gitignore matches when it
# ends in .lock: the session adds it to git with -f and commits it. The other knobs still act alongside it.
# STANDIN_INDEX_DENY set leaves the clone's index file with mode 000, as a session can.
# STANDIN_WATCH names a file holding a process id; the start record says whether that process
# is running. STANDIN_HOLD names a file the session creates before it waits for a signal.
CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
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
if os.environ.get("STANDIN_LOG") != "none":
    (folder / (session + ".jsonl")).write_text("not json\n" + text if os.environ.get("STANDIN_LOG") == "bad" else text)
if os.environ.get("STANDIN_TRACK"):
    import subprocess
    tracked = os.environ["STANDIN_TRACK"]
    (cwd / tracked).write_text("pinned\n")
    subprocess.run(["git", "add", "-f", tracked], check=True)
    subprocess.run(["git", "commit", "-q", "-m", "pin"], check=True)
else:
    (cwd / "replayed.txt").write_text("the replay's change\n")
if os.environ.get("STANDIN_TRAP"):
    trap = os.environ["STANDIN_TRAP"]
    for name, word in (("hooks/post-commit", "hook"), ("trap-filter", "filter")):
        script = cwd / ".git" / name
        script.write_text(f"#!/bin/sh\necho {word} >> '{trap}'\nexec cat\n")
        script.chmod(0o755)
    (cwd / ".gitattributes").write_text("* filter=trap\n")
    with open(cwd / ".git" / "config", "a") as config:
        config.write(f'[filter "trap"]\n\tclean = "{cwd / '.git' / 'trap-filter'}"\n\trequired = true\n')
if os.environ.get("STANDIN_INDEX_DENY"):
    (cwd / ".git" / "index").chmod(0)
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

    def replay(self, *args: str, unset: tuple[str, ...] = (), **extra: str) -> subprocess.CompletedProcess[str]:
        """Run the replay in env(**extra), less the variables unset names."""
        env = {key: value for key, value in self.env(**extra).items() if key not in unset}
        return subprocess.run([sys.executable, str(SCRIPTS / "replay.py"), *args], cwd=self.root,
                              env=env, text=True, capture_output=True, timeout=120)

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
        """The replay, running, for a test that signals it."""
        return subprocess.Popen([sys.executable, str(SCRIPTS / "replay.py"), *args], cwd=self.root,
                                env=self.env(**extra), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class ReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.world = World(Path(temp.name).resolve())
        self.git = self.world.git

    def replay(self, *args: str, unset: tuple[str, ...] = (), **extra: str) -> subprocess.CompletedProcess[str]:
        """Run the replay, then hold every session it started to the whole confinement."""
        result = self.world.replay(*args, unset=unset, **extra)
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
                            "strictAllowlist": True},
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

    def test_a_tracked_file_whose_name_holds_a_carriage_return_is_in_the_version_under_that_name(self) -> None:
        name = "a\rb.lock"
        result = self.replay("A", "7", STANDIN_TRACK=name)
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual(self.world.names(version["commit"]), [*self.BASE_FILES, name.encode()])

    def test_a_tracked_file_with_a_non_ascii_name_is_in_the_version_when_the_locale_is_not_utf_8(self) -> None:
        name = "café.lock"
        result = self.replay("A", "7", STANDIN_TRACK=name, LC_ALL="C", PYTHONUTF8="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        [version] = self.world.versions()
        self.assertEqual(self.world.names(version["commit"]), [*self.BASE_FILES, name.encode()])

    def test_a_tracked_file_whose_name_is_not_utf_8_is_in_the_version_under_its_bytes(self) -> None:
        name = b"caf\xe9.lock"
        probe = self.world.root / os.fsdecode(name)
        try:
            probe.write_bytes(b"")
        except OSError:
            self.skipTest("this file system refuses a name that is not UTF-8")
        probe.unlink()
        result = self.replay("A", "7", STANDIN_TRACK=os.fsdecode(name))
        self.assertEqual(result.returncode, 0, result.stderr)
        [version] = self.world.versions()
        self.assertEqual(self.world.names(version["commit"]), [*self.BASE_FILES, name])

    @unittest.skipIf(os.geteuid() == 0, "root reads a file whatever its mode")
    def test_a_clone_index_that_cannot_be_read_ends_in_one_line_and_records_nothing(self) -> None:
        result = self.replay("A", "7", STANDIN_INDEX_DENY="1")
        index = self.world.clone / ".git" / "index"
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"replay: the clone's index {index} cannot be read (Permission denied). "
                                        "Nothing is recorded, and the clone and the version's repo are kept.\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.world.versions(), [])
        self.assertEqual(self.world.rows(), [])
        self.assertTrue(self.world.clone.is_dir())
        self.assertTrue(self.world.store.is_dir())
        self.assertEqual(sorted(path.name for path in self.world.store.glob("replay-*")), ["replay-index"])

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

    def watch_setup(self, tail: str = "") -> Path:
        """A setup command that starts a process outliving it, whose pid it writes to the returned file."""
        watch = self.world.root / "watched.pid"
        self.world.write("repos.json", [{"repo": REPO, "check": "true", "setup":
                                         f"touch .setup-done && {{ sleep 60 </dev/null >/dev/null 2>&1 & "
                                         f'echo $! > "$STANDIN_WATCH"; }}{tail}'}])
        return watch

    def assert_gone(self, watch: Path) -> None:
        pid = int(watch.read_text())
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
        self.fail(f"the process setup started, {pid}, is still running")

    def test_what_setup_starts_runs_through_the_session_and_is_gone_when_the_replay_has_exited(self) -> None:
        watch = self.watch_setup()
        result = self.replay("A", "7", STANDIN_WATCH=str(watch))
        self.assertEqual(result.returncode, 0, result.stderr)
        [start] = self.world.starts_made()
        self.assertIs(start["watched_alive"], True)
        self.assert_gone(watch)

    def test_what_setup_starts_is_gone_when_the_setup_fails_or_the_session_s_start_is_refused(self) -> None:
        for tail, extra, message in (
                (" && exit 4", {}, "replay: the setup command exited 4; no session started."),
                ("", {"STANDIN_NO_SANDBOX": "1"}, "replay: claude exited 1, left no session log and changed "
                                                  "nothing, so no session started.")):
            with self.subTest(tail=tail, extra=extra):
                watch = self.watch_setup(tail)
                result = self.replay("A", "7", STANDIN_WATCH=str(watch), **extra)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr.splitlines()[-1], message)  # the stand-in's own error comes before
                self.assert_gone(watch)

    def test_what_setup_starts_is_gone_when_the_replay_is_interrupted_during_setup_or_the_session(self) -> None:
        for number in (signal.SIGINT, signal.SIGTERM):
            for where in ("setup", "session"):
                with self.subTest(signal=number.name, where=where):
                    shutil.rmtree(self.world.clone, ignore_errors=True)
                    shutil.rmtree(self.world.store, ignore_errors=True)
                    holding = self.world.root / "holding"
                    holding.unlink(missing_ok=True)
                    watch = self.watch_setup(f" && touch {holding} && sleep 60" if where == "setup" else "")
                    extra = {"STANDIN_HOLD": str(holding)} if where == "session" else {}
                    replay = self.world.start("A", "7", STANDIN_WATCH=str(watch), **extra)
                    self.addCleanup(replay.kill)
                    for _ in range(400):
                        if holding.exists() or replay.poll() is not None:
                            break
                        time.sleep(0.05)
                    self.assertTrue(holding.exists())
                    replay.send_signal(number)
                    _, stderr = replay.communicate(timeout=60)
                    self.assertNotEqual(replay.returncode, 0)
                    if number == signal.SIGTERM:
                        self.assertEqual((replay.returncode, stderr), (128 + signal.SIGTERM, "replay: stopped by SIGTERM.\n"))
                    self.assert_gone(watch)

    def test_the_group_setup_started_is_stopped_whichever_call_after_it_is_interrupted(self) -> None:
        # The invariant: once setup has run, no exit of the replay leaves a process of its group running.
        # Each call the replay makes between setup and its end takes a Ctrl-C in turn.
        points = (("replay", "snapshot", 1), ("replay", "command", 1), ("replay", "environment", 1),
                  ("scan", "resolve", 1), ("replay", "snapshot", 2), ("scan", "scan", 1), ("replay", "record", 1),
                  ("scan", "write_row", 1))
        wrapper = ("import sys\nsys.path.insert(0, {scripts!r})\nimport replay, scan\n"
                   "module, name, nth = {{'replay': replay, 'scan': scan}}[sys.argv[1]], sys.argv[2], int(sys.argv[3])\n"
                   "real, calls = getattr(module, name), []\n"
                   "def interrupted(*args, **options):\n"
                   "    calls.append(1)\n"
                   "    if len(calls) == nth:\n"
                   "        raise KeyboardInterrupt\n"
                   "    return real(*args, **options)\n"
                   "setattr(module, name, interrupted)\n"
                   "sys.exit(replay.main(['A', '7']))\n").format(scripts=str(SCRIPTS))
        for module, name, nth in points:
            with self.subTest(call=f"{module}.{name} #{nth}"):
                shutil.rmtree(self.world.clone, ignore_errors=True)
                shutil.rmtree(self.world.store, ignore_errors=True)
                watch = self.watch_setup()
                env = self.world.env(STANDIN_WATCH=str(watch))
                result = subprocess.run([sys.executable, "-c", wrapper, module, name, str(nth)], cwd=self.world.root,
                                        env=env, text=True, capture_output=True, timeout=120)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("KeyboardInterrupt", result.stderr)
                self.assert_gone(watch)

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
            shutil.rmtree(self.world.clone, ignore_errors=True)
            shutil.rmtree(self.world.store, ignore_errors=True)
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
        for skill, marked in (("implement-ticket", True), ("deliver", True), ("fan-out", True), ("tdd", False)):
            with self.subTest(skill=skill):
                shutil.rmtree(self.world.clone, ignore_errors=True)
                shutil.rmtree(self.world.store, ignore_errors=True)
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
        self.world = World(Path(temp.name).resolve(), branch="direct/release")
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
        text = " ".join(result.stdout.split())
        step4 = text[text.index("4. Commits whatever"):text.index("5. Scans the session")]
        self.assertEqual(step4.count(
            f"The replay's own git commands, gh's aside, set GIT_CONFIG_NOSYSTEM to 1 and GIT_CONFIG_GLOBAL to "
            f"{os.devnull}, which switch off git's default lookups of the system config file and of the user config "
            "files (~/.gitconfig and $XDG_CONFIG_HOME/git/config); a config file that a repo's own config names with "
            "include.path is still read."), 1)
        self.assertNotIn("no user or system config file", text)
        for sentence in (
                "The replay reads each name in the index as the bytes git holds it, in any locale.",
                "What setup starts runs on through the session. It is stopped once the session has ended, before step 4 "
                "commits the working tree, and on every other way the replay ends: a setup that fails, a start that is "
                "refused, an error, Ctrl-C or SIGTERM. SIGKILL to the replay leaves it running, and a process that "
                "starts its own group or session is not followed.",
                "A clone index that cannot be copied or read ends the replay with one line on standard error and "
                "nothing recorded. A row that cannot be written, after the version was recorded, ends it with one "
                "line that says the version is recorded without its row and names the command that writes the row "
                "from the session's log, python3 scripts/scan.py SESSION; the version's line stays in versions.jsonl."):
            with self.subTest(sentence=sentence[:40]):
                self.assertEqual(text.count(sentence), 1)
        self.assertFalse(self.world.starts.exists())


if __name__ == "__main__":
    unittest.main()
