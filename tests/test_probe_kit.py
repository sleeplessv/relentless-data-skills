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

import argparse
import contextlib
import dataclasses
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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
            "C1": "C1  claude  A plugin from a marketplace loads its skill, agents/ and hooks/hooks.json (not built)",
            "K6": "K6  cortex  The command line loads an installed skill from its description",
            "D3": "D3  codex  Two agent starts in one model step",
            "R5": "R5  cursor  A definition file in ~/.cursor/agents/ loads",
            "R1": "R1  cursor  The IDE chat (not probed, closed by reading 6) (not built)",
            "A7": "A7  antigravity  The model starts a stand-in skill described as typed only",
        }
        for entry, line in expected.items():
            self.assertEqual(lines[ids.index(entry)], line)
        self.assertEqual(sum("(not built)" not in line for line in lines), 25)


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
                                          "X2 codex failed: uv is not on PATH\n"
                                          # TestLimitEntries has the stand-in that follows these briefs
                                          "D3 codex failed: 0 of the 2 agents asked for in one message ran\n"
                                          "D4 codex failed: no agent of the reader role ran\n"
                                          "D5 codex failed: no agent of the reader role ran\n"))
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
                                          "X2 claude failed: uv is not on PATH\n"))
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
            ("codex", "D1"): "probe_kit: D1 is not built yet\n",
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
                              r"X2 claude recorded: uv run adds -?\d+ ms a call \(median of 5: \d+ ms, \d+ ms without\)\n$")
        self.assert_private(out, err)

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


# K1 to K5, D3 to D5, R2, R5 and A2 to A4 (#385). A third stand-in harness, installed as all five harness
# commands, follows the prompt and each brief as a model would. It reads the roles from its own definition
# folder, and Cursor's also from ~/.cursor/agents/. Each `Read <path> and follow it.` starts an agent of the
# role named before it; the starts between two waits run at once, in threads. An agent remembers the word its
# brief gives it to keep, writes the words its brief asks for, lists its agent tools, deletes its brief when
# asked, runs its shell commands, and starts the agents its brief names. On Cortex Code an agent below the depth
# limit (maxSubagentDepth from the variable, default 1) has task, agent, agent_output and kill_agent, and one at
# the limit has none and starts nothing; elsewhere there is no limit. Cortex Code's output shows each task call
# with its parent and its result, which gives the agentId or the depth error, and each kill_agent and
# agent_output call; Codex's shows each collab_tool_call item started and completed, with its thread. The kill
# lands while the agent's sleep runs. A resume or follow-up first waits for the agents before it. On
# Antigravity the session's invoke_subagent calls and the agents' run_command and write_file calls go to the
# registered hook, with the caller's model, and run only on an allow; the agents' other writes and the session's
# shell commands do not. A write_file call is refused to a role whose tools list lacks it. Knobs:
# STANDIN_AGENT_OFF starts no agent; STANDIN_DEPTH sets the depth limit; STANDIN_TOOLS_KEPT leaves an agent at
# the limit its tools, so its call is refused; STANDIN_SKIP_NESTED makes an agent start none; STANDIN_CAP lets
# that many agents of one prompt or brief run at once, the rest queued, or refused with STANDIN_CAP_REFUSE;
# STANDIN_STEP_APART lets each start end before the next; STANDIN_NO_KILL lets the sleep finish, with no
# kill_agent call; STANDIN_HIDE_KILL leaves the kill out of the output; STANDIN_KILL_OTHER names another agent
# in it; STANDIN_KILL_FAILS gives it an error; STANDIN_NO_CLOSE leaves close_agent out; STANDIN_CLOSE_OTHER
# names another thread in it; STANDIN_CLOSE_FAILS marks it failed; STANDIN_RESUME_FRESH resumes without the
# kept word; STANDIN_RESUME_FROM_DISK takes the first marker's word instead; STANDIN_RESUME_OTHER resumes
# another agent; STANDIN_RESUME_FAIL leaves a resume unanswered; STANDIN_OUTSIDE_DENIED refuses the write
# outside the folder; STANDIN_NO_USER_AGENTS ignores ~/.cursor/agents/; STANDIN_TOOLS_IGNORED lets a withheld
# tool run; STANDIN_NO_TRY makes no write_file call but reports it refused; STANDIN_OTHER_TOOL calls view_file
# on the marker instead; STANDIN_SHELL_WRITE writes through run_command instead; STANDIN_WRITE_ERROR lets the
# write_file call fail another way; STANDIN_TIER_WINS=file lets the file's tier win over the call's;
# STANDIN_SAME_TIERS gives every tier one model; STANDIN_NO_TIER drops the call's tier; STANDIN_FOREGROUND
# starts every agent in the foreground, or with =inner every agent an agent starts; STANDIN_NO_MODEL leaves the
# agents' models out of the output; STANDIN_DECOY puts an unrelated call with a model first; STANDIN_SLEEP waits
# before it acts.
LIMIT_HARNESS = r'''#!{python}
import json, os, re, signal, subprocess, sys, threading, time, tomllib
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
prompt = args[args.index("-p") + 1] if name in ("cortex", "agy") else args[-1]
cwd, knob = Path.cwd(), os.environ.get
folders = [cwd / {"claude": ".claude/agents", "cortex": ".cortex/agents", "codex": ".codex/agents",
                  "cursor-agent": ".cursor/agents", "agy": ".agents/agents"}[name]]
user_agents = Path(os.environ["HOME"]) / ".cursor" / "agents"
if name == "cursor-agent" and not knob("STANDIN_NO_USER_AGENTS"):
    folders.append(user_agents)
roles = {}
for folder in folders:
    for path in sorted(folder.glob("*.toml" if name == "codex" else "*.md")):
        text = path.read_text()
        if name == "codex":
            role = tomllib.loads(text)
            found, head, body = role["name"], "", role["developer_instructions"]
        else:
            head, body = text.split("---\n", 2)[1:]
            found = re.search(r"^name: (\S+)$", head, re.M).group(1)
        tools, tier = re.search(r"^tools: \[(.*)\]$", head, re.M), re.search(r"^model: (\S+)$", head, re.M)
        roles[found] = {"word": re.search(r"Your role word is (\S+)\.", body).group(1),
                        "tools": tools.group(1).split(", ") if tools else None, "tier": tier and tier.group(1)}
features = json.loads(knob("CORTEX_CODE_EXPERIMENTAL_FEATURES") or "{}")
limit = int(knob("STANDIN_DEPTH") or (features.get("maxSubagentDepth", 1) if name == "cortex" else 9))
hooks = cwd / ".agents" / "hooks.json"
hook = next(iter(json.loads(hooks.read_text()).values()))["PreToolUse"][0]["hooks"][0]["command"] \
    if hooks.is_file() else None
user_files = sorted(p.name for p in user_agents.glob("*")) if user_agents.is_dir() else []
lock, events, records, sent, counter = threading.Lock(), [], [], [], [0]
memory, markers, ids, ready, sleepers = {}, {}, {}, {}, {}
WRITES = re.compile(r"[Ww]rite the word (?P<word>\S+), a space(?P<recall>, the word your first brief asked you to "
                    r"remember, a space)? and your role word to the file (?P<file>\S+) in (?P<outside>your worktree, )?"
                    r"the folder (?P<folder>\S+?)(?P<tool> with the write_file tool, not with run_command)?\.(?:\s|$)")
LISTS = re.compile(r"write the word (\S+), a space and the names of those of these tools you have: task, agent, "
                   r"agent_output, kill_agent, or the word none, to the file (\S+) in the folder (\S+?)\.(?:\s|$)")
TOKENS = re.compile(r"(?:subagent_type|agent_type|of the role) (?P<role>probe-[a-z-]+)|run_in_background "
                    r"(?P<bg>true|false)|Model (?P<tier>\w+)|(?P<resume>resume set to that agentId|with "
                    r"followup_task)|call (?P<stop>kill_agent|close_agent) |(?P<wait>call agent_output with wait "
                    r"true)|Read (?P<line>\S+) and follow it\.")
AGENT_TOOLS = "task agent agent_output kill_agent"
time.sleep(float(knob("STANDIN_SLEEP", "0")))


def emit(**event):
    with lock:
        events.append({key: value for key, value in event.items() if value is not None})


def next_id(kind):
    with lock:
        counter[0] += 1
        return f"{kind}_{counter[0]}"


def tool(model, call, given, run):
    """Antigravity sends each tool call to the hook first and runs it only on an allow."""
    if hook:
        data = {"conversationId": "{session}", "cwd": str(cwd), "modelName": model,
                "toolCall": {"name": call, "args": given}}
        sent.append(data)
        done = subprocess.run(hook, shell=True, cwd=cwd / ".agents", input=json.dumps(data), capture_output=True,
                              text=True)
        if json.loads(done.stdout or "{}").get("decision") != "allow":
            return
    if run:
        run()


def result(parent, call, text, error=False):
    emit(type="user", parent_tool_use_id=parent, message={"content": [
        {"type": "tool_result", "tool_use_id": call, "content": text, "is_error": error}]})


def agent(own, role_name, line, depth, parent, resume, background, call_tier, slots):
    record = {"role": role_name, "depth": depth, "background": background, "resume": resume is not None,
              "brief": Path(line).name, "ran": False}
    with lock:
        records.append(record)
    role = roles.get(role_name)
    try:
        if knob("STANDIN_AGENT_OFF") or role is None:
            return
        if not slots.acquire(blocking=not knob("STANDIN_CAP_REFUSE")):
            return
        try:
            run(own, role_name, role, line, depth, parent, resume, background, call_tier, record)
        finally:
            slots.release()
    finally:
        ready[own].set()


def run(own, role_name, role, line, depth, parent, resume, background, call_tier, record):
    target = ids[resume] if resume else f"{'thread' if name == 'codex' else 'agent'}-{own}"
    named = ("thread-other" if name == "codex" else "agent-other") if resume and knob("STANDIN_RESUME_OTHER") \
        else target
    ids[own] = target
    if name == "cortex":
        given = {"subagent_type": role_name, "run_in_background": background, "prompt": f"Read {line} and follow it."}
        emit(type="assistant", parent_tool_use_id=parent, message={"content": [
            {"type": "tool_use", "id": own, "name": "task", "input": {**given, "resume": named} if resume else given}]})
        if depth > limit:
            result(parent, own, "Maximum subagent nesting depth of 1 reached.", True)
            return
        result(parent, own, f"Agent started. agentId: {named}")
    elif name == "codex":
        emit(type="item.completed", item={"id": f"item_{own}", "type": "collab_tool_call",
                                          "tool": "followup_task" if resume else "spawn_agent",
                                          "receiver_thread_ids": [named], "status": "completed"})
    if depth > limit or (resume and (knob("STANDIN_RESUME_FAIL") or knob("STANDIN_RESUME_OTHER"))):
        return
    if knob("STANDIN_RESUME_FRESH"):
        first = None
    elif knob("STANDIN_RESUME_FROM_DISK"):
        first = markers[resume].read_text().split()[0] if resume in markers else None
    else:
        first = memory.get(resume)
    record["ran"] = True
    if name == "agy":
        wins = role["tier"] if knob("STANDIN_TIER_WINS") == "file" and role["tier"] else call_tier or role["tier"]
        model = "standin-same-model" if knob("STANDIN_SAME_TIERS") else f"standin-{wins or 'default'}-model"
    else:
        model = f"standin-{'resumed' if resume else 'agent'}-model-{name}"
    if name == "cortex" and not knob("STANDIN_NO_MODEL"):
        emit(type="assistant", parent_tool_use_id=own, message={"model": model})
    brief = Path(line)
    text, word = brief.read_text(), role["word"]
    keep = re.search(r"Remember the word (\S+) for later", text)
    if keep:
        memory[own] = keep[1]
    control = re.search(r"Run the shell command `([^`]+)` in the folder (\S+), with your role word as a third "
                        r"argument\.", text)
    if control:
        command = f"{control[1]} {word}"
        tool(model, "run_command", {"CommandLine": command, "Cwd": control[2]},
             lambda: subprocess.run(command, shell=True, cwd=control[2], capture_output=True))
    ended = None
    for task in WRITES.finditer(text):
        words = [task["word"], *([first] if task["recall"] and first else []), word]
        target, body = Path(task["folder"]) / task["file"], " ".join(words) + "\n"
        markers.setdefault(own, target)
        if task["outside"] and knob("STANDIN_OUTSIDE_DENIED"):
            continue
        if not task["tool"]:
            target.write_text(body)
        elif knob("STANDIN_SHELL_WRITE"):
            tool(model, "run_command", {"CommandLine": f"echo {body.strip()} > {target}"},
                 lambda: target.write_text(body))
            ended = "wrote"
        elif knob("STANDIN_OTHER_TOOL"):
            tool(model, "view_file", {"AbsolutePath": str(target), "Note": body.strip()}, None)
            ended = "refused"
        elif knob("STANDIN_NO_TRY"):
            ended = "refused"
        else:
            withheld = role["tools"] is not None and "write_file" not in role["tools"]
            refused = withheld and not knob("STANDIN_TOOLS_IGNORED")
            failing = knob("STANDIN_WRITE_ERROR")
            tool(model, "write_file", {"TargetFile": str(target), "CodeContent": body},
                 None if refused or failing else lambda: target.write_text(body))
            ended = "failed" if failing else "refused" if refused else "wrote"
    report = re.search(r"run the shell command `([^`]+)` in the folder (\S+), with your role word and then one word "
                       r"for how the write_file call ended", text)
    if report and ended:
        command = f"{report[1]} {word} {ended}"
        tool(model, "run_command", {"CommandLine": command, "Cwd": report[2]},
             lambda: subprocess.run(command, shell=True, cwd=report[2], capture_output=True))
    has = depth < limit or knob("STANDIN_TOOLS_KEPT") or name != "cortex"
    for task in LISTS.finditer(text):
        kept = AGENT_TOOLS if has and (role["tools"] is None or "task" in role["tools"]) else "none"
        (Path(task[3]) / task[2]).write_text(f"{task[1]} {kept}\n")
    if "Then delete this brief file." in text:
        brief.unlink()
    shared = re.search(r"run this shell command in the folder (\S+): `([^`]+)`", text)
    if shared:
        subprocess.run(shared[2].replace("sleep 1", "sleep 0.05"), shell=True, cwd=shared[1], capture_output=True)
    slow = re.search(r"run the bash command `([^`]+)`", text)
    if slow:  # a live sleep: the kill ends it, or STANDIN_NO_KILL lets a short one finish
        sleeper = sleepers[own] = subprocess.Popen(
            slow[1].replace("sleep 300", "sleep 0" if knob("STANDIN_NO_KILL") else "sleep 5"), shell=True,
            start_new_session=True)
        ready[own].set()
        sleeper.wait()
    follow(text, depth, own, model, has)


def follow(text, depth, parent, model, able=True):
    """Start the agents the text asks for, the starts between two waits at once; an agent with no tools starts none."""
    role = background = tier = last = None
    resume, threads, pending = False, [], []
    slots = threading.BoundedSemaphore(int(knob("STANDIN_CAP", "8")))
    if depth and knob("STANDIN_SKIP_NESTED"):
        return

    def begin(args):
        own, resumed = args[0], args[5]
        if name == "codex":
            emit(type="item.started", item={"id": f"item_{own}", "type": "collab_tool_call",
                                            "tool": "followup_task" if resumed else "spawn_agent",
                                            "receiver_thread_ids": [], "status": "in_progress"})
        thread = threading.Thread(target=agent, args=args)
        threads.append(thread)
        return thread

    def flush():
        if knob("STANDIN_STEP_APART"):
            for args in pending:
                thread = begin(args)
                thread.start()
                thread.join()
        else:
            for thread in [begin(args) for args in pending]:
                thread.start()
        pending.clear()

    def settle():
        flush()
        for thread in threads:
            thread.join()

    for token in TOKENS.finditer(text):
        if token["role"]:
            role = token["role"]
        elif token["bg"]:
            forced = knob("STANDIN_FOREGROUND") and (depth or knob("STANDIN_FOREGROUND") != "inner")
            background = token["bg"] == "true" and not forced
        elif token["tier"]:
            tier = None if knob("STANDIN_NO_TIER") else token["tier"]
        elif token["wait"]:
            settle()
            if name == "cortex":
                emit(type="assistant", parent_tool_use_id=parent, message={"content": [
                    {"type": "tool_use", "id": next_id("toolu_wait"), "name": "agent_output",
                     "input": {"agent_id": ids.get(last), "wait": True}}]})
        elif token["stop"] == "kill_agent":
            flush()
            ready[last].wait(10)
            if not (knob("STANDIN_NO_KILL") or knob("STANDIN_HIDE_KILL")):
                kill = next_id("toolu_kill")
                emit(type="assistant", parent_tool_use_id=parent, message={"content": [
                    {"type": "tool_use", "id": kill, "name": "kill_agent",
                     "input": {"agent_id": "agent-other" if knob("STANDIN_KILL_OTHER") else ids.get(last)}}]})
                result(parent, kill, "Error: no such agent" if knob("STANDIN_KILL_FAILS") else "Agent killed.",
                       bool(knob("STANDIN_KILL_FAILS")))
            if last in sleepers and not knob("STANDIN_NO_KILL"):
                os.killpg(sleepers[last].pid, signal.SIGTERM)
            settle()
        elif token["stop"] == "close_agent":
            settle()
            if not knob("STANDIN_NO_CLOSE"):
                emit(type="item.completed", item={
                    "id": next_id("item_close"), "type": "collab_tool_call", "tool": "close_agent",
                    "receiver_thread_ids": ["thread-other" if knob("STANDIN_CLOSE_OTHER") else ids.get(last)],
                    "status": "failed" if knob("STANDIN_CLOSE_FAILS") else "completed"})
        elif token["resume"]:
            settle()
            resume = True
        elif not able:
            with lock:
                records.append({"role": role, "depth": depth + 1, "background": background, "resume": resume,
                                "brief": Path(token["line"]).name, "ran": False})
        else:
            own = next_id("toolu")
            ready[own] = threading.Event()
            if name == "agy":
                tool(model, "invoke_subagent", {"Prompt": f"Read {token['line']} and follow it.",
                                                **({"Model": tier} if tier else {})}, None)
            pending.append((own, role, token["line"], depth + 1, parent, last if resume else None, background, tier,
                            slots))
            last, resume = own, False
    settle()


if knob("STANDIN_DECOY"):  # an unrelated call first, whose own event names a model
    emit(type="assistant", message={"content": [{"type": "tool_use", "id": "toolu_decoy", "name": "read",
                                                 "input": {"path": "notes.md"}}]})
    emit(type="assistant", parent_tool_use_id="toolu_decoy", message={"model": "standin-decoy-model"})
follow(prompt, 0, None, "standin-session-model")
if name == "cortex":
    print(json.dumps({"type": "system", "subtype": "init", "session_id": "{session}", "cwd": str(cwd)}))
elif name == "codex":
    print(json.dumps({"type": "thread.started", "thread_id": "{session}"}))
for event in events:
    print(json.dumps(event))
print(json.dumps({"type": "turn.completed"} if name == "codex" else
                 {"type": "result", "session_id": "{session}", "result": "done"}))
with open(knob("STANDIN_STARTS"), "a") as starts:
    starts.write(json.dumps({
        "name": name, "args": args, "prompt": prompt.replace(str(cwd), "<work>"), "limit": limit,
        "features": knob("CORTEX_CODE_EXPERIMENTAL_FEATURES"), "user_files": user_files,
        "definitions": {str(p.relative_to(cwd)): p.read_text() for p in sorted(cwd.glob(".*/agents/*"))},
        "agents": sorted(records, key=lambda r: (r["brief"], r["resume"])), "sent": sent}) + "\n")
'''


class TestLimitEntries(HookTest):
    """Each harness's own agent limits against the stand-in that follows briefs, as all five commands."""

    def setUp(self) -> None:
        super().setUp()
        script = self.world.bin / "limit-harness"
        script.write_text(LIMIT_HARNESS.replace("{python}", sys.executable).replace("{session}", SESSION))
        script.chmod(0o755)
        self.world.install("limit-harness")

    def run_entry(self, harness: str, entry: str, **knobs: str) -> str:
        """The entry's output line; the exit code follows the verdict, and nothing printed is private."""
        code, out, err = self.world.kit("run", harness, entry, **knobs)
        self.assertEqual(code, 1 if " failed: " in out else 0, out)
        self.assert_private(out, err)
        self.assert_probe_folder_gone()
        return out

    def agents(self) -> list[tuple]:
        """The last run's agents: role, depth, brief, resumed, and whether it ran."""
        return [(a["role"], a["depth"], a["brief"], a["resume"], a["ran"])
                for a in self.world.harness_starts()[-1]["agents"]]

    def load_kit(self):
        spec = importlib.util.spec_from_file_location("probe_kit_under_test", KIT)
        kit = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = kit  # dataclass looks its module up there before Python 3.14
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(kit)
        return kit

    def run_in_process(self, kit, err: io.StringIO, *patches, **knobs: str) -> object:
        """R5's run_probe in this process against the world, with the patches given: its result or its exception."""
        saved = self.world.root / "saved"
        saved.mkdir(exist_ok=True)
        env = {"PATH": f"{self.world.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.world.home),
               "STANDIN_HC_DIR": str(self.world.hc_dir), "STANDIN_STARTS": str(self.world.starts),
               "STANDIN_UV_CALLS": str(self.world.uv_calls), **knobs}
        with contextlib.ExitStack() as stack:
            for patch in (mock.patch.dict(os.environ, env), mock.patch.object(tempfile, "tempdir", str(self.world.tmp)),
                          contextlib.redirect_stderr(err), *patches):
                stack.enter_context(patch)
            try:
                return kit.run_probe("cursor", "R5", argparse.Namespace(connection=None, time_limit=30.0, poll=0.05),
                                     saved)
            except BaseException as error:  # noqa: BLE001 - the test reads which one
                return error

    def test_k1_is_seen_when_neither_a_foreground_nor_a_background_agent_can_start_an_agent(self):
        self.assertEqual(self.run_entry("cortex", "K1"),
                         "K1 cortex seen: neither a foreground nor a background agent could start an agent: the "
                         "foreground author had none of task, agent; the background author had none of task, agent\n")
        start = self.world.harness_starts()[-1]
        self.assertEqual((start["features"], start["limit"]), ("{}", 1))
        brief = "<work>/.git/deliver/branches/probe-agent/brief-k1"
        self.assertEqual(start["prompt"], f"Call the task tool once with subagent_type probe-author, "
                                          f"run_in_background false and the prompt: Read {brief}-fg.md and follow "
                                          f"it. Then call the task tool once with subagent_type probe-author, "
                                          f"run_in_background true and the prompt: Read {brief}-bg.md and follow "
                                          f"it. Then call agent_output with wait true for it. Do not open those "
                                          f"files yourself, and do nothing else.")
        self.assertEqual(sorted(start["definitions"]), [".cortex/agents/probe-author.md",
                                                       ".cortex/agents/probe-reviewer.md"])
        self.assertNotIn("tools:", start["definitions"][".cortex/agents/probe-author.md"])
        expected = [("probe-author", 1, "brief-k1-bg.md", False, True),
                    ("probe-reviewer", 2, "brief-k1-bgleaf.md", False, False),
                    ("probe-author", 1, "brief-k1-fg.md", False, True),
                    ("probe-reviewer", 2, "brief-k1-fgleaf.md", False, False)]
        self.assertEqual(self.agents(), expected)
        self.assertEqual(self.run_entry("cortex", "K1", STANDIN_TOOLS_KEPT="1"),
                         "K1 cortex seen: neither a foreground nor a background agent could start an agent: the "
                         "foreground author's call to start an agent was refused; the background author's call to "
                         "start an agent was refused\n")
        self.assertEqual(self.agents(), expected)

    def test_k1_fails_when_an_agent_starts_one_no_author_ran_or_an_author_with_the_tools_did_not_try(self):
        self.assertEqual(self.run_entry("cortex", "K1", STANDIN_DEPTH="2"),
                         "K1 cortex failed: a foreground agent started an agent of the reviewer role\n")
        self.assertEqual(self.run_entry("cortex", "K1", STANDIN_AGENT_OFF="1"),
                         "K1 cortex failed: no foreground agent of the author role ran\n")
        skipped = ("K1 cortex failed: the foreground author had task, agent, agent_output, kill_agent, but the output "
                   "shows no call of its to start an agent\n")
        self.assertEqual(self.run_entry("cortex", "K1", STANDIN_DEPTH="2", STANDIN_SKIP_NESTED="1"), skipped)
        self.assertEqual(self.run_entry("cortex", "K1", STANDIN_TOOLS_KEPT="1", STANDIN_SKIP_NESTED="1"), skipped)

    def test_k2_and_k3_see_both_leaves_under_the_author_with_their_modes_and_no_agent_tools(self):
        self.assertEqual(self.run_entry("cortex", "K2"),
                         "K2 cortex seen: both agents of the leaf role ran at once under the foreground author, two "
                         "layers down, and neither had task, agent, agent_output or kill_agent\n")
        start = self.world.harness_starts()[-1]
        self.assertEqual((start["features"], start["limit"]), ('{"maxSubagentDepth": 2}', 2))
        self.assertEqual(self.agents(), [("probe-author", 1, "brief-k2-author.md", False, True),
                                         ("probe-leaf", 2, "brief-k2-first.md", False, True),
                                         ("probe-leaf", 2, "brief-k2-second.md", False, True)])
        self.assertNotIn("tools:", start["definitions"][".cortex/agents/probe-leaf.md"])
        self.assertEqual(self.run_entry("cortex", "K3", STANDIN_CAP="1"),
                         "K3 cortex seen: both foreground agents of the leaf role ran under the background author, "
                         "one after the other; with background inner calls, 2 of 2 agents of the leaf role ran\n")
        self.assertEqual([(a["brief"], a["background"]) for a in self.world.harness_starts()[-1]["agents"]],
                         [("brief-k3-author.md", True), ("brief-k3-first.md", False), ("brief-k3-second.md", False),
                          ("brief-k3-variant.md", True), ("brief-k3-vfirst.md", True),
                          ("brief-k3-vsecond.md", True)])
        self.assertEqual(self.run_entry("cortex", "K3"),
                         "K3 cortex seen: both foreground agents of the leaf role ran under the background author, "
                         "at once; with background inner calls, 2 of 2 agents of the leaf role ran\n")

    def test_k2_and_k3_fail_without_both_leaves_the_author_the_modes_at_once_or_the_depth(self):
        self.assertEqual(self.run_entry("cortex", "K2", STANDIN_DEPTH="1"),
                         "K2 cortex failed: 0 of the 2 agents of the leaf role ran under the author\n")
        self.assertEqual(self.run_entry("cortex", "K3", STANDIN_AGENT_OFF="1"),
                         "K3 cortex failed: no agent of the author role ran\n")
        self.assertEqual(self.run_entry("cortex", "K2", STANDIN_CAP="1"),
                         "K2 cortex failed: both agents of the leaf role ran under the author, but one after the "
                         "other\n")
        self.assertEqual(self.run_entry("cortex", "K2", STANDIN_DEPTH="3"),
                         "K2 cortex failed: an agent of the leaf role, two layers down, has task, agent, agent_output, "
                         "kill_agent, so the limit is deeper than 2\n")
        self.assertEqual(self.run_entry("cortex", "K3", STANDIN_FOREGROUND="1"),
                         "K3 cortex failed: the output does not show the session starting the author in the "
                         "background\n")
        self.assertEqual(self.run_entry("cortex", "K3", STANDIN_FOREGROUND="inner"),
                         "K3 cortex failed: the output does not show the author for background inner calls starting "
                         "both its agents in the background\n")

    def test_k4_is_seen_when_the_killed_agent_resumes_with_the_word_only_its_first_brief_gave(self):
        self.assertEqual(self.run_entry("cortex", "K4"),
                         "K4 cortex seen: the killed agent resumed with its earlier context\n")
        self.assertEqual(self.agents(), [("probe-reader", 1, "brief-k4-first.md", False, True),
                                         ("probe-reader", 1, "brief-k4-second.md", True, True)])
        self.assertIn("Step 2: wait until the file <work>/probe-k4-first.txt exists, then call kill_agent with "
                      "that agentId. Step 3: call the task tool again with resume set to that agentId",
                      self.world.harness_starts()[-1]["prompt"])

    def test_k4_fails_on_a_finished_sleep_a_missing_wrong_or_failed_kill_a_fresh_agent_or_no_answer(self):
        cases = {"STANDIN_NO_KILL": "the agent was not killed: its sleep finished",
                 "STANDIN_HIDE_KILL": "the output shows no kill_agent call",
                 "STANDIN_KILL_OTHER": "the kill_agent call names another agent",
                 "STANDIN_KILL_FAILS": "the kill_agent call did not succeed",
                 "STANDIN_RESUME_OTHER": "the output shows no task call that resumes that agent",
                 "STANDIN_RESUME_FRESH": "the agent that answered lacks its first brief's word, so it was not "
                                         "the same agent",
                 "STANDIN_RESUME_FROM_DISK": "the agent that answered lacks its first brief's word, so it was not "
                                             "the same agent",
                 "STANDIN_RESUME_FAIL": "no agent answered the call-back",
                 "STANDIN_AGENT_OFF": "no agent of the reader role ran"}
        for knob, fact in cases.items():
            self.assertEqual(self.run_entry("cortex", "K4", **{knob: "1"}), f"K4 cortex failed: {fact}\n")

    def test_k5_records_the_models_of_the_calls_that_started_and_resumed_the_agent(self):
        line = ("K5 cortex recorded: the resumed agent ran on standin-resumed-model-cortex, its first run on "
                "standin-agent-model-cortex, at assistant event .message.model\n")
        self.assertEqual(self.run_entry("cortex", "K5"), line)
        self.assertEqual(self.run_entry("cortex", "K5", STANDIN_DECOY="1"), line)

    def test_k5_fails_on_a_fresh_or_other_agent_or_no_model(self):
        cases = {"STANDIN_RESUME_FRESH": "the agent that answered lacks its first brief's word, so it was not the "
                                         "same agent",
                 "STANDIN_RESUME_FROM_DISK": "the agent that answered lacks its first brief's word, so it was not "
                                             "the same agent",
                 "STANDIN_RESUME_OTHER": "the output shows no task call that resumes that agent",
                 "STANDIN_NO_MODEL": "no assistant event tied to the call that resumed the agent names a model"}
        for knob, fact in cases.items():
            self.assertEqual(self.run_entry("cortex", "K5", **{knob: "1"}), f"K5 cortex failed: {fact}\n")

    def test_d3_is_seen_only_when_both_starts_were_under_way_at_once(self):
        self.assertEqual(self.run_entry("codex", "D3"), "D3 codex seen: both agents ran, and both spawn_agent calls "
                                                        "started before either ended, so one model step made them\n")
        self.assertEqual(self.agents(), [("probe-reader", 1, "brief-d3-one.md", False, True),
                                         ("probe-reader", 1, "brief-d3-two.md", False, True)])
        self.assertEqual(self.run_entry("codex", "D3", STANDIN_AGENT_OFF="1"),
                         "D3 codex failed: 0 of the 2 agents asked for in one message ran\n")
        self.assertEqual(self.run_entry("codex", "D3", STANDIN_STEP_APART="1"),
                         "D3 codex failed: both agents ran, but the output does not show both starts in one model "
                         "step, so the step was not measured\n")

    def test_d4_sees_the_closed_agent_answer_and_fails_without_its_own_successful_close_or_its_kept_word(self):
        self.assertEqual(self.run_entry("codex", "D4"),
                         "D4 codex seen: the closed agent answered with its earlier context\n")
        cases = {"STANDIN_NO_CLOSE": "the output shows no close_agent call, so the agent was not unloaded",
                 "STANDIN_CLOSE_OTHER": "the close_agent call names another agent",
                 "STANDIN_CLOSE_FAILS": "the close_agent call did not succeed",
                 "STANDIN_RESUME_FRESH": "the agent that answered lacks its first brief's word, so it was not the "
                                         "same agent",
                 "STANDIN_RESUME_FROM_DISK": "the agent that answered lacks its first brief's word, so it was not "
                                             "the same agent"}
        for knob, fact in cases.items():
            self.assertEqual(self.run_entry("codex", "D4", **{knob: "1"}), f"D4 codex failed: {fact}\n")

    def test_d5_runs_codex_without_the_temporary_folders_and_sees_the_write_outside(self):
        self.assertEqual(self.run_entry("codex", "D5"), "D5 codex seen: the agent wrote in its worktree outside the "
                                                        "session's writable directories\n")
        args = self.world.harness_starts()[-1]["args"]
        self.assertEqual(args[:-1], ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                                     "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
                                     "-c", "sandbox_workspace_write.exclude_slash_tmp=true"])
        self.assertEqual(self.run_entry("codex", "D5", STANDIN_OUTSIDE_DENIED="1"),
                         "D5 codex failed: the agent ran, but its file in the worktree outside the writable "
                         "directories is missing\n")
        self.assertEqual(self.run_entry("codex", "D5", STANDIN_AGENT_OFF="1"),
                         "D5 codex failed: no agent of the reader role ran\n")

    def test_the_cap_probes_ask_for_4_agents_and_record_the_overlap_naming_no_cap_below_4(self):
        fewer = "all 4 agents ran, at most {} at once; nothing shows a limit or a queue, so no cap is named"
        cases = [("cursor", "R2", {}, "R2 cursor recorded: no cap up to 4: all 4 agents ran at once\n"),
                 ("cursor", "R2", {"STANDIN_CAP": "2"}, f"R2 cursor recorded: {fewer.format(2)}\n"),
                 ("cursor", "R2", {"STANDIN_STEP_APART": "1"}, f"R2 cursor recorded: {fewer.format(1)}\n"),
                 ("antigravity", "A4", {}, "A4 antigravity recorded: no cap up to 4: all 4 agents ran at once\n"),
                 ("antigravity", "A4", {"STANDIN_CAP": "3"}, f"A4 antigravity recorded: {fewer.format(3)}\n")]
        for harness, entry, knobs, line in cases:
            self.assertEqual(self.run_entry(harness, entry, **knobs), line)
            self.assertEqual(self.agents(), [("probe-reader", 1, f"brief-{entry.lower()}-agent{n}.md", False, True)
                                             for n in range(1, 5)])
        self.assertTrue(self.world.harness_starts()[-1]["prompt"].startswith(
            "Start four agents of the role probe-reader at once, with four invoke_subagent calls in one turn, each "
            "in the background. Give each its own line, word for word, as its whole prompt. First: Read "))

    def test_the_cap_probes_fail_when_a_cap_refuses_rather_than_queues(self):
        for harness, entry in (("cursor", "R2"), ("antigravity", "A4")):
            self.assertEqual(self.run_entry(harness, entry, STANDIN_CAP="2", STANDIN_CAP_REFUSE="1"),
                             f"{entry} {harness} failed: 2 of the 4 agents ran, so a cap is not told apart from "
                             f"agents never started\n")
            self.assertEqual(len(self.agents()), 4)  # asked for 4, never more

    def test_r5_names_its_user_level_file_loads_the_role_and_removes_the_file(self):
        code, out, err = self.world.kit("run", "cursor", "R5")
        self.assertEqual((code, out), (0, "R5 cursor seen: an agent of the role defined only in ~/.cursor/agents/ "
                                          "wrote the marker its brief names\n"))
        start = self.world.harness_starts()[-1]
        (name,) = start["user_files"]  # the file was there while the harness ran
        self.assertRegex(name, r"^probe-r5-[0-9a-f]{8}\.md$")
        self.assertEqual(start["definitions"], {})  # no project definition folder
        self.assertEqual(err.splitlines()[:2], [f"probe_kit: R5 writes ~/.cursor/agents/{name} and removes it when "
                                                f"the probe ends", f"probe_kit: R5 removed ~/.cursor/agents/{name}"])
        self.assert_private(out, err)
        self.assert_home_empty()

    def test_r5_names_each_file_before_it_exists_and_leaves_one_it_did_not_make(self):
        kit, err, owner = self.load_kit(), io.StringIO(), "---\nname: owner-role\n---\n\nYour role word is owner-1.\n"
        agents, real_open, made = self.world.home / ".cursor" / "agents", os.open, []

        def watched(path, flags, *rest, **options):
            if Path(path).parent == agents:  # the stream as the file is made
                made.append((Path(path).name, Path(path).exists(), err.getvalue()))
                if len(made) == 1:  # the owner takes this very name first
                    Path(path).write_text(owner)
            return real_open(path, flags, *rest, **options)
        got = self.run_in_process(kit, err, mock.patch.object(os, "open", watched))
        self.assertEqual(got, ("seen", "an agent of the role defined only in ~/.cursor/agents/ wrote the marker its "
                                       "brief names"))
        (taken, _, _), (name, _, _) = made
        writes = "probe_kit: R5 writes ~/.cursor/agents/{} and removes it when the probe ends"
        self.assertEqual([(existed, stream.splitlines()[-1]) for _, existed, stream in made],
                         [(False, writes.format(taken)), (False, writes.format(name))])
        self.assertEqual(err.getvalue().splitlines(), [
            writes.format(taken), f"probe_kit: R5 leaves ~/.cursor/agents/{taken}, which was there already, and "
                                  f"picks another name", writes.format(name),
            f"probe_kit: R5 removed ~/.cursor/agents/{name}"])
        self.assertEqual(sorted(self.world.home.rglob("*")), [agents.parent, agents, agents / taken])
        self.assertEqual((agents / taken).read_text(), owner)
        self.assert_private(err.getvalue())

    def test_r5_removes_its_file_after_a_failed_probe_and_keeps_folders_it_did_not_make(self):
        self.assertEqual(self.run_entry("cursor", "R5", STANDIN_NO_USER_AGENTS="1"),
                         "R5 cursor failed: no marker the brief names\n")
        self.assert_home_empty()
        own = self.world.home / ".cursor" / "agents" / "owner-role.md"
        own.parent.mkdir(parents=True)
        owner = "---\nname: owner-role\ndescription: The owner's.\n---\n\nYour role word is owner-1.\n"
        own.write_text(owner)
        self.assertEqual(self.run_entry("cursor", "R5", STANDIN_AGENT_OFF="1"),
                         "R5 cursor failed: no marker the brief names\n")
        self.assertEqual(sorted(self.world.home.rglob("*")), [own.parent.parent, own.parent, own])
        self.assertEqual(own.read_text(), owner)

    def test_r5_removes_its_file_when_the_kit_is_interrupted(self):
        env = {"PATH": f"{self.world.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.world.home),
               "DELIVER_STATE_DIR": str(self.world.state), "TMPDIR": str(self.world.tmp),
               "STANDIN_HC_DIR": str(self.world.hc_dir), "STANDIN_STARTS": str(self.world.starts),
               "STANDIN_UV_CALLS": str(self.world.uv_calls), "STANDIN_SLEEP": "30", "LANG": "C.UTF-8"}
        err_file = self.world.root / "kit.err"
        with open(err_file, "w") as stderr:
            kit = subprocess.Popen([sys.executable, str(KIT), "run", "cursor", "R5", "--poll", "0.05"], env=env,
                                   stdout=subprocess.PIPE, stderr=stderr, text=True)
            deadline = time.monotonic() + 30
            while not any(call[0] == "get" for call in self.world.hc_calls()):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)
            self.assertEqual(len(list((self.world.home / ".cursor" / "agents").iterdir())), 1)
            kit.send_signal(signal.SIGINT)
            out, _ = kit.communicate(timeout=30)
        err = err_file.read_text()
        self.assertEqual((kit.returncode, out), (130, ""))
        lines = err.splitlines()
        self.assertEqual([line.split(" ~/")[0] for line in lines],
                         ["probe_kit: R5 writes", "probe_kit: R5 removed", "probe_kit: interrupted"])
        self.assertEqual([c[0] for c in self.world.hc_calls()][-1], "kill")
        self.assert_private(err)
        self.assert_home_empty()

    def test_r5_removes_its_file_when_the_probe_raises(self):
        def broken(*args):
            raise RuntimeError("hc broke")
        kit, err = self.load_kit(), io.StringIO()
        got = self.run_in_process(kit, err, mock.patch.object(kit, "hc", broken))
        self.assertEqual((type(got), str(got)), (RuntimeError, "hc broke"))
        self.assertEqual([line.split(" ~/")[0] for line in err.getvalue().splitlines()],
                         ["probe_kit: R5 writes", "probe_kit: R5 removed"])
        self.assert_home_empty()
        self.assertEqual(list(self.world.tmp.iterdir()), [])

    def test_r5_removes_its_file_on_an_interrupt_after_set_up_or_when_ending_the_terminal_raises(self):
        kit = self.load_kit()

        def interrupt(harness):
            raise KeyboardInterrupt

        def broken(command, *args):
            if command == "run":
                return {"address": "w1:probe-r5"}
            raise RuntimeError(f"hc {command} broke")
        cases = [("interrupt", KeyboardInterrupt, "",
                  mock.patch.dict(kit.PROBES, R5=dataclasses.replace(kit.PROBES["R5"], prompt=interrupt))),
                 ("get and kill raise", RuntimeError, "hc kill broke", mock.patch.object(kit, "hc", broken))]
        for label, kind, message, patch in cases:
            with self.subTest(label):
                err = io.StringIO()
                got = self.run_in_process(kit, err, patch)
                self.assertEqual((type(got), str(got)), (kind, message))
                self.assertEqual([line.split(" ~/")[0] for line in err.getvalue().splitlines()],
                                 ["probe_kit: R5 writes", "probe_kit: R5 removed"])
                self.assert_home_empty()
                self.assertEqual(list(self.world.tmp.iterdir()), [])

    def test_a2_is_seen_when_the_agent_s_write_file_call_to_its_marker_was_refused(self):
        self.assertEqual(self.run_entry("antigravity", "A2"),
                         "A2 antigravity seen: the agent's write_file call to the marker was refused, as it "
                         "reported\n")
        start = self.world.harness_starts()[-1]
        self.assertIn("tools: [view_file, run_command]\n", start["definitions"][".agents/agents/probe-reviewer.md"])
        self.assertEqual([s["toolCall"]["name"] for s in start["sent"]],
                         ["invoke_subagent", "run_command", "write_file", "run_command"])

    def test_a2_fails_on_a_written_file_another_tool_no_call_another_error_or_no_agent(self):
        no_call = "the agent made no write_file call to the marker, so the withheld tool's absence is not shown"
        cases = {"STANDIN_TOOLS_IGNORED": "the withheld tool wrote the file",
                 "STANDIN_SHELL_WRITE": "the agent wrote the file through run_command, not the withheld tool",
                 "STANDIN_NO_TRY": no_call,
                 "STANDIN_OTHER_TOOL": no_call,
                 "STANDIN_WRITE_ERROR": "the agent's write_file call failed another way, as it reported, so no "
                                        "refusal is shown",
                 "STANDIN_AGENT_OFF": "no agent of the reviewer role ran a command the hook saw"}
        for knob, fact in cases.items():
            self.assertEqual(self.run_entry("antigravity", "A2", **{knob: "1"}), f"A2 antigravity failed: {fact}\n")

    def test_a3_records_which_tier_wins_against_the_models_pro_and_flash_gave(self):
        self.assertEqual(self.run_entry("antigravity", "A3"),
                         "A3 antigravity recorded: the call's tier won: the agent whose file names flash, called with "
                         "pro, ran on standin-pro-model; pro gave standin-pro-model and flash standin-flash-model\n")
        start = self.world.harness_starts()[-1]
        definitions = start["definitions"]
        self.assertIn("\nmodel: flash\n---\n", definitions[".agents/agents/probe-reader.md"])
        self.assertNotIn("model:", definitions[".agents/agents/probe-author.md"])
        self.assertNotIn("tools:", definitions[".agents/agents/probe-author.md"])
        self.assertEqual([s["toolCall"]["args"].get("Model") for s in start["sent"]
                          if s["toolCall"]["name"] == "invoke_subagent"], ["pro", "pro", "flash"])
        self.assertEqual(self.run_entry("antigravity", "A3", STANDIN_TIER_WINS="file"),
                         "A3 antigravity recorded: the file's tier won: the agent whose file names flash, called with "
                         "pro, ran on standin-flash-model; pro gave standin-pro-model and flash standin-flash-model\n")

    def test_a3_fails_when_no_agent_ran_the_call_named_no_tier_or_the_tiers_gave_one_model(self):
        cases = {"STANDIN_AGENT_OFF": "no agent of the reader role ran for the tiered brief",
                 "STANDIN_NO_TIER": "the hook saw no invoke_subagent call with Model pro for the tiered brief",
                 "STANDIN_SAME_TIERS": "precedence could not be told: pro and flash both ran on standin-same-model"}
        for knob, fact in cases.items():
            self.assertEqual(self.run_entry("antigravity", "A3", **{knob: "1"}), f"A3 antigravity failed: {fact}\n")


if __name__ == "__main__":
    unittest.main()
