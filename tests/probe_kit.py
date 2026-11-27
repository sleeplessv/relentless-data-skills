#!/usr/bin/env python3
"""Probe kit: run one harness headless through Herdr and judge each entry from the files it left.

Usage:
  python3 tests/probe_kit.py list
  python3 tests/probe_kit.py run HARNESS ENTRY... [--connection NAME] [--time-limit SECONDS] [--poll SECONDS]
  python3 tests/probe_kit.py x7 HARNESS [--mode bypass|auto] [--connection NAME]

`list` prints every entry id of the not-observed list with its harnesses. An
entry the kit cannot run yet is marked "not built".

`run` takes a harness (claude, cortex, codex, cursor or antigravity) and one or more
entry ids, or `all` for every built entry of that harness. Each probe makes a
fresh temporary folder with `git init` and no remote, writes the stand-in skill
into the harness's project skill folder, and starts the harness's headless
command with `hc run --bg`. It waits until `hc get` reports `state: finished`,
never for `hc wait`, and past the time limit (default 300 seconds) it ends the
terminal and records the entry as failed. X6 and X9 type the stand-in skill as
`/name`, or `$name` on Cortex Code. X8 types a skill name that is not installed,
in the same form. K6 and A7 do not type the skill: their prompt is a request that
matches its description.

X1, X2 and A5 add the stand-in guard hook to the probe folder and register it at
project level, in the form the guard research note gives for each harness:
.claude/settings.json, .cortex/settings.json, .cursor/hooks.json,
.agents/hooks.json, and a -c override on the Codex command line. Nothing is
written to a user-level settings file. The hook appends each input it gets to
logs/hook.jsonl. It refuses `gh pr merge` and `gh pr ready`, refuses
merge-script.sh when the input marks an agent, and asks on oneway-probe.sh.
merge-script.sh, oneway-probe.sh and control-probe.sh each write a marker file
in logs/ when they run, so a refused command leaves none.

X1 asks the agent to run control-probe.sh from the folder sub. It compares the
hook input's cwd with the probe folder and with the directory the stand-in
recorded. X2 starts no session. It times the hook command as registered,
python3 and then `uv run --python 3.13 --no-project`, 5 calls each, and prints
the difference of the two medians. A5 asks the agent to run `agy -p "/hooks"`
and save the list and the call's exit status. It is seen when the call exited 0
and the list names the stand-in hook.

`x7` makes a probe folder with the hook the same way and starts the harness's
terminal UI in it with `hc run --bg`. It prints the `hc send` and `hc read`
commands for the owner, then the commands that list the folder's logs and remove
it. It gives no verdict. Claude Code needs --mode bypass or --mode auto. Cortex
Code runs with --bypass. Codex gets a `prompt` rule for oneway-probe.sh in the
folder's .codex/rules/.

Cortex Code needs --connection, the Snowflake connection its runs spend. The kit
passes it on the harness's command line only: it is not in the terminal name, it
is replaced by <connection> before any output reaches a file, the hook writes
<connection> in its place in logs/hook.jsonl, and the kit never prints it.

The kit judges from files: marker files, the output stream and the folder. The
raw output goes to probes/<run id>/ in the machine directory, $DELIVER_STATE_DIR
(default ~/.local/state/deliver). Each entry prints one line: the id, the
harness, seen, failed or recorded, and the fact in a few words. recorded is a
fact entry that was seen. A line holds no session id and no local path.

Exit status: 0 when every entry is seen or recorded, 1 when any failed, 2 when
hc or the harness command is missing or the command line is wrong.
`x7` exits 0 once the terminal UI has started.

The kit is never installed. Its tests are tests/test_probe_kit.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import threading
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ALL = ("claude", "cortex", "codex", "cursor", "antigravity")
NOT_CLAUDE = ALL[1:]

# Every entry of spec #381's two tables: id, harnesses, what it probes.
ENTRIES = {
    "X1": (ALL, "Hook input cwd"),
    "X2": (ALL, "What uv run adds to a hook before each shell command"),
    "X3": (ALL, "An agent reads a brief kept in the shared git directory"),
    "X4": (ALL, "An agent writes into .deliver/ in its own worktree"),
    "X5": (ALL, "An agent's model and tokens in the headless output"),
    "X6": (NOT_CLAUDE, "Detection with CLAUDECODE set"),
    "X7": (ALL, "The hook's ask with the owner present"),
    "X8": (NOT_CLAUDE, "A typed skill name that is not installed"),
    "X9": (("codex", "cursor", "antigravity"), "Who resolves a typed command for a skill closed to model invocation"),
    "C1": (("claude",), "A plugin from a marketplace loads its skill, agents/ and hooks/hooks.json"),
    "C2": (("claude",), "A role's definition file loads a skill closed to model invocation"),
    "C3": (("claude",), "claude plugin uninstall after the marketplace entry is gone"),
    "K1": (("cortex",), "Default nesting limit"),
    "K2": (("cortex",), "maxSubagentDepth at 2, two reviewers under an author"),
    "K3": (("cortex",), "A background agent starts foreground agents"),
    "K4": (("cortex",), "Resuming a killed agent"),
    "K5": (("cortex",), "The model a resumed agent runs on"),
    "K6": (("cortex",), "The command line loads an installed skill from its description"),
    "D1": (("codex",), "A trusted hook refuses a command and sees the agent marker"),
    "D2": (("codex",), "The hook name of the agent-starting tool"),
    "D3": (("codex",), "Two agent starts in one model step"),
    "D4": (("codex",), "Calling back an agent that was unloaded"),
    "D5": (("codex",), "An agent writes in a worktree outside the writable directories"),
    "D6": (("codex",), "The hook refuses the edit tool to a reviewer"),
    "R1": (("cursor",), "The IDE chat (not probed, closed by reading 6)"),
    "R2": (("cursor",), "Any cap on agents at once"),
    "R3": (("cursor",), "subagentStart fires"),
    "R4": (("cursor",), "Loading Claude Code plugins"),
    "R5": (("cursor",), "A definition file in ~/.cursor/agents/ loads"),
    "A1": (("antigravity",), "The app and the IDE (not probed, closed by reading 6)"),
    "A2": (("antigravity",), "A tool a definition file withholds is truly absent"),
    "A3": (("antigravity",), "Which tier wins when the call and the file both name one"),
    "A4": (("antigravity",), "Any cap on agents at once"),
    "A5": (("antigravity",), "agy -p \"/hooks\" called from inside a session"),
    "A6": (("antigravity",), "The hook refuses the merge stand-in to an agent"),
    "A7": (("antigravity",), "The model starts a stand-in skill described as typed only"),
}

# The headless command of each harness (#188 rule 3, with the prototype's permission flags).
# {prompt} is replaced. Codex never takes --ephemeral: it breaks starting agents.
COMMANDS = {
    "cortex": ["cortex", "-p", "{prompt}", "--output-format", "stream-json", "--private", "--bypass"],
    "codex": ["codex", "exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "{prompt}"],
    "cursor": ["cursor-agent", "-p", "--output-format", "stream-json", "--force", "{prompt}"],
    "antigravity": ["agy", "-p", "{prompt}", "--output-format", "stream-json", "--mode", "accept-edits"],
}
SKILL_DIRS = {"cortex": ".cortex/skills", "codex": ".agents/skills", "cursor": ".cursor/skills",
              "antigravity": ".agents/skills"}
DETECTION = {"cortex": "CORTEX_SESSION_ID", "codex": "CODEX_THREAD_ID", "cursor": "CURSOR_AGENT",
             "antigravity": "ANTIGRAVITY_AGENT"}

SKILL = "probe-standin"
MISSING_SKILL = "probe-not-installed"
MARKER = "probe-marker.txt"
ENV_NAMES = "probe-env-names.txt"
SKILL_TEXT = """---
name: {name}
description: Records a probe run for the probe kit. Start it only when the owner types its name, never on your own.
disable-model-invocation: true
---

Write the word {codeword} and nothing else to the file {marker} in the current folder. Then carry out the rest of the request, if there is one.
"""
# Codex's own switch that keeps a skill typed-only.
CODEX_POLICY = "policy:\n  allow_implicit_invocation: false\n"


@dataclass
class Finished:
    """What a probe left: its folder, the output stream, the harness's exit code and the skill's codeword."""
    work: Path
    out: str
    exit_code: int | None
    codeword: str

    def marker_holds_codeword(self) -> bool:
        marker = self.work / MARKER
        return marker.is_file() and self.codeword in marker.read_text(errors="replace")


def typed(harness: str, name: str) -> str:
    return ("$" if harness == "cortex" else "/") + name


def judge_x6(harness: str, run: Finished) -> tuple[str, str]:
    var = DETECTION[harness]
    names_file = run.work / ENV_NAMES
    if not names_file.is_file():
        return "failed", "no environment list written"
    names = set(names_file.read_text(errors="replace").split())
    if "CLAUDECODE" not in names:
        return "failed", "CLAUDECODE did not reach the harness"
    if var not in names:
        return "failed", f"{var} not set beside CLAUDECODE"
    return "seen", f"{var} set beside CLAUDECODE"


def judge_x8(harness: str, run: Finished) -> tuple[str, str]:
    return "recorded", f"harness exited {run.exit_code}, its output is kept"


def reads_skill_file(event: object) -> bool:
    """Whether a tool or command event names this stand-in's skill file; a message that names it does not count."""
    if isinstance(event, list):
        return any(reads_skill_file(item) for item in event)
    if not isinstance(event, dict):
        return False
    kind = str(event.get("type", "")).lower()
    if any(word in kind for word in ("tool", "command", "function_call")) or "tool_call" in event:
        return f"{SKILL}/SKILL.md" in json.dumps(event)
    return any(reads_skill_file(value) for value in event.values())


def judge_x9(harness: str, run: Finished) -> tuple[str, str]:
    if not run.marker_holds_codeword():
        return "failed", "the typed command did not start the skill"
    events = []
    for line in run.out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    if reads_skill_file(events):
        return "recorded", "the model read the skill file"
    return "recorded", "the stream does not show who resolved it"


def judge_from_description(harness: str, run: Finished) -> tuple[str, str]:
    if run.marker_holds_codeword():
        return "recorded", "the model started the skill untyped"
    return "recorded", "the skill was not started untyped"


@dataclass
class Probe:
    prompt: Callable[[str], str]
    judge: Callable[[str, Finished], tuple[str, str]]
    env: str = ""  # assignments put before the harness command
    any_exit: bool = False  # judged whatever the harness's exit code
    hook: bool = False  # the folder gets the stand-in guard hook, its registration and the stand-in commands
    direct: bool = False  # judged without a terminal or a harness session


UNTYPED = "Record a probe run for the probe kit."
PROBES = {
    "X6": Probe(lambda h: f"{typed(h, SKILL)} Then run this shell command: env | cut -d= -f1 | sort > {ENV_NAMES}",
                judge_x6, env="CLAUDECODE=1"),
    "X8": Probe(lambda h: typed(h, MISSING_SKILL), judge_x8, any_exit=True),
    "X9": Probe(lambda h: typed(h, SKILL), judge_x9),
    "K6": Probe(lambda h: UNTYPED, judge_from_description),
    "A7": Probe(lambda h: UNTYPED, judge_from_description),
}


class KitError(Exception):
    """A wrong command line or a missing program: one line on standard error, exit 2."""


def relay(out: str, err: str, secret: str, argv: list[str]) -> int:
    """Run the harness inside the terminal, replacing the secret in its output before any byte reaches a file."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def copy(stream, path: str) -> None:
        with open(path, "wb") as sink:
            for line in stream:
                sink.write(line.replace(secret.encode(), b"<connection>") if secret else line)
                sink.flush()

    copies = [threading.Thread(target=copy, args=pair) for pair in ((proc.stdout, out), (proc.stderr, err))]
    for thread in copies:
        thread.start()
    for thread in copies:
        thread.join()
    return proc.wait()


def hc(command: str, *args: str) -> dict:
    done = subprocess.run(["hc", command, "--json", *args], capture_output=True, text=True)
    try:
        got = json.loads(done.stdout)
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def make_folder(harness: str, codeword: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="probe-")).resolve()
    work = root / "work"
    skill = work / SKILL_DIRS[harness] / SKILL
    (skill / "agents").mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL_TEXT.format(name=SKILL, marker=MARKER, codeword=codeword))
    (skill / "agents" / "openai.yaml").write_text(CODEX_POLICY)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    return root


def wait(address: str, limit: float, poll: float) -> dict | None:
    """`hc get` until the terminal is finished; None once the time limit has passed and the terminal is ended."""
    deadline = time.monotonic() + limit
    while True:
        info = hc("get", address)
        if info.get("state") == "finished":
            return info
        if time.monotonic() >= deadline:
            hc("kill", address)
            return None
        time.sleep(poll)


def run_probe(harness: str, entry: str, args: argparse.Namespace, saved: Path) -> tuple[str, str]:
    probe = PROBES[entry]
    codeword = f"probe-{secrets.token_hex(4)}"
    root = make_folder(harness, codeword)
    if probe.hook:
        write_guard(harness, root / "work")
    out, err = root / "out.jsonl", root / "err.txt"
    argv = [part.replace("{prompt}", probe.prompt(harness)) for part in COMMANDS[harness]]
    if harness == "cortex":
        argv += ["-c", args.connection]
    if probe.hook and harness == "codex":
        argv[-1:-1] = codex_hook(root / "work")  # before the prompt, which comes last
    relayed = [sys.executable, str(Path(__file__).resolve()), "--relay", str(out), str(err), args.connection or "", *argv]
    line = f"{probe.env} {shlex.join(relayed)}".lstrip()
    if args.connection:  # the hook hides it in its log, as the relay does in the output
        line = f"{HIDE_VAR}={shlex.quote(args.connection)} {line}"
    name = f"probe-{harness}-{entry.lower()}-{os.getpid()}"
    address, ended = None, False
    try:
        if probe.direct:
            return probe.judge(harness, Finished(root / "work", "", None, codeword))
        started = hc("run", "--bg", "--no-notify", "--name", name, "--cwd", str(root / "work"), "bash", "-c", line)
        address = started.get("address")
        if address is None:
            return "failed", "hc run did not start the terminal"
        info = wait(address, args.time_limit, args.poll)
        ended = True
        for source in (out, err):
            text = source.read_text(errors="replace") if source.is_file() else ""
            (saved / f"{entry}-{harness}{source.suffix}").write_text(text)
        hook_log_file = root / "work" / "logs" / "hook.jsonl"
        if hook_log_file.is_file():
            (saved / f"{entry}-{harness}-hook.jsonl").write_text(hide(hook_log_file.read_text(), args.connection))
        if info is None:
            return "failed", f"no finish within {args.time_limit:g} seconds, terminal ended"
        hc("rm", address)
        finished = Finished(root / "work", (saved / f"{entry}-{harness}.jsonl").read_text(),
                            info.get("exit_code"), codeword)
        if finished.exit_code != 0 and not probe.any_exit:
            return "failed", f"harness exited {finished.exit_code}"
        return probe.judge(harness, finished)
    finally:
        if address is not None and not ended:
            hc("kill", address)  # interrupted while waiting: end the terminal
        shutil.rmtree(root, ignore_errors=True)


def chosen_entries(harness: str, wanted: list[str]) -> list[str]:
    if harness not in ALL:
        raise KitError(f"unknown harness {harness!r}; harnesses: {', '.join(ALL)}")
    if wanted == ["all"]:
        built = [e for e in PROBES if harness in ENTRIES[e][0]]
        if not built:
            raise KitError(f"no entry is built for {harness} yet")
        return built
    for entry in wanted:
        if entry not in ENTRIES:
            raise KitError(f"unknown entry {entry!r}; `list` shows every entry")
        if harness not in ENTRIES[entry][0]:
            raise KitError(f"{entry} does not run on {harness}")
        if entry == "X7":
            raise KitError("X7 is not run headless; `x7 HARNESS` starts the terminal UI for the owner")
        if entry not in PROBES:
            raise KitError(f"{entry} is not built yet")
    return list(dict.fromkeys(wanted))


def run(args: argparse.Namespace) -> int:
    entries = chosen_entries(args.harness, args.entries)
    if args.harness == "cortex" and not args.connection:
        raise KitError("cortex needs --connection, the Snowflake connection its runs spend")
    for program in ("hc", COMMANDS[args.harness][0]):
        if shutil.which(program) is None:
            raise KitError(f"{program} is not on PATH")
    state = Path(os.environ.get("DELIVER_STATE_DIR") or Path.home() / ".local" / "state" / "deliver")
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{os.getpid()}"
    saved = state / "probes" / run_id
    saved.mkdir(mode=0o700, parents=True)
    failed = False
    for entry in entries:
        verdict, fact = run_probe(args.harness, entry, args, saved)
        failed |= verdict == "failed"
        print(f"{entry} {args.harness} {verdict}: {fact}", flush=True)
    print(f"probe_kit: raw output kept in probes/{run_id}/ of the machine directory", file=sys.stderr)
    return 1 if failed else 0


# The stand-in guard hook, its registration, the stand-in commands, and X1, X2, A5 and X7 (#383).

# Claude Code: the guard research note's flags. --setting-sources project keeps the user's own settings
# and hooks out; --allowedTools names the shell tool because an untrusted folder ignores the project's
# allow rules.
COMMANDS["claude"] = ["claude", "-p", "{prompt}", "--output-format", "stream-json", "--verbose",
                      "--setting-sources", "project", "--no-session-persistence", "--allowedTools", "Bash"]
SKILL_DIRS["claude"] = ".claude/skills"

# How each harness shapes the hook's input and answer, named as in the research fixture.
HOOK_FORMS = {"claude": "settings", "cortex": "settings", "codex": "settings", "cursor": "beforeShell",
              "antigravity": "pre"}
HOOK_NAME = "probe-guard"  # the hook's name in Antigravity's hooks.json, which `agy -p "/hooks"` lists
HIDE_VAR = "PROBE_KIT_CONNECTION"  # GUARD reads the connection from this variable and logs <connection> instead


def hide(text: str, secret: str | None) -> str:
    return text.replace(secret, "<connection>") if secret else text


def codex_hook(work: Path) -> list[str]:
    """The hook inline on Codex, as the research note gives it, with the script's absolute path."""
    return ["-c", 'hooks.PreToolUse=[{matcher="Bash",hooks=[{type="command",'
                  f'command="{hook_command("codex", work)}",timeout=20}}]}}]']


CODEX_RULE = ('prefix_rule(pattern = ["./oneway-probe.sh"], decision = "prompt",\n'
              '    justification = "one-way command, needs the owner\'s answer")\n')
GUARD = r'''import json, os, sys
from pathlib import Path

# The stand-in guard hook, seeded from the guard research fixture. Its argument names the
# input and answer shape: settings, beforeShell (Cursor) or pre (Antigravity). sessionStart
# (Cursor) is logged only.
form = sys.argv[1]
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except ValueError:
    data = None
if not isinstance(data, dict):
    data = {"unparsed": raw}
cmd = ""
if form == "beforeShell":
    cmd = str(data.get("command") or "")
elif form == "pre":
    cmd = json.dumps((data.get("toolCall") or {}).get("args") or {})
elif form == "settings":
    cmd = str((data.get("tool_input") or {}).get("command") or "")
is_helper = "agent_id" in data
line = json.dumps({"form": form, "command": cmd, "hook_cwd": os.getcwd(), "input": data})
secret = os.environ.get("PROBE_KIT_CONNECTION", "")
if secret:  # the Cortex Code connection never reaches the log
    line = line.replace(json.dumps(secret)[1:-1], "<connection>")
with open(Path(__file__).resolve().parent.parent / "logs" / "hook.jsonl", "a") as log:
    log.write(line + "\n")
if form == "sessionStart":  # Cursor's session start: logged only, no decision
    sys.exit(0)


def out(decision, reason):
    if form == "beforeShell":
        print(json.dumps({"permission": decision, "user_message": reason, "agent_message": reason}))
    elif form == "pre":  # Antigravity refuses a call whose hook prints no decision
        print(json.dumps({"decision": decision, "reason": reason}))
    elif decision != "allow":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                                 "permissionDecisionReason": reason}}))
    sys.exit(0)


if "gh pr merge" in cmd or "gh pr ready" in cmd:
    out("deny", "GUARD-A: raw gh pr merge/ready is refused to every agent")
if "merge-script.sh" in cmd and is_helper:
    out("deny", "GUARD-B: the merge script is refused to a helper")
if "oneway-probe" in cmd:
    out("ask", "GUARD-C: one-way command, needs the owner's answer")
out("allow", "")
'''
# Each stand-in command prints a line and writes a marker file, holding the directory it ran in, to logs/.
STANDINS = {
    "merge-script.sh": 'echo MERGE-SCRIPT-RAN\npwd -P > {logs}/merge-ran.marker\n',
    "oneway-probe.sh": 'echo "ONEWAY-PROBE-RAN $1"\npwd -P > {logs}/"oneway-ran-$1.marker"\n',
    "control-probe.sh": 'echo "CONTROL-PROBE-RAN $1"\npwd -P > {logs}/"control-ran-$1.marker"\n',
}


def hook_command(harness: str, work: Path) -> str:
    form = HOOK_FORMS[harness]
    if harness == "claude":
        return f'python3 "$CLAUDE_PROJECT_DIR/hooks/guard.py" {form}'
    if harness == "cursor":
        return f"python3 hooks/guard.py {form}"
    return f"python3 {shlex.quote(str(work / 'hooks' / 'guard.py'))} {form}"


def write_guard(harness: str, work: Path) -> None:
    """The hook, its project-level registration, the stand-in commands, logs/ and an empty folder sub/."""
    for folder in ("hooks", "logs", "sub"):
        (work / folder).mkdir()
    (work / "hooks" / "guard.py").write_text(GUARD)
    for name, body in STANDINS.items():
        (work / name).write_text("#!/bin/sh\n" + body.format(logs=shlex.quote(str(work / "logs"))))
        (work / name).chmod(0o755)
    command = hook_command(harness, work)
    settings = {"hooks": {"PreToolUse": [{"matcher": "bash" if harness == "cortex" else "Bash",
                                          "hooks": [{"type": "command", "command": command}]}]}}
    files = {
        "claude": (".claude/settings.json", settings),
        "cortex": (".cortex/settings.json", settings),
        "cursor": (".cursor/hooks.json", {"version": 1, "hooks": {
            "beforeShellExecution": [{"command": command}],
            "sessionStart": [{"command": "python3 hooks/guard.py sessionStart"}]}}),
        "antigravity": (".agents/hooks.json", {HOOK_NAME: {"PreToolUse": [{"matcher": "", "hooks": [
            {"type": "command", "command": command, "timeout": 20}]}]}}),
    }
    if harness in files:
        path, body = files[harness]
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(json.dumps(body, indent=2) + "\n")


def hook_log(work: Path) -> list[dict]:
    log = work / "logs" / "hook.jsonl"
    lines = []
    for line in (log.read_text(errors="replace").splitlines() if log.is_file() else []):
        try:
            lines.append(json.loads(line))
        except ValueError:
            pass
    return [line for line in lines if isinstance(line, dict)]


def judge_x1(harness: str, run: Finished) -> tuple[str, str]:
    logged = [line for line in hook_log(run.work) if "control-probe.sh x1" in str(line.get("command"))]
    if not logged:
        return "failed", "the hook logged no input for the control stand-in"
    marker = run.work / "logs" / "control-ran-x1.marker"
    if not marker.is_file():
        return "failed", "the control stand-in left no marker"
    ran_in = Path(marker.read_text(errors="replace").strip()).resolve()
    given = (logged[-1].get("input") or {}).get("cwd")
    if not given:
        return "failed", "the hook input holds no cwd"
    if ran_in == run.work.resolve():
        return "failed", "the stand-in ran in the session's directory, so the two cannot be told apart"
    given = Path(given).resolve()
    if given == ran_in:
        return "recorded", "hook input cwd is the command's directory"
    if given == run.work.resolve():
        return "recorded", "hook input cwd is the session's directory"
    return "failed", "hook input cwd is neither the session's nor the command's directory"


def sample_input(harness: str, command: str, cwd: Path) -> dict:
    """A shell command in the hook input shape of the harness."""
    if HOOK_FORMS[harness] == "beforeShell":
        return {"command": command, "cwd": str(cwd)}
    if HOOK_FORMS[harness] == "pre":
        return {"toolCall": {"name": "run_command", "args": {"CommandLine": command}}, "cwd": str(cwd)}
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
            "cwd": str(cwd)}


def judge_x2(harness: str, run: Finished) -> tuple[str, str]:
    """Time the hook command 5 times with python3 and 5 times under uv run; compare the medians."""
    if shutil.which("uv") is None:
        return "failed", "uv is not on PATH"
    hook, form = str(run.work / "hooks" / "guard.py"), HOOK_FORMS[harness]
    sample = json.dumps(sample_input(harness, "./control-probe.sh x2", run.work))
    medians = []
    for argv in (["python3", hook, form], ["uv", "run", "--python", "3.13", "--no-project", hook, form]):
        times = []
        for _ in range(5):
            start = time.perf_counter()
            done = subprocess.run(argv, input=sample, capture_output=True, text=True, cwd=run.work)
            times.append(time.perf_counter() - start)
            if done.returncode != 0:
                return "failed", f"the hook under {argv[0]} exited {done.returncode}"
        medians.append(statistics.median(times) * 1000)
    logged = len(hook_log(run.work))
    if logged != 10:
        return "failed", f"the hook logged {logged} of its 10 calls"
    plain, under_uv = medians
    return "recorded", f"uv run adds {under_uv - plain:.0f} ms a call (median of 5: {under_uv:.0f} ms, {plain:.0f} ms without)"


HOOKS_LIST = "hooks-list.txt"
HOOKS_STATUS = "hooks-list.status"  # the exit status of the inner agy -p "/hooks"


def judge_a5(harness: str, run: Finished) -> tuple[str, str]:
    if not any('agy -p' in str(line.get("command")) and "/hooks" in str(line.get("command"))
               for line in hook_log(run.work)):
        return "failed", "the hook logged no agy -p \"/hooks\" command"
    listing = run.work / HOOKS_LIST
    if not listing.is_file():
        return "failed", "the agy -p \"/hooks\" call left no list"
    status = run.work / HOOKS_STATUS
    code = status.read_text(errors="replace").strip() if status.is_file() else ""
    if code != "0":
        return "failed", f"the agy -p \"/hooks\" call exited {code}" if code else "the agy -p \"/hooks\" call left no exit status"
    if not re.search(rf"(?<![\w.-]){re.escape(HOOK_NAME)}(?![\w.-])", listing.read_text(errors="replace")):
        return "failed", "the hook list does not name the probe's hook"
    return "seen", "the hook list names the probe's hook"


PROBES["X1"] = Probe(lambda h: "Run `../control-probe.sh x1` from the folder `sub`.", judge_x1, hook=True)
PROBES["X2"] = Probe(lambda h: "", judge_x2, hook=True, direct=True)
PROBES["A5"] = Probe(lambda h: f'Run `agy -p "/hooks" > {HOOKS_LIST}; echo $? > {HOOKS_STATUS}`.', judge_a5,
                     hook=True)

X7_MODES = {"bypass": "bypassPermissions", "auto": "auto"}


def x7_command(harness: str, args: argparse.Namespace, work: Path) -> list[str]:
    """The harness's terminal UI: Claude Code in the chosen mode, Cortex Code with --bypass."""
    if harness == "claude":
        return ["claude", "--setting-sources", "project", "--permission-mode", X7_MODES[args.mode]]
    if harness == "cortex":
        return ["env", f"{HIDE_VAR}={args.connection}", "cortex", "--bypass", "-c", args.connection]
    if harness == "codex":
        return ["codex", *codex_hook(work)]
    return [COMMANDS[harness][0]]


def x7(args: argparse.Namespace) -> int:
    harness, mode = args.harness, args.mode
    if harness not in ALL:
        raise KitError(f"unknown harness {harness!r}; harnesses: {', '.join(ALL)}")
    if harness == "claude" and mode is None:
        raise KitError("x7 on claude needs --mode bypass or --mode auto")
    if harness != "claude" and mode is not None:
        raise KitError("--mode is for claude only")
    if harness == "cortex" and not args.connection:
        raise KitError("cortex needs --connection, the Snowflake connection its runs spend")
    for program in ("hc", COMMANDS[harness][0]):
        if shutil.which(program) is None:
            raise KitError(f"{program} is not on PATH")
    root = make_folder(harness, f"probe-{secrets.token_hex(4)}")
    work = root / "work"
    write_guard(harness, work)
    if harness == "codex":
        (work / ".codex" / "rules").mkdir(parents=True)
        (work / ".codex" / "rules" / "guards.rules").write_text(CODEX_RULE)
    name = "-".join(["probe", harness, "x7", *([mode] if mode else []), str(os.getpid())])
    started = hc("run", "--bg", "--no-notify", "--name", name, "--cwd", str(work), *x7_command(harness, args, work))
    if started.get("address") is None:
        shutil.rmtree(root, ignore_errors=True)
        print("probe_kit: hc run did not start the terminal", file=sys.stderr)
        return 1
    folder = f'"${{TMPDIR:-/tmp}}"/{root.name}'
    print(f"X7 {harness}{' ' + mode if mode else ''}: the terminal UI runs in terminal {name}, "
          f"in the probe folder {root.name}. Run these in order:")
    for command in (f"hc read {name} --lines 40", f"hc send {name} 'run ./oneway-probe.sh x7'",
                    f"hc read {name} --lines 40", f"ls {folder}/work/logs  # oneway-ran-x7.marker: the command ran",
                    f"hc kill {name}", f"rm -rf {folder}"):
        print(f"  {command}")
    return 0


def show_list() -> int:
    for entry, (harnesses, what) in ENTRIES.items():
        built = "" if entry in PROBES or entry == "X7" else " (not built)"
        print(f"{entry}  {', '.join(harnesses)}  {what}{built}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--relay"]:  # inside the terminal: python3 probe_kit.py --relay OUT ERR SECRET HARNESS-ARGV...
        return relay(argv[1], argv[2], argv[3], argv[4:])
    parser = argparse.ArgumentParser(prog="probe_kit.py", description=__doc__.split("\n\n", 1)[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="print every entry id with its harnesses")
    runner = commands.add_parser("run", help="run entries on one harness")
    runner.add_argument("harness")
    runner.add_argument("entries", nargs="+", metavar="ENTRY", help="entry ids, or all")
    runner.add_argument("--connection", help="the Snowflake connection; required for cortex, never printed")
    runner.add_argument("--time-limit", type=float, default=300.0, help="seconds per probe (default 300)")
    runner.add_argument("--poll", type=float, default=2.0, help="seconds between hc get calls (default 2)")
    owner = commands.add_parser("x7", help="start a harness's terminal UI for X7 and print the owner's commands")
    owner.add_argument("harness")
    owner.add_argument("--mode", choices=tuple(X7_MODES), help="Claude Code's permission mode; required for claude")
    owner.add_argument("--connection", help="the Snowflake connection; required for cortex, never printed")
    args = parser.parse_args(argv)
    try:
        return show_list() if args.command == "list" else x7(args) if args.command == "x7" else run(args)
    except KitError as error:
        print(f"probe_kit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
