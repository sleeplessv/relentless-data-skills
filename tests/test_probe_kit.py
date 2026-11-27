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

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
            "X1": f"X1  {every}  Hook input cwd (not built)",
            "X6": "X6  cortex, codex, cursor, antigravity  Detection with CLAUDECODE set",
            "X8": "X8  cortex, codex, cursor, antigravity  A typed skill name that is not installed",
            "X9": "X9  codex, cursor, antigravity  Who resolves a typed command for a skill closed to model invocation",
            "C1": "C1  claude  A plugin from a marketplace loads its skill, agents/ and hooks/hooks.json (not built)",
            "K6": "K6  cortex  The command line loads an installed skill from its description",
            "D3": "D3  codex  Two agent starts in one model step (not built)",
            "R1": "R1  cursor  The IDE chat (not probed, closed by reading 6) (not built)",
            "A7": "A7  antigravity  The model starts a stand-in skill described as typed only",
        }
        for entry, line in expected.items():
            self.assertEqual(lines[ids.index(entry)], line)
        self.assertEqual(sum("(not built)" not in line for line in lines), 8)


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
                                          "X5 codex failed: no agent of the reader role ran\n"))
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
        self.assertEqual((code, out), (0, "X3 claude seen: an agent of the reader role wrote the marker its brief "
                                          "names\n"
                                          "X4 claude seen: an agent of the reader role wrote into .deliver/ of its "
                                          "worktree\n"
                                          "X5 claude recorded: agent model standin-agent-model-claude at assistant "
                                          "event .message.model, tokens input_tokens=5 output_tokens=70 at "
                                          "assistant event .message.usage; not tied to the agent model "
                                          "standin-session-model-claude at system event .model, tokens "
                                          "input_tokens=12 output_tokens=340 at result event .usage\n"))
        self.assertEqual(self.world.harness_starts()[0]["args"][2:],
                         ["--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
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


if __name__ == "__main__":
    unittest.main()
