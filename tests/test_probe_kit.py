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
            "D3": "D3  codex  Two agent starts in one model step (not built)",
            "R1": "R1  cursor  The IDE chat (not probed, closed by reading 6) (not built)",
            "A7": "A7  antigravity  The model starts a stand-in skill described as typed only",
        }
        for entry, line in expected.items():
            self.assertEqual(lines[ids.index(entry)], line)
        self.assertEqual(sum("(not built)" not in line for line in lines), 9)


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
# commands, separated by ";;"; STANDIN_NO_HOOKS makes `/hooks` list none.
HOOK_HARNESS = r'''#!{python}
import json, os, re, subprocess, sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
prompt = args[args.index("-p") + 1] if name in ("claude", "cortex", "agy") else args[-1]
cwd, knob = Path.cwd(), os.environ.get
if name == "agy" and prompt == "/hooks":
    hooks = {} if knob("STANDIN_NO_HOOKS") else json.loads((cwd / ".agents" / "hooks.json").read_text())
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
for command, run_dir in commands:
    hook_cwd = str(run_dir if knob("STANDIN_HOOK_CWD") == "command" else cwd)
    if form == "settings":
        data = {"session_id": "''' + SESSION + r'''", "cwd": hook_cwd, "hook_event_name": "PreToolUse",
                "tool_name": "Bash", "tool_input": {"command": command}}
        if knob("STANDIN_AS_AGENT"):
            data["agent_id"] = "agent-1"
    elif form == "beforeShell":
        data = {"conversation_id": "''' + SESSION + r'''", "command": command, "cwd": hook_cwd}
    else:
        data = {"conversationId": "''' + SESSION + r'''", "cwd": hook_cwd,
                "toolCall": {"name": "run_command", "args": {"CommandLine": command, "Cwd": str(run_dir)}}}
    if knob("STANDIN_NO_CWD"):
        del data["cwd"]
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
                             "sent": sent, "decisions": decisions, "logs": sorted(p.name for p in logs.iterdir())}) + "\n")
print(json.dumps({"type": "result", "session_id": "''' + SESSION + r'''", "result": "done"}))
'''

# Stands in for uv: records its arguments, waits STANDIN_UV_SLEEP seconds, then runs the script with python.
UV = r'''#!{python}
import json, os, subprocess, sys, time
with open(os.environ["STANDIN_UV_CALLS"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
time.sleep(float(os.environ.get("STANDIN_UV_SLEEP", "0.2")))
assert sys.argv[1:5] == ["run", "--python", "3.13", "--no-project"]
sys.exit(subprocess.run([sys.executable, *sys.argv[5:]]).returncode)
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
CODEX_C = ('hooks.PreToolUse=[{matcher="Bash",hooks=[{type="command",command="python3 hooks/guard.py settings",'
           'timeout=20}]}]')
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
        "cursor": {".cursor/hooks.json": {"version": 1, "hooks": {"beforeShellExecution": [
            {"command": "python3 hooks/guard.py beforeShell"}]}}},
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
                       "--no-session-persistence", "--allowedTools", "Bash"],
            "cortex": ["-p", x1, "--output-format", "stream-json", "--private", "--bypass", "-c", CONNECTION],
            "codex": ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "-c", CODEX_C, x1],
            "cursor": ["-p", "--output-format", "stream-json", "--force", x1],
            "antigravity": ["-p", x1, "--output-format", "stream-json", "--mode", "accept-edits"],
        }
        for harness in HARNESS_COMMANDS:
            for where, fact in (("session", "the session's directory"), ("command", "the command's directory")):
                code, out, err = self.world.kit("run", harness, "X1", STANDIN_HOOK_CWD=where)
                self.assertEqual((code, out), (0, f"X1 {harness} recorded: hook input cwd is {fact}\n"))
                self.assert_private(out, err)
            start = self.world.harness_starts()[-1]
            self.assertEqual(start["args"], argv[harness])
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
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"^X1 claude recorded: hook input cwd is the session's directory\n"
                              r"X2 claude recorded: uv run adds -?\d+ ms a call \(median of 5: \d+ ms, \d+ ms without\)\n$")
        self.assert_private(out, err)

    def test_a5_is_seen_when_the_inner_agy_call_lists_the_probe_hook(self):
        code, out, err = self.world.kit("run", "antigravity", "A5")
        self.assertEqual((code, out), (0, "A5 antigravity seen: the hook list names the probe's hook\n"))
        self.assert_private(out, err)
        (start,) = self.world.harness_starts()
        self.assertEqual(start["prompt"], 'Run `agy -p "/hooks" > hooks-list.txt`.')
        self.assertEqual(start["decisions"], [['agy -p "/hooks" > hooks-list.txt', "allow"]])
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_NO_HOOKS="1")
        self.assertEqual((code, out), (1, "A5 antigravity failed: the hook list does not name the probe's hook\n"))
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_FORCE_DENY="1")
        self.assertEqual((code, out), (1, "A5 antigravity failed: the agy -p \"/hooks\" call left no list\n"))
        code, out, _ = self.world.kit("run", "antigravity", "A5", STANDIN_SKIP_HOOK="1")
        self.assertEqual((code, out), (1, "A5 antigravity failed: the hook logged no agy -p \"/hooks\" command\n"))
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
            ("codex", [], "codex", ["codex", "-c", CODEX_C]),
            ("cursor", [], "cursor", ["cursor-agent"]),
            ("antigravity", [], "antigravity", ["agy"]),
        ]
        for number, (harness, extra, label, argv) in enumerate(cases, 1):
            code, out, err = self.world.kit("x7", harness, *extra)
            self.assertEqual((code, err), (0, ""), label)
            run = self.world.hc_calls()[-1]
            name, work = run[5], Path(run[7])
            self.assertRegex(name, rf"^probe-{harness}-x7-{label.split(' ')[1] + '-' if ' ' in label else ''}\d+$")
            self.assertEqual(run, ["run", "--json", "--bg", "--no-notify", "--name", name, "--cwd", str(work), *argv])
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


if __name__ == "__main__":
    unittest.main()
