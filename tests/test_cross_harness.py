"""Exercise tests/cross_harness.py at its command line against stand-ins.

Each test builds its own world in a temporary folder: a copy of the driver and the probe kit
beside a stand-in skills/deliver/scripts/deliver.py, the probe kit tests' stand-in `hc`, one
stand-in harness installed as all five harness commands, a stand-in `gh`, a `git` that logs each
call before it runs the real one, and a local bare repo as the fixture, its base commit tagged
`base`. The stand-in harness writes what a real run of G, T1 or T2 leaves: deliver's records, which T1
and T2 remove after their merge as `deliver.py finish` does, refusal log lines, the stand-in commands' markers, a PR the stand-in `gh` answers for, a merge pushed to
the fixture, and output with a session id and local paths in it. T2's output also holds the two
brief lines and the two `save review` commands, in tool calls of no harness's real shape. PATH holds only the stand-ins
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
# agent starts an agent, agent-event prints an event an agent made, no-cached leaves Codex's cached count out; no-small-test, merge-owner, not-merged, no-merge, denied, no-usage.
# T2: path=<path>, no-path, no-roles, roles-<knob> (ROLES below), no-findings, no-defect-review, no-brief=<role>,
# brief-key=<key> puts the defect agent start's brief line under that key, no-agent-start prints the brief commands'
# output and starts no agent, save-first saves the first review before the defect agent start,
# two-blocks puts a stale measurement block before the run's own.
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
                             "request": (cwd / ".deliver/request.md").read_text() if (cwd / ".deliver/request.md").exists() else None,
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


ROLES = {"": "roles: author; requirements reviewer standin-opus/high; defect reviewer standin-sonnet/high, not applied",
         "roles-no-defect": "roles: author; requirements reviewer standin-opus/high",
         "roles-text-only": "roles: author; requirements reviewer standin-opus/high; defect reviewer not needed, text only",
         "roles-no-model": "roles: author; requirements reviewer /high; defect reviewer standin-sonnet/high",
         "roles-auto": "roles: author; requirements reviewer standin-opus/high; defect reviewer auto/high",
         "roles-no-effort": "roles: author; requirements reviewer standin-opus/; defect reviewer standin-sonnet/high"}
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
elif "multiply" not in prompt:  # T1
    (cwd / "calc.py").write_text((cwd / "calc.py").read_text().replace("Return a + b.", "Return the sum of a and b."))
    git("commit", "-q", "-am", "docs: reword add")
    git("push", "-q", "origin", "HEAD:refs/heads/deliver/run-1")
    saved = Path(os.environ["STANDIN_GH_DIR"]) / "prs.json"
    prs = json.loads(saved.read_text())
    number = max(map(int, prs)) + 1  # the run's PR, and after it one more the run leaves open
    record("pr", number=number, url=f"https://github.example/pr/{number}")
    record("ready", commit="abc", result="small edit")
    small = "" if "no-small-test" in knobs else "small test: pass, 1 line, no critical path, no dependents command\n"
    merged = "merge: left to the owner, one-way door" if "merge-owner" in knobs else "merge: by the session, squash"
    if "not-merged" not in knobs:
        git("push", "-q", "origin", "HEAD:refs/heads/main")
    if "no-merge" not in knobs:
        record("merge", commit="abc", method="squash", merge_line=merged)
    body = ("Reword add.\n\n<details><summary>Measurement</summary>\n\n```text\nversion: 0.1.0\npath: small edit\n"
            + small + "door: two-way\n" + ("" if "no-merge" in knobs else merged + "\n") + "```\n\n</details>\n")
    prs[str(number)] = {"state": "OPEN" if "not-merged" in knobs else "MERGED", "body": body}
    prs[str(number + 1)] = {"state": "OPEN", "body": "left open by the run"}
    saved.write_text(json.dumps(prs))
    if "not-merged" not in knobs:  # deliver.py finish removes the records after a merge
        records.unlink()
    if "denied" in knobs:
        result["denied_actions"] = [{"tool": "run_command"}]
else:  # T2, ticket A
    (cwd / "calc.py").write_text((cwd / "calc.py").read_text() + "\n\ndef multiply(a, b):\n    return a * b\n")
    git("commit", "-q", "-am", "feat: multiply")
    git("push", "-q", "origin", "HEAD:refs/heads/deliver/run-1")
    saved = Path(os.environ["STANDIN_GH_DIR"]) / "prs.json"
    prs = json.loads(saved.read_text())
    number = max(map(int, prs)) + 1
    record("pr", number=number, url=f"https://github.example/pr/{number}")
    roles = ROLES.get(next((k for k in knobs if k.startswith("roles-")), ""), ROLES[""])
    findings = ("findings: requirements review 2 (1 proven)" + ("" if "no-defect-review" in knobs
                else "; defect review 1 (0 proven)"))
    block = ["version: 0.1.2", "" if "no-path" in knobs else "path: " + knobs.get("path", "single ticket"),
             "small test: fail, needs review: high blast radius, critical paths changed: test_calc.py",
             "door: two-way", "" if "no-roles" in knobs else roles, "" if "no-findings" in knobs else findings,
             "fix rounds: 1", "follow-ups: 0 filed, 0 not filed",
             "merge: left to the owner, one-way door" if "merge-owner" in knobs else "merge: by the session, squash"]
    def details(lines):
        return "<details><summary>Measurement</summary>\n\n```text\n" + "".join(l + "\n" for l in lines if l) + "```\n\n</details>\n"
    stale = details(["version: 0.1.2", "path: small edit", "small test: pass, 1 line"]) + "\n" if "two-blocks" in knobs else ""
    prs[str(number)] = {"state": "OPEN" if "not-merged" in knobs else "MERGED", "body": "Add multiply.\n\n" + stale + details(block)}
    saved.write_text(json.dumps(prs))
    if "not-merged" not in knobs:
        git("push", "-q", "origin", "HEAD:refs/heads/main")
        records.unlink()
    briefs = records.parent / "briefs"
    deliver = "uv run --python 3.13 --no-project " + str(cwd) + "/deliver.py"
    def call(**fields):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_2", **fields}]}}
    said = {role: [{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_3",
                                                              "content": f"Read {briefs}/{role}-0.md and follow it.\n"}]}},
                   call(name="Agent", input={"prompt": f"Read {briefs}/{role}-0.md and follow it."})]
            for role in ("requirements", "defect") if knobs.get("no-brief") != role}  # the brief command's output, the agent start
    if "brief-key" in knobs and "defect" in said:  # a key the driver does not know
        said["defect"][1] = {"type": "item.completed", "item": {knobs["brief-key"]: f"Read {briefs}/defect-0.md and follow it."}}
    if "no-agent-start" in knobs:
        said = {role: pair[:1] for role, pair in said.items()}
    save = {role: call(name="Bash", input={"command": f"{deliver} save review {role}"}) for role in ("requirements", "defect")}
    order = (["requirements", "save requirements", "defect", "save defect"] if "save-first" in knobs
             else ["requirements", "defect", "save requirements", "save defect"])
    for step in order:
        for event in [save[step.split()[1]]] if step.startswith("save") else said.get(step, []):
            print(json.dumps(event), flush=True)
starting = "agent" in knobs
usage = None if "no-usage" in knobs else {"input_tokens": 12, "output_tokens": 340}


def emit(**event):
    print(json.dumps({k: v for k, v in event.items() if v is not None}), flush=True)


if name in ("claude", "cortex"):
    emit(type="system", subtype="init", session_id=SESSION, cwd=str(cwd), model="standin-model")
    if starting:
        emit(type="assistant", message={"content": [{"type": "tool_use", "id": "toolu_1", "input": {},
                                                     "name": "task" if name == "cortex" else "Agent"}]})
    if "agent-event" in knobs:  # an event an agent made, with no agent call in the output
        agent_events.append({"type": "assistant", "parent_tool_use_id": "toolu_9", "message": {"content": []}})
    for event in agent_events:
        print(json.dumps(event))
    emit(type="result", session_id=SESSION, result="done in " + str(cwd), usage=usage)
elif name == "codex":
    emit(type="thread.started", thread_id=SESSION)
    if starting:
        emit(type="item.started", item={"type": "collab_tool_call", "tool": "spawn_agent"})
    cached = {} if "no-cached" in knobs else {"cached_input_tokens": 8}  # 20 in, 8 of them from the cache
    emit(type="turn.completed", usage=usage and {**usage, "input_tokens": 20, **cached})
elif name == "agy":
    emit(event="init", init={"model": "standin-model", "cwd": str(cwd)})
    if starting:
        emit(event="step_update", step={"tool": "invoke_subagent"})
    emit(event="result", result={"response": "done", "conversation_id": SESSION, **result,
                                 **({"usage": usage} if usage else {})})
else:  # cursor-agent
    emit(type="system", subtype="init", session_id=SESSION, cwd=str(cwd), model="standin-model")
    if starting:
        emit(type="tool_call", subtype="started", tool_call={"taskToolCall": {"args": {"prompt": "go"}}})
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
    state = args[args.index("--state") + 1]
    print(json.dumps([{"number": int(n), **pr} for n, pr in sorted(prs.items(), key=lambda p: -int(p[0]))
                      if state == "all" or pr["state"] == state.upper()]))
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
if os.environ.get("STANDIN_GIT_REFUSE_FORCE") and "--force" in sys.argv:
    sys.exit(1)
os.execv({git!r}, ["git", *sys.argv[1:]])
'''

# The stand-in uv: runs `uv run --python V --no-project SCRIPT ARGS` with this Python and passes on its options.
UV = r'''#!{python}
import os, sys
assert sys.argv[1] == "run" and sys.argv[4] == "--no-project", sys.argv
os.environ["STANDIN_UV"] = " ".join(sys.argv[1:5])
os.execv(sys.executable, [sys.executable, *sys.argv[5:]])
'''

# The stand-in deliver.py the driver runs for `install cursor`. Like install.py, it refuses inside a
# Claude Code session, which sets CLAUDECODE.
DELIVER = r'''import json, os, sys
from pathlib import Path
with open(os.environ["STANDIN_DELIVER_LOG"], "a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "uv": os.environ.get("STANDIN_UV"),
                          "state_dir": os.environ.get("DELIVER_STATE_DIR")}) + "\n")
if os.environ.get("CLAUDECODE"):
    print("REFUSED install.wrong-harness: this session runs on claude-code, not cursor, at " + os.getcwd())
    sys.exit(10)
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
        stand_ins = {"hc": HC, "standin-harness": HARNESS, "gh": GH, "uv": UV, "git": GIT.replace("{git!r}", repr(real_git))}
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
        # A PR and its branch from before the run, which the reset leaves alone.
        (self.root / "gh" / "prs.json").write_text(json.dumps({"5": {"state": "OPEN", "body": "an owner's PR"}}))

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
        git("push", "-q", str(self.root / "fixture.git"), "main", "base", "main:refs/heads/owner/keep")
        return git("rev-parse", "HEAD")

    def drive(self, *args: str, **env: str) -> tuple[int, str, str]:
        """Run the driver once, its output sent to files, and return its exit code, stdout and stderr."""
        if args[:1] == ("run",) and "--fixture" not in args:
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

    def next_pr(self) -> int:
        """The number of the PR the next T1 opens."""
        return max(map(int, json.loads((self.world.root / "gh" / "prs.json").read_text()))) + 1

    def run_on(self, harness: str, *tasks: str, **env: str) -> tuple[int, list[str]]:
        connection = ("--connection", CONNECTION) if harness == "cortex" else ()
        return self.drive("run", harness, *(tasks or ("G", "T1")), *connection, **env)

    def test_g_and_t1_pass_on_each_harness(self):
        refused = "the probe, a raw gh pr merge, a raw gh pr ready, the one-way command and the agent's deliver.py merge"
        g_facts = {
            "claude": ("preflight passed as claude-code; the guard refused the probe, a raw gh pr merge, a raw gh pr "
                       "ready, the one-way command, the agent's deliver.py merge and the agent's probe; "
                       "the control command ran"),
            "cortex": f"preflight passed as cortex-code; the guard refused {refused}; the control command ran",
            "codex": f"preflight passed as codex; the guard refused {refused}; the control command ran",
            "cursor": ("preflight passed as cursor; preflight warned that the guard cannot tell an agent from the "
                       "session; the guard refused the probe, a raw gh pr merge, a raw gh pr ready and the one-way "
                       "command; the control command ran"),
            "antigravity": (f"preflight passed as antigravity; the guard refused {refused}; the control command ran; "
                            "denied_actions: none"),
        }
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                pr = self.next_pr()
                code, out = self.run_on(harness)
                self.assertEqual(out, [
                    f"G {harness} passed: {g_facts[harness]}; tokens: 12 in, 340 out",
                    f"T1 {harness} passed: one session and no agent; the small test passed; the session merged "
                    f"PR {pr}; "
                    "tokens: 12 in, 340 out",
                ])
                self.assertEqual(code, 0)

    def test_each_harness_gets_its_headless_command(self):
        plugin = str(self.world.tree / "skills" / "deliver")
        expected = {
            "claude": ["-p", "{prompt}", "--output-format", "stream-json", "--verbose", "--setting-sources", "project",
                       "--no-session-persistence", "--permission-mode", "acceptEdits", "--allowedTools",
                       "Agent,Read,Write,Edit,Bash,Glob,Grep", "--plugin-dir", plugin],
            "cortex": ["-p", "{prompt}", "--output-format", "stream-json", "--bypass", "-c", CONNECTION],
            "codex": ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "{prompt}"],
            "cursor": ["-p", "--output-format", "stream-json", "--force", "{prompt}"],
            "antigravity": ["-p", "{prompt}", "--output-format", "stream-json", "--mode", "accept-edits",
                            "--settings", '{"permissions": {"allow": ["command(*)"]}}'],
        }
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                before = len(self.world.starts())
                self.run_on(harness, "T1")
                start, = self.world.starts()[before:]
                self.assertEqual(start["name"], COMMAND_NAMES[harness])
                self.assertEqual([part if part != start["prompt"] else "{prompt}" for part in start["args"]],
                                 expected[harness])
                self.assertEqual(start["allow_rule_files"], [])  # the allow rule is on the command line only
                self.assertEqual(Path(start["state_dir"]).name, "state")  # the run's own machine directory
                self.assertNotEqual(start["state_dir"], str(self.world.state))

    def test_cursor_runs_install_in_the_clone_before_the_session(self):
        self.run_on("cursor", "T1")
        install, = lines(self.world.root / "deliver.jsonl")
        start, = self.world.starts()
        self.assertEqual(install, {"args": ["install", "cursor"], "cwd": start["cwd"],
                                   "uv": "run --python 3.13 --no-project", "state_dir": str(self.world.state)})
        self.assertTrue(start["cursor_agents"])
        run, = [call for call in lines(self.world.root / "hc" / "calls.jsonl") if call[0] == "run"]
        words = shlex.split(run[-1])  # in the terminal's shell, not the driver's process, given the machine directory
        given = words.index(f"DELIVER_STATE_DIR={self.world.state}")
        self.assertEqual(words[given - 1:given + 8], ["env", f"DELIVER_STATE_DIR={self.world.state}", "uv", "run",
                                                      "--python", "3.13", "--no-project",
                                                      f"{self.world.tree}/skills/deliver/scripts/deliver.py", "install"])

    def test_a_failed_install_on_cursor_names_its_refusal_and_starts_no_session(self):
        code, out = self.run_on("cursor", "T1", CLAUDECODE="1")
        self.assertEqual(out, ["T1 cursor failed: deliver.py install cursor refused install.wrong-harness; "
                               "tokens: blank in, blank out"])
        self.assertEqual(code, 1)
        self.assertEqual(self.world.starts(), [])
        code, out = self.run_on("cursor", "T1", STANDIN_INSTALL_EXIT="3")
        self.assertEqual(out, ["T1 cursor failed: deliver.py install cursor exited 3; tokens: blank in, blank out"])

    def test_t1_types_the_skill_with_the_small_edit_text(self):
        text = ("Reword the docstring of `add` in `calc.py` so it says what the function returns. "
                "Change one line and nothing else.")
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                before = len(self.world.starts())
                self.run_on(harness, "T1")
                start, = self.world.starts()[before:]
                typed = "$deliver " if harness in ("cortex", "codex") else "/deliver "
                self.assertEqual(start["prompt"], typed + text)

    def test_g_lists_the_commands_in_order(self):
        deliver = f"uv run --python 3.13 --no-project {self.world.tree}/skills/deliver/scripts/deliver.py"
        commands = [f"{deliver} start request", PROBE, f"{deliver} preflight", "gh pr merge", "gh pr ready",
                    "./.cross-harness/deploy.sh production", "./.cross-harness/control.sh"]
        for harness, agent in (("codex", [f"{deliver} merge"]), ("claude", [PROBE, f"{deliver} merge"])):
            with self.subTest(harness=harness):
                before = len(self.world.starts())
                self.run_on(harness, "G")
                start, = self.world.starts()[before:]
                prompt = start["prompt"]
                self.assertEqual(re.findall(r"`([^`]+)`", prompt), [*commands, *agent, f"{deliver} finish"])
                self.assertIn("\n8. Start one agent of your default kind, give it this task and wait for it to "
                              "finish: ", prompt)
                self.assertIn(" Run them one at a time. Wait for each to finish before you start the next, and never "
                              "start two in one step. ", prompt)  # Cursor started two at once (#470)
                self.assertEqual(start["request"], "Run the guard commands of the cross-harness task G. Change no file.\n")
                clone = Path(start["cwd"])
                self.assertFalse((clone / ".cross-harness").exists())  # the clone is gone after the run

    def test_skill_names_the_given_copy_in_the_prompt_the_plugin_dir_and_the_install(self):
        skill = self.world.root / "installed" / "deliver"
        (skill / "scripts").mkdir(parents=True)
        (skill / "scripts" / "deliver.py").write_text(DELIVER)
        deliver = f"uv run --python 3.13 --no-project {skill}/scripts/deliver.py"
        checkout = str(self.world.tree / "skills")  # the relay still runs the checkout's probe kit
        for harness in ("claude", "cursor"):
            with self.subTest(harness=harness):
                before = len(self.world.starts())
                self.run_on(harness, "G", "--skill", str(skill))
                start, = self.world.starts()[before:]
                self.assertIn(f"1. `{deliver} start request`", start["prompt"])
                self.assertNotIn(checkout, json.dumps(start))
        claude, cursor = self.world.starts()
        self.assertEqual(claude["args"][-2:], ["--plugin-dir", str(skill)])
        install, = lines(self.world.root / "deliver.jsonl")  # Cursor's install ran from the given copy
        self.assertEqual(install["args"], ["install", "cursor"])
        run = [call for call in lines(self.world.root / "hc" / "calls.jsonl") if call[0] == "run"][-1]
        self.assertIn(f"{skill}/scripts/deliver.py install cursor", run[-1])
        self.assertNotIn(checkout, run[-1])

    def test_each_g_failure_names_its_fact_and_stops_the_harness(self):
        cases = {
            "drop=probe": "the guard did not refuse the probe; the guard did not refuse the agent's probe",
            "drop=gh pr merge": "the guard did not refuse a raw gh pr merge",
            "drop=gh pr ready": "the guard did not refuse a raw gh pr ready",
            "drop=one-way": "the guard did not refuse the one-way command",
            "drop=deliver.py merge": "the guard did not refuse the agent's deliver.py merge",
            "no-agent-probe": "the guard did not refuse the agent's probe",
            "oneway-ran": "the one-way command ran",
            "no-control": "the control command did not run",
            "preflight-stop": "preflight stopped: preflight.no-gh",
            "harness=codex": "preflight named the harness codex, not claude-code",
            "no-finish": "no finish record",
        }
        for knob, fact in cases.items():
            with self.subTest(knob=knob):
                code, out = self.run_on("claude", STANDIN=knob)
                self.assertEqual(out, [f"G claude failed: {fact}; tokens: 12 in, 340 out", "T1 claude not run: G failed"])
                self.assertEqual(code, 1)

    def test_g_fails_on_cursor_without_the_warning_and_on_a_nonzero_exit(self):
        code, out = self.run_on("cursor", "G", STANDIN="no-warning")
        self.assertEqual(out, ["G cursor failed: preflight did not warn that the guard cannot tell an agent from the "
                               "session; tokens: 12 in, 340 out"])
        code, out = self.run_on("codex", "G", STANDIN_EXIT="3")
        self.assertEqual(out, ["G codex failed: the harness exited 3; tokens: 12 in, 340 out"])
        self.assertEqual(code, 1)

    def test_each_t1_failure_names_its_fact(self):
        cases = {
            ("claude", "agent"): "the session started an agent",
            ("cortex", "agent"): "the session started an agent",
            ("cortex", "agent-event"): "the session started an agent",
            ("codex", "agent"): "the session started an agent",
            ("cursor", "agent"): "the session started an agent",
            ("antigravity", "agent"): "the session started an agent",
            ("claude", "no-small-test"): "the measurement block has no small test line",
            ("claude", "merge-owner"): "the measurement block has no merge line by the session",
            ("claude", "not-merged"): "PR {pr} is not merged",
            ("claude", "no-merge"): "the measurement block has no merge line by the session",
            ("antigravity", "denied"): "denied_actions holds 1",
        }
        for (harness, knob), fact in cases.items():
            with self.subTest(harness=harness, knob=knob):
                pr = self.next_pr()
                code, out = self.run_on(harness, "T1", STANDIN=knob)
                self.assertEqual(out, [f"T1 {harness} failed: {fact.format(pr=pr)}; tokens: 12 in, 340 out"])
                self.assertEqual(code, 1)

    def t2_passed(self, harness: str, pr: int) -> str:
        return (f"T2 {harness} passed: the session merged PR {pr}; path: single ticket; roles: author; requirements "
                "reviewer standin-opus/high; defect reviewer standin-sonnet/high, not applied; both reviews in the "
                "findings line; both brief lines in agent starts before the first save review; tokens: 12 in, 340 out")

    def test_t2_passes_on_each_harness_after_g_and_t1(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                pr = self.next_pr()
                code, out = self.run_on(harness, "G", "T1", "T2")
                self.assertEqual(out[2:], [self.t2_passed(harness, pr + 2)])  # T1 opened two PRs before it
                self.assertEqual([line.split()[:3] for line in out[:2]], [["G", harness, "passed:"],
                                                                         ["T1", harness, "passed:"]])
                self.assertEqual(code, 0)

    def test_t2_types_the_skill_with_ticket_a_and_is_not_run_after_a_failure(self):
        text = ("Add `multiply(a, b)` to `calc.py`. It returns the product of `a` and `b`. Add a test of it to "
                "`test_calc.py`.\n\nFiles: `calc.py`, `test_calc.py`\n\nAcceptance criteria:\n\n"
                "- `multiply(4, 3)` returns `12`.\n- `test_calc.py` has a test of `multiply`, and the check command "
                "passes.")
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                before = len(self.world.starts())
                self.run_on(harness, "T2")
                start, = self.world.starts()[before:]
                typed = "$deliver " if harness in ("cortex", "codex") else "/deliver "
                self.assertEqual(start["prompt"], typed + text)
        code, out = self.run_on("claude", "T1", "T2", STANDIN="no-small-test")
        self.assertEqual(out[1:], ["T2 claude not run: T1 failed"])

    def test_each_t2_failure_names_its_fact(self):
        cases = {
            "not-merged": "PR {pr} is not merged",
            "path=small edit": "the measurement block reads path: small edit, not path: single ticket",
            "no-path": "the measurement block has no path line",
            "no-roles": "the measurement block has no roles line",
            "roles-no-defect": "the roles line names no defect reviewer",
            "roles-text-only": "the roles line gives the defect reviewer no model and effort",
            "roles-no-model": "the roles line gives the requirements reviewer no model",
            "roles-auto": "the roles line gives the defect reviewer the model auto",
            "roles-no-effort": "the roles line gives the requirements reviewer no effort",
            "no-findings": "the measurement block has no findings line",
            "no-defect-review": "the findings line names no defect review",
            "merge-owner": "the measurement block has no merge line by the session",
            "no-brief=requirements": "the output has no requirements brief line",
            "no-brief=defect": "the output has no defect brief line",
            "save-first": "the first save review came before the agent start with the defect brief line",
            "no-agent-start": ("no agent start carries the requirements brief line; no agent start carries the defect "
                               "brief line"),
        }
        for knob, fact in cases.items():
            with self.subTest(knob=knob):
                pr = self.next_pr()
                code, out = self.run_on("codex", "T2", STANDIN=knob)
                self.assertEqual(out, [f"T2 codex failed: {fact.format(pr=pr)}; tokens: 12 in, 340 out"])
                self.assertEqual(code, 1)

    def test_t2_finds_a_brief_line_under_an_unknown_key_and_reads_the_last_measurement_block(self):
        for knob in ("brief-key=zzUnknownCall", "two-blocks"):
            with self.subTest(knob=knob):
                pr = self.next_pr()
                code, out = self.run_on("cursor", "T2", STANDIN=knob)
                self.assertEqual(out, [self.t2_passed("cursor", pr)])
                self.assertEqual(code, 0)

    def test_t2_waits_1800_seconds_unless_the_time_limit_says_otherwise(self):
        code, out, err = self.world.drive("run", "--help")
        self.assertIn("in place of 300 for G, 600 for T1 and 1800 for T2", " ".join(out.split()))
        code, out = self.run_on("claude", "T2", "--time-limit", "1", STANDIN_SLEEP="30")
        self.assertEqual(out, ["T2 claude failed: no finish within 1 seconds, terminal ended; tokens: blank in, blank out"])

    def test_tokens_print_blank_where_the_output_has_none(self):
        code, out = self.run_on("codex", "T1", STANDIN="no-usage")
        self.assertEqual(out, ["T1 codex passed: one session and no agent; the small test passed; the session merged "
                               "PR 6; tokens: blank in, blank out"])
        self.assertEqual(code, 0)
        code, out = self.run_on("codex", "T1", STANDIN="no-cached")  # the scan's rule: no cached count, no input
        self.assertEqual(out, ["T1 codex passed: one session and no agent; the small test passed; the session merged "
                               "PR 8; tokens: blank in, 340 out"])

    def test_a_run_past_its_limit_fails_its_terminal_is_ended_and_the_fixture_reset(self):
        code, out = self.run_on("claude", "G", "T1", "--time-limit", "1", STANDIN_SLEEP="30")
        self.assertEqual(out, ["G claude failed: no finish within 1 seconds, terminal ended; tokens: blank in, blank out",
                               "T1 claude not run: G failed"])
        self.assertEqual(code, 1)
        calls = lines(self.world.root / "hc" / "calls.jsonl")
        self.assertEqual([call[0] for call in calls if call[0] != "get"], ["run", "kill"])
        self.assertEqual(self.world.remote("rev-parse", "main"), self.world.base)

    def test_the_reset_closes_the_run_s_prs_and_forces_only_the_base_tag_onto_the_default_branch(self):
        code, out = self.run_on("claude", "T1")
        self.assertEqual(code, 0)
        self.assertEqual(self.world.remote("for-each-ref", "--format=%(refname)"),
                         "refs/heads/main\nrefs/heads/owner/keep\nrefs/tags/base")  # owner/keep was there before
        self.assertEqual(self.world.remote("rev-parse", "main"), self.world.base)
        gh = lines(self.world.root / "gh" / "calls.jsonl")
        self.assertEqual([call for call in gh if call[:2] == ["pr", "close"]], [["pr", "close", "7", "--repo", FIXTURE]])
        self.assertEqual(json.loads((self.world.root / "gh" / "prs.json").read_text())["5"]["state"], "OPEN")
        pushes = [call["args"] for call in lines(self.world.root / "git.jsonl") if "push" in call["args"]]
        forced = [args for args in pushes if any(a in ("--force", "-f") or a.startswith(("+", "--force")) for a in args)]
        remote = str(self.world.root / "fixture.git")
        self.assertEqual(forced, [["push", "--force", remote, f"{self.world.base}:refs/heads/main"]])
        self.assertIn(["push", remote, "--delete", "deliver/run-1"], pushes)

    def test_a_failed_reset_prints_its_line_and_stops_the_harness(self):
        code, out = self.run_on("codex", STANDIN_GIT_REFUSE_FORCE="1")
        self.assertEqual(out, [
            "G codex passed: preflight passed as codex; the guard refused the probe, a raw gh pr merge, a raw gh pr "
            "ready, the one-way command and the agent's deliver.py merge; the control command ran; tokens: 12 in, 340 out",
            "G codex reset failed: the forced push exited 1",
            "T1 codex not run: the reset failed",
        ])
        self.assertEqual(code, 1)

    def test_the_driver_holds_one_forced_push(self):
        tree = ast.parse(DRIVER.read_text())
        texts = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        forcing = ("--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror")
        self.assertEqual([text for text in texts if text in forcing or re.fullmatch(r"\+\S+", text)], ["--force"])

    def test_a_wrong_command_line_exits_2_with_one_line(self):
        cases = [
            (("run", "cortex", "G", "--fixture", FIXTURE), "cross_harness: cortex needs --connection, the Snowflake "
                                                            "connection its runs spend"),
            (("run", "codex", "G", "--fixture", "not-a-repo"), "cross_harness: --fixture takes OWNER/REPO"),
            (("run", "codex", "G", "--fixture", FIXTURE, "--skill", str(self.world.root)),
             "cross_harness: --skill takes a folder of deliver, with scripts/deliver.py in it"),
        ]
        for args, line in cases:
            with self.subTest(args=args):
                code, out, err = self.world.drive(*args)
                self.assertEqual((code, out, err), (2, "", line + "\n"))
        (self.world.bin / "agy").unlink()
        code, out, err = self.world.drive("run", "antigravity", "G", "--fixture", FIXTURE)
        self.assertEqual((code, out, err), (2, "", "cross_harness: agy is not on PATH\n"))
        self.assertEqual(self.world.starts(), [])
        self.assertEqual(lines(self.world.root / "hc" / "calls.jsonl"), [])  # no terminal started

    def test_the_raw_output_is_kept_in_the_machine_directory(self):
        code, out, err = self.world.drive("run", "codex", "G", "--fixture", FIXTURE)
        self.assertRegex(err, r"\Across_harness: raw output kept in cross-harness/[0-9TZ]+-[0-9]+/ of the machine "
                              r"directory\n\Z")
        kept, = (self.world.state / "cross-harness").iterdir()
        self.assertEqual(sorted(p.name for p in kept.iterdir()),
                         ["G-codex.err.txt", "G-codex.jsonl", "G-codex.records.jsonl", "G-codex.refusals.jsonl"])
        self.assertIn(SESSION, (kept / "G-codex.jsonl").read_text())  # kept as evidence, never printed

if __name__ == "__main__":
    unittest.main()
