"""Exercise tests/cross_harness.py at its command line against stand-ins.

Each test builds its own world in a temporary folder: a copy of the driver and the probe kit
beside a stand-in skills/deliver/scripts/deliver.py, the probe kit tests' stand-in `hc`, one
stand-in harness installed as all five harness commands, a stand-in `gh`, a `git` that logs each
call before it runs the real one, and a local bare repo as the fixture, its base commit tagged
`base`. The stand-in harness writes what a real run of G or T1 leaves: deliver's records, refusal
log lines, the stand-in commands' markers, a PR the stand-in `gh` answers for, a merge pushed to
the fixture, and output with a session id and local paths in it. PATH holds only the stand-ins
and the system folders, and HOME and the machine directory point inside the world, so no test
starts a real session, touches the network or reads the real machine directory.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from test_probe_kit import HC  # noqa: E402  the probe kit tests' stand-in hc

DRIVER = TESTS / "cross_harness.py"
GUARD = TESTS.parent / "skills" / "deliver" / "scripts" / "guard.py"
SESSION = "sess-5d2e81b0"  # the session id the stand-in harness prints
CONNECTION = "client-conn-x"  # the Cortex Code connection the tests pass
FIXTURE = "owner/fixture"
PROBE = "gh pr merge --deliver-guard-probe"
HARNESSES = ("claude", "cortex", "codex", "cursor", "antigravity")
COMMAND_NAMES = {"claude": "claude", "cortex": "cortex", "codex": "codex", "cursor": "cursor-agent",
                 "antigravity": "agy"}

# Knobs, comma-separated in STANDIN: drop=<class>|<class> leaves those refusals out of the log;
# no-control, oneway-ran, no-warning, no-finish, preflight-stop, no-agent-probe, harness=<name>;
# agent starts an agent; no-small-test, merge-owner, not-merged, no-merge, denied, no-usage.
HARNESS = (r'''#!{python}
import json, os, re, subprocess, sys, time
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
prompt = args[args.index("-p") + 1] if name in ("claude", "cortex", "agy") else args[-1]
cwd, home = Path.cwd(), Path(os.environ["HOME"])
knobs = dict((k.split("=", 1) + [""])[:2] for k in os.environ.get("STANDIN", "").split(",") if k)
state = Path(os.environ["DELIVER_STATE_DIR"])
held = sorted(str(p) for p in [*cwd.rglob("*"), *home.rglob("*")]
              if p.is_file() and ".git" not in p.parts and "command(*)" in p.read_text(errors="replace"))
with open(os.environ["STANDIN_STARTS"], "a") as starts:
    starts.write(json.dumps({"name": name, "args": args, "prompt": prompt, "cwd": str(cwd),
                             "state_dir": str(state), "cursor_agents": (cwd / ".cursor/agents").is_dir(),
                             "allow_rule_files": held}) + "\n")
print("stand-in " + SESSION + " in " + str(cwd) + " started with " + " ".join(args), file=sys.stderr, flush=True)
time.sleep(float(os.environ.get("STANDIN_SLEEP", "0")))
records = cwd / ".git/deliver/branches/deliver/run-1/records.jsonl"
records.parent.mkdir(parents=True, exist_ok=True)
own = {"claude": "claude-code", "cortex": "cortex-code", "codex": "codex", "cursor-agent": "cursor", "agy": "antigravity"}


def record(event, **fields):
    with records.open("a") as f:
        f.write(json.dumps({"event": event, "at": "2026-11-28T10:00:00Z", **fields}) + "\n")


def refuse(cls, run="run-1"):
    state.mkdir(parents=True, exist_ok=True)
    with (state / "guard-refusals.jsonl").open("a") as f:
        f.write(json.dumps({"at": "2026-11-28T10:00:01Z", "guard": "raw-pr", "class": cls,
                            "permission_mode": "acceptEdits", "run": run}) + "\n")


def git(*a):
    subprocess.run(["git", *a], check=True, capture_output=True)


agent_events, result = [], {}
typed = prompt.startswith(("/deliver ", "$deliver "))
record("start", run="run-1", branch_created=True, stop_at_ready=False)
if not typed:  # G
    refuse("gh pr ready", run="run-0")  # another run's line, which must not count
    classes = ["probe", "gh pr merge", "gh pr ready", "one-way"]
    classes += [] if name == "cursor-agent" else ["deliver.py merge"]
    classes += ["probe"] if name == "claude" else []
    for cls in classes:
        if cls not in knobs.get("drop", "").split("|"):
            refuse(cls)
    commands = re.findall(r"`([^`]+)`", prompt)
    if "no-control" not in knobs:
        subprocess.run(next(c for c in commands if c.endswith("/control.sh")), shell=True, check=True)
    if "oneway-ran" in knobs:
        subprocess.run(next(c for c in commands if "/deploy.sh" in c), shell=True, check=True)
    warnings = ["the guard cannot tell an agent from the session on Cursor"] if name == "cursor-agent" else []
    if "no-warning" in knobs:
        warnings = []
    stop = "preflight-stop" in knobs
    record("preflight", run="run-1", result="stop" if stop else "pass", stops=["preflight.no-gh"] if stop else [],
           warnings=warnings, guard_probe="seen", permission_mode="acceptEdits",
           harness=knobs.get("harness") or own[name])
    if "no-finish" not in knobs:
        record("finish", run="run-1")
    if name == "claude" and "no-agent-probe" not in knobs:
        agent_events.append({"type": "assistant", "parent_tool_use_id": "toolu_1", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "''' + PROBE + r'''"}}]}})
else:  # T1
    (cwd / "calc.py").write_text((cwd / "calc.py").read_text().replace("Return a + b.", "Return the sum of a and b."))
    git("commit", "-q", "-am", "docs: reword add")
    git("push", "-q", "origin", "HEAD:refs/heads/deliver/run-1")
    record("pr", number=7, url="https://github.example/pr/7")
    record("ready", commit="abc", result="small edit")
    small = "" if "no-small-test" in knobs else "small test: pass, 1 line, no critical path, no dependents command\n"
    merged = "merge: left to the owner, one-way door" if "merge-owner" in knobs else "merge: by the session, squash"
    if "not-merged" not in knobs:
        git("push", "-q", "origin", "HEAD:refs/heads/main")
    if "no-merge" not in knobs:
        record("merge", commit="abc", method="squash", merge_line=merged)
    body = ("Reword add.\n\n<details><summary>Measurement</summary>\n\n```text\nversion: 0.1.0\npath: small edit\n"
            + small + "door: two-way\n" + ("" if "no-merge" in knobs else merged + "\n") + "```\n\n</details>\n")
    gh = Path(os.environ["STANDIN_GH_DIR"])
    (gh / "prs.json").write_text(json.dumps({
        "7": {"state": "OPEN" if "not-merged" in knobs else "MERGED", "body": body},
        "8": {"state": "OPEN", "body": "left open by the run"}}))
    if "denied" in knobs:
        result["denied_actions"] = [{"tool": "run_command"}]
starting = "agent" in knobs
usage = None if "no-usage" in knobs else {"input_tokens": 12, "output_tokens": 340}


def emit(**event):
    print(json.dumps({k: v for k, v in event.items() if v is not None}), flush=True)


if name in ("claude", "cortex"):
    emit(type="system", subtype="init", session_id=SESSION, cwd=str(cwd), model="standin-model")
    if starting:
        emit(type="assistant", message={"content": [{"type": "tool_use", "id": "toolu_1", "name": "Agent", "input": {}}]})
    for event in agent_events:
        print(json.dumps(event))
    emit(type="result", session_id=SESSION, result="done in " + str(cwd), usage=usage)
elif name == "codex":
    emit(type="thread.started", thread_id=SESSION)
    if starting:
        emit(type="item.started", item={"type": "collab_tool_call", "tool": "spawn_agent"})
    emit(type="turn.completed", usage=usage)
elif name == "agy":
    emit(event="init", init={"model": "standin-model", "cwd": str(cwd)})
    if starting:
        emit(event="step_update", step={"tool": "invoke_subagent"})
    emit(event="result", result={"response": "done", "conversation_id": SESSION, **result,
                                 **({"usage": usage} if usage else {})})
else:  # cursor-agent
    emit(type="system", subtype="init", session_id=SESSION, cwd=str(cwd), model="standin-model")
    if starting:
        emit(type="tool_call", subtype="started", tool_call={"name": "Task"})
    emit(type="result", session_id=SESSION, result="done",
         usage=usage and {"inputTokens": 12, "outputTokens": 340})
sys.exit(int(os.environ.get("STANDIN_EXIT", "0")))
''').replace("SESSION", repr(SESSION))

# The stand-in gh: answers for the fixture only, from prs.json, and logs every call.
GH = r'''#!{python}
import json, os, subprocess, sys
from pathlib import Path
folder, args = Path(os.environ["STANDIN_GH_DIR"]), sys.argv[1:]
with open(folder / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\n")
if os.environ["STANDIN_FIXTURE"] not in args:
    sys.exit(3)
saved = folder / "prs.json"
prs = json.loads(saved.read_text()) if saved.exists() else {}
if args[:2] == ["repo", "clone"]:
    subprocess.run(["git", "clone", "-q", os.environ["STANDIN_REMOTE"], args[3]], check=True)
elif args[:2] == ["pr", "list"]:
    print(json.dumps([{"number": int(n)} for n, pr in prs.items() if pr["state"] == "OPEN"]))
elif args[:2] == ["pr", "close"]:
    prs[args[2]]["state"] = "CLOSED"
    saved.write_text(json.dumps(prs))
elif args[:2] == ["pr", "view"] and args[2] in prs:
    print(json.dumps({"state": prs[args[2]]["state"], "body": prs[args[2]]["body"]}))
elif args[:2] == ["repo", "view"]:
    print(json.dumps({"url": os.environ["STANDIN_REMOTE"], "defaultBranchRef": {"name": "main"}}))
else:
    sys.exit(1)
'''

# git first on PATH: logs each call with its folder, then runs the real git.
GIT = r'''#!{python}
import json, os, sys
with open(os.environ["STANDIN_GIT_LOG"], "a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
os.execv({git!r}, ["git", *sys.argv[1:]])
'''

# The stand-in deliver.py the driver runs for `install cursor`.
DELIVER = r'''import json, os, sys
from pathlib import Path
with open(os.environ["STANDIN_DELIVER_LOG"], "a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
if sys.argv[1:] == ["install", "cursor"]:
    (Path.cwd() / ".cursor/agents").mkdir(parents=True)
    (Path.cwd() / ".cursor/agents/deliver-reader.md").write_text("reader\n")
sys.exit(int(os.environ.get("STANDIN_INSTALL_EXIT", "0")))
'''


def lines(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class World:
    """A temporary folder holding the stand-ins, HOME, the machine directory and the fixture."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cross-harness-test-")).resolve()
        for name in ("bin", "home", "state", "hc", "gh", "tmp"):
            (self.root / name).mkdir()
        self.bin, self.state = self.root / "bin", self.root / "state"
        self.tree = self.root / "tree"
        (self.tree / "tests").mkdir(parents=True)
        (self.tree / "skills/deliver/scripts").mkdir(parents=True)
        for name in ("cross_harness.py", "probe_kit.py"):
            shutil.copy(TESTS / name, self.tree / "tests" / name)
        (self.tree / "skills/deliver/scripts/deliver.py").write_text(DELIVER)
        real_git = shutil.which("git")
        stand_ins = {"hc": HC, "standin-harness": HARNESS, "gh": GH, "git": GIT.replace("{git!r}", repr(real_git))}
        for name, text in stand_ins.items():
            (self.bin / name).write_text(text.replace("{python}", sys.executable))
            (self.bin / name).chmod(0o755)
        for name in COMMAND_NAMES.values():
            (self.bin / name).symlink_to(self.bin / "standin-harness")
        (self.root / "gitconfig").write_text("[user]\n\tname = Stand-in\n\temail = standin@example.com\n")
        self.env = {"PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.root / "home"),
                    "DELIVER_STATE_DIR": str(self.state), "TMPDIR": str(self.root / "tmp"),
                    "STANDIN_HC_DIR": str(self.root / "hc"), "STANDIN_GH_DIR": str(self.root / "gh"),
                    "STANDIN_STARTS": str(self.root / "starts.jsonl"), "STANDIN_FIXTURE": FIXTURE,
                    "STANDIN_REMOTE": str(self.root / "fixture.git"),
                    "STANDIN_GIT_LOG": str(self.root / "git.jsonl"),
                    "STANDIN_DELIVER_LOG": str(self.root / "deliver.jsonl"),
                    "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_SYSTEM": os.devnull, "LANG": "C.UTF-8"}
        self.base = self.make_fixture(real_git)

    def make_fixture(self, real_git: str) -> str:
        """The bare fixture repo: tests/fixture-repo committed on main and tagged base. Returns the base commit."""
        work = self.root / "seed"
        shutil.copytree(TESTS / "fixture-repo", work, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))

        def git(*args: str, cwd: Path = work) -> str:
            return subprocess.run([real_git, *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                                  text=True).stdout.strip()

        git("init", "-q", "--bare", "-b", "main", str(self.root / "fixture.git"), cwd=self.root)
        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("tag", "base")
        git("push", "-q", str(self.root / "fixture.git"), "main", "base")
        return git("rev-parse", "HEAD")

    def drive(self, *args: str, **env: str) -> tuple[int, str, str]:
        """Run the driver once, its output sent to files, and return its exit code, stdout and stderr."""
        if args[:1] == ("run",):
            args += ("--fixture", FIXTURE, "--poll", "0.05")
        out, err = self.root / "driver.out", self.root / "driver.err"
        with open(out, "w") as stdout, open(err, "w") as stderr:
            done = subprocess.run([sys.executable, str(self.tree / "tests/cross_harness.py"), *args],
                                  env={**self.env, **env}, stdout=stdout, stderr=stderr, timeout=120)
        return done.returncode, out.read_text(), err.read_text()

    def starts(self) -> list[dict]:
        return lines(self.root / "starts.jsonl")

    def remote(self, *args: str) -> str:
        return subprocess.run(["git", "--git-dir", str(self.root / "fixture.git"), *args], env=self.env,
                              check=True, capture_output=True, text=True).stdout.strip()


class CrossHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World()
        self.addCleanup(shutil.rmtree, self.world.root, ignore_errors=True)

    def drive(self, *args: str, **env: str) -> tuple[int, list[str]]:
        """Run the driver; check that nothing it printed holds a session id, the connection or a local path."""
        code, out, err = self.world.drive(*args, **env)
        for text in (out, err):
            self.assertNotIn(SESSION, text)
            self.assertNotIn(CONNECTION, text)
            self.assertNotRegex(text, r"(?<![\w.])/(?:Users|home|private|tmp|var)\b")
            self.assertNotIn(str(self.world.root), text)
        return code, out.splitlines()

    def test_g_and_t1_pass_on_claude_code(self):
        code, out = self.drive("run", "claude", "G", "T1")
        self.assertEqual(out, [
            "G claude passed: preflight passed as claude-code; the guard refused the probe, a raw gh pr merge, "
            "a raw gh pr ready, the one-way command, the agent's deliver.py merge and the agent's probe; "
            "the control command ran; tokens: 12 in, 340 out",
            "T1 claude passed: one session and no agent; the small test passed; the session merged PR 7; "
            "tokens: 12 in, 340 out",
        ])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
