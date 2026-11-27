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
import importlib
import importlib.util
import io
import json
import os
import re
import shlex
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
# Code, Cortex Code) beside them. Codex loads a role only from the role files its -c overrides name, and on
# Cortex Code and Codex an agent the prompt does not wait for is cancelled before it writes (#405). Knobs:
# STANDIN_AGENT_OFF starts no agent; STANDIN_SESSION_DOES has the
# session read the brief itself, so the file lacks a role's word; STANDIN_ROLE starts that role instead
# of the one asked for; STANDIN_ROLE_ONLY writes the role's word without the brief's; STANDIN_PARENT_ONLY
# prints no event of the agent's; STANDIN_COUNT makes each output count null, omit or zero;
# STANDIN_NO_MODEL and STANDIN_NO_TOKENS leave that field out.
LOADED_ROLES = r'''

def loaded_roles(args):
    """The role files Codex loads: each named by an agents.<name>.config_file override that has a description."""
    given = dict(arg.split("=", 1) for arg in args if arg.startswith("agents.") and "=" in arg)
    return [Path(json.loads(value)) for key, value in given.items() if key.endswith(".config_file")
            and key.removesuffix(".config_file") + ".description" in given]
'''
AGENT_HARNESS = r'''#!{python}
import json, os, re, subprocess, sys, tomllib
from pathlib import Path
{loaded_roles}
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
    """Each role's word by its name, read in this harness's format from its own folder only, or on Codex from
    the role files the command line names."""
    words = {}
    paths = sorted((cwd / folder).glob("*.toml" if name == "codex" else "*.md"))
    if name == "codex":  # Codex loads no project role file in an untrusted folder: only the -c overrides
        paths = loaded_roles(args)
    for path in paths:
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
WAITS = {"cortex": "Then call agent_output with wait true for it.",
         "codex": "Then call wait_agent for it and end only when it has finished."}
cancelled = name in WAITS and WAITS[name] not in prompt  # the session ended first, which cancels its agent
word = None if os.environ.get("STANDIN_AGENT_OFF") or cancelled else words.get(role_name)
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
            "D3": "D3  codex  Two agent starts in one model step",
            "R5": "R5  cursor  A definition file in ~/.cursor/agents/ loads",
            "R1": "R1  cursor  The IDE chat (not probed, closed by reading 6) (not built)",
            "A7": "A7  antigravity  The model starts a stand-in skill described as typed only",
        }
        for entry, line in expected.items():
            self.assertEqual(lines[ids.index(entry)], line)
        self.assertEqual(sum("(not built)" not in line for line in lines), 34)


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
                                          # This world's stand-in calls no hook, so the line names the trust step.
                                          f"D1 codex failed: {UNTRUSTED}\n"
                                          f"D2 codex failed: {UNTRUSTED}\n"
                                          "D6 codex failed: skipped, D1 failed in this run\n"
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
        script.write_text(AGENT_HARNESS.replace("{loaded_roles}", LOADED_ROLES).replace("{python}", sys.executable)
                          .replace("{session}", SESSION))
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
                                          f"for word, as its whole prompt: {line} Then call wait_agent for it and "
                                          f"end only when it has finished. Do not open that file yourself, and do "
                                          f"nothing else.")
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

    def test_on_cortex_and_codex_the_prompt_waits_for_the_agent_and_elsewhere_it_does_not(self):
        waits = {"cortex": "Then call agent_output with wait true for it. ",
                 "codex": "Then call wait_agent for it and end only when it has finished. "}
        for harness in ("cortex", "codex", "cursor"):
            for entry in ("X3", "X4", "X5"):
                code, out, _ = self.run_entry(harness, entry)
                self.assertEqual(code, 0, out)
                start = self.world.harness_starts()[-1]
                self.assertEqual(start["prompt"], f"Start one agent of the role probe-reader and give it this line, "
                                                  f"word for word, as its whole prompt: {start['line']} "
                                                  f"{waits.get(harness, '')}Do not open that file yourself, and do "
                                                  f"nothing else.", (harness, entry))

    def test_codex_loads_the_kits_role_files_from_the_command_line_and_nothing_reaches_the_users_settings(self):
        for entry in ("X3", "X4", "X5"):
            code, out, _ = self.run_entry("codex", entry)
            self.assertEqual(code, 0, out)
            args = self.world.harness_starts()[-1]["args"]
            self.assertEqual(args, ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                                    *role_args(work_of(args)), args[-1]])
            self.assertTrue(work_of(args).startswith(str(self.world.tmp)))
        self.assertEqual(sorted(self.world.home.rglob("*")), [])  # no ~/.codex: no trust or role is saved

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
            ("cursor", "R1"): "probe_kit: R1 is not built yet\n",
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
    """The Codex -c override of the research note, matching every tool, the same in every probe folder (#386)."""
    return ('hooks.PreToolUse=[{matcher="",hooks=[{type="command",command="python3 $(git rev-parse '
            '--path-format=absolute --git-common-dir)/../hooks/guard.py settings",timeout=20}]}]')


def role_args(work: str, kinds: tuple[str, ...] = ("reader", "reviewer")) -> list[str]:
    """The -c overrides that load the kit's Codex role files of the probe folder `work` (#405)."""
    return [arg for kind in kinds for arg in (
        "-c", f'agents.probe-{kind}.config_file="{work}/.codex/agents/probe-{kind}.toml"',
        "-c", f'agents.probe-{kind}.description="Stand-in {kind} for the probe kit. Start it only when asked for '
              f'probe-{kind} by name."')]


def work_of(args: list[str]) -> str:
    """The probe folder a Codex command line's role overrides name."""
    return re.search(r'config_file="(\S+)/\.codex/agents/', " ".join(args)).group(1)


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
            "antigravity": ["-p", x1, "--output-format", "stream-json", "--mode", "accept-edits",
                            "--settings", '{"permissions": {"allow": ["command(*)"]}}'],
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
                     "The hook and the judges share one rule for merge-script.sh: a command runs it when its name "
                     "is a command word, so reading the script is not refused",
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
        self.assertRegex(err, "^" + user_level_lines("C1") + "probe_kit: interrupted\n" + LEFT_AS_IT_WAS + "\n$")
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
        self.assertEqual(out.splitlines()[-4:], [
            "R4 cursor recorded: skill file in the output once, skill ran, hook fired once",
            # This stand-in `cursor-agent` names no shell command for the prompts of R3, R2 and R5
            # (TestHookAgentEntries covers R3, TestLimitEntries R2 and R5).
            "R3 cursor failed: harness exited 1",
            "R2 cursor failed: harness exited 1",
            "R5 cursor failed: harness exited 1"])
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


# Taken from the chief of staff's description of real `codex exec` runs (#405): what Codex CLI v0.172.0 gave
# around one agent start. Key names and values are as that run gave them; every id and path is made up. The
# re-run added fork_turns to the spawn input. The stand-ins below send and print what it holds. "session" holds the
# keys of each of the session's hook inputs besides cwd and the call; "spawn" and "wait" are the session's two
# calls; "agent" holds the two keys an agent's own call adds; "stream" is the JSON output, which shows no spawn
# item and no item for the agent's commands.
CODEX_RUN = {
    "session": {"hook_event_name": "PreToolUse", "model": "standin-codex-model", "permission_mode": "default",
                "session_id": "thread-made-up-0001", "transcript_path": "/standin/sessions/rollout-0001.jsonl",
                "turn_id": "turn-made-up-0001"},
    "spawn": {"tool_name": "collaborationspawn_agent", "tool_use_id": "call-made-up-0001",
              "tool_input": {"agent_type": "probe-reader", "task_name": "probe_reader_task", "fork_turns": "none",
                             "message": "<not readable>"}},
    "wait": {"tool_name": "collaborationwait_agent", "tool_use_id": "call-made-up-0002",
             "tool_input": {"timeout_ms": 60000}},
    "agent": {"agent_id": "thread-made-up-0002", "agent_type": "probe-reader"},
    "stream": [
        {"type": "thread.started", "thread_id": "thread-made-up-0001"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "Starting the agent."}},
        {"type": "item.started", "item": {"id": "item_1", "type": "collab_tool_call", "tool": "wait",
                                          "sender_thread_id": "thread-made-up-0001", "receiver_thread_ids": [],
                                          "prompt": None, "agents_states": {}, "status": "in_progress"}},
        {"type": "item.completed", "item": {"id": "item_1", "type": "collab_tool_call", "tool": "wait",
                                            "sender_thread_id": "thread-made-up-0001", "receiver_thread_ids": [],
                                            "prompt": None, "agents_states": {}, "status": "completed"}},
        {"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "The agent finished."}},
        {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 340}},
    ],
}

# D1, D2, D6, R3 and A6 (#386): a stand-in harness, installed as all five harness commands, that sends the
# session's agent start and then the agent's one call to the hook in its harness's input shape, and runs the
# call only on an allow. The agent's call is the brief's command, or for D6 an apply_patch that adds the file
# the brief names. Codex marks the agent with agent_id and agent_type, Cursor with a conversation id of its
# own, and Antigravity with the file the parent writes in .system_generated/subagents/ of its artifact folder.
# Knobs: STANDIN_UNTRUSTED calls no hook, as Codex does with a hook it has not trusted; STANDIN_SESSION_DOES
# makes the call the session's; STANDIN_FORCE_ALLOW runs the call whatever the hook said;
# STANDIN_NO_AGENT_TYPE leaves agent_type out; STANDIN_SPAWN_TOOL names the agent-starting tool (default
# spawn_agent) and STANDIN_SPAWN_ALSO sends a second start under that name; STANDIN_SUBAGENT_START calls
# Cursor's subagentStart hook; STANDIN_NO_AGENT_FILE writes no agent file on Antigravity. On Codex it prints
# CODEX_RUN's stream; STANDIN_FIXTURE sends CODEX_RUN's calls in place of its own start, and STANDIN_NO_CALL
# makes no call at all and prints the stream without the wait.
# STANDIN_HOOK_IN runs Codex's hook in that folder of the probe folder; an empty STANDIN_SPAWN_TOOL leaves
# tool_name out; STANDIN_SPAWN_READS makes the session's call a read of the brief's path instead of the
# handoff; STANDIN_AGENT_CMD is the agent's command instead of the brief's; STANDIN_AGENT_FIRST is a command
# the agent runs before it, giving up when the hook refuses it; STANDIN_DROP_REFUSALS takes the
# hook's refusal lines out of its log; STANDIN_EXIT is the exit code. The record keeps each hook answer.
HOOK_AGENT_HARNESS = r'''#!{python}
import json, os, re, subprocess, sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
prompt = args[args.index("-p") + 1] if name in ("claude", "cortex", "agy") else args[-1]
cwd, knob = Path.cwd(), os.environ.get
role = re.search(r"of the role (\S+)", prompt).group(1)
line = re.search(r"whole prompt: (Read (\S+) and follow it\.)", prompt)
brief = Path(line.group(2)).read_text()
registered = {path: json.loads((cwd / path).read_text()) for path in (".cursor/hooks.json", ".agents/hooks.json")
              if (cwd / path).is_file()}
agent = not knob("STANDIN_SESSION_DOES")
sent, decisions, answers = [], [], []
RUN = json.loads("""{codex_run}""")


def call(hook, data, hook_dir, form):
    """Send one input to the hook; return its decision, or allow when no hook runs."""
    if knob("STANDIN_UNTRUSTED") or hook is None:
        return "allow"
    sent.append(data)
    done = subprocess.run(hook, shell=True, cwd=hook_dir, input=json.dumps(data), capture_output=True, text=True)
    answer = json.loads(done.stdout) if done.stdout.strip() else {}
    answers.append(answer)
    log = cwd / "logs" / "hook.jsonl"
    if knob("STANDIN_DROP_REFUSALS") in ("1", role) and log.is_file():
        log.write_text("".join(l for l in log.read_text().splitlines(True) if '"decision": "deny"' not in l))
    if form == "settings":
        return answer.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
    if form == "beforeShell":
        return answer.get("permission", "allow")
    return answer.get("decision", "deny")


ran = re.search(r"Run the command `([^`]+)` in the folder (\S+)\.", brief)
command = knob("STANDIN_AGENT_CMD") or (ran.group(1) if ran else None)
edit = re.search(r"Create the file (\S+) holding the word (\S+) with your file-editing tool", brief)
if name == "codex" and knob("STANDIN_NO_CALL"):
    decision = None
elif name == "codex":
    hook = re.search(r'command="([^"]*)"', args[args.index("-c") + 1]).group(1)
    spawns = [knob("STANDIN_SPAWN_TOOL", "spawn_agent")] + ([knob("STANDIN_SPAWN_ALSO")] if knob("STANDIN_SPAWN_ALSO") else [])
    hook_dir = cwd / knob("STANDIN_HOOK_IN", "")
    for tool in spawns:
        given = {"path": line.group(2)} if knob("STANDIN_SPAWN_READS") else {"agent_type": role, "message": line.group(1)}
        start = {"session_id": "{session}", "cwd": str(cwd), "hook_event_name": "PreToolUse", "tool_name": tool,
                 "tool_input": given}
        if not tool:
            del start["tool_name"]
        if knob("STANDIN_FIXTURE"):
            start = {**RUN["session"], "cwd": str(cwd), **RUN["spawn"]}
        call(hook, start, hook_dir, "settings")
    if knob("STANDIN_FIXTURE"):
        call(hook, {**RUN["session"], "cwd": str(cwd), **RUN["wait"]}, hook_dir, "settings")
    data = {"session_id": "{session}", "cwd": str(cwd), "hook_event_name": "PreToolUse"}
    if agent:
        data["agent_id"] = RUN["agent"]["agent_id"] if knob("STANDIN_FIXTURE") else "agent-1"
        if not knob("STANDIN_NO_AGENT_TYPE"):
            data["agent_type"] = role
    if edit:
        patch = f"*** Begin Patch\n*** Add File: {edit.group(1)}\n+{edit.group(2)}\n*** End Patch\n"
        data.update(tool_name="apply_patch", tool_input={"command": patch})
    else:
        data.update(tool_name="Bash", tool_input={"command": command})
    first = knob("STANDIN_AGENT_FIRST")  # as the real agent: a refused first command and it gives up (#405)
    decision = call(hook, {**data, "tool_name": "Bash", "tool_input": {"command": first}}, hook_dir,
                    "settings") if first else "allow"
    if decision == "allow":
        decision = call(hook, data, hook_dir, "settings")
elif name == "cursor-agent":
    hooks = registered[".cursor/hooks.json"]["hooks"]
    call(hooks["sessionStart"][0]["command"], {"conversation_id": "{session}", "hook_event_name": "sessionStart"},
         cwd, "sessionStart")
    if knob("STANDIN_SUBAGENT_START") and "subagentStart" in hooks:
        call(hooks["subagentStart"][0]["command"], {"subagent_id": "agent-1", "parent_conversation_id": "{session}",
                                                    "hook_event_name": "subagentStart"}, cwd, "subagentStart")
    decision = call(hooks["beforeShellExecution"][0]["command"], {
        "conversation_id": "conv-agent-2" if agent else "{session}", "command": command, "cwd": str(cwd)},
        cwd, "beforeShell")
else:  # agy: the hook runs in the folder that holds hooks.json
    hook = next(iter(registered[".agents/hooks.json"].values()))["PreToolUse"][0]["hooks"][0]["command"]
    brain = cwd.parent / "brain"
    conversation = "conv-agent-2" if agent else "{session}"
    (brain / conversation).mkdir(parents=True, exist_ok=True)
    if agent and not knob("STANDIN_NO_AGENT_FILE"):
        made = brain / "{session}" / ".system_generated" / "subagents"
        made.mkdir(parents=True)
        (made / f"{conversation}.json").write_text("{}")
    decision = call(hook, {"conversationId": conversation, "artifactDirectoryPath": str(brain / conversation),
                           "cwd": str(cwd), "toolCall": {"name": "run_command",
                                                         "args": {"CommandLine": command, "Cwd": ran.group(2)}}},
                    cwd / ".agents", "pre")
if knob("STANDIN_FORCE_ALLOW") in ("1", role):
    decision = "allow"
decisions.append(decision)
if decision == "allow":
    if edit:
        Path(edit.group(1)).write_text(edit.group(2) + "\n")
    else:
        subprocess.run(command, shell=True, cwd=ran.group(2), stdout=subprocess.DEVNULL)
logs = cwd / "logs"
with open(knob("STANDIN_STARTS"), "a") as starts:
    starts.write(json.dumps({"name": name, "args": args, "prompt": prompt, "brief": brief, "registered": registered,
                             "sent": sent, "decisions": decisions, "answers": answers,
                             "logs": sorted(p.name for p in logs.iterdir()),
                             "hook_log": (logs / "hook.jsonl").read_text() if (logs / "hook.jsonl").is_file() else ""})
                 + "\n")
if name == "codex":
    for event in RUN["stream"]:
        if not (knob("STANDIN_NO_CALL") and event.get("item", {}).get("type") == "collab_tool_call"):
            print(json.dumps(event))
print(json.dumps({"type": "result", "session_id": "{session}", "result": "done"}))
sys.exit(int(knob("STANDIN_EXIT", "0")))
'''
# STANDIN_FORCE_ALLOW and STANDIN_DROP_REFUSALS act for every role at 1, or for the role they name.
TRUST_STEP = ("Trust the stand-in hook once in Codex: in a terminal in the root of this checkout, start "
              f"codex -c '{codex_c('')}', type /hooks, trust the hook, then quit.")


def no_input(code: int) -> str:
    return (f"the hook logged no input and the harness exited {code}. Codex runs no hook it has not trusted. "
            f"{TRUST_STEP}")


UNTRUSTED = no_input(0)
# Stands in for hc in front of the stand-in hc: at `hc run` it records what the kit's stderr held then.
HC_WATCH = r"""#!{python}
import json, os, sys
if sys.argv[1:2] == ["run"]:
    err = os.environ.get("STANDIN_KIT_ERR", "")
    with open(os.path.join(os.environ["STANDIN_HC_DIR"], "err-at-run.jsonl"), "a") as seen:
        seen.write(json.dumps(open(err).read() if os.path.isfile(err) else None) + "\n")
os.execv("{hc}", ["{hc}", *sys.argv[1:]])
"""
D1_SEEN = "D1 codex seen: the hook saw the agent marker and refused the merge stand-in\n"
D2_SEEN = "D2 codex recorded: the agent-starting tool reaches the hook as spawn_agent\n"
FORBIDDEN = ("ephemeral", "bypass", "trust")  # no Codex argv of these entries holds one of these words


class TestHookAgentEntries(HookTest):
    """D1, D2, D6, R3 and A6 against the stand-in that starts one agent and sends its call to the hook."""

    def setUp(self) -> None:
        super().setUp()
        script = self.world.bin / "hook-agent-harness"
        script.write_text(HOOK_AGENT_HARNESS.replace("{python}", sys.executable).replace("{session}", SESSION)
                          .replace("{codex_run}", json.dumps(CODEX_RUN)))
        script.chmod(0o755)
        self.world.install("hook-agent-harness")
        (self.world.bin / "hc").rename(self.world.bin / "hc-standin")
        (self.world.bin / "hc").write_text(HC_WATCH.replace("{python}", sys.executable)
                                           .replace("{hc}", str(self.world.bin / "hc-standin")))
        (self.world.bin / "hc").chmod(0o755)

    def err_at_runs(self) -> list[str | None]:
        seen = self.world.hc_dir / "err-at-run.jsonl"
        return [json.loads(line) for line in seen.read_text().splitlines()] if seen.exists() else []

    def assert_codex_argv(self, start: dict) -> None:
        self.assertEqual(start["args"], ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                                         "-c", codex_c(""), *role_args(work_of(start["args"])), start["prompt"]])
        for word in FORBIDDEN:
            self.assertNotIn(word, " ".join(start["args"][:-1]))

    def test_d1_prints_the_trust_step_before_the_terminal_starts_and_is_seen_when_the_hook_refuses_an_agents_merge_script(self):
        code, out, err = self.world.kit("run", "codex", "D1", STANDIN_KIT_ERR=str(self.world.root / "kit.err"))
        self.assertEqual((code, out), (0, D1_SEEN))
        (at_run,) = self.err_at_runs()
        self.assertIn(f"probe_kit: D1 needs a trusted hook. {TRUST_STEP}\n", at_run)
        self.assert_private(out, err)
        start = self.world.harness_starts()[-1]
        self.assert_codex_argv(start)
        self.assertIn("Start one agent of the role probe-reader", start["prompt"])
        self.assertRegex(start["brief"], r"Run the command `\./merge-script\.sh` in the folder \S+\. Change nothing else\.")
        self.assertEqual((start["decisions"], start["logs"]), (["deny"], ["hook.jsonl"]))
        self.assertEqual(start["answers"][-1], {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "GUARD-B: the merge script is refused to a helper"}})
        self.assert_home_empty()

    def test_the_codex_hook_text_is_the_same_in_every_probe_folder_and_in_the_trust_step(self):
        for _ in range(2):
            self.world.kit("run", "codex", "D2")
        code, out, err = self.world.kit("run", "codex", "D1")
        first, second, third = (s["args"] for s in self.world.harness_starts())
        self.assertEqual(first[first.index("-c") + 1], second[second.index("-c") + 1])
        trust = re.search(r"start (codex -c '[^']*')", err).group(1)
        self.assertEqual(shlex.split(trust)[1:], ["-c", third[third.index("-c") + 1]])
        for arg in (first, second, third):  # the role overrides name the probe folder; the hook's text does not
            self.assertNotIn(str(self.world.root), " ".join(a for a in arg[:-1] if not a.startswith("agents.")))
            self.assertNotIn(str(Path.home()), " ".join(a for a in arg[:-1] if not a.startswith("agents.")))

    def test_d1_lets_an_agent_read_the_merge_script_and_refuses_running_it(self):
        code, out, err = self.world.kit("run", "codex", "D1", STANDIN_AGENT_FIRST="cat ./merge-script.sh")
        self.assertEqual((code, out), (0, D1_SEEN))  # the real agent read the script first (#405)
        self.assertEqual(self.world.harness_starts()[-1]["decisions"], ["deny"])
        self.assertEqual([a.get("hookSpecificOutput", {}).get("permissionDecision")
                          for a in self.world.harness_starts()[-1]["answers"][-2:]], [None, "deny"])

    def test_d1_finds_its_hook_from_a_subfolder_and_from_the_agents_worktree(self):
        for folder in ("sub", ".probe-worktrees/agent"):
            code, out, err = self.world.kit("run", "codex", "D1", STANDIN_HOOK_IN=folder)
            self.assertEqual((code, out), (0, D1_SEEN), folder)

    def test_d1_fails_untrusted_with_the_trust_step_and_on_a_session_call_or_a_merge_script_that_ran(self):
        cases = {(("STANDIN_UNTRUSTED", "1"),): UNTRUSTED,
                 (("STANDIN_UNTRUSTED", "1"), ("STANDIN_EXIT", "1")): no_input(1),
                 (("STANDIN_SESSION_DOES", "1"),): "no agent's call of the merge stand-in reached the hook",
                 (("STANDIN_FORCE_ALLOW", "1"),): "the merge stand-in ran",
                 (("STANDIN_AGENT_CMD", "ls -l ./merge-script.sh"),): "no agent's call of the merge stand-in reached the hook",
                 (("STANDIN_DROP_REFUSALS", "1"),): "the hook logged no refusal of the merge stand-in",
                 (("STANDIN_EXIT", "1"),): "harness exited 1",
                 (("STANDIN_NO_CALL", "1"),): UNTRUSTED,
                 (("STANDIN_NO_CALL", "1"), ("STANDIN_EXIT", "1")): no_input(1)}
        for knobs, fact in cases.items():
            code, out, err = self.world.kit("run", "codex", "D1", **dict(knobs))
            self.assertEqual((code, out), (1, f"D1 codex failed: {fact}\n"), knobs)
            self.assert_private(out, err)

    def test_d2_records_the_tool_name_of_the_session_call_that_names_the_brief(self):
        for tool in ("spawn_agent", "Agent"):
            code, out, err = self.world.kit("run", "codex", "D2", STANDIN_SPAWN_TOOL=tool)
            self.assertEqual((code, out), (0, f"D2 codex recorded: the agent-starting tool reaches the hook as {tool}\n"))
            self.assert_private(out, err)
        self.assertIn("control-ran-d2.marker", self.world.harness_starts()[-1]["logs"])

    def test_d2_records_the_real_runs_tool_name_from_an_input_whose_message_is_not_readable(self):
        code, out, err = self.world.kit("run", "codex", "D2", STANDIN_FIXTURE="1")
        self.assertEqual((code, out), (0, "D2 codex recorded: the agent-starting tool reaches the hook as "
                                          "collaborationspawn_agent\n"))
        self.assert_private(out, err)
        start = self.world.harness_starts()[-1]
        self.assertEqual([s["tool_name"] for s in start["sent"]], ["collaborationspawn_agent",
                                                                     "collaborationwait_agent", "Bash"])
        self.assertNotIn("brief-d2.md", start["hook_log"])  # the handoff line is nowhere in what the hook saw
        spawn = json.loads(start["hook_log"].splitlines()[0])["input"]["tool_input"]
        self.assertEqual(sorted(spawn), ["agent_type", "fork_turns", "message", "task_name"])  # the re-run's keys

    def test_d2_fails_untrusted_with_no_agent_call_two_tool_names_or_a_name_that_is_not_plain(self):
        cases = {(("STANDIN_UNTRUSTED", "1"),): UNTRUSTED,
                 (("STANDIN_SESSION_DOES", "1"),): "no agent's call reached the hook",
                 (("STANDIN_SPAWN_ALSO", "Agent"),): "2 tools of the session's started an agent of the reader role",
                 (("STANDIN_SPAWN_TOOL", "/tmp/x y"),): "the agent-starting tool's name is not a plain name",
                 (("STANDIN_SPAWN_TOOL", ""),): "the hook input of the agent-starting call holds no tool name",
                 (("STANDIN_SPAWN_READS", "1"),): "no call of the session's that starts an agent of the reader role "
                                                  "reached the hook"}
        for knobs, fact in cases.items():
            code, out, err = self.world.kit("run", "codex", "D2", **dict(knobs))
            self.assertEqual((code, out), (1, f"D2 codex failed: {fact}\n"), knobs)

    def test_d6_runs_after_d1_and_d2_and_is_seen_when_the_hook_refuses_the_reviewers_edit(self):
        code, out, err = self.world.kit("run", "codex", "D1", "D2", "D6")
        self.assertEqual((code, out), (0, D1_SEEN + D2_SEEN + "D6 codex seen: the hook refused the edit tool to a reviewer\n"))
        self.assert_private(out, err)
        start = self.world.harness_starts()[-1]
        self.assertIn("Start one agent of the role probe-reviewer", start["prompt"])
        self.assertEqual(start["sent"][-1]["tool_name"], "apply_patch")
        self.assertEqual(start["decisions"], ["deny"])
        for each in self.world.harness_starts():
            self.assert_codex_argv(each)

    def test_d6_fails_when_the_agents_edit_input_names_no_reviewer(self):
        code, out, _ = self.world.kit("run", "codex", "D1", "D2", "D6", STANDIN_NO_AGENT_TYPE="1")
        self.assertEqual((code, out), (1, "D1 codex seen: the hook saw the agent marker and refused the merge stand-in\n"
                                          "D2 codex recorded: the agent-starting tool reaches the hook as spawn_agent\n"
                                          "D6 codex failed: the hook input of the agent's edit call does not name the "
                                          "reviewer role\n"))

    def test_d6_fails_without_a_refusal_line_or_with_the_reviewers_file_written(self):
        cases = {"STANDIN_DROP_REFUSALS": "the hook logged no refusal of the edit tool",
                 "STANDIN_FORCE_ALLOW": "the reviewer's edit went through"}
        for knob, fact in cases.items():
            code, out, _ = self.world.kit("run", "codex", "D1", "D2", "D6", **{knob: "probe-reviewer"})
            self.assertEqual((code, out), (1, D1_SEEN + D2_SEEN + f"D6 codex failed: {fact}\n"), knob)

    def test_d6_is_skipped_and_failed_when_d1_failed_or_did_not_run_first(self):
        code, out, _ = self.world.kit("run", "codex", "D1", "D2", "D6", STANDIN_UNTRUSTED="1")
        self.assertEqual((code, out), (1, f"D1 codex failed: {UNTRUSTED}\nD2 codex failed: {UNTRUSTED}\n"
                                          "D6 codex failed: skipped, D1 failed in this run\n"))
        self.assertEqual(len(self.world.harness_starts()), 2)  # D6 started no session
        code, out, _ = self.world.kit("run", "codex", "D6")
        self.assertEqual((code, out), (1, "D6 codex failed: skipped, D1 did not run before it in this run\n"))
        self.assertEqual(len(self.world.harness_starts()), 2)

    def test_d6_is_skipped_and_failed_when_d2_failed_or_did_not_run_first(self):
        code, out, _ = self.world.kit("run", "codex", "D1", "D2", "D6", STANDIN_SPAWN_ALSO="Agent")
        self.assertEqual((code, out), (1, D1_SEEN + "D2 codex failed: 2 tools of the session's started an agent of "
                                                     "the reader role\n"
                                          "D6 codex failed: skipped, D2 failed in this run\n"))
        code, out, _ = self.world.kit("run", "codex", "D1", "D6")
        self.assertEqual((code, out), (1, D1_SEEN + "D6 codex failed: skipped, D2 did not run before it in this run\n"))
        starts = self.world.harness_starts()
        self.assertEqual(len(starts), 3)  # D1, D2, then D1: D6 started no session
        self.assertFalse(any("probe-reviewer" in start["prompt"] for start in starts))

    def test_r3_records_whether_subagent_start_fired_and_fails_with_no_agent_call(self):
        cases = {(("STANDIN_SUBAGENT_START", "1"),): (0, "R3 cursor recorded: subagentStart fired\n"),
                 (): (0, "R3 cursor recorded: subagentStart did not fire, though an agent ran\n"),
                 (("STANDIN_SESSION_DOES", "1"),): (1, "R3 cursor failed: no agent's call of the control stand-in "
                                                       "reached the hook\n"),
                 (("STANDIN_UNTRUSTED", "1"),): (1, "R3 cursor failed: the hook logged no session start\n")}
        for knobs, expected in cases.items():
            code, out, err = self.world.kit("run", "cursor", "R3", **dict(knobs))
            self.assertEqual((code, out), expected, knobs)
            self.assert_private(out, err)
        hooks = self.world.harness_starts()[0]["registered"][".cursor/hooks.json"]["hooks"]
        self.assertEqual(hooks["subagentStart"], [{"command": "python3 hooks/guard.py subagentStart"}])

    def test_a6_is_seen_when_the_marker_is_absent_and_the_hook_logged_a_refusal(self):
        code, out, err = self.world.kit("run", "antigravity", "A6")
        self.assertEqual((code, out), (0, "A6 antigravity seen: the hook refused the merge stand-in to an agent\n"))
        self.assert_private(out, err)
        start = self.world.harness_starts()[-1]
        refusal = json.loads(start["hook_log"].splitlines()[-1])
        self.assertEqual((refusal["decision"], refusal["reason"]), ("deny", "GUARD-B: the merge script is refused to a helper"))
        for knobs in ({"STANDIN_NO_AGENT_FILE": "1"}, {"STANDIN_SESSION_DOES": "1"}, {"STANDIN_FORCE_ALLOW": "1"}):
            code, out, _ = self.world.kit("run", "antigravity", "A6", **knobs)
            self.assertEqual((code, out), (1, "A6 antigravity failed: the merge stand-in ran\n"), knobs)
        self.world.kit("run", "antigravity", "A6", STANDIN_AGENT_CMD="cat ./merge-script.sh")
        self.assertEqual(self.world.harness_starts()[-1]["decisions"], ["allow"])  # reading it is not refused
        for knobs in ({"STANDIN_AGENT_CMD": "ls -l ./merge-script.sh"}, {"STANDIN_DROP_REFUSALS": "1"}):
            code, out, _ = self.world.kit("run", "antigravity", "A6", **knobs)
            self.assertEqual((code, out), (1, "A6 antigravity failed: the hook logged no refusal of the merge stand-in\n"),
                             knobs)

    def test_help_states_the_trust_step_the_refusal_line_and_each_entrys_evidence(self):
        code, out, err = self.world.kit("--help")
        self.assertEqual((code, err), (0, ""))
        text = " ".join(out.split())
        for fact in ("matches every tool", "from any folder inside the probe folder",
                     "the same in every probe folder, so one trust covers every run",
                     "Codex runs no hook it has not trusted", "Before D1 runs, the kit prints the step that trusts the hook",
                     "When D1 to D4 or D6 fails because its hook logged no input, the line gives that step and the "
                     "harness's exit status.",
                     "writes a refusal line to logs/hook.jsonl",
                     "marked by agent_id, reached the hook for a command that runs merge-script.sh",
                     "D2 records the tool name of the session's call whose input names the reader role as its "
                     "agent_type; it never reads the message",
                     "The line names the trust step even when the output shows no tool call, since Codex's output "
                     "shows no agent start and no agent's command.",
                     "D6 runs only after D1 was seen and D2 recorded in the same run",
                     "refuses the edit tool (apply_patch, Edit or Write) when the input's agent_type is the reviewer role",
                     "R3 registers subagentStart in .cursor/hooks.json", "conversation id other than the session's",
                     ".system_generated/subagents/", "A6 is seen when the merge marker is absent and the hook logged a refusal"):
            self.assertIn(fact, text)
        self.assertNotIn("names no trust step", text)  # the rule before #408


# K1 to K5, D3 to D5, R2, R5 and A2 to A4 (#385). A third stand-in harness, installed as all five harness
# commands, follows the prompt and each brief as a model would. It reads the roles from its own definition
# folder, and Cursor's also from ~/.cursor/agents/. Each `Read <path> and follow it.` starts an agent of the
# role named before it; the starts between two waits run at once, in threads. An agent remembers the word its
# brief gives it to keep, writes the words its brief asks for, lists its agent tools, deletes its brief when
# asked, runs its shell commands, and starts the agents its brief names. On Cortex Code an agent below the depth
# limit (maxSubagentDepth from the variable, default 1) has task, agent, agent_output and kill_agent, and one at
# the limit has none and starts nothing; elsewhere there is no limit. Cortex Code's output shows each task call
# with its parent and its result, which gives the agentId or the depth error, and each kill_agent and
# agent_output call; Codex's shows each collab_tool_call item started and completed, with its thread, and
# Codex loads a role only from the role files its -c overrides name. With the inline hook, Codex sends the
# session's spawn, interrupt and follow-up calls and each agent's call that wrote its marker to the hook, in
# CODEX_RUN's shape (#405). On Antigravity an agent whose role file has no tools line has no shell and no file
# write, so it makes no call the hook sees (#405). The kill
# lands while the agent's sleep runs. A resume or follow-up first waits for the agents before it. On
# Antigravity the session's invoke_subagent calls and the agents' run_command and write_file calls go to the
# registered hook, with the caller's model, and run only on an allow; the agents' other writes and the session's
# shell commands do not. A write_file call is refused to a role whose tools list lacks it. Knobs:
# STANDIN_AGENT_OFF starts no agent; STANDIN_DEPTH sets the depth limit; STANDIN_TOOLS_KEPT leaves an agent at
# the limit its tools, so its call is refused; STANDIN_SKIP_NESTED makes an agent start none; STANDIN_CAP lets
# that many agents of one prompt or brief run at once, the rest queued, or refused with STANDIN_CAP_REFUSE;
# STANDIN_STEP_APART lets each start end before the next; STANDIN_NO_KILL lets the sleep finish, with no
# kill_agent call; STANDIN_HIDE_KILL leaves the kill out of the output; STANDIN_KILL_OTHER names another agent
# in it; STANDIN_KILL_FAILS gives it an error; STANDIN_NO_CLOSE leaves interrupt_agent out; STANDIN_CLOSE_OTHER
# names another thread in it; STANDIN_NO_COLLAB leaves Codex's spawn and follow-up items out of the output, as
# the real one does; STANDIN_UNTRUSTED calls no inline hook; STANDIN_NO_AGENT_TYPE leaves agent_type out of a
# spawn call; STANDIN_RESUME_ERROR=text or =empty fails the resume call with or without a reason, and =plain
# fails it as Cortex Code does, a "task tool failed:" string with no is_error key;
# STANDIN_BY_TASK names the agent by its task_name in the interrupt and follow-up; STANDIN_LETTER_IDS gives
# Cortex Code agents ids of letters only; STANDIN_RESUME_FRESH resumes without the
# kept word; STANDIN_RESUME_FROM_DISK takes the first marker's word instead; STANDIN_RESUME_OTHER resumes
# another agent; STANDIN_RESUME_FAIL leaves a resume unanswered; STANDIN_OUTSIDE_DENIED refuses the write
# outside the folder; STANDIN_NO_USER_AGENTS ignores ~/.cursor/agents/; STANDIN_TOOLS_IGNORED lets a withheld
# tool run; STANDIN_NO_TRY makes no write_file call but reports it refused, or failed with =failed;
# STANDIN_OTHER_TOOL calls view_file on the marker instead; STANDIN_SHELL_WRITE writes through run_command
# instead; STANDIN_WRITE_ERROR lets the
# write_file call fail another way; STANDIN_TIER_WINS=file lets the file's tier win over the call's;
# STANDIN_SAME_TIERS gives every tier one model; STANDIN_NO_TIER drops the call's tier; STANDIN_FOREGROUND
# starts every agent in the foreground, or with =inner every agent an agent starts; STANDIN_NO_MODEL leaves the
# agents' models out of the output; STANDIN_DECOY puts an unrelated call with a model first; STANDIN_SLEEP waits
# before it acts.
LIMIT_HARNESS = r'''#!{python}
import json, os, re, signal, subprocess, sys, threading, time, tomllib
from pathlib import Path
{loaded_roles}
name, args = Path(sys.argv[0]).name, sys.argv[1:]
prompt = args[args.index("-p") + 1] if name in ("cortex", "agy") else args[-1]
cwd, knob = Path.cwd(), os.environ.get
folders = [cwd / {"claude": ".claude/agents", "cortex": ".cortex/agents", "codex": ".codex/agents",
                  "cursor-agent": ".cursor/agents", "agy": ".agents/agents"}[name]]
user_agents = Path(os.environ["HOME"]) / ".cursor" / "agents"
if name == "cursor-agent" and not knob("STANDIN_NO_USER_AGENTS"):
    folders.append(user_agents)
roles = {}
paths = [path for folder in folders for path in sorted(folder.glob("*.toml" if name == "codex" else "*.md"))]
if name == "codex":  # Codex loads no project role file in an untrusted folder: only the -c overrides
    paths = loaded_roles(args)
for path in paths:
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
inline = next((arg for arg in args if arg.startswith("hooks.PreToolUse=")), None)
codex_hook = re.search(r'command="([^"]*)"', inline).group(1) \
    if name == "codex" and inline and not knob("STANDIN_UNTRUSTED") else None
user_files = sorted(p.name for p in user_agents.glob("*")) if user_agents.is_dir() else []
lock, events, records, sent, counter = threading.Lock(), [], [], [], [0]
RUN = json.loads("""{codex_run}""")
memory, markers, ids, ready, sleepers = {}, {}, {}, {}, {}
WRITES = re.compile(r"[Ww]rite the word (?P<word>\S+), a space(?P<recall>, the word your first brief asked you to "
                    r"remember, a space)? and your role word to the file (?P<file>\S+) in (?P<outside>your worktree, )?"
                    r"the folder (?P<folder>\S+?)(?P<tool> with the write_file tool, not with run_command)?\.(?:\s|$)")
LISTS = re.compile(r"write the word (\S+), a space and the names of those of these tools you have: task, agent, "
                   r"agent_output, kill_agent, or the word none, to the file (\S+) in the folder (\S+?)\.(?:\s|$)")
TOKENS = re.compile(r"(?:subagent_type|agent_type|of the role) (?P<role>probe-[a-z-]+)|run_in_background "
                    r"(?P<bg>true|false)|Model (?P<tier>\w+)|(?P<resume>resume set to that agentId|with "
                    r"followup_task)|call (?P<stop>kill_agent|interrupt_agent) |(?P<wait>call agent_output with wait "
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


def codex_call(tool_name, given, agent_id=None, role=None):
    """Codex sends each call to the inline hook, in CODEX_RUN's shape; an agent's call carries its id and role."""
    if codex_hook:
        data = {**RUN["session"], "cwd": str(cwd), "tool_name": tool_name, "tool_input": given}
        if agent_id:
            data.update(agent_id=agent_id, agent_type=role)
        subprocess.run(codex_hook, shell=True, cwd=cwd, input=json.dumps(data), capture_output=True, text=True)


def result(parent, call, text, error=False):
    """A tool_result item; with error None it has no is_error key, as Cortex Code's failed resume (#405)."""
    item = {"type": "tool_result", "tool_use_id": call, "content": text}
    emit(type="user", parent_tool_use_id=parent, message={"content": [
        item if error is None else item | {"is_error": error}]})


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
    if knob("STANDIN_LETTER_IDS") and not resume:  # an id of letters only, which the digit rule cannot catch
        target = "agent-" + str(own).translate(str.maketrans("0123456789_", "abcdefghijk"))
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
        if resume and knob("STANDIN_RESUME_ERROR") == "plain":  # the real one: a string, no is_error key
            result(parent, own, f"task tool failed: Agent session '{named}' not found. Cannot resume.", None)
            return
        if resume and knob("STANDIN_RESUME_ERROR"):  # as with --private, which keeps no session history
            result(parent, own, [{"type": "text", "text": f"Agent session {named} not found under "
                                                          f"/standin/sessions. Cannot resume."}]
                   if knob("STANDIN_RESUME_ERROR") == "text" else "", True)
            return
        result(parent, own, f"Agent started. agentId: {named}")
    elif name == "codex":
        codex_call("collaborationfollowup_task" if resume else "collaborationspawn_agent",
                   ({"task_name": f"task_{resume}"} if knob("STANDIN_BY_TASK") else {"id": named}) | {
                       "message": "<not readable>"} if resume else
                   {**({} if knob("STANDIN_NO_AGENT_TYPE") else {"agent_type": role_name}),
                    "task_name": f"task_{own}", "message": "<not readable>"})
        if not knob("STANDIN_NO_COLLAB"):
            emit(type="item.completed", item={"id": f"item_{own}", "type": "collab_tool_call",
                                              "tool": "followup_task" if resume else "spawn_agent",
                                              "receiver_thread_ids": [named], "status": "completed"})
    if depth > limit or (resume and (knob("STANDIN_RESUME_FAIL") or knob("STANDIN_RESUME_OTHER"))):
        return
    if name == "agy" and role["tools"] is None:  # no tools line: no shell and no file write (#405)
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
            ended = "failed" if knob("STANDIN_NO_TRY") == "failed" else "refused"
        else:
            withheld = role["tools"] is not None and "write_file" not in role["tools"]
            refused = withheld and not knob("STANDIN_TOOLS_IGNORED")
            failing = knob("STANDIN_WRITE_ERROR")
            tool(model, "write_file", {"TargetFile": str(target), "CodeContent": body},
                 None if refused or failing else lambda: target.write_text(body))
            ended = "failed" if failing else "refused" if refused else "wrote"
    if name == "codex" and markers.get(own):  # the agent's own call that wrote its marker
        codex_call("Bash", {"command": f"echo ... > {markers[own]}"}, ids[own], role_name)
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
        if name == "codex" and not knob("STANDIN_NO_COLLAB"):
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
        elif token["stop"] == "interrupt_agent":
            settle()
            if not knob("STANDIN_NO_CLOSE"):
                other = knob("STANDIN_CLOSE_OTHER")
                codex_call("collaborationinterrupt_agent",
                           {"task_name": "task_other" if other else f"task_{last}"} if knob("STANDIN_BY_TASK") else
                           {"id": "thread-other" if other else ids.get(last)})
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
        script.write_text(LIMIT_HARNESS.replace("{loaded_roles}", LOADED_ROLES).replace("{python}", sys.executable)
                          .replace("{session}", SESSION).replace("{codex_run}", json.dumps(CODEX_RUN)))
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
        for entry in ("K4", "K5"):  # a failed resume, as under --private, says so with the reason, no id or path
            self.assertEqual(self.run_entry("cortex", entry, STANDIN_RESUME_ERROR="text"),
                             f"{entry} cortex failed: the resume call failed: Agent session ... not found under ... "
                             f"Cannot resume.\n")
            self.assertEqual(self.run_entry("cortex", entry, STANDIN_RESUME_ERROR="empty"),
                             f"{entry} cortex failed: the resume call failed\n")
            line = self.run_entry("cortex", entry, STANDIN_RESUME_ERROR="text", STANDIN_LETTER_IDS="1")
            self.assertEqual(line, f"{entry} cortex failed: the resume call failed: Agent session ... not found under "
                                   f"... Cannot resume.\n")  # the letters-only id the kit knew is gone too
            self.assertEqual(self.run_entry("cortex", entry, STANDIN_RESUME_ERROR="plain"),
                             f"{entry} cortex failed: the resume call failed: task tool failed: Agent session ... not "
                             f"found. Cannot resume.\n")  # Cortex Code's string error, with no is_error flag

    def test_k4s_second_brief_tells_the_agent_to_run_no_command_its_first_brief_gave_and_the_help_says_so(self):
        # The resumed agent ran its first brief's sleep again, and the session hit the time limit (#408).
        kit, work = self.load_kit(), self.world.root / "k4-work"
        kit.PROBES["K4"].setup("cortex", work, "k4-codeword")
        brief = (work / ".git" / kit.BRIEFS / "brief-k4-second.md").read_text().splitlines()
        self.assertEqual(brief[2], f"Write the word {kit.WORDS['k4-codeword']['second']}, a space, the word your "
                                   f"first brief asked you to remember, a space and your role word to the file "
                                   f"probe-k4-second.txt in the folder {work}. Do not run any command your first "
                                   f"brief gave you, even one that did not finish. Change nothing else.")
        code, out, err = self.world.kit("--help")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("K4's second brief tells the agent to run no command its first brief gave it.",
                      " ".join(out.split()))

    def test_k4_and_k5_run_cortex_without_private_and_other_cortex_entries_keep_it(self):
        for entry in ("K4", "K5", "K1"):  # resume reads the saved session, and --private saves none (#405)
            self.run_entry("cortex", entry)
            self.assertEqual("--private" in self.world.harness_starts()[-1]["args"], entry == "K1", entry)
            self.assertIn("--bypass", self.world.harness_starts()[-1]["args"], entry)

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

    def test_d4_sees_the_interrupted_agent_answer_from_the_hook_log_and_fails_without_its_interrupt_or_kept_word(self):
        seen = "D4 codex seen: the interrupted agent answered the follow-up with its earlier context\n"
        self.assertEqual(self.run_entry("codex", "D4"), seen)
        self.assertEqual(self.run_entry("codex", "D4", STANDIN_NO_COLLAB="1"), seen)  # the stream is not read
        start = self.world.harness_starts()[-1]
        self.assertIn("Step 2: call interrupt_agent for it. Step 3: send it this message with followup_task: ",
                      start["prompt"])
        self.assertNotIn("close_agent", start["prompt"])
        self.assertIn("-c", start["args"])
        self.assertIn(codex_c(""), start["args"])
        cases = {"STANDIN_NO_CLOSE": "the hook log shows no interrupt_agent call of the session's after the "
                                     "agent's first call",
                 "STANDIN_CLOSE_OTHER": "the interrupt_agent call names another agent",
                 "STANDIN_RESUME_OTHER": "the hook log shows no followup_task call to the agent after its interrupt",
                 "STANDIN_RESUME_FAIL": "the hook log shows no call of the agent's after the follow-up",
                 "STANDIN_RESUME_FRESH": "the agent that answered lacks its first brief's word, so it was not the "
                                         "same agent",
                 "STANDIN_RESUME_FROM_DISK": "the agent that answered lacks its first brief's word, so it was not "
                                             "the same agent"}
        for knob, fact in cases.items():
            self.assertEqual(self.run_entry("codex", "D4", STANDIN_NO_COLLAB="1", **{knob: "1"}),
                             f"D4 codex failed: {fact}\n", knob)
        # The interrupt and the follow-up may name the agent by the task_name its start gave it.
        self.assertEqual(self.run_entry("codex", "D4", STANDIN_NO_COLLAB="1", STANDIN_BY_TASK="1"), seen)
        self.assertEqual(self.run_entry("codex", "D4", STANDIN_NO_COLLAB="1", STANDIN_BY_TASK="1",
                                        STANDIN_CLOSE_OTHER="1"),
                         "D4 codex failed: the interrupt_agent call names another agent\n")
        # An empty hook log names the trust step whatever the output shows (#408).
        self.assertEqual(self.run_entry("codex", "D4", STANDIN_UNTRUSTED="1"), f"D4 codex failed: {UNTRUSTED}\n")
        self.assert_home_empty()

    def test_d3_reads_the_starts_and_agents_from_the_hook_log_and_measures_no_step_without_the_spawn_items(self):
        # The real output shows no spawn item, so the step is recorded as not measured, not failed.
        self.assertEqual(self.run_entry("codex", "D3", STANDIN_NO_COLLAB="1"),
                         "D3 codex recorded: both agents ran and the hook log shows 2 starts and 2 agents; the output "
                         "shows no spawn_agent item, so whether one model step made them was not measured\n")
        self.assertEqual(self.run_entry("codex", "D3", STANDIN_NO_COLLAB="1", STANDIN_STEP_APART="1"),
                         "D3 codex recorded: both agents ran and the hook log shows 2 starts and 2 agents; the output "
                         "shows no spawn_agent item, so whether one model step made them was not measured\n")
        self.assertIn("both with agent_type probe-reader, fork_turns none: the first",
                      self.world.harness_starts()[-1]["prompt"])
        self.assertEqual(self.run_entry("codex", "D3", STANDIN_NO_AGENT_TYPE="1"),
                         "D3 codex failed: both agents ran, but the hook log shows 0 starts of the reader role and 2 "
                         "agents of it, not 2 and 2\n")
        self.assertEqual(self.run_entry("codex", "D3", STANDIN_UNTRUSTED="1"), f"D3 codex failed: {UNTRUSTED}\n")
        self.assert_home_empty()

    def test_d3_prints_the_trust_step_when_the_hook_logged_nothing_and_the_output_shows_no_agent_start(self):
        # Codex's output shows no agent start, so a session whose only calls start agents shows no tool call (#408).
        self.assertEqual(self.run_entry("codex", "D3", STANDIN_UNTRUSTED="1", STANDIN_NO_COLLAB="1"),
                         f"D3 codex failed: {UNTRUSTED}\n")
        self.assertEqual(self.agents(), [("probe-reader", 1, "brief-d3-one.md", False, True),
                                         ("probe-reader", 1, "brief-d3-two.md", False, True)])

    def test_d5_runs_codex_without_the_temporary_folders_and_sees_the_write_outside(self):
        self.assertEqual(self.run_entry("codex", "D5"), "D5 codex seen: the agent wrote in its worktree outside the "
                                                        "session's writable directories\n")
        args = self.world.harness_starts()[-1]["args"]
        self.assertEqual(args[:-1], ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                                     *role_args(work_of(args), ("reader",)),
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

    def test_a2_is_seen_when_the_withheld_tool_was_absent_with_no_call_no_file_and_a_refused_ending(self):
        # As in Antigravity's real run: the tool is taken away, so the agent makes no write_file call at all.
        self.assertEqual(self.run_entry("antigravity", "A2", STANDIN_NO_TRY="1"),
                         "A2 antigravity seen: the withheld write_file tool was absent: the agent made no call to it, "
                         "wrote no file and reported it could not\n")
        start = self.world.harness_starts()[-1]
        self.assertEqual([s["toolCall"]["name"] for s in start["sent"]],
                         ["invoke_subagent", "run_command", "run_command"])
        self.assertEqual(self.run_entry("antigravity", "A2", STANDIN_NO_TRY="failed"),
                         "A2 antigravity failed: the agent made no write_file call and did not report it refused, so "
                         "the tool's absence is not shown\n")
        # A call of another tool to the marker is no write: with no file and a refused report the tool was absent.
        self.assertEqual(self.run_entry("antigravity", "A2", STANDIN_OTHER_TOOL="1"),
                         "A2 antigravity seen: the withheld write_file tool was absent: the agent made no call to it, "
                         "wrote no file and reported it could not\n")

    def test_a2_fails_on_a_written_file_another_tool_no_call_another_error_or_no_agent(self):
        cases = {"STANDIN_TOOLS_IGNORED": "the withheld tool wrote the file",
                 "STANDIN_SHELL_WRITE": "the agent wrote the file through run_command, not the withheld tool",
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
        self.assertIn("\ntools: [view_file, run_command, write_file, edit_file, invoke_subagent]\n",
                      definitions[".agents/agents/probe-author.md"])
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
