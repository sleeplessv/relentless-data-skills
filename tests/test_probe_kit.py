"""Exercise tests/probe_kit.py at its command line against stand-ins.

Each test builds its own world in a temporary folder: a stand-in `hc`, first on
PATH, that records every call, runs the command it is given in the background
and reports `state: finished` only after that command has ended; and one
stand-in harness script, installed as `cortex`, `codex`, `cursor-agent` and
`agy`, that records how it was started and what its folder held, sets the
harness's own detection variable, and leaves what a real run of the entry
would: a marker file, an environment list, output with a session id and local
paths in it. PATH holds only the stand-ins and the system folders, and HOME and
the machine directory point inside the world, so no test starts a real session,
touches the network or reads the real machine directory.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent / "probe_kit.py"
SESSION = "sess-7f3a9c41"  # the session id the stand-in harness prints

HC = r'''#!{python}
import json, os, signal, subprocess, sys
from pathlib import Path
state = Path(os.environ["STANDIN_HC_DIR"])
args = sys.argv[1:]
with open(state / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\n")
command, rest = args[0], args[1:]
if command == "run":
    opts, i = {}, 0
    while rest[i].startswith("--"):
        if rest[i] in ("--bg", "--json", "--no-notify"):
            i += 1
        else:
            opts[rest[i]], i = rest[i + 1], i + 2
    term = state / opts["--name"]
    term.mkdir()
    # The exit code lands in a file only once the command has ended.
    wrapped = ["bash", "-c", '"$@"; echo $? > "$0.tmp"; mv "$0.tmp" "$0"', str(term / "exit"), *rest[i:]]
    with open(term / "screen", "w") as screen:
        proc = subprocess.Popen(wrapped, cwd=opts["--cwd"], start_new_session=True,
                                stdout=screen, stderr=subprocess.STDOUT)
    (term / "pid").write_text(str(proc.pid))
    print(json.dumps({"address": "w1:" + opts["--name"]}))
    sys.exit(0)
term = state / rest[-1].removeprefix("w1:")
pid = int((term / "pid").read_text())
if command == "kill":
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    print("{}")
elif command == "get":
    alive = True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        alive = False
    if (term / "exit").exists():
        reply = {"state": "finished", "exit_code": int((term / "exit").read_text())}
    elif not alive:
        reply = {"state": "finished", "exit_code": None}
    else:  # STANDIN_HC_STATUS: the agent's successive statuses, comma-separated, while the program still runs
        statuses = os.environ.get("STANDIN_HC_STATUS", "working").split(",")
        count = term / "gets"
        seen = int(count.read_text()) if count.exists() else 0
        count.write_text(str(seen + 1))
        reply = {"state": "running", "status": {"state": statuses[min(seen, len(statuses) - 1)]}}
    with open(state / "replies.jsonl", "a") as log:
        log.write(json.dumps(reply) + "\n")
    print(json.dumps(reply))
else:
    print("{}")
'''

# Knobs: STANDIN_SLEEP seconds before it acts; STANDIN_EXIT its exit code; STANDIN_NO_VAR leaves the
# detection variable unset; STANDIN_TYPED_OFF ignores a typed skill command; STANDIN_MODEL_READS shows
# a read of the skill file in the output; STANDIN_MENTION names the skill file in an ordinary message;
# STANDIN_UNTYPED starts the skill from a prompt that does not type it. It prints its arguments, which
# hold the connection on Cortex Code, to both streams, and records what the output files held then.
HARNESS = r'''#!{python}
import json, os, re, subprocess, sys, time
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
var = {"cortex": "CORTEX_SESSION_ID", "codex": "CODEX_THREAD_ID", "cursor-agent": "CURSOR_AGENT",
       "agy": "ANTIGRAVITY_AGENT"}[name]
prompt = args[args.index("-p") + 1] if name in ("cortex", "agy") else args[-1]
cwd = Path.cwd()
skills = sorted(str(p.relative_to(cwd)) for p in cwd.glob(".*/skills/*/**/*") if p.is_file())
skill_file = next((cwd / s for s in skills if s.endswith("SKILL.md")), None)
remotes = subprocess.run(["git", "remote"], capture_output=True, text=True)
print(json.dumps({"type": "system", "subtype": "init", "session_id": "''' + SESSION + r'''", "cwd": str(cwd),
                  "args": args}), flush=True)
print("stand-in log for " + str(cwd) + " started with " + " ".join(args), file=sys.stderr, flush=True)
# The output files beside the folder, read while this run is still live, once both lines have reached them.
for _ in range(100):
    live = {p.name: p.read_text() for p in cwd.parent.iterdir() if p.is_file()}
    if len(live) == 2 and all(text.endswith("\n") for text in live.values()):
        break
    time.sleep(0.02)
with open(os.environ["STANDIN_STARTS"], "a") as starts:
    starts.write(json.dumps({
        "name": name, "args": args, "prompt": prompt, "claudecode": os.environ.get("CLAUDECODE"),
        "git": (cwd / ".git").is_dir(), "remotes": remotes.stdout, "remote_rc": remotes.returncode,
        "skills": skills, "skill_text": skill_file.read_text() if skill_file else None, "live": live}) + "\n")
env = dict(os.environ)
if not os.environ.get("STANDIN_NO_VAR"):
    env[var] = "1"
time.sleep(float(os.environ.get("STANDIN_SLEEP", "0")))
typed = prompt.startswith(("/probe-standin", "$probe-standin")) and not os.environ.get("STANDIN_TYPED_OFF")
if typed or (os.environ.get("STANDIN_UNTYPED") and not prompt.startswith(("/", "$"))):
    if os.environ.get("STANDIN_MODEL_READS"):
        print(json.dumps({"type": "tool_call", "subtype": "started",
                          "tool_call": {"readToolCall": {"args": {"path": str(skill_file)}}}}))
    if os.environ.get("STANDIN_MENTION"):
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Done, as probe-standin/SKILL.md asks."}]}}))
    word = re.search(r"Write the word (\S+)", skill_file.read_text()).group(1)
    (cwd / "probe-marker.txt").write_text(word + "\n")
if "shell command: " in prompt:
    subprocess.run(prompt.split("shell command: ", 1)[1], shell=True, env=env, check=True)
print(json.dumps({"type": "result", "session_id": "''' + SESSION + r'''", "result": "done"}))
sys.exit(int(os.environ.get("STANDIN_EXIT", "0")))
'''

# X3 to X5: a stand-in harness, installed as all five harness commands, that starts an agent the way the
# real ones do. It loads a role only from its own harness's definition folder, in that harness's format;
# the agent reads the brief the one-line prompt names and writes the brief's word and its role's word
# where the brief says. It prints the session's and the agent's model and tokens in its harness's output
# format, with a tool call that has a `model` argument (Codex) and a token limit in modelUsage (Claude
# Code, Cortex Code) beside them. Knobs: STANDIN_AGENT_OFF starts no agent; STANDIN_SESSION_DOES has the
# session read the brief itself, so the file lacks a role's word; STANDIN_ROLE starts that role instead
# of the one asked for; STANDIN_ROLE_ONLY writes the role's word without the brief's; STANDIN_PARENT_ONLY
# prints no event of the agent's; STANDIN_COUNT makes each output count null, omit or zero;
# STANDIN_NO_MODEL and STANDIN_NO_TOKENS leave that field out.
AGENT_HARNESS = r'''#!{python}
import json, os, re, subprocess, sys, tomllib
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
prompt = args[args.index("-p") + 1] if name in ("claude", "cortex", "agy") else args[-1]
cwd = Path.cwd()
folder = {"claude": ".claude/agents", "cortex": ".cortex/agents", "codex": ".codex/agents",
          "cursor-agent": ".cursor/agents", "agy": ".agents/agents"}[name]
role_name = os.environ.get("STANDIN_ROLE") or re.search(r"of the role (\S+)", prompt).group(1)
line = re.search(r"whole prompt: (Read (\S+) and follow it\.)", prompt)
brief = Path(line.group(2))
common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                        capture_output=True, text=True).stdout.strip()
worktrees = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True).stdout


def role_words():
    """Each role's word by its name, read in this harness's format from its own folder only."""
    words = {}
    for path in sorted((cwd / folder).glob("*.toml" if name == "codex" else "*.md")):
        text = path.read_text()
        if name == "codex":
            role = tomllib.loads(text)
            found, body = role["name"], role["developer_instructions"]
        else:
            head, body = text.split("---\n", 2)[1:]
            found = re.search(r"^name: (\S+)$", head, re.M).group(1)
        words[found] = re.search(r"Your role word is (\S+)\.", body).group(1)
    return words


def follow(own_word):
    task = re.search(r"Write the word (\S+), a space and your role word to the file (\S+) in "
                     r"(?:your worktree, )?the folder (\S+)\. Change nothing else", brief.read_text())
    words = [w for w in (None if os.environ.get("STANDIN_ROLE_ONLY") else task.group(1), own_word) if w]
    (Path(task.group(3)) / task.group(2)).write_text(" ".join(words) + "\n")


words = role_words()
word = None if os.environ.get("STANDIN_AGENT_OFF") else words.get(role_name)
skill = next(cwd.glob(".*/skills/probe-standin/SKILL.md"))
with open(os.environ["STANDIN_STARTS"], "a") as starts:
    starts.write(json.dumps({
        "name": name, "args": args, "prompt": prompt, "line": line.group(1),
        "definitions": {str(p.relative_to(cwd)): p.read_text() for p in sorted(cwd.glob(".*/agents/*"))},
        "brief": brief.read_text(), "brief_in_common_dir": brief.is_relative_to(common),
        "worktrees": worktrees.replace(str(cwd), "<work>"), "role_word": word, "role_words": words,
        "skill_text": skill.read_text()}) + "\n")
if os.environ.get("STANDIN_SESSION_DOES"):
    follow(None)
elif word:
    follow(word)


def usage(given, made):
    if os.environ.get("STANDIN_NO_TOKENS"):
        return None
    count = {"null": None, "zero": 0}.get(os.environ.get("STANDIN_COUNT", ""), made)
    keys = ("inputTokens", "outputTokens") if name == "cursor-agent" else ("input_tokens", "output_tokens")
    shown = {keys[0]: given, keys[1]: count}
    if os.environ.get("STANDIN_COUNT") == "omit":
        del shown[keys[1]]
    return shown


def model(kind):
    return None if os.environ.get("STANDIN_NO_MODEL") else f"standin-{kind}-model-{name}"


def emit(**event):
    print(json.dumps({key: value for key, value in event.items() if value is not None}))


agent = word and not os.environ.get("STANDIN_PARENT_ONLY")
if name in ("claude", "cortex"):  # a stream; the agent's messages name its tool call in parent_tool_use_id
    emit(type="system", subtype="init", session_id="{session}", cwd=str(cwd), model=model("session"))
    emit(type="assistant", parent_tool_use_id=None,
         message={"model": model("session"), "usage": usage(3, 9), "content": [
             {"type": "tool_use", "id": "toolu_1", "name": "Agent", "input": {"subagent_type": role_name}}]})
    if agent:
        emit(type="assistant", parent_tool_use_id="toolu_1",
             message={"model": model("agent"), "usage": usage(5, 70)})
    emit(type="result", session_id="{session}", result="done",
         modelUsage={model("session") or "unnamed": {"inputTokens": 4, "maxOutputTokens": 100}},
         usage=usage(12, 340))
elif name == "codex":  # the exec output names no model
    emit(type="thread.started", thread_id="{session}")
    emit(type="item.completed", item={"type": "mcp_tool_call", "arguments": {"model": str(cwd / "weights.bin")}})
    emit(type="item.completed", item={"type": "agent_message", "text": "done"})
    emit(type="turn.completed", usage=usage(12, 340))
elif name == "agy":  # the stream carries only the parent's steps
    emit(event="init", init={"model": model("session")})
    emit(event="result", result={"response": "done", "usage": usage(12, 340)})
else:  # cursor-agent
    emit(type="system", subtype="init", session_id="{session}", cwd=str(cwd), model=model("session"))
    emit(type="result", session_id="{session}", result="done", usage=usage(12, 340))
'''
COMMAND_NAMES = {"claude": "claude", "cortex": "cortex", "codex": "codex", "cursor": "cursor-agent",
                 "antigravity": "agy"}


class World:
    """A temporary folder holding the stand-ins, HOME, the machine directory and the records."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="probe-kit-test-")).resolve()
        self.bin, self.home, self.state, self.hc_dir = (self.root / n for n in ("bin", "home", "state", "hc"))
        for folder in (self.bin, self.home, self.state, self.hc_dir):
            folder.mkdir()
        self.starts = self.root / "starts.jsonl"
        (self.bin / "hc").write_text(HC.replace("{python}", sys.executable))
        (self.bin / "standin-harness").write_text(HARNESS.replace("{python}", sys.executable))
        for name in ("hc", "standin-harness"):
            (self.bin / name).chmod(0o755)
        for name in ("cortex", "codex", "cursor-agent", "agy"):
            (self.bin / name).symlink_to(self.bin / "standin-harness")
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()

    def kit(self, *args: str, **knobs: str) -> tuple[int, str, str]:
        """Run the kit once, its output sent to files, and return its exit code, stdout and stderr."""
        env = {"PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.home),
               "DELIVER_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp), "STANDIN_HC_DIR": str(self.hc_dir),
               "STANDIN_STARTS": str(self.starts), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
               "LANG": "C.UTF-8", **knobs}
        if args[:1] == ("run",) and "--poll" not in args:
            args += ("--poll", "0.05")  # keeps each run short; the default of 2 seconds is for real harnesses
        out, err = self.root / "kit.out", self.root / "kit.err"
        with open(out, "w") as stdout, open(err, "w") as stderr:
            done = subprocess.run([sys.executable, str(KIT), *args], env=env, stdout=stdout, stderr=stderr,
                                  timeout=60)
        return done.returncode, out.read_text(), err.read_text()

    def hc_calls(self) -> list[list[str]]:
        log = self.hc_dir / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def harness_starts(self) -> list[dict]:
        return [json.loads(line) for line in self.starts.read_text().splitlines()] if self.starts.exists() else []

    def saved(self) -> dict[str, str]:
        """The files the kit kept in the machine directory, by name."""
        return {p.name: p.read_text() for p in (self.state / "probes").glob("*/*")}


class ProbeKitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World()
        self.addCleanup(shutil.rmtree, self.world.root, ignore_errors=True)

    def assert_private(self, *texts: str) -> None:
        """No session id, no path under the test's folder (HOME and TMPDIR are inside it), no home folder."""
        for text in texts:
            self.assertNotIn(SESSION, text)
            self.assertNotIn(str(self.world.root), text)
            self.assertNotIn(str(Path.home()), text)


    def assert_probe_folder_gone(self) -> None:
        """The temporary folder the kit made for the probe, the parent of the terminal's working folder, is gone."""
        run = next(call for call in self.world.hc_calls() if call[0] == "run")
        root = Path(run[run.index("--cwd") + 1]).parent
        self.assertEqual((root.parent, root.name[:6]), (self.world.tmp, "probe-"))
        self.assertFalse(root.exists())


class TestHelpAndList(ProbeKitTest):
    def test_help_states_the_waiting_rule_the_limit_the_connection_rule_the_evidence_and_the_exits(self):
        code, out, err = self.world.kit("--help")
        self.assertEqual((code, err), (0, ""))
        text = " ".join(out.split())
        for fact in ("`hc run --bg`", "`state: finished`", "never for `hc wait`", "default 300 seconds",
                     "ends the terminal and records the entry as failed", "X6 and X9 type the stand-in skill as `/name`, or `$name` on Cortex Code",
                     "X8 types a skill name that is not installed, in the same form",
                     "K6 and A7 do not type the skill: their prompt is a request that matches its description",
                     "Cortex Code needs --connection", "replaced by <connection> before any output reaches a file",
                     "the kit never prints it", "probes/<run id>/ in the machine directory",
                     "$DELIVER_STATE_DIR", "seen, failed or recorded", "no session id and no local path",
                     "0 when every entry is seen or recorded, 1 when any failed, 2 when hc or the harness command is missing",
                     "`git init` and no remote", "never installed"):
            self.assertIn(fact, text)

    def test_list_prints_every_entry_of_the_spec_with_its_harnesses(self):
        code, out, err = self.world.kit("list")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        ids = [line.split("  ")[0] for line in lines]
        self.assertEqual(ids, [f"X{n}" for n in range(1, 10)] + ["C1", "C2", "C3"] + [f"K{n}" for n in range(1, 7)]
                         + [f"D{n}" for n in range(1, 7)] + [f"R{n}" for n in range(1, 6)]
                         + [f"A{n}" for n in range(1, 8)])
        every = "claude, cortex, codex, cursor, antigravity"
        expected = {
            "X1": f"X1  {every}  Hook input cwd",
            "X6": "X6  cortex, codex, cursor, antigravity  Detection with CLAUDECODE set",
            "X8": "X8  cortex, codex, cursor, antigravity  A typed skill name that is not installed",
            "X9": "X9  codex, cursor, antigravity  Who resolves a typed command for a skill closed to model invocation",
            "C1": "C1  claude  A plugin from a marketplace loads its skill, agents/ and hooks/hooks.json",
            "R4": "R4  cursor  Loading Claude Code plugins",
            "K6": "K6  cortex  The command line loads an installed skill from its description",
            "D3": "D3  codex  Two agent starts in one model step (not built)",
            "R1": "R1  cursor  The IDE chat (not probed, closed by reading 6) (not built)",
            "A7": "A7  antigravity  The model starts a stand-in skill described as typed only",
        }
        for entry, line in expected.items():
            self.assertEqual(lines[ids.index(entry)], line)
        self.assertEqual(sum("(not built)" not in line for line in lines), 16)


class TestRuns(ProbeKitTest):
    def test_seen_x6_runs_in_a_fresh_git_folder_with_no_remote_and_the_closed_stand_in_skill(self):
        code, out, err = self.world.kit("run", "codex", "X6")
        self.assertEqual((code, out), (0, "X6 codex seen: CODEX_THREAD_ID set beside CLAUDECODE\n"))
        (start,) = self.world.harness_starts()
        self.assertEqual(start["prompt"], "/probe-standin Then run this shell command: "
                                          "env | cut -d= -f1 | sort > probe-env-names.txt")
        self.assertEqual(start["args"], ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                                         start["prompt"]])
        self.assertEqual((start["claudecode"], start["git"], start["remotes"], start["remote_rc"]), ("1", True, "", 0))
        self.assertEqual(start["skills"], [".agents/skills/probe-standin/SKILL.md",
                                           ".agents/skills/probe-standin/agents/openai.yaml"])
        self.assertIn("\ndisable-model-invocation: true\n", start["skill_text"])
        self.assertIn("\ndescription: Records a probe run for the probe kit. Start it only when the owner types its "
                      "name, never on your own.\n", start["skill_text"])
        self.assertRegex(start["skill_text"], r"Write the word probe-[0-9a-f]{8} and nothing else to the file "
                                              r"probe-marker.txt in the current folder. Then carry out the rest of "
                                              r"the request, if there is one.\n$")
        self.assertNotIn("Change nothing else", start["skill_text"])
        # The terminal: started in the background, named by harness, entry and run, waited on with get only.
        calls = self.world.hc_calls()
        self.assertEqual(calls[0][:6], ["run", "--json", "--bg", "--no-notify", "--name", f"probe-codex-x6-{calls[0][5].rsplit('-', 1)[1]}"])
        self.assertEqual({c[0] for c in calls}, {"run", "get", "rm"})
        self.assert_private(out, err)
        # The temporary folder is gone; the raw output is kept in the machine directory.
        self.assert_probe_folder_gone()
        saved = self.world.saved()
        self.assertEqual(sorted(saved), ["X6-codex.jsonl", "X6-codex.txt"])
        self.assertIn(SESSION, saved["X6-codex.jsonl"])
        self.assertEqual(err, f"probe_kit: raw output kept in probes/"
                              f"{next((self.world.state / 'probes').iterdir()).name}/ of the machine directory\n")

    def test_failed_x6_when_the_harness_sets_no_variable_of_its_own(self):
        code, out, err = self.world.kit("run", "cursor", "X6", STANDIN_NO_VAR="1")
        self.assertEqual((code, out), (1, "X6 cursor failed: CURSOR_AGENT not set beside CLAUDECODE\n"))
        self.assert_private(out, err)

    def test_recorded_x9_names_the_model_only_on_a_read_of_the_skill_file(self):
        code, out, _ = self.world.kit("run", "antigravity", "X9")
        self.assertEqual((code, out), (0, "X9 antigravity recorded: the stream does not show who resolved it\n"))
        code, out, _ = self.world.kit("run", "antigravity", "X9", STANDIN_MODEL_READS="1")
        self.assertEqual((code, out), (0, "X9 antigravity recorded: the model read the skill file\n"))
        code, out, _ = self.world.kit("run", "antigravity", "X9", STANDIN_MENTION="1")
        self.assertEqual((code, out), (0, "X9 antigravity recorded: the stream does not show who resolved it\n"))
        code, out, _ = self.world.kit("run", "antigravity", "X9", STANDIN_MENTION="1", STANDIN_MODEL_READS="1")
        self.assertEqual((code, out), (0, "X9 antigravity recorded: the model read the skill file\n"))
        self.assertEqual([s["prompt"] for s in self.world.harness_starts()], ["/probe-standin"] * 4)
        code, out, _ = self.world.kit("run", "antigravity", "X9", STANDIN_TYPED_OFF="1")
        self.assertEqual((code, out), (1, "X9 antigravity failed: the typed command did not start the skill\n"))

    def test_a_harness_that_exits_non_zero_fails_except_on_x8_where_the_exit_is_the_fact(self):
        code, out, _ = self.world.kit("run", "cursor", "X9", "X8", STANDIN_EXIT="3")
        self.assertEqual((code, out), (1, "X9 cursor failed: harness exited 3\n"
                                          "X8 cursor recorded: harness exited 3, its output is kept\n"))
        self.assertEqual([s["prompt"] for s in self.world.harness_starts()], ["/probe-standin", "/probe-not-installed"])

    def test_all_runs_every_built_entry_of_the_harness(self):
        code, out, err = self.world.kit("run", "codex", "all")
        self.assertEqual((code, out), (1, "X6 codex seen: CODEX_THREAD_ID set beside CLAUDECODE\n"
                                          "X8 codex recorded: harness exited 0, its output is kept\n"
                                          "X9 codex recorded: the stream does not show who resolved it\n"
                                          # this stand-in starts no agent; TestAgentEntries has one that does
                                          "X3 codex failed: no marker the brief names\n"
                                          "X4 codex failed: no file in .deliver/ of the agent's worktree\n"
                                          "X5 codex failed: no agent of the reader role ran\n"
                                          # This world's stand-in calls no hook and has no uv (see TestGuardHook).
                                          "X1 codex failed: the hook logged no input for the control stand-in\n"
                                          "X2 codex failed: uv is not on PATH\n"))
        self.assert_private(out, err)

    def test_cortex_types_dollar_names_and_keeps_the_connection_out_of_every_file_and_line(self):
        connection = "probe_conn_q7"
        code, out, err = self.world.kit("run", "cortex", "X8", "K6", "X6", "--connection", connection,
                                        STANDIN_UNTYPED="1")
        self.assertEqual((code, out), (0, "X8 cortex recorded: harness exited 0, its output is kept\n"
                                          "K6 cortex recorded: the model started the skill untyped\n"
                                          "X6 cortex seen: CORTEX_SESSION_ID set beside CLAUDECODE\n"))
        starts = self.world.harness_starts()
        self.assertEqual([s["prompt"].split(" ")[0] for s in starts],
                         ["$probe-not-installed", "Record", "$probe-standin"])
        self.assertEqual(starts[1]["prompt"], "Record a probe run for the probe kit.")
        for start in starts:  # the output files as they stood while the harness still ran
            self.assertEqual(sorted(start["live"]), ["err.txt", "out.jsonl"])
            self.assertIn("<connection>", start["live"]["out.jsonl"])
            self.assertIn("<connection>", start["live"]["err.txt"])
            self.assertNotIn(connection, json.dumps(start["live"]))
        self.assertEqual([s["args"][-2:] for s in starts], [["-c", connection]] * 3)
        self.assertEqual([s["skills"][0] for s in starts], [".cortex/skills/probe-standin/SKILL.md"] * 3)
        saved = self.world.saved()
        self.assertIn('"-c", "<connection>"', saved["K6-cortex.jsonl"])
        for name, text in saved.items():
            self.assertNotIn(connection, text, name)
        for call in self.world.hc_calls():
            if call[0] == "run":
                self.assertNotIn(connection, call[5])
        self.assertNotIn(connection, out + err)
        self.assert_private(out, err)

    def test_a7_records_whether_the_model_starts_the_untyped_skill(self):
        code, out, _ = self.world.kit("run", "antigravity", "A7")
        self.assertEqual((code, out), (0, "A7 antigravity recorded: the skill was not started untyped\n"))
        code, out, _ = self.world.kit("run", "antigravity", "A7", STANDIN_UNTYPED="1")
        self.assertEqual((code, out), (0, "A7 antigravity recorded: the model started the skill untyped\n"))
        prompt = self.world.harness_starts()[0]["prompt"]
        self.assertEqual(prompt, "Record a probe run for the probe kit.")
        description = re.search(r"\ndescription: (.*)\n", self.world.harness_starts()[0]["skill_text"]).group(1)
        self.assertIn("a probe run for the probe kit", description)  # the request matches the description
        self.assertIn("a probe run for the probe kit", prompt)
        for word in ("codeword", "probe-marker.txt", "probe-standin"):
            self.assertNotIn(word, prompt)

    def test_past_the_time_limit_the_terminal_is_ended_and_the_entry_failed(self):
        code, out, err = self.world.kit("run", "codex", "X9", "--time-limit", "1", "--poll", "0.1",
                                        STANDIN_SLEEP="30")
        self.assertEqual((code, out), (1, "X9 codex failed: no finish within 1 seconds, terminal ended\n"))
        calls = self.world.hc_calls()
        self.assertEqual(calls[-1], ["kill", "--json", "w1:" + calls[0][5]])
        self.assertEqual(sorted(self.world.saved()), ["X9-codex.jsonl", "X9-codex.txt"])  # what it printed so far
        self.assert_probe_folder_gone()

    def test_the_wait_polls_through_working_and_done_statuses_until_the_state_is_finished(self):
        # Herdr reports the agent's status as status.state; it turns to done before the program ends.
        code, out, _ = self.world.kit("run", "cursor", "X9", "--poll", "0.05",
                                      STANDIN_SLEEP="0.6", STANDIN_HC_STATUS="working,done")
        self.assertEqual((code, out), (0, "X9 cursor recorded: the stream does not show who resolved it\n"))
        gets = [c for c in self.world.hc_calls() if c[0] == "get"]
        self.assertGreater(len(gets), 2)
        self.assertNotIn("wait", [c[0] for c in self.world.hc_calls()])
        replies = [json.loads(line) for line in (self.world.hc_dir / "replies.jsonl").read_text().splitlines()]
        statuses = [r["status"]["state"] for r in replies if r["state"] == "running"]
        self.assertEqual(statuses[:2], ["working", "done"])
        self.assertIn("done", statuses[2:])
        self.assertEqual(replies[-1], {"state": "finished", "exit_code": 0})
        self.assertEqual(sum(r["state"] == "finished" for r in replies), 1)
        self.assertEqual([c[0] for c in self.world.hc_calls()][-2:], ["get", "rm"])


class TestAgentEntries(ProbeKitTest):
    """X3, X4 and X5 against the stand-in that starts an agent, installed as all five harness commands."""

    def setUp(self) -> None:
        super().setUp()
        script = self.world.bin / "standin-agent-harness"
        script.write_text(AGENT_HARNESS.replace("{python}", sys.executable).replace("{session}", SESSION))
        script.chmod(0o755)
        for command in COMMAND_NAMES.values():
            (self.world.bin / command).unlink(missing_ok=True)
            (self.world.bin / command).symlink_to(script)

    def run_entry(self, harness: str, entry: str, **knobs: str) -> tuple[int, str, str]:
        extra = ("--connection", "probe_conn_q7") if harness == "cortex" else ()
        return self.world.kit("run", harness, entry, *extra, **knobs)

    def test_help_states_how_the_agent_entries_are_judged(self):
        code, out, err = self.world.kit("--help")
        self.assertEqual((code, err), (0, ""))
        text = " ".join(out.split())
        for fact in ("a harness (claude, cortex, codex, cursor or antigravity)",
                     "a stand-in reader role and a stand-in reviewer role into the harness's project definition folder",
                     "saves the entry's brief in the shared git directory", "`Read <path> and follow it.`",
                     "The kit draws each word at random, and none is in the prompt",
                     "in .deliver/ of the agent's worktree",
                     "A word the kit did not give the reader, such as the reviewer's, fails the entry",
                     "A field counts as the agent's only in an event the output ties to the agent's tool call; the "
                     "rest prints as not tied to the agent",
                     "A field the output lacks prints as absent",
                     "a token count the output leaves empty or out prints blank, never as 0"):
            self.assertIn(fact, text)

    def test_x3_is_seen_on_every_harness_with_the_role_files_in_its_own_definition_folder(self):
        for harness in COMMAND_NAMES:
            code, out, err = self.run_entry(harness, "X3")
            self.assertEqual((code, out), (0, f"X3 {harness} seen: an agent of the reader role wrote the marker "
                                              f"its brief names\n"))
            self.assert_private(out, err)
        starts = self.world.harness_starts()
        self.assertEqual([s["name"] for s in starts], list(COMMAND_NAMES.values()))
        files = {
            "claude": [".claude/agents/probe-reader.md", ".claude/agents/probe-reviewer.md"],
            "cortex": [".cortex/agents/probe-reader.md", ".cortex/agents/probe-reviewer.md"],
            "codex": [".codex/agents/probe-reader.toml", ".codex/agents/probe-reviewer.toml"],
            "cursor-agent": [".cursor/agents/probe-reader.md", ".cursor/agents/probe-reviewer.md"],
            "agy": [".agents/agents/probe-reader.md", ".agents/agents/probe-reviewer.md"],
        }
        tools = {"claude": ("Read, Grep, Glob, Bash, Write, Edit", "Read, Grep, Glob, Bash"),
                 "cortex": ("[read, grep, glob, bash, write, edit]", "[read, grep, glob, bash]"),
                 "agy": ("[view_file, run_command, write_file, edit_file]", "[view_file, run_command]")}
        for start in starts:
            name = start["name"]
            self.assertEqual(sorted(start["definitions"]), files[name])
            for path, kind, limit in ((files[name][0], "reader", 0), (files[name][1], "reviewer", 1)):
                text = start["definitions"][path]
                description = f"Stand-in {kind} for the probe kit. Start it only when asked for probe-{kind} by name."
                body = (f"You are the probe kit's stand-in {kind}. Your role word is "
                        f"{start['role_words'][f'probe-{kind}']}. When a brief asks for your role word, give this "
                        f"one. Do only what your prompt and its brief ask.")
                if name == "codex":
                    expected = (f'name = "probe-{kind}"\ndescription = "{description}"\n'
                                f'developer_instructions = """\n{body}\n"""\n')
                else:
                    limits = f"tools: {tools[name][limit]}\n" if name in tools else ""
                    expected = f"---\nname: probe-{kind}\ndescription: {description}\n{limits}---\n\n{body}\n"
                self.assertEqual(text, expected, path)
            self.assertEqual(start["role_word"], start["role_words"]["probe-reader"])
            self.assertRegex(start["role_words"]["probe-reader"], r"^probe-reader-[0-9a-f]{8}$")
            self.assertRegex(start["role_words"]["probe-reviewer"], r"^probe-reviewer-[0-9a-f]{8}$")

    def test_the_prompt_is_the_one_line_and_holds_no_word_and_the_brief_sits_in_the_shared_git_directory(self):
        code, out, _ = self.run_entry("codex", "X3")
        self.assertEqual(code, 0, out)
        (start,) = self.world.harness_starts()
        line = start["line"]
        self.assertRegex(line, r"^Read /\S+/work/\.git/deliver/branches/probe-agent/brief-x3\.md and follow it\.$")
        self.assertEqual(start["prompt"], f"Start one agent of the role probe-reader and give it this line, word "
                                          f"for word, as its whole prompt: {line} Do not open that file yourself, "
                                          f"and do nothing else.")
        self.assertTrue(start["brief_in_common_dir"])
        brief_word = re.fullmatch(r"# Probe brief\n\nWrite the word (brief-[0-9a-f]{8}), a space and your role word "
                                  r"to the file probe-brief-marker\.txt in the folder /\S+/work\. Change nothing "
                                  r"else\.\n", start["brief"]).group(1)
        reviewer_word = start["role_words"]["probe-reviewer"]
        for word in (brief_word, start["role_word"], reviewer_word, "probe-brief-marker.txt"):
            self.assertNotIn(word, start["prompt"])
        for word in (brief_word, start["role_word"], reviewer_word):  # the stand-in skill gives no word away
            self.assertNotIn(word, start["skill_text"])
        codeword = re.search(r"Write the word (probe-[0-9a-f]{8})", start["skill_text"]).group(1)
        for word in (brief_word, start["role_word"], reviewer_word):
            self.assertNotIn(codeword.removeprefix("probe-"), word)
        self.assertNotIn(start["role_word"], start["brief"])
        self.assertNotIn(reviewer_word, start["brief"])
        self.assertIn("worktree <work>/.probe-worktrees/agent\nHEAD 0000000000000000000000000000000000000000\n"
                      "branch refs/heads/probe-agent\n", start["worktrees"])

    def test_x3_fails_with_its_own_line_unless_the_reader_wrote_the_brief_s_word(self):
        cases = [
            ("claude", {"STANDIN_AGENT_OFF": "1"}, "no marker the brief names"),
            ("cursor", {"STANDIN_SESSION_DOES": "1"}, "the marker the brief names lacks the reader role's word"),
            ("cursor", {"STANDIN_ROLE": "probe-reviewer"},
             "the marker the brief names holds the reviewer role's word, not the reader's"),
            ("codex", {"STANDIN_ROLE_ONLY": "1"}, "the marker the brief names lacks the brief's word"),
        ]
        for harness, knobs, fact in cases:
            code, out, _ = self.run_entry(harness, "X3", **knobs)
            self.assertEqual((code, out), (1, f"X3 {harness} failed: {fact}\n"), knobs)

    def test_x4_is_seen_on_every_harness_when_the_agent_writes_into_deliver_of_its_worktree(self):
        for harness in COMMAND_NAMES:
            code, out, err = self.run_entry(harness, "X4")
            self.assertEqual((code, out), (0, f"X4 {harness} seen: an agent of the reader role wrote into .deliver/ "
                                              f"of its worktree\n"))
            self.assert_private(out, err)
        self.assertRegex(self.world.harness_starts()[-1]["brief"],
                         r"to the file \.deliver/probe-drop\.txt in your worktree, the folder "
                         r"/\S+/work/\.probe-worktrees/agent\. Change nothing else\.\n$")

    def test_x4_fails_with_its_own_line_unless_the_reader_wrote_the_brief_s_word(self):
        cases = [
            ("codex", {"STANDIN_AGENT_OFF": "1"}, "no file in .deliver/ of the agent's worktree"),
            ("cortex", {"STANDIN_SESSION_DOES": "1"},
             "the file in .deliver/ of the agent's worktree lacks the reader role's word"),
            ("antigravity", {"STANDIN_ROLE_ONLY": "1"},
             "the file in .deliver/ of the agent's worktree lacks the brief's word"),
            ("claude", {"STANDIN_ROLE": "probe-reviewer"},
             "the file in .deliver/ of the agent's worktree holds the reviewer role's word, not the reader's"),
        ]
        for harness, knobs, fact in cases:
            code, out, _ = self.run_entry(harness, "X4", **knobs)
            self.assertEqual((code, out), (1, f"X4 {harness} failed: {fact}\n"), knobs)

    def test_x5_records_the_agent_s_fields_apart_from_the_ones_not_tied_to_it(self):
        expected = {
            "claude": "agent model standin-agent-model-claude at assistant event .message.model, "
                      "tokens input_tokens=5 output_tokens=70 at assistant event .message.usage; "
                      "not tied to the agent model standin-session-model-claude at system event .model, "
                      "tokens input_tokens=12 output_tokens=340 at result event .usage",
            "cortex": "agent model standin-agent-model-cortex at assistant event .message.model, "
                      "tokens input_tokens=5 output_tokens=70 at assistant event .message.usage; "
                      "not tied to the agent model standin-session-model-cortex at system event .model, "
                      "tokens input_tokens=12 output_tokens=340 at result event .usage",
            "codex": "agent model absent, tokens absent; not tied to the agent model absent, "
                     "tokens input_tokens=12 output_tokens=340 at turn.completed event .usage",
            "cursor": "agent model absent, tokens absent; not tied to the agent model "
                      "standin-session-model-cursor-agent at system event .model, "
                      "tokens inputTokens=12 outputTokens=340 at result event .usage",
            "antigravity": "agent model absent, tokens absent; not tied to the agent model "
                           "standin-session-model-agy at init event .init.model, "
                           "tokens input_tokens=12 output_tokens=340 at result event .result.usage",
        }
        for harness, fact in expected.items():
            code, out, err = self.run_entry(harness, "X5")
            self.assertEqual((code, out), (0, f"X5 {harness} recorded: {fact}\n"))
            self.assert_private(out, err)
        # Codex's tool call with a `model` argument and Claude Code's token limit in modelUsage are not read.
        saved = self.world.saved()
        self.assertIn('"arguments": {"model": ', saved["X5-codex.jsonl"])
        self.assertIn('"modelUsage": {"standin-session-model-claude": {"inputTokens": 4, "maxOutputTokens": 100}}, '
                      '"usage": {', saved["X5-claude.jsonl"])

    def test_x5_prints_the_agent_s_fields_absent_when_the_output_shows_only_the_session(self):
        code, out, _ = self.run_entry("claude", "X5", STANDIN_PARENT_ONLY="1")
        self.assertEqual((code, out), (0, "X5 claude recorded: agent model absent, tokens absent; not tied to the "
                                          "agent model standin-session-model-claude at system event .model, tokens "
                                          "input_tokens=12 output_tokens=340 at result event .usage\n"))

    def test_x5_prints_an_omitted_or_null_count_blank_and_a_zero_as_0(self):
        for count, shown in (("omit", ""), ("null", ""), ("zero", "0")):
            code, out, _ = self.run_entry("codex", "X5", STANDIN_COUNT=count)
            self.assertEqual((code, out), (0, f"X5 codex recorded: agent model absent, tokens absent; not tied to "
                                              f"the agent model absent, tokens input_tokens=12 output_tokens={shown} "
                                              f"at turn.completed event .usage\n"), count)
            code, out, _ = self.run_entry("cursor", "X5", STANDIN_COUNT=count)
            self.assertEqual((code, out), (0, f"X5 cursor recorded: agent model absent, tokens absent; not tied to "
                                              f"the agent model standin-session-model-cursor-agent at system event "
                                              f".model, tokens inputTokens=12 outputTokens={shown} at result event "
                                              f".usage\n"), count)
        code, out, _ = self.run_entry("cortex", "X5", STANDIN_COUNT="omit")
        self.assertEqual((code, out), (0, "X5 cortex recorded: agent model standin-agent-model-cortex at assistant "
                                          "event .message.model, tokens input_tokens=5 output_tokens= at assistant "
                                          "event .message.usage; not tied to the agent model "
                                          "standin-session-model-cortex at system event .model, tokens "
                                          "input_tokens=12 output_tokens= at result event .usage\n"))
        code, out, _ = self.run_entry("antigravity", "X5", STANDIN_NO_TOKENS="1", STANDIN_NO_MODEL="1")
        self.assertEqual((code, out), (0, "X5 antigravity recorded: agent model absent, tokens absent; not tied to "
                                          "the agent model absent, tokens absent\n"))
        code, out, _ = self.run_entry("claude", "X5", STANDIN_AGENT_OFF="1")
        self.assertEqual((code, out), (1, "X5 claude failed: no agent of the reader role ran\n"))
        code, out, _ = self.run_entry("claude", "X5", STANDIN_ROLE="probe-reviewer")
        self.assertEqual((code, out), (1, "X5 claude failed: no agent of the reader role ran\n"))

    def test_all_on_claude_runs_the_three_agent_entries_with_its_allowed_tools_named(self):
        code, out, _ = self.world.kit("run", "claude", "all")
        self.assertEqual((code, out), (1, "X3 claude seen: an agent of the reader role wrote the marker its brief "
                                          "names\n"
                                          "X4 claude seen: an agent of the reader role wrote into .deliver/ of its "
                                          "worktree\n"
                                          "X5 claude recorded: agent model standin-agent-model-claude at assistant "
                                          "event .message.model, tokens input_tokens=5 output_tokens=70 at "
                                          "assistant event .message.usage; not tied to the agent model "
                                          "standin-session-model-claude at system event .model, tokens "
                                          "input_tokens=12 output_tokens=340 at result event .usage\n"
                                          # This world's stand-in reads only an agent prompt and has no uv
                                          # (see TestGuardHook).
                                          "X1 claude failed: harness exited 1\n"
                                          "X2 claude failed: uv is not on PATH\n"
                                          # This stand-in `claude` has no plugin subcommand, so C1 and C3
                                          # stop at the registration (TestPlugin covers them).
                                          "C1 claude failed: claude plugin marketplace add exited 1\n"
                                          "C2 claude failed: harness exited 1\n"
                                          "C3 claude failed: claude plugin marketplace add exited 1\n"))
        self.assertEqual(self.world.harness_starts()[0]["args"][2:],
                         ["--output-format", "stream-json", "--verbose", "--setting-sources", "project",
                          "--no-session-persistence", "--permission-mode", "acceptEdits",
                          "--allowedTools", "Agent,Read,Write,Edit,Bash,Glob,Grep"])
        self.assert_probe_folder_gone()


class TestRefusals(ProbeKitTest):
    def test_a_missing_harness_command_or_hc_exits_2_before_any_terminal(self):
        (self.world.bin / "agy").unlink()
        self.assertEqual(self.world.kit("run", "antigravity", "A7"), (2, "", "probe_kit: agy is not on PATH\n"))
        (self.world.bin / "hc").unlink()
        self.assertEqual(self.world.kit("run", "codex", "X9"), (2, "", "probe_kit: hc is not on PATH\n"))
        self.assertEqual((self.world.hc_calls(), self.world.harness_starts()), ([], []))

    def test_cortex_without_a_connection_and_entries_not_built_or_elsewhere_exit_2(self):
        cases = {
            ("cortex", "K6"): "probe_kit: cortex needs --connection, the Snowflake connection its runs spend\n",
            ("codex", "D3"): "probe_kit: D3 is not built yet\n",
            ("codex", "K6"): "probe_kit: K6 does not run on codex\n",
            ("codex", "Z1"): "probe_kit: unknown entry 'Z1'; `list` shows every entry\n",
            ("claude", "X6"): "probe_kit: X6 does not run on claude\n",
            ("vim", "X6"): "probe_kit: unknown harness 'vim'; harnesses: claude, cortex, codex, cursor, antigravity\n",
        }
        for argv, message in cases.items():
            self.assertEqual(self.world.kit("run", *argv), (2, "", message), argv)
        self.assertEqual(self.world.hc_calls(), [])


# The stand-in guard hook (#383). A second stand-in harness, installed as all five harness commands, finds
# the hook where the harness would: a project settings or hooks file, or Codex's -c override. It sends
# each shell command of the prompt to the hook in that harness's input shape and runs the command only on
# an allow; it treats an ask as refused. `agy -p "/hooks"` lists the hooks in .agents/hooks.json. Knobs:
# STANDIN_HOOK_CWD=command puts the command's directory in the input's cwd, else the session's;
# STANDIN_NO_CWD leaves cwd out; STANDIN_STAY runs the control stand-in in the session's directory;
# STANDIN_SKIP_HOOK calls no hook; STANDIN_FORCE_DENY refuses every command whatever the hook said;
# STANDIN_AS_AGENT marks the input as an agent's where the harness has a field for it; STANDIN_ALSO adds
# commands, separated by ";;"; STANDIN_NO_HOOKS makes `/hooks` list none. STANDIN_HOOKS_FAIL makes `/hooks`
# name the hook in an error and exit 4; STANDIN_HOOKS_AS lists the hooks under that name instead;
# STANDIN_AGENT_TYPE adds agent_type and no agent_id to a settings-form input, as `claude --agent` does;
# STANDIN_ARGV_IN_INPUT puts the harness's arguments in every hook input. Cursor's sessionStart hook is
# called once before the commands. The record holds the hook log as it stood when the harness ended.
HOOK_HARNESS = r'''#!{python}
import json, os, re, subprocess, sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
prompt = args[args.index("-p") + 1] if name in ("claude", "cortex", "agy") else args[-1]
cwd, knob = Path.cwd(), os.environ.get
if name == "agy" and prompt == "/hooks":
    hooks = {} if knob("STANDIN_NO_HOOKS") else json.loads((cwd / ".agents" / "hooks.json").read_text())
    if knob("STANDIN_HOOKS_FAIL"):
        print("Failed to load probe-guard")
        sys.exit(4)
    if knob("STANDIN_HOOKS_AS"):
        hooks = {knob("STANDIN_HOOKS_AS"): events for events in hooks.values()}
    print("Hooks loaded:")
    for hook_name, events in hooks.items():
        print(f"  {hook_name}: {', '.join(events)}")
    sys.exit(0)
print(json.dumps({"type": "system", "session_id": "''' + SESSION + r'''", "cwd": str(cwd)}), flush=True)
registered = {path: json.loads((cwd / path).read_text()) for path in (
    ".claude/settings.json", ".cortex/settings.json", ".cursor/hooks.json", ".agents/hooks.json")
    if (cwd / path).is_file()}
if name in ("claude", "cortex"):
    form, hook_dir = "settings", cwd
    hook = registered[f".{name}/settings.json"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
elif name == "codex":
    form, hook_dir = "settings", cwd
    hook = re.search(r'command="([^"]*)"', args[args.index("-c") + 1]).group(1)
elif name == "cursor-agent":
    form, hook_dir = "beforeShell", cwd
    hook = registered[".cursor/hooks.json"]["hooks"]["beforeShellExecution"][0]["command"]
else:  # Antigravity runs a hook in the folder that holds hooks.json
    form, hook_dir = "pre", cwd / ".agents"
    hook = next(iter(registered[".agents/hooks.json"].values()))["PreToolUse"][0]["hooks"][0]["command"]
asked = re.match(r"Run `([^`]+)`(?: from the folder `([^`]+)`)?", prompt)
commands = [(asked.group(1), cwd / asked.group(2) if asked.group(2) else cwd)]
if knob("STANDIN_STAY"):
    commands = [("./control-probe.sh x1", cwd)]
commands += [(command, cwd) for command in knob("STANDIN_ALSO", "").split(";;") if command]
sent, decisions = [], []
if name == "cursor-agent" and not knob("STANDIN_SKIP_HOOK"):
    data = {"conversation_id": "''' + SESSION + r'''", "hook_event_name": "sessionStart"}
    sent.append(data)
    start_hook = registered[".cursor/hooks.json"]["hooks"]["sessionStart"][0]["command"]
    answer = subprocess.run(start_hook, shell=True, cwd=hook_dir, input=json.dumps(data), capture_output=True,
                            text=True, check=True)
    assert answer.stdout == "", answer.stdout  # the sessionStart hook logs only
for command, run_dir in commands:
    hook_cwd = str(run_dir if knob("STANDIN_HOOK_CWD") == "command" else cwd)
    if form == "settings":
        data = {"session_id": "''' + SESSION + r'''", "cwd": hook_cwd, "hook_event_name": "PreToolUse",
                "tool_name": "Bash", "tool_input": {"command": command}}
        if knob("STANDIN_AS_AGENT"):
            data["agent_id"] = "agent-1"
        if knob("STANDIN_AGENT_TYPE"):
            data["agent_type"] = "helper"
    elif form == "beforeShell":
        data = {"conversation_id": "''' + SESSION + r'''", "command": command, "cwd": hook_cwd}
    else:
        data = {"conversationId": "''' + SESSION + r'''", "cwd": hook_cwd,
                "toolCall": {"name": "run_command", "args": {"CommandLine": command, "Cwd": str(run_dir)}}}
    if knob("STANDIN_NO_CWD"):
        del data["cwd"]
    if knob("STANDIN_ARGV_IN_INPUT"):
        data["argv"] = args
    decision = "allow"
    if not knob("STANDIN_SKIP_HOOK"):
        sent.append(data)
        done = subprocess.run(hook, shell=True, cwd=hook_dir, input=json.dumps(data), capture_output=True,
                              text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)})
        answer = json.loads(done.stdout) if done.stdout.strip() else {}
        if form == "settings":
            decision = answer.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
        else:
            decision = answer.get("permission" if form == "beforeShell" else "decision", "deny")
    if knob("STANDIN_FORCE_DENY"):
        decision = "deny"
    decisions.append([command, decision])
    if decision == "allow":
        subprocess.run(command, shell=True, cwd=run_dir, stdout=subprocess.DEVNULL)
logs = cwd / "logs"
with open(knob("STANDIN_STARTS"), "a") as starts:
    starts.write(json.dumps({"name": name, "args": args, "prompt": prompt, "cwd": str(cwd), "registered": registered,
                             "sent": sent, "decisions": decisions, "logs": sorted(p.name for p in logs.iterdir()),
                             "hook_log": (logs / "hook.jsonl").read_text() if (logs / "hook.jsonl").is_file() else ""})
                 + "\n")
print(json.dumps({"type": "result", "session_id": "''' + SESSION + r'''", "result": "done"}))
'''

# Stands in for uv: records its arguments, waits STANDIN_UV_SLEEP seconds, then runs the script with python.
# STANDIN_UV_SLEEPS gives the wait of each call in turn instead, space-separated.
UV = r'''#!{python}
import json, os, subprocess, sys, time
calls = os.environ["STANDIN_UV_CALLS"]
done = len(open(calls).read().splitlines()) if os.path.exists(calls) else 0
with open(calls, "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
sleeps = os.environ.get("STANDIN_UV_SLEEPS", "").split()
time.sleep(float(sleeps[done % len(sleeps)]) if sleeps else float(os.environ.get("STANDIN_UV_SLEEP", "0.2")))
assert sys.argv[1:5] == ["run", "--python", "3.13", "--no-project"]
sys.exit(subprocess.run([sys.executable, *sys.argv[5:]]).returncode)
'''

# Stands in for python3 in the X2 timing test: waits the next of STANDIN_PY_SLEEPS seconds, counted in
# STANDIN_PY_CALLS, then runs the real interpreter.
PYTHON = r'''#!{python}
import os, sys, time
calls = os.environ["STANDIN_PY_CALLS"]
done = len(open(calls).read()) if os.path.exists(calls) else 0
with open(calls, "a") as log:
    log.write(".")
sleeps = os.environ["STANDIN_PY_SLEEPS"].split()
time.sleep(float(sleeps[done % len(sleeps)]))
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
'''

# Stands in for a terminal UI: records how it was started and the files of its folder, then ends.
TUI = r'''#!{python}
import json, os, sys
from pathlib import Path
cwd = Path.cwd()
files = sorted(str(p.relative_to(cwd)) for p in cwd.rglob("*") if p.is_file() and ".git" not in p.parts)
with open(os.environ["STANDIN_STARTS"], "a") as starts:
    starts.write(json.dumps({"name": Path(sys.argv[0]).name, "args": sys.argv[1:], "files": files}) + "\n")
'''

HARNESS_COMMANDS = {"claude": "claude", "cortex": "cortex", "codex": "codex", "cursor": "cursor-agent",
                    "antigravity": "agy"}


def codex_c(work: str) -> str:
    """The Codex -c override of the research note, with the probe folder's absolute script path."""
    return (f'hooks.PreToolUse=[{{matcher="Bash",hooks=[{{type="command",command="python3 {work}/hooks/guard.py '
            f'settings",timeout=20}}]}}]')


CONNECTION = "probe_conn_q7"


class HookWorld(World):
    """The world with the hook stand-in harness as all five commands, a stand-in uv and python3 first on PATH."""

    def __init__(self) -> None:
        super().__init__()
        self.uv_calls = self.root / "uv.jsonl"
        for name, text in (("hook-harness", HOOK_HARNESS), ("uv", UV), ("tui", TUI)):
            (self.bin / name).write_text(text.replace("{python}", sys.executable))
            (self.bin / name).chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)
        self.install("hook-harness")

    def install(self, standin: str) -> None:
        for name in HARNESS_COMMANDS.values():
            (self.bin / name).unlink(missing_ok=True)
            (self.bin / name).symlink_to(self.bin / standin)

    def kit(self, *args: str, **knobs: str) -> tuple[int, str, str]:
        if args[:2] == ("run", "cortex") or args[:2] == ("x7", "cortex"):
            args += ("--connection", CONNECTION)
        return super().kit(*args, STANDIN_UV_CALLS=str(self.uv_calls), **knobs)

    def uv_runs(self) -> list[list[str]]:
        return [json.loads(line) for line in self.uv_calls.read_text().splitlines()] if self.uv_calls.exists() else []


def registration(harness: str, work: str) -> dict:
    """The project-level registration the guard research note gives for the harness."""
    absolute = f"python3 {work}/hooks/guard.py"
    settings = {"hooks": {"PreToolUse": [{"matcher": "bash" if harness == "cortex" else "Bash", "hooks": [
        {"type": "command", "command": f"{absolute} settings" if harness == "cortex"
         else 'python3 "$CLAUDE_PROJECT_DIR/hooks/guard.py" settings'}]}]}}
    return {
        "claude": {".claude/settings.json": settings},
        "cortex": {".cortex/settings.json": settings},
        "codex": {},
        "cursor": {".cursor/hooks.json": {"version": 1, "hooks": {
            "beforeShellExecution": [{"command": "python3 hooks/guard.py beforeShell"}],
            "sessionStart": [{"command": "python3 hooks/guard.py sessionStart"}]}}},
        "antigravity": {".agents/hooks.json": {"probe-guard": {"PreToolUse": [{"matcher": "", "hooks": [
            {"type": "command", "command": f"{absolute} pre", "timeout": 20}]}]}}},
    }[harness]


class HookTest(ProbeKitTest):
    def setUp(self) -> None:
        self.world = HookWorld()
        self.addCleanup(shutil.rmtree, self.world.root, ignore_errors=True)

    def assert_home_empty(self) -> None:
        self.assertEqual(sorted(self.world.home.rglob("*")), [])


class TestGuardHook(HookTest):
    def test_x1_records_the_directory_in_the_hook_input_on_every_harness_registered_at_project_level(self):
        x1 = "Run `../control-probe.sh x1` from the folder `sub`."
        argv = {
            "claude": ["-p", x1, "--output-format", "stream-json", "--verbose", "--setting-sources", "project",
                       "--no-session-persistence", "--permission-mode", "acceptEdits",
                       "--allowedTools", "Agent,Read,Write,Edit,Bash,Glob,Grep"],
            "cortex": ["-p", x1, "--output-format", "stream-json", "--private", "--bypass", "-c", CONNECTION],
            "codex": ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "-c", "{codex_c}", x1],
            "cursor": ["-p", "--output-format", "stream-json", "--force", x1],
            "antigravity": ["-p", x1, "--output-format", "stream-json", "--mode", "accept-edits"],
        }
        for harness in HARNESS_COMMANDS:
            for where, fact in (("session", "the session's directory"), ("command", "the command's directory")):
                code, out, err = self.world.kit("run", harness, "X1", STANDIN_HOOK_CWD=where)
                self.assertEqual((code, out), (0, f"X1 {harness} recorded: hook input cwd is {fact}\n"))
                self.assert_private(out, err)
            start = self.world.harness_starts()[-1]
            self.assertEqual(start["args"], [codex_c(start["cwd"]) if a == "{codex_c}" else a for a in argv[harness]])
            self.assertEqual(start["registered"], registration(harness, start["cwd"]), harness)
            self.assertEqual(start["decisions"], [["../control-probe.sh x1", "allow"]])
            self.assertEqual(start["logs"], ["control-ran-x1.marker", "hook.jsonl"])
            hook_log = max((self.world.state / "probes").glob(f"*/X1-{harness}-hook.jsonl"),
                           key=lambda p: p.stat().st_mtime_ns)
            self.assertEqual([line["input"] for line in map(json.loads, hook_log.read_text().splitlines())],
                             start["sent"])
        self.assert_home_empty()
        self.assertNotIn(CONNECTION, json.dumps(self.world.saved()))

    def test_x1_fails_on_a_refused_control_stand_in_a_missing_hook_line_or_cwd_or_a_command_that_stayed(self):
        cases = {
            "STANDIN_FORCE_DENY": "the control stand-in left no marker",
            "STANDIN_SKIP_HOOK": "the hook logged no input for the control stand-in",
            "STANDIN_NO_CWD": "the hook input holds no cwd",
            "STANDIN_STAY": "the stand-in ran in the session's directory, so the two cannot be told apart",
        }
        for knob, fact in cases.items():
            code, out, err = self.world.kit("run", "codex", "X1", **{knob: "1"})
            self.assertEqual((code, out), (1, f"X1 codex failed: {fact}\n"), knob)
            self.assert_private(out, err)
        refused = self.world.harness_starts()[0]
        self.assertEqual((refused["decisions"], refused["logs"]), ([["../control-probe.sh x1", "deny"]], ["hook.jsonl"]))

    def test_the_hook_refuses_and_asks_by_the_three_rules_and_only_the_commands_it_allows_leave_a_marker(self):
        also = "gh pr merge 7;;gh pr ready 7;;./merge-script.sh;;./oneway-probe.sh t1;;./control-probe.sh t2"
        for harness in HARNESS_COMMANDS:
            code, out, _ = self.world.kit("run", harness, "X1", STANDIN_ALSO=also, STANDIN_AS_AGENT="1")
            self.assertEqual(code, 0, out)
            start = self.world.harness_starts()[-1]
            # Only Claude Code, Cortex Code and Codex mark an agent in the input (the agent_id field).
            merge = "deny" if harness in ("claude", "cortex", "codex") else "allow"
            self.assertEqual(start["decisions"], [["../control-probe.sh x1", "allow"], ["gh pr merge 7", "deny"],
                                                  ["gh pr ready 7", "deny"], ["./merge-script.sh", merge],
                                                  ["./oneway-probe.sh t1", "ask"], ["./control-probe.sh t2", "allow"]])
            self.assertEqual(start["logs"], ["control-ran-t2.marker", "control-ran-x1.marker", "hook.jsonl"]
                             + (["merge-ran.marker"] if merge == "allow" else []), harness)
        self.world.kit("run", "codex", "X1", STANDIN_ALSO="./merge-script.sh")
        self.assertEqual(self.world.harness_starts()[-1]["decisions"][1], ["./merge-script.sh", "allow"])
        self.assertIn("merge-ran.marker", self.world.harness_starts()[-1]["logs"])

    def test_a_claude_session_with_an_agent_type_and_no_agent_id_may_run_the_merge_script(self):
        # The guard research note: `claude --agent` gives the session's own call agent_type and no agent_id.
        code, out, _ = self.world.kit("run", "claude", "X1", STANDIN_ALSO="./merge-script.sh", STANDIN_AGENT_TYPE="1")
        self.assertEqual(code, 0, out)
        start = self.world.harness_starts()[-1]
        self.assertEqual((start["sent"][1].get("agent_type"), "agent_id" in start["sent"][1]), ("helper", False))
        self.assertEqual(start["decisions"][1], ["./merge-script.sh", "allow"])
        self.assertIn("merge-ran.marker", start["logs"])

    def test_the_connection_in_a_hook_input_reaches_neither_the_live_nor_the_saved_hook_log(self):
        code, out, err = self.world.kit("run", "cortex", "X1", STANDIN_ARGV_IN_INPUT="1")
        self.assertEqual((code, out), (0, "X1 cortex recorded: hook input cwd is the session's directory\n"))
        (start,) = self.world.harness_starts()
        self.assertIn(CONNECTION, json.dumps(start["sent"]))  # the harness put it in the hook input
        saved = self.world.saved()
        for name, log in (("live", start["hook_log"]), ("saved", saved["X1-cortex-hook.jsonl"])):
            self.assertIn('"-c", "<connection>"', log, name)
            self.assertNotIn(CONNECTION, log, name)
        self.assertNotIn(CONNECTION, json.dumps(saved) + out + err)

    def test_x2_prints_the_median_of_each_five_calls_and_their_difference(self):
        # An outlier in each five sets the mean apart from the median: medians 100 and 400 ms, means 380 and 920.
        (self.world.bin / "python3").unlink()
        (self.world.bin / "python3").write_text(PYTHON.replace("{python}", sys.executable))
        (self.world.bin / "python3").chmod(0o755)
        code, out, err = self.world.kit("run", "cursor", "X2", STANDIN_PY_CALLS=str(self.world.root / "py.calls"),
                                        STANDIN_PY_SLEEPS="0.1 0.1 1.5 0.1 0.1", STANDIN_UV_SLEEPS="0.4 0.4 3.0 0.4 0.4")
        self.assertEqual(code, 0, out + err)
        line = re.fullmatch(r"X2 cursor recorded: uv run adds (-?\d+) ms a call "
                            r"\(median of 5: (\d+) ms, (\d+) ms without\)\n", out)
        self.assertIsNotNone(line, out)
        added, under_uv, plain = map(int, line.groups())
        self.assertTrue(100 <= plain < 300, out)
        self.assertTrue(400 <= under_uv < 600, out)
        self.assertLessEqual(abs(added - (under_uv - plain)), 1, out)  # each number is rounded on its own
        self.assertTrue(200 <= added <= 400, out)
        self.assertEqual(len(self.world.uv_runs()), 5)

    def test_x2_times_the_registered_hook_command_with_and_without_uv_run_and_starts_no_session(self):
        for harness, form in (("claude", "settings"), ("cursor", "beforeShell"), ("antigravity", "pre")):
            code, out, err = self.world.kit("run", harness, "X2")
            self.assertEqual(code, 0, out)
            line = re.fullmatch(rf"X2 {harness} recorded: uv run adds (-?\d+) ms a call "
                                rf"\(median of 5: (\d+) ms, (\d+) ms without\)\n", out)
            self.assertIsNotNone(line, out)
            self.assertGreaterEqual(int(line.group(1)), 150)  # the stand-in uv waits 200 ms
            runs = self.world.uv_runs()[-5:]
            self.assertEqual([r[:4] + [r[5]] for r in runs], [["run", "--python", "3.13", "--no-project", form]] * 5)
            self.assertEqual([r[4].endswith("/work/hooks/guard.py") for r in runs], [True] * 5)
            self.assert_private(out, err)
        self.assertEqual(len(self.world.uv_runs()), 15)
        self.assertEqual((self.world.hc_calls(), self.world.harness_starts()), ([], []))
        (self.world.bin / "uv").unlink()
        self.assertEqual(self.world.kit("run", "codex", "X2")[:2], (1, "X2 codex failed: uv is not on PATH\n"))

    def test_all_on_claude_runs_x1_and_x2(self):
        code, out, err = self.world.kit("run", "claude", "all")
        self.assertEqual(code, 1, out)
        # This world's stand-in starts no agent; TestAgentEntries has one that does.
        self.assertRegex(out, r"^X3 claude failed: harness exited 1\n"
                              r"X4 claude failed: harness exited 1\n"
                              r"X5 claude failed: harness exited 1\n"
                              r"X1 claude recorded: hook input cwd is the session's directory\n"
                              r"X2 claude recorded: uv run adds -?\d+ ms a call \(median of 5: \d+ ms, \d+ ms without\)\n"
                              # This stand-in `claude` has no plugin subcommand, so C1 and C3 stop at
                              # the registration (TestPlugin covers them).
                              r"C1 claude failed: claude plugin marketplace add exited 1\n"
                              r"C2 claude failed: harness exited 1\n"
                              r"C3 claude failed: claude plugin marketplace add exited 1\n$")
        self.assert_private(out, err)
        self.assert_home_empty()

    def test_a5_is_seen_when_the_inner_agy_call_lists_the_probe_hook(self):
        code, out, err = self.world.kit("run", "antigravity", "A5")
        self.assertEqual((code, out), (0, "A5 antigravity seen: the hook list names the probe's hook\n"))
        self.assert_private(out, err)
        (start,) = self.world.harness_starts()
        inner = 'agy -p "/hooks" > hooks-list.txt; echo $? > hooks-list.status'
        self.assertEqual(start["prompt"], f"Run `{inner}`.")
        self.assertEqual(start["decisions"], [[inner, "allow"]])
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_NO_HOOKS="1")
        self.assertEqual((code, out), (1, "A5 antigravity failed: the hook list does not name the probe's hook\n"))
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_FORCE_DENY="1")
        self.assertEqual((code, out), (1, "A5 antigravity failed: the agy -p \"/hooks\" call left no list\n"))
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_SKIP_HOOK="1")
        self.assertEqual((code, out), (1, "A5 antigravity failed: the hook logged no agy -p \"/hooks\" command\n"))
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_HOOKS_FAIL="1")  # its error names the hook
        self.assertEqual((code, out), (1, "A5 antigravity failed: the agy -p \"/hooks\" call exited 4\n"))
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_HOOKS_AS="old-probe-guard")
        self.assertEqual((code, out), (1, "A5 antigravity failed: the hook list does not name the probe's hook\n"))
        self.assert_home_empty()

    def test_help_states_the_hook_its_registration_and_how_x1_x2_a5_and_x7_are_measured(self):
        code, out, err = self.world.kit("--help")
        self.assertEqual((code, err), (0, ""))
        text = " ".join(out.split())
        for fact in ("x7 HARNESS [--mode bypass|auto] [--connection NAME]", "(claude, cortex, codex, cursor or antigravity)",
                     ".claude/settings.json, .cortex/settings.json, .cursor/hooks.json, .agents/hooks.json, "
                     "and a -c override on the Codex command line", "Nothing is written to a user-level settings file",
                     "appends each input it gets to logs/hook.jsonl", "refuses `gh pr merge` and `gh pr ready`",
                     "refuses merge-script.sh when the input marks an agent", "asks on oneway-probe.sh",
                     "a refused command leaves none", "compares the hook input's cwd with the probe folder and with "
                     "the directory the stand-in recorded", "X2 starts no session",
                     "python3 and then `uv run --python 3.13 --no-project`, 5 calls each",
                     "the difference of the two medians", "`agy -p \"/hooks\"`", "`hc run --bg`",
                     "prints the `hc send` and `hc read` commands for the owner", "It gives no verdict",
                     "Claude Code needs --mode bypass or --mode auto", "Cortex Code runs with --bypass",
                     "Codex gets a `prompt` rule for oneway-probe.sh", "`x7` exits 0 once the terminal UI has started"):
            self.assertIn(fact, text)


class TestX7(HookTest):
    def wait_for_start(self, count: int) -> dict:
        deadline = time.monotonic() + 20
        while len(self.world.harness_starts()) < count and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.world.harness_starts()[count - 1]

    def test_x7_starts_the_terminal_ui_and_prints_the_owners_commands_on_every_harness_and_mode(self):
        self.world.install("tui")
        cases = [
            ("claude", ["--mode", "bypass"], "claude bypass",
             ["claude", "--setting-sources", "project", "--permission-mode", "bypassPermissions"]),
            ("claude", ["--mode", "auto"], "claude auto",
             ["claude", "--setting-sources", "project", "--permission-mode", "auto"]),
            ("cortex", [], "cortex", ["cortex", "--bypass", "-c", CONNECTION]),
            ("codex", [], "codex", ["codex", "-c", "{codex_c}"]),
            ("cursor", [], "cursor", ["cursor-agent"]),
            ("antigravity", [], "antigravity", ["agy"]),
        ]
        for number, (harness, extra, label, argv) in enumerate(cases, 1):
            code, out, err = self.world.kit("x7", harness, *extra)
            self.assertEqual((code, err), (0, ""), label)
            run = self.world.hc_calls()[-1]
            name, work = run[5], Path(run[7])
            argv = [codex_c(str(work)) if a == "{codex_c}" else a for a in argv]
            self.assertRegex(name, rf"^probe-{harness}-x7-{label.split(' ')[1] + '-' if ' ' in label else ''}\d+$")
            hidden = ["env", f"PROBE_KIT_CONNECTION={CONNECTION}"] if harness == "cortex" else []
            self.assertEqual(run, ["run", "--json", "--bg", "--no-notify", "--name", name, "--cwd", str(work),
                                   *hidden, *argv])
            folder = f'"${{TMPDIR:-/tmp}}"/{work.parent.name}'
            self.assertEqual(out, f"X7 {label}: the terminal UI runs in terminal {name}, in the probe folder "
                                  f"{work.parent.name}. Run these in order:\n"
                                  f"  hc read {name} --lines 40\n"
                                  f"  hc send {name} 'run ./oneway-probe.sh x7'\n"
                                  f"  hc read {name} --lines 40\n"
                                  f"  ls {folder}/work/logs  # oneway-ran-x7.marker: the command ran\n"
                                  f"  hc kill {name}\n"
                                  f"  rm -rf {folder}\n")
            self.assert_private(out, err)
            self.assertNotIn(CONNECTION, out + err)
            start = self.wait_for_start(number)
            self.assertEqual([start["name"], *start["args"]], argv)
            self.assertLessEqual({"hooks/guard.py", "merge-script.sh", "oneway-probe.sh", "control-probe.sh",
                                  *registration(harness, str(work))}, set(start["files"]), label)
            rule = work / ".codex" / "rules" / "guards.rules"
            self.assertEqual(rule.read_text() if rule.exists() else None, (
                'prefix_rule(pattern = ["./oneway-probe.sh"], decision = "prompt",\n'
                '    justification = "one-way command, needs the owner\'s answer")\n') if harness == "codex" else None)
            self.assertTrue(work.is_dir())  # the folder stays for the owner
        self.assertEqual({call[0] for call in self.world.hc_calls()}, {"run"})  # the owner sends and reads
        self.assert_home_empty()

    def test_x7_refuses_a_wrong_mode_a_missing_connection_or_program_and_a_headless_x7(self):
        cases = {
            ("x7", "claude"): "probe_kit: x7 on claude needs --mode bypass or --mode auto\n",
            ("x7", "codex", "--mode", "auto"): "probe_kit: --mode is for claude only\n",
            ("x7", "vim"): "probe_kit: unknown harness 'vim'; harnesses: claude, cortex, codex, cursor, antigravity\n",
            ("run", "claude", "X7"): "probe_kit: X7 is not run headless; `x7 HARNESS` starts the terminal UI for the owner\n",
        }
        for argv, message in cases.items():
            self.assertEqual(self.world.kit(*argv), (2, "", message), argv)
        self.assertEqual(World.kit(self.world, "x7", "cortex"),
                         (2, "", "probe_kit: cortex needs --connection, the Snowflake connection its runs spend\n"))
        (self.world.bin / "hc").unlink()
        self.assertEqual(self.world.kit("x7", "cursor"), (2, "", "probe_kit: hc is not on PATH\n"))
        self.assertEqual((self.world.hc_calls(), self.world.harness_starts()), ([], []))


# C1, C2, C3 and R4 (#387). A stand-in `claude` that keeps `claude plugin`'s state under HOME the way the
# real one is taken to: known_marketplaces.json, a copy of each marketplace, a cache of each installed
# plugin, installed_plugins.json, and enabledPlugins in ~/.claude/settings.json. As a session it loads an
# installed plugin only when --setting-sources names user: it runs the typed plugin skill, starts the
# plugin's role, sends the shell command to the plugin's hook and runs it. For a project role whose file
# lists skills, the agent gets the skill's text and writes the marker. Knobs: STANDIN_PLUGIN_FAIL makes
# those `claude plugin` actions exit 1, comma-separated; STANDIN_OFF leaves those parts unloaded (skill,
# role, hook, skills); STANDIN_SESSION_READS has the session read the skill file and write the marker;
# STANDIN_SESSION_WRITES has the session write it with no read shown; STANDIN_UNINSTALL_NEEDS_ENTRY makes
# uninstall refuse a plugin its marketplace no longer offers; STANDIN_BREAK_SOURCE deletes the probe's
# marketplace file on install; STANDIN_LOCK leaves the plugin cache folder read-only; STANDIN_SLEEP waits
# before the session acts. Fix round 1: hooks run only when their matcher matches Bash. STANDIN_LOCK_SETTINGS
# leaves settings.json read-only after install; STANDIN_MATCHER sets the installed hook's matcher;
# STANDIN_HOOK_PAYLOAD=description sends `pwd` as the command and the prompt's command in the description;
# STANDIN_PLUGIN_READS has the session read the plugin's skill and role files and write both words with no
# agent; STANDIN_ROLE_TOP has the session, not the plugin role's agent, write the role word;
# STANDIN_SESSION_READS=glob reads the skill with `cat .claude/skills/*/SKILL.md`; STANDIN_AGENT_TYPE starts
# another role than the one asked for; STANDIN_FOREIGN has the session write the marker, then sends the word
# in a user tool result of the agent's call (user) or in an assistant event of another call (other).
PLUGIN_CLAUDE = r'''#!{python}
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path
args, knob = sys.argv[1:], os.environ.get
home = Path.home() / ".claude"
plugins = home / "plugins"
known, installed, settings = plugins / "known_marketplaces.json", plugins / "installed_plugins.json", home / "settings.json"
with open(knob("STANDIN_CLAUDE_CALLS"), "a") as calls:
    calls.write(json.dumps(args) + "\n")


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def word_of(text):
    return re.search(r"Write the word (\S+)", text).group(1)


if args[0] == "plugin":
    action, target = " ".join(args[1:3] if args[1] == "marketplace" else args[1:2]), args[-1]
    if action in (knob("STANDIN_PLUGIN_FAIL") or "").split(","):
        print("stand-in refusal under " + str(home), file=sys.stderr)
        sys.exit(1)
    if action == "marketplace add":
        name = json.loads((Path(target) / ".claude-plugin" / "marketplace.json").read_text())["name"]
        save(known, {**load(known, {}), name: {"source": {"source": "directory", "path": target}}})
        shutil.copytree(target, plugins / "marketplaces" / name)
    elif action == "marketplace update":
        shutil.rmtree(plugins / "marketplaces" / target)
        shutil.copytree(load(known, {})[target]["source"]["path"], plugins / "marketplaces" / target)
    elif action == "marketplace remove":
        save(known, {key: value for key, value in load(known, {}).items() if key != target})
        shutil.rmtree(plugins / "marketplaces" / target, ignore_errors=True)
    elif action == "install":
        plugin, market = target.split("@")
        offered = plugins / "marketplaces" / market
        source = next(p["source"] for p in json.loads((offered / ".claude-plugin" / "marketplace.json").read_text())[
            "plugins"] if p["name"] == plugin)
        path = plugins / "cache" / market / plugin / "1.0.0"
        shutil.copytree(offered / source, path)
        if knob("STANDIN_LOCK"):
            (plugins / "cache").chmod(0o555)
        if knob("STANDIN_BREAK_SOURCE"):
            (Path(load(known, {})[market]["source"]["path"]) / ".claude-plugin" / "marketplace.json").unlink()
        data = load(installed, {"version": 2, "plugins": {}})
        data["plugins"][target] = [{"scope": "user", "installPath": str(path), "version": "1.0.0"}]
        save(installed, data)
        prefs = load(settings, {})
        prefs.setdefault("enabledPlugins", {})[target] = True
        save(settings, prefs)
        if knob("STANDIN_LOCK_SETTINGS"):
            settings.chmod(0o444)
        if knob("STANDIN_MATCHER"):
            hooks = json.loads((path / "hooks" / "hooks.json").read_text())
            hooks["hooks"]["PreToolUse"][0]["matcher"] = knob("STANDIN_MATCHER")
            (path / "hooks" / "hooks.json").write_text(json.dumps(hooks))
    elif action == "uninstall":
        plugin, market = target.split("@")
        offered = plugins / "marketplaces" / market / ".claude-plugin" / "marketplace.json"
        listed = offered.exists() and plugin in [p["name"] for p in json.loads(offered.read_text())["plugins"]]
        data = load(installed, {"version": 2, "plugins": {}})
        if target not in data["plugins"] or (knob("STANDIN_UNINSTALL_NEEDS_ENTRY") and not listed):
            sys.exit(1)
        del data["plugins"][target]
        save(installed, data)
        prefs = load(settings, {})
        prefs.get("enabledPlugins", {}).pop(target, None)
        save(settings, prefs)
        shutil.rmtree(plugins / "cache" / market / plugin)
        (plugins / "cache" / market).rmdir()
    sys.exit(0)
prompt, cwd, off = args[args.index("-p") + 1], Path.cwd(), (knob("STANDIN_OFF") or "").split(",")
sources = args[args.index("--setting-sources") + 1].split(",")
enabled = load(settings, {}).get("enabledPlugins", {}) if "user" in sources else {}
roots = [Path(e[0]["installPath"]) for key, e in load(installed, {"plugins": {}})["plugins"].items() if enabled.get(key)]
with open(knob("STANDIN_STARTS"), "a") as starts:
    starts.write(json.dumps({
        "name": "claude", "args": args, "prompt": prompt,
        "project_skills": sorted(str(p.relative_to(cwd)) for p in cwd.glob(".claude/skills/*/SKILL.md")),
        "skill_texts": {str(p.relative_to(cwd)): p.read_text() for p in cwd.glob(".claude/skills/*/SKILL.md")},
        "definitions": {str(p.relative_to(cwd)): p.read_text() for p in sorted(cwd.glob(".claude/agents/*"))},
        "plugins": [sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) for root in roots],
        "plugin_texts": [{str(p.relative_to(root)): p.read_text() for p in root.rglob("*") if p.is_file()}
                         for root in roots]}) + "\n")
time.sleep(float(knob("STANDIN_SLEEP", "0")))


def emit(**event):
    print(json.dumps(event), flush=True)


emit(type="system", subtype="init", session_id="{session}", cwd=str(cwd))
typed = re.match(r"/(\S+):(\S+) ", prompt)
role = re.search(r"of the role (\S+):(\S+) and", prompt)
for root in roots:
    name = json.loads((root / ".claude-plugin" / "plugin.json").read_text())["name"]
    if knob("STANDIN_PLUGIN_READS") and typed and role:  # the words from plain reads, with no agent
        files = [root / "skills" / typed.group(2) / "SKILL.md", root / "agents" / (role.group(2) + ".md")]
        for number, path in enumerate(files):
            emit(type="assistant", parent_tool_use_id=None, message={"content": [
                {"type": "tool_use", "id": f"toolu_read{number}", "name": "Read", "input": {"file_path": str(path)}}]})
        (cwd / "probe-marker.txt").write_text(word_of(files[0].read_text()))
        task = re.search(r"Write your role word to the file (\S+) in the folder (.+)\. Then run", prompt)
        word = re.search(r"Your role word is (\S+)\.", files[1].read_text())
        (Path(task.group(2)) / task.group(1)).write_text(word.group(1) + "\n")
        continue
    if typed and typed.group(1) == name and "skill" not in off:
        (cwd / "probe-marker.txt").write_text(word_of((root / "skills" / typed.group(2) / "SKILL.md").read_text()))
    if role and role.group(1) == name and "role" not in off:
        task = re.search(r"Write your role word to the file (\S+) in the folder (.+)\. Then run", prompt)
        word = re.search(r"Your role word is (\S+)\.", (root / "agents" / (role.group(2) + ".md")).read_text())
        emit(type="assistant", parent_tool_use_id=None, message={"content": [
            {"type": "tool_use", "id": "toolu_role", "name": "Agent",
             "input": {"subagent_type": role.group(1) + ":" + role.group(2), "prompt": task.group(0)}}]})
        (Path(task.group(2)) / task.group(1)).write_text(word.group(1) + "\n")
        emit(type="assistant", parent_tool_use_id=None if knob("STANDIN_ROLE_TOP") else "toolu_role", message={
            "content": [{"type": "tool_use", "id": "toolu_role_write", "name": "Write",
                         "input": {"file_path": task.group(1), "content": word.group(1)}}]})
command = re.search(r"shell command `([^`]+)`", prompt)
if command:
    sent = {"command": command.group(1)}
    if knob("STANDIN_HOOK_PAYLOAD") == "description":
        sent = {"command": "pwd", "description": "not " + command.group(1)}
    for root in [] if "hook" in off else roots:
        for group in json.loads((root / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]:
            if group.get("matcher", "") not in ("", "*") and not re.fullmatch(group["matcher"], "Bash"):
                continue
            for hook in group["hooks"]:
                subprocess.run(hook["command"], shell=True, check=True, text=True, input=json.dumps(
                    {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": sent, "cwd": str(cwd)}))
    subprocess.run(command.group(1), shell=True, check=True)
skilled = re.search(r"of the role ([\w-]+) and give it", prompt)
if skilled:
    head = (cwd / ".claude" / "agents" / (skilled.group(1) + ".md")).read_text().split("---\n")[1]
    skill = cwd / ".claude" / "skills" / "probe-standin" / "SKILL.md"
    emit(type="assistant", parent_tool_use_id=None, message={"content": [
        {"type": "tool_use", "id": "toolu_1", "name": "Agent",
         "input": {"subagent_type": knob("STANDIN_AGENT_TYPE") or skilled.group(1)}}]})
    writer = "toolu_1"
    if knob("STANDIN_SESSION_READS") == "glob":
        emit(type="assistant", parent_tool_use_id=None, message={"content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "cat .claude/skills/*/SKILL.md"}}]})
        writer = None
    elif knob("STANDIN_SESSION_READS"):
        emit(type="assistant", parent_tool_use_id=None, message={"content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Read", "input": {"file_path": str(skill)}}]})
        writer = None
    if knob("STANDIN_SESSION_WRITES") or knob("STANDIN_FOREIGN"):
        writer = None
    if writer is None or (re.search(r"^skills:\n  - probe-standin$", head, re.M) and "skills" not in off):
        word = word_of(skill.read_text())
        (cwd / "probe-marker.txt").write_text(word + "\n")
        emit(type="assistant", parent_tool_use_id=writer, message={"content": [
            {"type": "tool_use", "id": "toolu_3", "name": "Write",
             "input": {"file_path": str(cwd / "probe-marker.txt"), "content": word}}]})
        if knob("STANDIN_FOREIGN") == "user":
            emit(type="user", parent_tool_use_id="toolu_1", message={"content": [
                {"type": "tool_result", "tool_use_id": "toolu_4", "content": "the marker holds " + word}]})
        elif knob("STANDIN_FOREIGN") == "other":
            emit(type="assistant", parent_tool_use_id="toolu_9", message={"content": [
                {"type": "text", "text": "The word is " + word}]})
emit(type="result", session_id="{session}", result="done")
'''

# R4: a stand-in `cursor-agent` that loads each plugin of Claude Code's installed list STANDIN_CURSOR_LOADS
# times (default 1): from the cache, then from the marketplace copy. Its init event names each loaded skill
# file; a typed /probe-standin runs the first; each loaded hook gets the shell command, which then runs
# unless STANDIN_NO_SHELL is set. Like the stand-in `claude`, it runs a hook only when its matcher matches
# Bash, and STANDIN_HOOK_PAYLOAD=description sends `pwd` as the command.
PLUGIN_CURSOR = r'''#!{python}
import json, os, re, subprocess, sys
from pathlib import Path
args, cwd = sys.argv[1:], Path.cwd()
prompt = args[-1]
plugins = Path.home() / ".claude" / "plugins"
listed = plugins / "installed_plugins.json"
copies = []
for key, entries in (json.loads(listed.read_text())["plugins"] if listed.exists() else {}).items():
    plugin, market = key.split("@")
    copies += [Path(entries[0]["installPath"]), plugins / "marketplaces" / market / plugin]
copies = copies[:int(os.environ.get("STANDIN_CURSOR_LOADS", "1"))]
with open(os.environ["STANDIN_STARTS"], "a") as starts:
    starts.write(json.dumps({"name": "cursor-agent", "args": args, "prompt": prompt,
                             "project_skills": sorted(str(p.relative_to(cwd)) for p in cwd.glob(".cursor/skills/*/*"))}) + "\n")
skills = [str(copy / "skills" / "probe-standin" / "SKILL.md") for copy in copies]
print(json.dumps({"type": "system", "subtype": "init", "session_id": "{session}", "skills": skills}), flush=True)
if prompt.startswith("/probe-standin") and skills:
    word = re.search(r"Write the word (\S+)", Path(skills[0]).read_text()).group(1)
    (cwd / "probe-marker.txt").write_text(word + "\n")
command = re.search(r"shell command `([^`]+)`", prompt).group(1)
sent = {"command": command}
if os.environ.get("STANDIN_HOOK_PAYLOAD") == "description":
    sent = {"command": "pwd", "description": "not " + command}
for copy in copies:
    for group in json.loads((copy / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]:
        if group.get("matcher", "") not in ("", "*") and not re.fullmatch(group["matcher"], "Bash"):
            continue
        for hook in group["hooks"]:
            subprocess.run(hook["command"], shell=True, check=True, text=True, input=json.dumps({**sent, "cwd": str(cwd)}))
if not os.environ.get("STANDIN_NO_SHELL"):
    subprocess.run(command, shell=True, check=True)
print(json.dumps({"type": "result", "session_id": "{session}", "result": "done"}))
'''


class PluginWorld(World):
    """The world with the plugin stand-ins as `claude` and `cursor-agent`, and python3 first on PATH."""

    def __init__(self) -> None:
        super().__init__()
        self.claude_calls = self.root / "claude.jsonl"
        for name, text in (("claude", PLUGIN_CLAUDE), ("cursor-agent", PLUGIN_CURSOR)):
            (self.bin / name).unlink(missing_ok=True)
            (self.bin / name).write_text(text.replace("{python}", sys.executable).replace("{session}", SESSION))
            (self.bin / name).chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)

    def env(self, **knobs: str) -> dict[str, str]:
        return {"STANDIN_CLAUDE_CALLS": str(self.claude_calls), **knobs}

    def kit(self, *args: str, **knobs: str) -> tuple[int, str, str]:
        return super().kit(*args, **self.env(**knobs))

    def plugin_calls(self) -> list[list[str]]:
        lines = self.claude_calls.read_text().splitlines() if self.claude_calls.exists() else []
        return [json.loads(line)[:3] for line in lines if json.loads(line)[0] == "plugin"]


MARKET = r"probe-market-[0-9a-f]{8}"
LEFT_AS_IT_WAS = "probe_kit: the machine was left as it was"


def user_level_lines(entry: str) -> str:
    """What the kit prints on standard error before it changes Claude Code's plugins."""
    return (rf"probe_kit: {entry} registers the marketplace ({MARKET}) with Claude Code, under ~/\.claude/\n"
            rf"probe_kit: {entry} installs the plugin probe-plugin@\1 on Claude Code, under ~/\.claude/\n")


RAW = r"probe_kit: raw output kept in probes/\d{8}T\d{6}Z-\d+/ of the machine directory\n"


class TestPlugin(ProbeKitTest):
    def setUp(self) -> None:
        self.world = PluginWorld()
        self.addCleanup(shutil.rmtree, self.world.root, ignore_errors=True)

    def assert_home_empty(self) -> None:
        self.assertEqual(sorted(self.world.home.rglob("*")), [])

    def assert_changes_undone(self, entry: str, err: str, raw: bool = True) -> str:
        """The two changes named first, the last line, an empty HOME and the folder gone; the marketplace's name."""
        found = re.fullmatch(user_level_lines(entry) + RAW * raw + LEFT_AS_IT_WAS + "\n", err)
        self.assertIsNotNone(found, err)
        self.assert_home_empty()
        self.assertEqual(list(self.world.tmp.iterdir()), [])
        self.assert_private(err)
        return found.group(1)

    def test_help_states_the_user_level_changes_and_how_c1_c2_c3_and_r4_are_judged(self):
        code, out, err = self.world.kit("--help")
        self.assertEqual((code, err), (0, ""))
        text = " ".join(out.split())
        for fact in ("C1, C3 and R4 change Claude Code's user-level plugins, under ~/.claude/",
                     "It names each change on standard error before it makes it",
                     "also after a failure or an interrupt, it uninstalls the plugin, removes the marketplace and "
                     "deletes what still names it under ~/.claude/",
                     "The kit's last line then says the machine was left as it was, or names what it could not remove",
                     "C1 reads the user's settings as well as the project's",
                     "C2 installs nothing: a project role file names the stand-in skill in its skills list",
                     "C3 starts no session", "records the exit code and whether the plugin stayed",
                     "R4 runs Cursor with the typed skill and one shell command"):
            self.assertIn(fact, text)

    def test_c1_is_seen_when_the_installed_plugin_loads_its_skill_role_file_and_hook(self):
        code, out, err = self.world.kit("run", "claude", "C1")
        self.assertEqual((code, out), (0, "C1 claude seen: the installed plugin loaded its skill, role file and hook\n"))
        market = self.assert_changes_undone("C1", err)
        source = json.loads(self.world.claude_calls.read_text().splitlines()[0])[3]
        self.assertEqual(self.world.plugin_calls(), [
            ["plugin", "marketplace", "add"], ["plugin", "install", f"probe-plugin@{market}"],
            ["plugin", "uninstall", f"probe-plugin@{market}"], ["plugin", "marketplace", "remove"]])
        self.assertEqual(Path(source).name, "market")
        start = self.world.harness_starts()[0]
        self.assertEqual(start["args"][2:], ["--output-format", "stream-json", "--verbose", "--setting-sources",
                                             "user,project", "--no-session-persistence", "--permission-mode",
                                             "acceptEdits", "--allowedTools", "Agent,Read,Write,Edit,Bash,Glob,Grep"])
        self.assertEqual(start["plugins"], [[".claude-plugin/plugin.json", "agents/probe-plugin-role.md",
                                             "hooks/hooks.json", "skills/probe-standin/SKILL.md"]])
        self.assertEqual(start["project_skills"], [])  # the plugin's copy of the skill is the only one
        texts = start["plugin_texts"][0]
        codeword = re.search(r"Write the word (\S+)", texts["skills/probe-standin/SKILL.md"]).group(1)
        role_word = re.search(r"Your role word is (\S+)\.", texts["agents/probe-plugin-role.md"]).group(1)
        self.assertIn("disable-model-invocation: true", texts["skills/probe-standin/SKILL.md"])
        for word in (codeword, role_word, market):
            self.assertNotIn(word, start["prompt"])
        self.assertTrue(start["prompt"].startswith("/probe-plugin:probe-standin Then start one agent of the role "
                                                   "probe-plugin:probe-plugin-role "))
        self.assertNotIn(codeword, texts["agents/probe-plugin-role.md"] + texts["hooks/hooks.json"] + market)

    def test_c1_fails_naming_each_part_of_the_plugin_that_did_not_load_and_still_undoes_its_changes(self):
        cases = {"role": "role file", "hook": "hook", "skill,hook": "skill and hook",
                 "skill,role,hook": "skill, role file and hook"}
        for parts, missing in cases.items():
            code, out, err = self.world.kit("run", "claude", "C1", STANDIN_OFF=parts)
            self.assertEqual((code, out), (1, f"C1 claude failed: the installed plugin's {missing} did not load\n"))
            self.assert_changes_undone("C1", err)

    def test_a_failed_install_or_registration_fails_c1_before_any_session_and_is_undone(self):
        for action, made in (("install", 2), ("marketplace add", 1)):
            code, out, err = self.world.kit("run", "claude", "C1", STANDIN_PLUGIN_FAIL=action)
            self.assertEqual((code, out), (1, f"C1 claude failed: claude plugin {action} exited 1\n"))
            named = user_level_lines("C1") if made == 2 else user_level_lines("C1").split(r"\n")[0] + r"\n"
            self.assertRegex(err, "^" + named + LEFT_AS_IT_WAS + "\n$")  # no session, so no raw output (F13)
            self.assert_home_empty()
            self.assertEqual((self.world.hc_calls(), self.world.harness_starts()), ([], []))
            self.assertEqual(self.world.plugin_calls()[-2:], [["plugin", "uninstall", self.world.plugin_calls()[-2][2]],
                                                              ["plugin", "marketplace", "remove"]])

    def test_an_interrupt_during_c1_ends_the_terminal_and_undoes_the_changes(self):
        import signal
        env = {"PATH": f"{self.world.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.world.home),
               "DELIVER_STATE_DIR": str(self.world.state), "TMPDIR": str(self.world.tmp),
               "STANDIN_HC_DIR": str(self.world.hc_dir), "STANDIN_STARTS": str(self.world.starts),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull, "LANG": "C.UTF-8",
               **self.world.env(STANDIN_SLEEP="30")}
        kit = subprocess.Popen([sys.executable, str(KIT), "run", "claude", "C1", "--poll", "0.05"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(kit.kill)
        deadline = time.monotonic() + 20
        while not self.world.harness_starts() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue((self.world.home / ".claude" / "settings.json").is_file())
        kit.send_signal(signal.SIGINT)
        out, err = kit.communicate(timeout=30)
        self.assertEqual((kit.returncode, out), (130, ""))
        self.assertRegex(err, "^" + user_level_lines("C1") + LEFT_AS_IT_WAS + "\n$")
        self.assert_home_empty()
        self.assertEqual(self.world.hc_calls()[-1][:1], ["kill"])
        self.assertEqual(list(self.world.tmp.iterdir()), [])

    def test_the_last_line_names_what_could_not_be_removed(self):
        cache = self.world.home / ".claude" / "plugins" / "cache"
        self.addCleanup(lambda: cache.exists() and cache.chmod(0o755))
        code, out, err = self.world.kit("run", "claude", "C1", STANDIN_LOCK="1")
        self.assertEqual((code, out), (0, "C1 claude seen: the installed plugin loaded its skill, role file and hook\n"))
        self.assertRegex(err, "^" + user_level_lines("C1") + RAW + r"probe_kit: could not remove "
                         r"~/\.claude/plugins/cache/\1; remove by hand\n$")
        self.assertEqual(sorted(str(p.relative_to(self.world.home)) for p in self.world.home.rglob("*")),
                         [".claude", ".claude/plugins", ".claude/plugins/cache",
                          ".claude/plugins/cache/" + re.search(MARKET, err).group(0)])
        self.assert_private(out, err)

    def test_c2_is_seen_when_an_agent_of_the_role_writes_the_codeword_its_file_loaded_and_installs_nothing(self):
        code, out, err = self.world.kit("run", "claude", "C2")
        self.assertEqual((code, out), (0, "C2 claude seen: an agent of the role wrote the codeword only the skill holds\n"))
        self.assertRegex(err, "^" + RAW + "$")
        self.assertEqual(self.world.plugin_calls(), [])
        self.assert_home_empty()
        start = self.world.harness_starts()[0]
        self.assertEqual(start["args"][4:6], ["--verbose", "--setting-sources"])
        self.assertEqual(start["args"][6], "project")
        self.assertEqual(start["project_skills"], [".claude/skills/probe-standin/SKILL.md"])
        role = start["definitions"][".claude/agents/probe-skilled.md"]
        self.assertIn("\nskills:\n  - probe-standin\n", role)
        self.assertIn("\ndisable-model-invocation: true\n", start["skill_texts"][".claude/skills/probe-standin/SKILL.md"])
        codeword = re.search(r"probe-[0-9a-f]{8}", self.world.saved()["C2-claude.jsonl"]).group(0)
        for text in (role, start["prompt"]):
            self.assertNotIn(codeword, text)
        self.assertEqual(start["prompt"], "Start one agent of the role probe-skilled and give it this line, word for "
                         "word, as its whole prompt: Follow the skill you were given, in the folder "
                         + start["prompt"].split("in the folder ")[1])

    def test_c2_fails_unless_the_agent_got_the_codeword_without_a_read_of_the_skill_file(self):
        cases = {"STANDIN_OFF": ("skills", "no marker holds the skill's codeword"),
                 "STANDIN_SESSION_READS": ("1", "a tool read the skill file, so the codeword need not have come "
                                                "through the role file"),
                 "STANDIN_SESSION_WRITES": ("1", "no event of the agent's holds the codeword")}
        for name, (value, fact) in [*cases.items(), *[
                # Fix round 1 (F7): a shell read by glob, a word in a user tool result of the agent's call or in
                # an event of another call, and an agent of another role.
                ("STANDIN_SESSION_READS", ("glob", cases["STANDIN_SESSION_READS"][1])),
                ("STANDIN_FOREIGN", ("user", cases["STANDIN_SESSION_WRITES"][1])),
                ("STANDIN_FOREIGN", ("other", cases["STANDIN_SESSION_WRITES"][1])),
                ("STANDIN_AGENT_TYPE", ("probe-other", "no agent of the role probe-skilled was started"))]]:
            code, out, err = self.world.kit("run", "claude", "C2", **{name: value})
            self.assertEqual((code, out), (1, f"C2 claude failed: {fact}\n"))
            self.assert_private(out, err)

    def test_c3_records_what_uninstall_does_once_the_marketplace_no_longer_offers_the_plugin(self):
        for knobs, fact in (({}, "uninstall exited 0 and the plugin is gone"),
                            ({"STANDIN_UNINSTALL_NEEDS_ENTRY": "1"}, "uninstall exited 1 and the plugin stayed")):
            self.world.claude_calls.unlink(missing_ok=True)
            code, out, err = self.world.kit("run", "claude", "C3", **knobs)
            self.assertEqual((code, out), (0, f"C3 claude recorded: {fact}\n"))
            market = self.assert_changes_undone("C3", err, raw=False)  # C3 keeps no file (F13)
            self.assertEqual(list((self.world.state / "probes").iterdir()), [])
            self.assertEqual(self.world.plugin_calls(), [
                ["plugin", "marketplace", "add"], ["plugin", "install", f"probe-plugin@{market}"],
                ["plugin", "marketplace", "update"], ["plugin", "uninstall", f"probe-plugin@{market}"],
                ["plugin", "uninstall", f"probe-plugin@{market}"], ["plugin", "marketplace", "remove"]])
            self.assertEqual((self.world.hc_calls(), self.world.harness_starts()), ([], []))

    def test_c3_fails_when_the_marketplace_update_fails_or_the_probe_raises_and_still_undoes_its_changes(self):
        for knobs, fact in (({"STANDIN_PLUGIN_FAIL": "marketplace update"},
                             "claude plugin marketplace update exited 1"),
                            ({"STANDIN_BREAK_SOURCE": "1"}, "the probe stopped on FileNotFoundError")):
            code, out, err = self.world.kit("run", "claude", "C3", **knobs)
            self.assertEqual((code, out), (1, f"C3 claude failed: {fact}\n"))
            self.assert_changes_undone("C3", err, raw=False)

    def test_r4_records_how_often_cursor_shows_the_installed_plugin_s_skill_and_fires_its_hook(self):
        for loads, fact in (("1", "skill file in the output once, skill ran, hook fired once"),
                            ("2", "skill file in the output twice, skill ran, hook fired twice"),
                            ("0", "skill file in the output not at all, skill did not run, hook fired not at all")):
            code, out, err = self.world.kit("run", "cursor", "R4", STANDIN_CURSOR_LOADS=loads)
            self.assertEqual((code, out), (0, f"R4 cursor recorded: {fact}\n"))
            self.assert_changes_undone("R4", err)
        start = self.world.harness_starts()[0]
        self.assertEqual(start["prompt"], "/probe-standin Then run the shell command `echo probe-r4 > probe-r4.txt`.")
        self.assertEqual(start["project_skills"], [])  # only the plugin's copy could show
        self.assertEqual(start["args"][:5], ["-p", "--output-format", "stream-json", "--force", start["prompt"]])

    def test_r4_fails_when_the_command_did_not_run_or_claude_is_missing(self):
        code, out, err = self.world.kit("run", "cursor", "R4", STANDIN_NO_SHELL="1")
        self.assertEqual((code, out), (1, "R4 cursor failed: the shell command did not run, so the hook count "
                                          "says nothing\n"))
        self.assert_changes_undone("R4", err)
        (self.world.bin / "claude").unlink()
        code, out, err = self.world.kit("run", "cursor", "R4")
        self.assertEqual((code, out), (1, "R4 cursor failed: claude is not on PATH\n"))
        self.assertEqual(err, "")  # nothing was changed or kept, so no line about the machine or raw output
        self.assert_home_empty()

    def test_all_on_cursor_and_claude_runs_the_plugin_entries_with_their_own_lines(self):
        code, out, err = self.world.kit("run", "cursor", "all")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[-1], "R4 cursor recorded: skill file in the output once, skill ran, "
                                               "hook fired once")
        self.assertEqual(err.splitlines()[-1], LEFT_AS_IT_WAS)
        code, out, err = self.world.kit("run", "claude", "all")
        self.assertEqual(out.splitlines()[-3:], [
            "C1 claude seen: the installed plugin loaded its skill, role file and hook",
            "C2 claude seen: an agent of the role wrote the codeword only the skill holds",
            "C3 claude recorded: uninstall exited 0 and the plugin is gone"])
        self.assertEqual(err.splitlines()[-1], LEFT_AS_IT_WAS)
        self.assert_home_empty()
        self.assert_private(out, err)


    # Fix round 1 (#387 review of c2b121c).
    def populate_home(self) -> dict[Path, bytes]:
        """The user's own settings and plugin registry, in a form the stand-in would write differently."""
        files = {self.world.home / ".claude" / "settings.json": b'{"theme": "dark"}\n',
                 self.world.home / ".claude" / "plugins" / "known_marketplaces.json":
                     b'{"my-market": {"source": {"source": "github", "repo": "someone/tools"}}}\n',
                 self.world.home / ".claude" / "plugins" / "installed_plugins.json":
                     b'{"version": 2, "plugins": {"tool@my-market": [{"scope": "user", "version": "2.0.0"}]}}\n'}
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return files

    def test_existing_user_files_hold_the_same_bytes_after_a_pass_and_a_failure(self):
        files = self.populate_home()
        tree = sorted(self.world.home.rglob("*"))
        for entry, knobs, fact in (
                ("C1", {}, "C1 claude seen: the installed plugin loaded its skill, role file and hook\n"),
                ("C1", {"STANDIN_OFF": "role"}, "C1 claude failed: the installed plugin's role file did not load\n"),
                ("C1", {"STANDIN_PLUGIN_FAIL": "install"}, "C1 claude failed: claude plugin install exited 1\n"),
                ("C3", {}, "C3 claude recorded: uninstall exited 0 and the plugin is gone\n")):
            code, out, err = self.world.kit("run", "claude", entry, **knobs)
            self.assertEqual(out, fact)
            raw = RAW if (entry, knobs.keys() & {"STANDIN_PLUGIN_FAIL"}) == ("C1", set()) else ""
            self.assertRegex(err, "^" + user_level_lines(entry) + raw + LEFT_AS_IT_WAS + "\n$")
            self.assertEqual({path: path.read_bytes() for path in files}, files)
            self.assertEqual(sorted(self.world.home.rglob("*")), tree)

    def test_the_last_line_names_a_user_file_it_could_not_put_back(self):
        settings = self.world.home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_bytes(b'{"theme": "dark"}\n')
        self.addCleanup(settings.chmod, 0o644)
        code, out, err = self.world.kit("run", "claude", "C1", STANDIN_LOCK_SETTINGS="1")
        self.assertEqual((code, out), (0, "C1 claude seen: the installed plugin loaded its skill, role file and hook\n"))
        self.assertRegex(err, "^" + user_level_lines("C1") + RAW + r"probe_kit: could not restore ~/\.claude/settings"
                         r"\.json to what it held before; fix by hand\n$")
        self.assertNotEqual(settings.read_bytes(), b'{"theme": "dark"}\n')
        self.assert_private(out, err)

    def test_c1_is_not_seen_when_the_session_reads_the_plugin_s_files_or_writes_the_role_word_itself(self):
        for knobs, fact in (({"STANDIN_PLUGIN_READS": "1"}, "a tool read the installed plugin's files, so its words "
                                                             "need not have come from loading them"),
                            ({"STANDIN_ROLE_TOP": "1"}, "the installed plugin's role file did not load")):
            code, out, err = self.world.kit("run", "claude", "C1", **knobs)
            self.assertEqual((code, out), (1, f"C1 claude failed: {fact}\n"))
            self.assert_changes_undone("C1", err)

    def test_a_hook_line_counts_only_with_the_command_in_its_command_field_and_a_matching_matcher(self):
        for knobs in ({"STANDIN_HOOK_PAYLOAD": "description"}, {"STANDIN_MATCHER": "Edit"}):
            code, out, err = self.world.kit("run", "claude", "C1", **knobs)
            self.assertEqual((code, out), (1, "C1 claude failed: the installed plugin's hook did not load\n"))
            self.assert_changes_undone("C1", err)
            code, out, err = self.world.kit("run", "cursor", "R4", **knobs)
            self.assertEqual((code, out), (0, "R4 cursor recorded: skill file in the output once, skill ran, hook "
                                              "fired not at all\n"))
            self.assert_changes_undone("R4", err)

    def test_c2_fails_before_launch_when_the_codeword_is_in_another_file_of_the_folder(self):
        sys.path.insert(0, str(KIT.parent))
        self.addCleanup(sys.path.remove, str(KIT.parent))
        kit = importlib.import_module("probe_kit")
        work = self.world.tmp / "work"
        (work / ".claude" / "skills" / "probe-standin").mkdir(parents=True)
        (work / ".claude" / "skills" / "probe-standin" / "SKILL.md").write_text("Write the word probe-1234abcd\n")
        kit.setup_skilled_role("claude", work, "probe-1234abcd")  # the skill file alone holds it
        shutil.rmtree(work / ".claude" / "agents")
        (work / "notes.txt").write_text("probe-1234abcd\n")
        with self.assertRaisesRegex(kit.SetupFailed, "^the codeword is in a file of the folder other than the skill "
                                                     "file$"):
            kit.setup_skilled_role("claude", work, "probe-1234abcd")

if __name__ == "__main__":
    unittest.main()
