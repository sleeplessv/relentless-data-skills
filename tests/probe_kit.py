#!/usr/bin/env python3
"""Probe kit: run one harness headless through Herdr and judge each entry from the files it left.

Usage:
  python3 tests/probe_kit.py list
  python3 tests/probe_kit.py run HARNESS ENTRY... [--connection NAME] [--time-limit SECONDS] [--poll SECONDS]
  python3 tests/probe_kit.py x7 HARNESS [--mode bypass|auto] [--connection NAME]

`list` prints every entry id of the not-observed list with its harnesses. An
entry the kit cannot run yet is marked "not built".

`run` takes a harness (claude, cortex, codex, cursor or antigravity) and one or
more entry ids, or `all` for every built entry of that harness. Each probe makes a
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

X3, X4 and X5 start one agent. The kit writes a stand-in reader role and a
stand-in reviewer role into the harness's project definition folder, cuts the
agent's own worktree inside the probe folder, and saves the entry's brief in the
shared git directory under deliver/branches/probe-agent/. The prompt asks the
session to start the reader with the one line `Read <path> and follow it.` The
brief asks for a word of its own and the role's word. The kit draws each word at
random, and none is in the prompt. X3 is seen when both words are in the marker
file the brief names. X4 is seen when both are in the file the brief names in
.deliver/ of the agent's worktree. A word the kit did not give the reader, such
as the reviewer's, fails the entry. X5 needs the X3 marker too, then reads the
model and the token counts from the fields each harness's output keeps them in,
and prints where. A field counts as the agent's only in an event the output ties
to the agent's tool call; the rest prints as not tied to the agent. A field the
output lacks prints as absent, and a token count the output leaves empty or out
prints blank, never as 0.

D1, D2 and D6 on Codex, R3 on Cursor and A6 on Antigravity add the hook and
start one agent as X3 does. The brief names a stand-in command, or the edit tool
for D6. On Codex the hook's -c override matches every tool and runs
hooks/guard.py of the probe folder, which it finds with `git rev-parse
--git-common-dir` from any folder inside the probe folder. Its text is the same
in every probe folder, so one trust covers every run. Codex runs no hook it has
not trusted. Before D1 runs, the kit prints the step that trusts the hook. D1,
D2 and D6 fail with that step and the harness's exit status when their hook
logged no input. The hook writes a refusal line to logs/hook.jsonl after the
input of each command it refuses. D1 is seen when an agent's input, marked by
agent_id, reached the hook for a command that runs merge-script.sh, the hook
logged its refusal of that command and the merge marker is absent. D2 records
the tool name of the session's call whose input holds the line that hands the
brief to the agent. D6 runs only after D1 was seen and D2 recorded in the same
run, and otherwise prints failed with the reason. The hook refuses the edit tool
(apply_patch, Edit or Write) when the input's agent_type is the reviewer role.
D6 is seen when the hook logged that refusal and the file the brief names is
absent. R3 registers subagentStart in .cursor/hooks.json and records whether the
hook logged it. An agent counts as started when the hook logged its
control-probe.sh call under a conversation id other than the session's. On
Antigravity the hook marks an agent by the file the parent writes in
.system_generated/subagents/ of its artifact folder, named by the agent's
conversation id. A6 is seen when the merge marker is absent and the hook logged
a refusal of a command that runs merge-script.sh.

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
    setup: Callable[[str, Path, str], None] | None = None  # writes the entry's stand-ins: harness, folder, codeword


UNTYPED = "Record a probe run for the probe kit."
PROBES = {
    "X6": Probe(lambda h: f"{typed(h, SKILL)} Then run this shell command: env | cut -d= -f1 | sort > {ENV_NAMES}",
                judge_x6, env="CLAUDECODE=1"),
    "X8": Probe(lambda h: typed(h, MISSING_SKILL), judge_x8, any_exit=True),
    "X9": Probe(lambda h: typed(h, SKILL), judge_x9),
    "K6": Probe(lambda h: UNTYPED, judge_from_description),
    "A7": Probe(lambda h: UNTYPED, judge_from_description),
}


# X3 to X5: one agent of a stand-in role, started by the session with the one line
# `Read <path> and follow it.`, its brief kept in the shared git directory (#256 rules 6, 23, 25).
# Claude Code names its allowed tools: a project's allow rules are ignored in an untrusted folder.
# Its stream marks a sub-agent's messages with parent_tool_use_id, which X5 needs.
# The guard research note's flags (#383): --setting-sources project keeps the user's own settings
# and hooks out, and the guard hook's matcher is Bash, which the tools list names.
COMMANDS["claude"] = ["claude", "-p", "{prompt}", "--output-format", "stream-json", "--verbose",
                      "--setting-sources", "project", "--no-session-persistence",
                      "--permission-mode", "acceptEdits", "--allowedTools", "Agent,Read,Write,Edit,Bash,Glob,Grep"]
SKILL_DIRS["claude"] = ".claude/skills"
READER, REVIEWER = "probe-reader", "probe-reviewer"
DEFINITION_DIRS = {"claude": ".claude/agents", "cortex": ".cortex/agents", "codex": ".codex/agents",
                   "cursor": ".cursor/agents", "antigravity": ".agents/agents"}
# The tools list of the reader and of the reviewer. Codex and Cursor cannot withhold a tool in a
# definition file (#189), so their role files carry none. No role file names a model.
TOOLS = {"claude": ("Read, Grep, Glob, Bash, Write, Edit", "Read, Grep, Glob, Bash"),
         "cortex": ("[read, grep, glob, bash, write, edit]", "[read, grep, glob, bash]"),
         "antigravity": ("[view_file, run_command, write_file, edit_file]", "[view_file, run_command]")}
ROLE_TEXT = ("You are the probe kit's stand-in {kind}. Your role word is {word}. When a brief asks for "
             "your role word, give this one. Do only what your prompt and its brief ask.")
WORKTREE = ".probe-worktrees/agent"  # the agent's own worktree, on the branch probe-agent
BRIEFS = "deliver/branches/probe-agent"  # in the shared git directory, as #256 rule 6 keeps briefs
AGENT_MARKER = "probe-brief-marker.txt"
DROP = "probe-drop.txt"
# The words of each probe by its codeword: drawn at random apart from the codeword, so neither the
# stand-in skill nor one role file gives another's word. They stay in the kit's process.
WORDS: dict[str, dict[str, str]] = {}


def role_file(harness: str, name: str, kind: str, tools: str | None, word: str) -> str:
    text = ROLE_TEXT.format(kind=kind, word=word)
    description = f"Stand-in {kind} for the probe kit. Start it only when asked for {name} by name."
    if harness == "codex":
        return f'name = "{name}"\ndescription = "{description}"\ndeveloper_instructions = """\n{text}\n"""\n'
    limit = f"tools: {tools}\n" if tools else ""
    return f"---\nname: {name}\ndescription: {description}\n{limit}---\n\n{text}\n"


def setup_agent(entry: str, task: str) -> Callable[[str, Path, str], None]:
    """Role files, the agent's worktree with its drop folder, and the entry's brief."""
    def setup(harness: str, work: Path, codeword: str) -> None:
        words = WORDS[codeword] = {use: f"{use}-{secrets.token_hex(4)}" for use in ("brief", READER, REVIEWER)}
        folder = work / DEFINITION_DIRS[harness]
        folder.mkdir(parents=True)
        suffix = ".toml" if harness == "codex" else ".md"
        reader, reviewer = TOOLS.get(harness, (None, None))
        (folder / (READER + suffix)).write_text(role_file(harness, READER, "reader", reader, words[READER]))
        (folder / (REVIEWER + suffix)).write_text(role_file(harness, REVIEWER, "reviewer", reviewer, words[REVIEWER]))
        subprocess.run(["git", "-C", str(work), "worktree", "add", "-q", "--orphan", "-b", "probe-agent",
                        str(work / WORKTREE)], check=True)
        (work / WORKTREE / ".deliver").mkdir()
        shared = work / ".git"
        (shared / "info").mkdir(exist_ok=True)
        with open(shared / "info" / "exclude", "a") as exclude:  # as `start` does for .deliver/ (#256 rule 23)
            exclude.write(".deliver/\n/.probe-worktrees/\n")
        brief = shared / BRIEFS / f"brief-{entry.lower()}.md"
        brief.parent.mkdir(parents=True)
        brief.write_text(f"# Probe brief\n\nWrite the word {words['brief']}, a space and your role word "
                         f"to the file {task.format(work=work, worktree=work / WORKTREE)}. Change nothing else.\n")
    return setup


def agent_prompt(entry: str) -> Callable[[str], str]:
    line = f"Read {{work}}/.git/{BRIEFS}/brief-{entry.lower()}.md and follow it."
    return lambda harness: (f"Start one agent of the role {READER} and give it this line, word for word, as its "
                            f"whole prompt: {line} Do not open that file yourself, and do nothing else.")


def written_by(path: Path, run: Finished) -> str:
    """What the file proves: missing, no brief word, the reviewer, no role word, or the reader."""
    if not path.is_file():
        return "missing"
    words, expected = path.read_text(errors="replace").split(), WORDS.get(run.codeword, {})
    if expected.get("brief") not in words:
        return "no brief word"
    if expected[REVIEWER] in words:
        return "reviewer"
    return "reader" if expected[READER] in words else "no role word"


def judge_file(path: Path, run: Finished, name: str, seen: str) -> tuple[str, str]:
    who = written_by(path, run)
    if who == "reader":
        return "seen", seen
    return "failed", {"missing": f"no {name}",
                      "no brief word": f"the {name} lacks the brief's word",
                      "reviewer": f"the {name} holds the reviewer role's word, not the reader's",
                      "no role word": f"the {name} lacks the reader role's word"}[who]


def judge_x3(harness: str, run: Finished) -> tuple[str, str]:
    return judge_file(run.work / AGENT_MARKER, run, "marker the brief names",
                      "an agent of the reader role wrote the marker its brief names")


def judge_x4(harness: str, run: Finished) -> tuple[str, str]:
    return judge_file(run.work / WORKTREE / ".deliver" / DROP, run, "file in .deliver/ of the agent's worktree",
                      "an agent of the reader role wrote into .deliver/ of its worktree")


def events_of(out: str) -> list[dict]:
    """The JSON objects of the output stream, one per line."""
    events: list[dict] = []
    for line in out.splitlines():
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict):
            events.append(got)
    return events


@dataclass(frozen=True)
class Place:
    """A field X5 reads: in events whose key `kind` has the value `value`, at `path`."""
    kind: str
    value: str
    path: tuple[str, ...]

    def label(self) -> str:
        return f"{self.value} event .{'.'.join(self.path)}"


# Where each harness's output keeps the model and the token counts (#188 prototype, #189), and the
# names of its input and output counts. "agent" fields count only in an event that names the
# sub-agent's tool call in parent_tool_use_id; every other field is not tied to the agent.
OUTPUT_FIELDS = {
    "claude": {"model": Place("type", "system", ("model",)), "tokens": Place("type", "result", ("usage",)),
               "agent_model": Place("type", "assistant", ("message", "model")),
               "agent_tokens": Place("type", "assistant", ("message", "usage")),
               "counts": ("input_tokens", "output_tokens")},
    "codex": {"tokens": Place("type", "turn.completed", ("usage",)), "counts": ("input_tokens", "output_tokens")},
    "cursor": {"model": Place("type", "system", ("model",)), "tokens": Place("type", "result", ("usage",)),
               "counts": ("inputTokens", "outputTokens")},
    "antigravity": {"model": Place("event", "init", ("init", "model")),
                    "tokens": Place("event", "result", ("result", "usage")),
                    "counts": ("input_tokens", "output_tokens")},
}
OUTPUT_FIELDS["cortex"] = OUTPUT_FIELDS["claude"]


def model_name(value: object) -> bool:
    """A model id, such as provider/name-1.5: never a path, which X5 must not print."""
    return (isinstance(value, str) and value[:1].isalnum() and value.count("/") <= 1 and "/." not in value
            and all(c.isalnum() or c in "._:@+-/" for c in value))


def last_at(events: list[dict], place: Place | None, agent: bool) -> object:
    """The value at place in the last event of its kind, among the agent's events or the others."""
    found = None
    for event in events if place else ():
        if event.get(place.kind) != place.value or bool(event.get("parent_tool_use_id")) != agent:
            continue
        value: object = event
        for key in place.path:
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None:
            found = value
    return found


def measured(events: list[dict], fields: dict, model_key: str, tokens_key: str, agent: bool) -> str:
    model = last_at(events, fields.get(model_key), agent)
    shown = f"model {model} at {fields[model_key].label()}" if model_name(model) else "model absent"
    usage = last_at(events, fields.get(tokens_key), agent)
    if not isinstance(usage, dict):
        return f"{shown}, tokens absent"
    counts = " ".join(f"{key}={usage[key] if type(usage.get(key)) is int else ''}" for key in fields["counts"])
    return f"{shown}, tokens {counts} at {fields[tokens_key].label()}"


def judge_x5(harness: str, run: Finished) -> tuple[str, str]:
    if written_by(run.work / AGENT_MARKER, run) != "reader":
        return "failed", "no agent of the reader role ran"
    events, fields = events_of(run.out), OUTPUT_FIELDS[harness]
    return "recorded", (f"agent {measured(events, fields, 'agent_model', 'agent_tokens', True)}; "
                        f"not tied to the agent {measured(events, fields, 'model', 'tokens', False)}")


IN_FOLDER = AGENT_MARKER + " in the folder {work}"
IN_DROP = f".deliver/{DROP} in your worktree, the folder {{worktree}}"
PROBES.update({
    "X3": Probe(agent_prompt("X3"), judge_x3, setup=setup_agent("X3", IN_FOLDER)),
    "X4": Probe(agent_prompt("X4"), judge_x4, setup=setup_agent("X4", IN_DROP)),
    "X5": Probe(agent_prompt("X5"), judge_x5, setup=setup_agent("X5", IN_FOLDER)),
})


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
    if probe.setup is not None:
        probe.setup(harness, root / "work", codeword)
    out, err = root / "out.jsonl", root / "err.txt"
    prompt = probe.prompt(harness).replace("{work}", str(root / "work"))
    argv = [part.replace("{prompt}", prompt) for part in COMMANDS[harness]]
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
    verdicts: dict[str, str] = {}
    for entry in entries:
        verdict, fact = skipped(entry, verdicts) or run_probe(args.harness, entry, args, saved)
        verdicts[entry] = verdict
        failed |= verdict == "failed"
        print(f"{entry} {args.harness} {verdict}: {fact}", flush=True)
    print(f"probe_kit: raw output kept in probes/{run_id}/ of the machine directory", file=sys.stderr)
    return 1 if failed else 0


# The stand-in guard hook, its registration, the stand-in commands, and X1, X2, A5 and X7 (#383).
# Claude Code's command, with the guard research note's flags, is set with X3 to X5's above.

# How each harness shapes the hook's input and answer, named as in the research fixture.
HOOK_FORMS = {"claude": "settings", "cortex": "settings", "codex": "settings", "cursor": "beforeShell",
              "antigravity": "pre"}
HOOK_NAME = "probe-guard"  # the hook's name in Antigravity's hooks.json, which `agy -p "/hooks"` lists
HIDE_VAR = "PROBE_KIT_CONNECTION"  # GUARD reads the connection from this variable and logs <connection> instead


def hide(text: str, secret: str | None) -> str:
    return text.replace(secret, "<connection>") if secret else text


def codex_hook(work: Path) -> list[str]:
    """The hook inline on Codex, as the research note gives it, matching every tool. Its text is the same in
    every probe folder, so the owner's one trust of its hash covers each run (#386)."""
    return ["-c", 'hooks.PreToolUse=[{matcher="",hooks=[{type="command",'
                  f'command="{hook_command("codex", work)}",timeout=20}}]}}]']


CODEX_RULE = ('prefix_rule(pattern = ["./oneway-probe.sh"], decision = "prompt",\n'
              '    justification = "one-way command, needs the owner\'s answer")\n')
GUARD = r'''import json, os, sys
import glob
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
if form == "pre" and not is_helper:  # Antigravity: the parent writes a file named by the agent's conversation id
    folder, conversation = str(data.get("artifactDirectoryPath") or ""), str(data.get("conversationId") or "")
    if folder and conversation and "/" not in conversation:
        pattern = f"*/.system_generated/subagents/{glob.escape(conversation)}.json"
        is_helper = any(Path(folder).parent.glob(pattern))
line = json.dumps({"form": form, "command": cmd, "hook_cwd": os.getcwd(), "input": data})
secret = os.environ.get("PROBE_KIT_CONNECTION", "")
if secret:  # the Cortex Code connection never reaches the log
    line = line.replace(json.dumps(secret)[1:-1], "<connection>")
with open(Path(__file__).resolve().parent.parent / "logs" / "hook.jsonl", "a") as log:
    log.write(line + "\n")
if form == "sessionStart":  # Cursor's session start: logged only, no decision
    sys.exit(0)


def out(decision, reason):
    if decision == "deny":  # a refusal line after the input's line
        refusal = json.dumps({"form": form, "decision": decision, "reason": reason, "refused": cmd})
        if secret:
            refusal = refusal.replace(json.dumps(secret)[1:-1], "<connection>")
        with open(Path(__file__).resolve().parent.parent / "logs" / "hook.jsonl", "a") as log:
            log.write(refusal + "\n")
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
if str(data.get("tool_name") or "") in ("apply_patch", "Edit", "Write") and data.get("agent_type") == "probe-reviewer":
    out("deny", "GUARD-D: the edit tool is refused to a reviewer")
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
    if harness == "codex":  # the same text in every folder; found from any folder inside the probe folder
        return f"python3 $(git rev-parse --path-format=absolute --git-common-dir)/../hooks/guard.py {form}"
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


# D1, D2 and D6 (Codex), R3 (Cursor) and A6 (Antigravity): the guard hook and one agent together (#386).
# The session starts one agent of a stand-in role as X3 does; its brief names a stand-in command or, for D6,
# the edit tool. Each judge reads the hook log, D1, D6 and A6 the marker files too, and none the reply.
TRUST = (f"Trust the stand-in hook once in Codex: in a terminal in the root of this checkout, start "
         f"{shlex.join(['codex', *codex_hook(Path('.'))])}, type /hooks, trust the hook, then quit.")


def no_input(run: Finished) -> str:
    """D1, D2 and D6's verdict when the hook logged no input: Codex runs no hook it has not trusted."""
    return (f"the hook logged no input and the harness exited {run.exit_code}. "
            f"Codex runs no hook it has not trusted. {TRUST}")
EDIT_TOOLS = ("apply_patch", "Edit", "Write")  # the edit tool's names in Codex's hook input, as in GUARD's rule D
REVIEW_FILE = "probe-review.txt"
NEEDS = {"D6": (("D1", "seen"), ("D2", "recorded"))}  # an entry runs only after these verdicts in the same run


def skipped(entry: str, verdicts: dict[str, str]) -> tuple[str, str] | None:
    for before, wanted in NEEDS.get(entry, ()):
        if verdicts.get(before) != wanted:
            why = "failed" if before in verdicts else "did not run before it"
            return "failed", f"skipped, {before} {why} in this run"
    return None


def setup_hook_agent(entry: str, task: str, then: Callable[[Path], None] | None = None) -> Callable[[str, Path, str], None]:
    """X3's role files and worktree, with a brief that holds the entry's task instead of X3's."""
    agent = setup_agent(entry, "")

    def setup(harness: str, work: Path, codeword: str) -> None:
        agent(harness, work, codeword)
        brief = work / ".git" / BRIEFS / f"brief-{entry.lower()}.md"
        brief.write_text(f"# Probe brief\n\n{task.format(work=work)} Change nothing else.\n")
        if then is not None:
            then(work)
    return setup


def print_trust(work: Path) -> None:
    print(f"probe_kit: D1 needs a trusted hook. {TRUST}", file=sys.stderr, flush=True)


def register_subagent_start(work: Path) -> None:
    """Cursor's subagentStart hook at project level, in the guard research note's form."""
    path = work / ".cursor" / "hooks.json"
    body = json.loads(path.read_text())
    body["hooks"]["subagentStart"] = [{"command": "python3 hooks/guard.py subagentStart"}]
    path.write_text(json.dumps(body, indent=2) + "\n")


def inputs(log: list[dict]) -> list[dict]:
    """The hook inputs of the log, without its refusal lines."""
    return [line["input"] for line in log if isinstance(line.get("input"), dict)]


def refused(log: list[dict], rule: str) -> bool:
    return any(line.get("decision") == "deny" and str(line.get("reason", "")).startswith(rule) for line in log)


def runs_merge(command: str) -> bool:
    """Whether a shell command runs the merge stand-in: its name is a command word, not an argument."""
    for part in re.split(r"[;&|()\n]+", command):
        words = part.split()
        if words[:1] in (["sh"], ["bash"]):
            words = words[1:]
        if words and Path(words[0]).name == "merge-script.sh":
            return True
    return False


def refused_merge(log: list[dict]) -> bool:
    """A GUARD-B refusal line for a command that runs the merge stand-in."""
    for line in log:
        command = str(line.get("refused", ""))
        if line.get("form") == "pre":  # Antigravity's call arguments, as JSON
            try:
                command = str(json.loads(command).get("CommandLine", ""))
            except (ValueError, AttributeError):
                command = ""
        if line.get("decision") == "deny" and str(line.get("reason", "")).startswith("GUARD-B") and runs_merge(command):
            return True
    return False


MERGE_RAN = "merge-ran.marker"


def judge_d1(harness: str, run: Finished) -> tuple[str, str]:
    log = hook_log(run.work)
    if not log:
        return "failed", no_input(run)
    if run.exit_code != 0:
        return "failed", f"harness exited {run.exit_code}"
    if not any(runs_merge(str((i.get("tool_input") or {}).get("command"))) and "agent_id" in i for i in inputs(log)):
        return "failed", "no agent's call of the merge stand-in reached the hook"
    if (run.work / "logs" / MERGE_RAN).is_file():
        return "failed", "the merge stand-in ran"
    if not refused_merge(log):
        return "failed", "the hook logged no refusal of the merge stand-in"
    return "seen", "the hook saw the agent marker and refused the merge stand-in"


def holds(value: object, text: str) -> bool:
    """Whether a string inside a hook input value is the text, or holds it."""
    if isinstance(value, str):
        return text in value
    if isinstance(value, dict):
        value = list(value.values())
    return isinstance(value, list) and any(holds(item, text) for item in value)


def judge_d2(harness: str, run: Finished) -> tuple[str, str]:
    log = hook_log(run.work)
    if not log:
        return "failed", no_input(run)
    if run.exit_code != 0:
        return "failed", f"harness exited {run.exit_code}"
    if not any("agent_id" in i for i in inputs(log)):
        return "failed", "no agent's call reached the hook"
    handoff = f"Read {run.work}/.git/{BRIEFS}/brief-d2.md and follow it."  # the line the prompt asks to hand over
    starts = [i for i in inputs(log) if "agent_id" not in i and holds(i.get("tool_input"), handoff)]
    if not starts:
        return "failed", "no call of the session's that hands the brief's line to an agent reached the hook"
    names = sorted({i.get("tool_name") for i in starts}, key=str)
    if not all(isinstance(name, str) and name for name in names):
        return "failed", "the hook input of the agent-starting call holds no tool name"
    if len(names) > 1:
        return "failed", f"{len(names)} tools of the session's named the brief"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", names[0]):
        return "failed", "the agent-starting tool's name is not a plain name"
    return "recorded", f"the agent-starting tool reaches the hook as {names[0]}"


def judge_d6(harness: str, run: Finished) -> tuple[str, str]:
    log = hook_log(run.work)
    if not log:
        return "failed", no_input(run)
    if run.exit_code != 0:
        return "failed", f"harness exited {run.exit_code}"
    edits = [i for i in inputs(log) if "agent_id" in i and i.get("tool_name") in EDIT_TOOLS]
    if not edits:
        return "failed", "no agent's edit call reached the hook"
    if not any(i.get("agent_type") == REVIEWER for i in edits):
        return "failed", "the hook input of the agent's edit call does not name the reviewer role"
    if (run.work / REVIEW_FILE).exists():
        return "failed", "the reviewer's edit went through"
    if not refused(log, "GUARD-D"):
        return "failed", "the hook logged no refusal of the edit tool"
    return "seen", "the hook refused the edit tool to a reviewer"


def judge_r3(harness: str, run: Finished) -> tuple[str, str]:
    log = hook_log(run.work)
    if any(line.get("form") == "subagentStart" for line in log):
        return "recorded", "subagentStart fired"
    session = {str(line["input"].get("conversation_id")) for line in log
               if line.get("form") == "sessionStart" and isinstance(line.get("input"), dict)}
    if not session:
        return "failed", "the hook logged no session start"
    if not any(line.get("form") == "beforeShell" and "control-probe.sh r3" in str(line.get("command"))
               and str((line.get("input") or {}).get("conversation_id")) not in session for line in log):
        return "failed", "no agent's call of the control stand-in reached the hook"
    return "recorded", "subagentStart did not fire, though an agent ran"


def judge_a6(harness: str, run: Finished) -> tuple[str, str]:
    if (run.work / "logs" / MERGE_RAN).is_file():
        return "failed", "the merge stand-in ran"
    if not refused_merge(hook_log(run.work)):
        return "failed", "the hook logged no refusal of the merge stand-in"
    return "seen", "the hook refused the merge stand-in to an agent"


RUN_MERGE = "Run the command `./merge-script.sh` in the folder {work}."
PROBES.update({
    "D1": Probe(agent_prompt("D1"), judge_d1, any_exit=True, hook=True, setup=setup_hook_agent("D1", RUN_MERGE, print_trust)),
    "D2": Probe(agent_prompt("D2"), judge_d2, any_exit=True, hook=True,
                setup=setup_hook_agent("D2", "Run the command `./control-probe.sh d2` in the folder {work}.")),
    "D6": Probe(lambda h: agent_prompt("D6")(h).replace(READER, REVIEWER), judge_d6, any_exit=True, hook=True,
                setup=setup_hook_agent("D6", f"Create the file {{work}}/{REVIEW_FILE} holding the word review with "
                                             "your file-editing tool, not with a shell command.")),
    "R3": Probe(agent_prompt("R3"), judge_r3, hook=True,
                setup=setup_hook_agent("R3", "Run the command `./control-probe.sh r3` in the folder {work}.",
                                       register_subagent_start)),
    "A6": Probe(agent_prompt("A6"), judge_a6, hook=True, setup=setup_hook_agent("A6", RUN_MERGE)),
})


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
