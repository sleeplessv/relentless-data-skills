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
The hook and the judges share one rule for merge-script.sh: a command runs it
when its name is a command word, so reading the script is not refused.
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
session to start the reader with the one line `Read <path> and follow it.`, and
on Cortex Code and Codex to wait for it. Codex loads no project role file in a
folder it has not trusted, so the kit passes each role file it wrote as -c
overrides on the Codex command line, as it passes the hook: nothing is saved to
the user's Codex settings. The brief asks for a word of its own and the role's
word. The kit draws each word at random, and none is in the prompt. X3 is seen
when both words are in the marker file the brief names. X4 is seen when both are
in the file the brief names in .deliver/ of the agent's worktree. A word the kit
did not give the reader, such as the reviewer's, fails the entry. X5 needs the
X3 marker too, then reads the model and the token counts from the fields each
harness's output keeps them in, and prints where. A field counts as the agent's
only in an event the output ties to the agent's tool call; the rest prints as
not tied to the agent. A field the output lacks prints as absent, and a token
count the output leaves empty or out prints blank, never as 0.

C1, C3 and R4 change Claude Code's user-level plugins, under ~/.claude/. Each
writes a stand-in plugin (the stand-in skill, one role file in agents/ and a
hook in hooks/hooks.json that logs each input) and a local marketplace that
offers it into the probe's temporary folder, and removes the project's copy of
the skill. It keeps the bytes of each file it finds in ~/.claude/, its settings
file and ~/.claude/plugins/ two levels down. It names each change on standard
error before it makes it, then runs `claude plugin marketplace add` and `claude
plugin install`. On the way out, also after a failure or an interrupt, it
uninstalls the plugin, removes the marketplace and deletes what still names it
under ~/.claude/, and writes each kept file back as it was. The kit's last line
then says the machine was left as it was, or names what it could not remove or
restore. C1 reads the user's settings as well as the project's, because the
installed plugin is a user-level setting. It types the plugin's skill, starts
one agent of the plugin's role and runs one shell command. It is seen when the
marker holds the skill's codeword, the role-word file holds the word only the
role file holds and an event of that agent's call wrote it, and the plugin's
hook logged the command in its command field. It fails when a tool reads the
plugin's skill or role file. C2 installs nothing: a project role file names the
stand-in skill in its skills list, and the codeword is in no other file of the
folder. It is seen when the marker holds the codeword, an event of the
probe-skilled agent's call holds it, and no tool names a skill file. C3 starts
no session. It drops the plugin from the marketplace, runs `claude plugin
marketplace update`, then `claude plugin uninstall`, and records the exit code
and whether the plugin stayed. R4 runs Cursor with the typed skill and one
shell command. It records how many paths of the skill file the output names,
whether the skill ran, and how many times the plugin's hook logged the command
in its command field. The line about raw output prints only when the run kept
a file.

D1, D2 and D6 on Codex, R3 on Cursor and A6 on Antigravity add the hook and
start one agent as X3 does. The brief names a stand-in command, or the edit tool
for D6. On Codex the hook's -c override matches every tool and runs
hooks/guard.py of the probe folder, which it finds with `git rev-parse
--git-common-dir` from any folder inside the probe folder. Its text is the same
in every probe folder, so one trust covers every run. Codex runs no hook it has
not trusted. Before D1 runs, the kit prints the step that trusts the hook. D1 to
D4 and D6 fail with that step and the harness's exit status when their hook
logged no input and the output shows a tool call; with no tool call in the
output, the line says so and names no trust step. The hook writes a refusal line
to logs/hook.jsonl after the input of each command it refuses. D1 is seen when
an agent's input, marked by agent_id, reached the hook for a command that runs
merge-script.sh, the hook logged its refusal of that command and the merge
marker is absent. D2 records the tool name of the session's call whose input
names the reader role as its agent_type; it never reads the message the call
hands over. D6 runs only after D1 was seen and D2 recorded in the same run, and
otherwise prints failed with the reason. The hook refuses the edit tool
(apply_patch, Edit or Write) when the input's agent_type is the reviewer role.
D6 is seen when the hook logged that refusal and the file the brief names is
absent. R3 registers subagentStart in .cursor/hooks.json and records whether the
hook logged it. An agent counts as started when the hook logged its
control-probe.sh call under a conversation id other than the session's. On
Antigravity the hook marks an agent by the file the parent writes in
.system_generated/subagents/ of its artifact folder, named by the agent's
conversation id. A6 is seen when the merge marker is absent and the hook logged
a refusal of a command that runs merge-script.sh.

K1 to K5, D3 to D5, R2, R5 and A2 to A4 probe each harness's own agent limits.
Each agent's brief asks for a word of its own and its role's word, as X3's does,
and a brief that has the agent start another names that agent's brief, so no
nested path is in the prompt. K1 to K4 follow the four draft tests of the Cortex
Code nesting note: K1 sets CORTEX_CODE_EXPERIMENTAL_FEATURES to {} and K2 and K3
to a maxSubagentDepth of 2, on the command line only. In K1 each author lists
which of task, agent, agent_output and kill_agent it has; one that has task or
agent must show its refused call in the output. K2 and K3 need both leaves'
lists empty and the output to show each start's mode and parent; K2 also needs
the leaves at once, and K3 the session's agent_output wait and a second author
whose leaves start in the background, which it reports. K4, K5 and D4 count the
agent as called back only when its second marker holds a word its first brief
gave it to remember and write nowhere; that brief deleted itself. K4 needs a
kill_agent call that names the agent and succeeded, before the resume, and no
finished sleep. When the resume call failed, K4 and K5 say so, with the
harness's reason, its ids and paths left out. K5 reads the model from the events
tied to the call that resumed the agent and fails when they name none. D3 and D4
add the guard hook and read the agents from its log, since Codex's output shows
no agent start: a start is the session's call whose input names the reader role
as its agent_type, and an agent's call carries its agent_id. D4 needs the
session's interrupt_agent call that names the agent, then its followup_task call
that names it, then a call of that agent's. D3 needs two starts and two agents,
and is seen only when the output shows both spawn_agent calls started before
either ended. D5 runs Codex with the temporary folders kept out of its writable
directories and cuts the agent's worktree beside the session's folder. R2 and A4
ask for 4 agents at once, never more; each agent keeps the longest list of
agents it saw running beside it. They record no cap up to 4 when a list holds
all 4, and otherwise the most at once, naming no cap. R5 names each file it
makes in ~/.cursor/agents/ before making it, never touches one it did not make,
and removes it when the probe ends, also when it fails or is interrupted. A2 and
A3 add the guard hook: A2 is seen when no file was written and the agent
reported the write refused, with the hook having logged its write_file call to
the marker or, as Antigravity takes a withheld tool away, no write_file call at
all. On Antigravity the author role's file lists the reader's tools and
invoke_subagent, since a file with no tools line gives no shell and no write. A3
starts the agent whose file names flash with Model pro beside two agents whose
files name no tier, one called with pro and one with flash, and compares the
models in their hook inputs; it names the winner only when pro and flash gave
two models.

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
import inspect
import json
import os
import re
import secrets
import threading
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
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
    "K2": (("cortex",), "maxSubagentDepth at 2, two leaf agents under an author"),
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
    # accept-edits alone refuses every command in print mode; the allow rule holds for this run only, never saved.
    "antigravity": ["agy", "-p", "{prompt}", "--output-format", "stream-json", "--mode", "accept-edits",
                    "--settings", '{"permissions": {"allow": ["command(*)"]}}'],
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
    args: tuple[str, ...] = ()  # put before the prompt, which comes last on the Codex line
    command: list[str] | None = None  # the headless command, when the entry needs another than the harness's


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
# definition file (#189), so their role files carry none. No role file names a model but A3's reader.
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


# What makes the session wait for the agent: a headless Cortex Code or Codex session that ends first cancels it
# (#405). Cortex Code's is K1 to K3's WAIT; Codex's is the wording that made `codex exec` wait in a real run.
CODEX_WAIT = "Then call wait_agent for it and end only when it has finished. "


def agent_prompt(entry: str) -> Callable[[str], str]:
    line = f"Read {{work}}/.git/{BRIEFS}/brief-{entry.lower()}.md and follow it."
    return lambda harness: (f"Start one agent of the role {READER} and give it this line, word for word, as its "
                            f"whole prompt: {line} {({'cortex': WAIT, 'codex': CODEX_WAIT}).get(harness, '')}"
                            f"Do not open that file yourself, and do nothing else.")


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
    codeword = f"probe-{secrets.token_hex(4)}"
    try:  # outermost, so what the probe wrote outside its folder goes on every way out
        return run_in_folder(harness, entry, args, saved, codeword)
    finally:
        remove_outside(codeword)


def run_in_folder(harness: str, entry: str, args: argparse.Namespace, saved: Path, codeword: str) -> tuple[str, str]:
    probe = PROBES[entry]
    root = make_folder(harness, codeword)
    address, ended = None, False
    try:
        if probe.hook:
            write_guard(harness, root / "work")
        if probe.setup is not None:
            probe.setup(harness, root / "work", codeword)
        out, err = root / "out.jsonl", root / "err.txt"
        prompt = probe.prompt(harness).replace("{work}", str(root / "work"))
        argv = [part.replace("{prompt}", prompt) for part in probe.command or COMMANDS[harness]]
        if harness == "cortex":
            argv += ["-c", args.connection]
        if probe.hook and harness == "codex":
            argv[-1:-1] = codex_hook(root / "work")  # before the prompt, which comes last
        if harness == "codex":
            argv[-1:-1] = codex_roles(root / "work")
        argv[-1:-1] = probe.args
        relayed = [sys.executable, str(Path(__file__).resolve()), "--relay", str(out), str(err),
                   args.connection or "", *argv]
        line = f"{probe.env} {shlex.join(relayed)}".lstrip()
        if args.connection:  # the hook hides it in its log, as the relay does in the output
            line = f"{HIDE_VAR}={shlex.quote(args.connection)} {line}"
        name = f"probe-{harness}-{entry.lower()}-{os.getpid()}"
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
    except SetupFailed as error:
        return "failed", str(error)
    finally:
        try:
            if address is not None and not ended:
                hc("kill", address)  # interrupted while waiting: end the terminal
        finally:
            undo_user_level()
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
        try:
            verdict, fact = skipped(entry, verdicts) or run_probe(args.harness, entry, args, saved)
        except Exception as error:  # a traceback would print local paths; the clean-up has run
            verdict, fact = "failed", f"the probe stopped on {type(error).__name__}"
        verdicts[entry] = verdict
        failed |= verdict == "failed"
        print(f"{entry} {args.harness} {verdict}: {fact}", flush=True)
    if any(saved.iterdir()):
        print(f"probe_kit: raw output kept in probes/{run_id}/ of the machine directory", file=sys.stderr)
    else:
        saved.rmdir()  # a run that kept nothing, such as C3 alone, points to no folder
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


def codex_roles(work: Path) -> list[str]:
    """Each Codex role file the kit wrote, as session settings: Codex loads no project role file in a folder it
    has not trusted, and a per-run trust override does not change that (#405). Nothing is saved."""
    argv = []
    for path in sorted((work / DEFINITION_DIRS["codex"]).glob("*.toml")):
        role = tomllib.loads(path.read_text())
        argv += ["-c", f"agents.{role['name']}.config_file={json.dumps(str(path))}",
                 "-c", f"agents.{role['name']}.description={json.dumps(role['description'])}"]
    return argv


CODEX_RULE = ('prefix_rule(pattern = ["./oneway-probe.sh"], decision = "prompt",\n'
              '    justification = "one-way command, needs the owner\'s answer")\n')
GUARD = r'''import json, os, sys
import glob, re
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
shell = cmd
if form == "pre":  # Antigravity: the shell command of a run_command call
    args = (data.get("toolCall") or {}).get("args")
    shell = str(args.get("CommandLine") or "") if isinstance(args, dict) else ""


{runs_merge}


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
if runs_merge(shell) and is_helper:  # the judges' rule: reading the script is allowed, running it is not
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
    (work / "hooks" / "guard.py").write_text(GUARD.replace("{runs_merge}", inspect.getsource(runs_merge)))
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


# C1, C2, C3 and R4 (#387): the stand-in plugin, offered by a local marketplace in the probe folder and
# installed on Claude Code. C1, C3 and R4 are the only entries here that change anything outside the
# probe folder (spec #381, reading 4): the marketplace registration and the installed plugin, which
# Claude Code keeps under ~/.claude/. C2 installs nothing.
PLUGIN = "probe-plugin"
PLUGIN_ROLE = "probe-plugin-role"
SKILLED_ROLE = "probe-skilled"
ROLE_OUT = "probe-role-word.txt"
R4_RAN = "probe-r4.txt"
PLUGIN_LOG = "logs/plugin-hook.jsonl"
HOOK_LOGGER = 'import json, sys\nwith open({log!r}, "a") as log:\n    log.write(json.dumps({{"input": sys.stdin.read()}}) + "\\n")\n'
# The installed plugin is a user-level setting, which --setting-sources project leaves out.
PLUGIN_COMMAND = [part if part != "project" else "user,project" for part in COMMANDS["claude"]]
# The marketplaces made, what could not be removed, and the files that could not be put back.
USER_LEVEL: dict[str, list[str]] = {"made": [], "left": [], "changed": []}
# Each marketplace to undo, with the paths near ~/.claude before it and the bytes of each file among them.
PENDING: list[tuple[str, set[Path], dict[Path, bytes]]] = []
PLUGIN_FILES = ("SKILL.md", "skills/", f"{PLUGIN_ROLE}.md", "agents/")  # a tool input naming one read the plugin


class SetupFailed(Exception):
    """A stand-in the entry needs could not be made: the entry fails with this fact."""


def listed(items: list[str]) -> str:
    return " and ".join(items) if len(items) < 3 else ", ".join(items[:-1]) + " and " + items[-1]


def times(count: int) -> str:
    return {0: "not at all", 1: "once", 2: "twice"}.get(count, f"{count} times")


def claude_home() -> Path:
    return Path.home() / ".claude"


def near(home: Path) -> list[Path]:
    """~/.claude, its settings file and ~/.claude/plugins two levels down: where a marketplace and a plugin land."""
    plugins = home / "plugins"
    found = [home, home / "settings.json", plugins, *plugins.glob("*"), *plugins.glob("*/*")]
    return [path for path in dict.fromkeys(found) if path.exists() or path.is_symlink()]


def names(path: Path, text: str) -> bool:
    return text in path.name or (path.suffix == ".json" and path.is_file() and text in path.read_text(errors="replace"))


def scrub(value: object, market: str) -> object:
    """The JSON value without the keys, items and string values that name the marketplace."""
    if isinstance(value, dict):
        return {key: scrub(item, market) for key, item in value.items()
                if market not in key and not (isinstance(item, str) and market in item)}
    if isinstance(value, list):
        return [scrub(item, market) for item in value if not (isinstance(item, str) and market in item)]
    return value


def hollow(value: object) -> bool:
    """Whether every list and object in the JSON value is empty."""
    if isinstance(value, dict):
        return all(hollow(item) for item in value.values())
    return value == [] if isinstance(value, list) else True


def plugin_cli(*args: str) -> int:
    """`claude plugin ...`; its output can hold local paths, so none of it is printed."""
    return subprocess.run(["claude", "plugin", *args], capture_output=True, text=True, check=False,
                          stdin=subprocess.DEVNULL, timeout=120).returncode


def shown(path: Path) -> str:
    return "~/" + str(path.relative_to(Path.home()))


def undo_user_level() -> None:
    """Uninstall each pending plugin, remove its marketplace, delete what still names it, put kept files back.

    What could not be removed or put back goes to USER_LEVEL, with ~ for the home folder.
    """
    while PENDING:
        market, before, kept = PENDING.pop()
        for args in (("uninstall", f"{PLUGIN}@{market}"), ("marketplace", "remove", market)):
            try:
                plugin_cli(*args)
            except (OSError, subprocess.SubprocessError):
                pass
        home = claude_home()
        for path in sorted(near(home), key=lambda p: len(p.parts), reverse=True):  # a folder after what it holds
            try:
                if market in path.name:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                elif path in kept:
                    continue  # written back below
                elif path.suffix == ".json" and path.is_file() and path not in before:
                    data = json.loads(path.read_text())
                    scrubbed = scrub(data, market)
                    if hollow(scrubbed):
                        path.unlink()  # a file the install made, now holding nothing
                    elif scrubbed != data:
                        path.write_text(json.dumps(scrubbed, indent=2) + "\n")
                elif path.is_dir() and path not in before and not any(path.iterdir()):
                    path.rmdir()
            except (OSError, ValueError):
                pass
        changed = []
        for path, data in kept.items():
            try:
                if not path.is_file() or path.read_bytes() != data:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                same = path.read_bytes() == data
            except OSError:
                same = False
            if not same:
                changed.append(path)
        USER_LEVEL["changed"] += [shown(p) for p in changed]
        USER_LEVEL["left"] += [shown(p) for p in near(home) if p not in changed and names(p, market)]


def write_plugin(folder: Path, work: Path, codeword: str, role_word: str) -> None:
    """The stand-in skill, one role file in agents/ and a hook in hooks/hooks.json that logs each input."""
    for part in (".claude-plugin", f"skills/{SKILL}", "agents", "hooks"):
        (folder / part).mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps(
        {"name": PLUGIN, "version": "1.0.0", "description": "Stand-in plugin for the probe kit."}, indent=2) + "\n")
    (folder / "skills" / SKILL / "SKILL.md").write_text(SKILL_TEXT.format(name=SKILL, marker=MARKER, codeword=codeword))
    (folder / "agents" / f"{PLUGIN_ROLE}.md").write_text(role_file("claude", PLUGIN_ROLE, "plugin role", None, role_word))
    logger = work.parent / "plugin-hook.py"
    logger.write_text(HOOK_LOGGER.format(log=str(work / PLUGIN_LOG)))
    (work / PLUGIN_LOG).parent.mkdir(exist_ok=True)
    hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": f"python3 {shlex.quote(str(logger))}"}]}]}}
    (folder / "hooks" / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n")


def setup_plugin(entry: str) -> Callable[[str, Path, str], None]:
    """The plugin and its marketplace beside the folder, registered and installed, each change named first."""
    def setup(harness: str, work: Path, codeword: str) -> None:
        if shutil.which("claude") is None:
            raise SetupFailed("claude is not on PATH")
        market = f"probe-market-{secrets.token_hex(4)}"  # not the codeword, which only the skill holds
        WORDS[codeword] = {"role": f"role-{secrets.token_hex(4)}", "market": market}
        shutil.rmtree(work / SKILL_DIRS[harness] / SKILL)  # the plugin's copy of the skill is the only one
        source = work.parent / "market"
        write_plugin(source / PLUGIN, work, codeword, WORDS[codeword]["role"])
        (source / ".claude-plugin").mkdir()
        (source / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
            {"name": market, "owner": {"name": "probe kit"},
             "plugins": [{"name": PLUGIN, "source": f"./{PLUGIN}", "description": "Stand-in plugin."}]}, indent=2) + "\n")
        before = near(claude_home())
        try:
            kept = {path: path.read_bytes() for path in before if path.is_file() and not path.is_symlink()}
        except OSError as error:
            raise SetupFailed("a file under ~/.claude/ could not be read, so it could not be put back") from error
        PENDING.append((market, set(before), kept))
        USER_LEVEL["made"].append(market)
        for change, args in ((f"registers the marketplace {market} with", ("marketplace", "add", str(source))),
                             (f"installs the plugin {PLUGIN}@{market} on", ("install", f"{PLUGIN}@{market}"))):
            print(f"probe_kit: {entry} {change} Claude Code, under ~/.claude/", file=sys.stderr, flush=True)
            code = plugin_cli(*args)
            if code != 0:
                raise SetupFailed(f"claude plugin {' '.join(args[:-1])} exited {code}")
    return setup


def setup_skilled_role(harness: str, work: Path, codeword: str) -> None:
    """A project role file that names the stand-in skill in its skills list, and no codeword."""
    folder = work / DEFINITION_DIRS[harness]
    folder.mkdir(parents=True)
    (folder / f"{SKILLED_ROLE}.md").write_text(
        f"---\nname: {SKILLED_ROLE}\ndescription: Stand-in role for the probe kit. Start it only when asked for "
        f"{SKILLED_ROLE} by name.\nskills:\n  - {SKILL}\n---\n\nYou are the probe kit's stand-in role. Do what "
        "your prompt asks, with the skill this file gives you.\n")
    skill = work / SKILL_DIRS[harness] / SKILL / "SKILL.md"
    for path in work.rglob("*"):
        if path.is_file() and path != skill and ".git" not in path.relative_to(work).parts:
            if codeword in path.read_text(errors="replace"):
                raise SetupFailed("the codeword is in a file of the folder other than the skill file")


def plugin_hook_calls(work: Path, harness: str, command: str) -> int:
    """The plugin hook's log lines whose input has the command in the harness's command field.

    Claude Code sends tool_input.command; Cursor sends command, as the guard hook reads it.
    """
    log = work / PLUGIN_LOG
    count = 0
    for line in log.read_text(errors="replace").splitlines() if log.is_file() else []:
        try:
            data = json.loads(json.loads(line)["input"])
        except (ValueError, KeyError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        field = data.get("tool_input") if harness == "claude" else data
        count += isinstance(field, dict) and str(field.get("command") or "").strip() == command
    return count


def names_any(event: object, needles: tuple[str, ...]) -> bool:
    """Whether a tool or command event names any of the needles; a message that names one does not count."""
    if isinstance(event, list):
        return any(names_any(item, needles) for item in event)
    if not isinstance(event, dict):
        return False
    kind = str(event.get("type", "")).lower()
    if any(word in kind for word in ("tool", "command", "function_call")) or "tool_call" in event:
        text = json.dumps(event)
        return any(needle in text for needle in needles)
    return any(names_any(value, needles) for value in event.values())


def agent_calls(events: list[dict], role: str) -> set[str]:
    """The ids of the Agent (or Task) tool calls that start the role."""
    ids = set()
    for event in events:
        message = event.get("message") if event.get("type") == "assistant" else None
        for item in message.get("content") or [] if isinstance(message, dict) else []:
            if (isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") in ("Agent", "Task")
                    and isinstance(item.get("input"), dict) and item["input"].get("subagent_type") == role
                    and item.get("id")):
                ids.add(item["id"])
    return ids


def said_by(events: list[dict], calls: set[str], word: str) -> bool:
    """Whether an assistant event of one of the calls holds the word: the agent's own quote or tool call."""
    return any(event.get("type") == "assistant" and event.get("parent_tool_use_id") in calls
               and word in json.dumps(event.get("message")) for event in events)


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict | list):
        for item in value.values() if isinstance(value, dict) else value:
            yield from strings(item)


def judge_c1(harness: str, run: Finished) -> tuple[str, str]:
    events, role, word = events_of(run.out), run.work / ROLE_OUT, WORDS[run.codeword]["role"]
    if names_any(events, PLUGIN_FILES):
        return "failed", "a tool read the installed plugin's files, so its words need not have come from loading them"
    loaded = {"skill": run.marker_holds_codeword(),
              "role file": role.is_file() and word in role.read_text(errors="replace").split()
              and said_by(events, agent_calls(events, f"{PLUGIN}:{PLUGIN_ROLE}"), word),
              "hook": plugin_hook_calls(run.work, harness, "echo probe-c1") > 0}
    missing = [part for part, seen in loaded.items() if not seen]
    if missing:
        return "failed", f"the installed plugin's {listed(missing)} did not load"
    return "seen", "the installed plugin loaded its skill, role file and hook"


def judge_c2(harness: str, run: Finished) -> tuple[str, str]:
    if not run.marker_holds_codeword():
        return "failed", "no marker holds the skill's codeword"
    events = events_of(run.out)
    if names_any(events, ("SKILL.md", "skills/")):
        return "failed", "a tool read the skill file, so the codeword need not have come through the role file"
    calls = agent_calls(events, SKILLED_ROLE)
    if not calls:
        return "failed", f"no agent of the role {SKILLED_ROLE} was started"
    if not said_by(events, calls, run.codeword):
        return "failed", "no event of the agent's holds the codeword"
    return "seen", "an agent of the role wrote the codeword only the skill holds"


def judge_c3(harness: str, run: Finished) -> tuple[str, str]:
    """Drop the plugin from the marketplace, update it, then uninstall the plugin and record what stayed."""
    market = WORDS[run.codeword]["market"]
    listing = run.work.parent / "market" / ".claude-plugin" / "marketplace.json"
    offered = json.loads(listing.read_text())
    listing.write_text(json.dumps({**offered, "plugins": []}, indent=2) + "\n")
    code = plugin_cli("marketplace", "update", market)
    if code != 0:
        return "failed", f"claude plugin marketplace update exited {code}"
    code = plugin_cli("uninstall", f"{PLUGIN}@{market}")
    stayed = (claude_home() / "plugins" / "cache" / market / PLUGIN).exists() or any(
        names(path, f"{PLUGIN}@{market}") for path in near(claude_home()))
    return "recorded", f"uninstall exited {code} and the plugin {'stayed' if stayed else 'is gone'}"


def judge_r4(harness: str, run: Finished) -> tuple[str, str]:
    if not (run.work / R4_RAN).is_file():
        return "failed", "the shell command did not run, so the hook count says nothing"
    shown = {text for text in strings(events_of(run.out)) if text.endswith(f"/{SKILL}/SKILL.md")}
    return "recorded", (f"skill file in the output {times(len(shown))}, skill "
                        f"{'ran' if run.marker_holds_codeword() else 'did not run'}, hook fired "
                        f"{times(plugin_hook_calls(run.work, harness, 'echo probe-r4 > ' + R4_RAN))}")


PROBES.update({
    "C1": Probe(lambda h: (f"/{PLUGIN}:{SKILL} Then start one agent of the role {PLUGIN}:{PLUGIN_ROLE} and give it "
                           f"this line, word for word, as its whole prompt: Write your role word to the file "
                           f"{ROLE_OUT} in the folder {{work}}. Then run the shell command `echo probe-c1`."),
                judge_c1, setup=setup_plugin("C1"), command=PLUGIN_COMMAND),
    "C2": Probe(lambda h: (f"Start one agent of the role {SKILLED_ROLE} and give it this line, word for word, as its "
                           "whole prompt: Follow the skill you were given, in the folder {work}. Do not open any "
                           "skill file yourself, and do nothing else."), judge_c2, setup=setup_skilled_role),
    "C3": Probe(lambda h: "", judge_c3, setup=setup_plugin("C3"), direct=True),
    "R4": Probe(lambda h: f"/{SKILL} Then run the shell command `echo probe-r4 > {R4_RAN}`.", judge_r4,
                setup=setup_plugin("R4")),
})


# D1, D2 and D6 (Codex), R3 (Cursor) and A6 (Antigravity): the guard hook and one agent together (#386).
# The session starts one agent of a stand-in role as X3 does; its brief names a stand-in command or, for D6,
# the edit tool. Each judge reads the hook log, D1, D6 and A6 the marker files too, and none the reply.
TRUST = (f"Trust the stand-in hook once in Codex: in a terminal in the root of this checkout, start "
         f"{shlex.join(['codex', *codex_hook(Path('.'))])}, type /hooks, trust the hook, then quit.")


TALK = ("agent_message", "reasoning", "error", "todo_list")  # Codex's output items that are not tool calls


def no_input(run: Finished) -> str:
    """The verdict when the hook logged no input: Codex runs no hook it has not trusted, which matters only when
    the output shows the session made a tool call."""
    if not any(str(event.get("type")).startswith("item.") and isinstance(event.get("item"), dict)
               and event["item"].get("type") not in TALK for event in events_of(run.out)):
        return f"the hook logged no input, the output shows no tool call, and the harness exited {run.exit_code}"
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


def starts_of(log: list[dict]) -> list[dict]:
    """The session's agent starts: its calls whose input names the reader role as agent_type. The message the
    call hands over is not read: Codex's hook input does not show it as text (#405)."""
    return [i for i in inputs(log) if "agent_id" not in i and isinstance(i.get("tool_input"), dict)
            and i["tool_input"].get("agent_type") == READER]


def agents_of(log: list[dict]) -> list[str]:
    """The distinct agent_id values of the reader role's calls, in the order they reached the hook."""
    ids = [str(i["agent_id"]) for i in inputs(log) if i.get("agent_id") and i.get("agent_type") == READER]
    return list(dict.fromkeys(ids))


def judge_d2(harness: str, run: Finished) -> tuple[str, str]:
    log = hook_log(run.work)
    if not log:
        return "failed", no_input(run)
    if run.exit_code != 0:
        return "failed", f"harness exited {run.exit_code}"
    if not any("agent_id" in i for i in inputs(log)):
        return "failed", "no agent's call reached the hook"
    starts = starts_of(log)
    if not starts:
        return "failed", "no call of the session's that starts an agent of the reader role reached the hook"
    names = sorted({i.get("tool_name") for i in starts}, key=str)
    if not all(isinstance(name, str) and name for name in names):
        return "failed", "the hook input of the agent-starting call holds no tool name"
    if len(names) > 1:
        return "failed", f"{len(names)} tools of the session's started an agent of the reader role"
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


# K1 to K5, D3 to D5, R2, R5 and A2 to A4: each harness's own agent limits (#385). Every brief asks for a
# word of its own and the role's word, as X3's does. A brief that has its agent start another holds that
# agent's one line, so no nested path is in the prompt. The rule each judge follows is in the run's
# ticket snapshot: the files and the output show who acted, never the reply alone.
AUTHOR = "probe-author"  # no tools line: it keeps the tools that start, wait on and stop agents
LEAF = "probe-leaf"  # no tools line either, so the tools it lists show the depth limit alone
USER_ROLE = "probe-user-reader"  # R5's role, defined only in ~/.cursor/agents/
CAP = 4  # the cap probes ask for 4 agents, one more than the 3 authors deliver starts at once (#381)
AGENT_TOOLS = ("task", "agent", "agent_output", "kill_agent")  # what Cortex Code takes from an agent at the limit
WRITE = "Write the word {word}, a space and your role word to the file {marker} in the folder {work}."
KEEP = "Remember the word {keep} for later, and write it nowhere. "  # the call-back word: only in this brief
RECALL = ("Write the word {word}, a space, the word your first brief asked you to remember, a space and your role "
          "word to the file {marker} in the folder {work}.")
FORGET = " Then delete this brief file."
LIST_TOOLS = (" Then write the word {word}, a space and the names of those of these tools you have: task, agent, "
              "agent_output, kill_agent, or the word none, to the file {tools} in the folder {work}.")
CONTROL = ("Run the shell command `./control-probe.sh {control} {word}` in the folder {work}, with your role word as a "
           "third argument.")
TOGETHER = " Then run this shell command in the folder {work}: `{together}`"
DEPTH_VAR = "CORTEX_CODE_EXPERIMENTAL_FEATURES"
# Codex writes only in the session's folder: the temporary folders, which hold the probe folder, are left out.
CODEX_NO_TMP = ("-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
                "-c", "sandbox_workspace_write.exclude_slash_tmp=true")
OUTSIDE: dict[str, list[tuple[Path, str | None]]] = {}  # by codeword: what a probe made outside its folder


def marker_of(entry: str, key: str) -> str:
    return f"probe-{entry.lower()}-{key}.txt"


def line_of(entry: str, key: str) -> str:
    return f"Read {{work}}/.git/{BRIEFS}/brief-{entry.lower()}-{key}.md and follow it."


def together(entry: str, key: str, count: int) -> str:
    """Make this agent's live file and wait up to 30 seconds for `count` of them, keeping the longest list seen."""
    live, seen = f"probe-{entry.lower()}-live", f"probe-{entry.lower()}-seen-{key}.txt"
    return (f"touch {live}-{key}; best=0; for i in $(seq 30); do n=$(ls {live}-* | wc -l); if [ $n -gt $best ]; "
            f"then best=$n; ls {live}-* > {seen}; fi; [ $n -ge {count} ] && break; sleep 1; done; rm {live}-{key}")


# On Antigravity a role file with no tools line gives no shell and no file write, so the author's names the
# reader's tools and invoke_subagent (#405). Elsewhere the author's file has no tools line and keeps every tool.
AUTHOR_TOOLS = {"antigravity": TOOLS["antigravity"][0].replace("]", ", invoke_subagent]")}


def setup_limit(entry: str, briefs: dict[str, str], roles: tuple[str, ...] = (READER,), count: int = 0,
                tier: str | None = None, worktree: bool = False) -> Callable[[str, Path, str], None]:
    """The roles' files, a brief per key, and for D5 a worktree beside the probe folder."""
    def setup(harness: str, work: Path, codeword: str) -> None:
        words = WORDS[codeword] = {use: f"{use}-{secrets.token_hex(4)}"
                                   for use in (*briefs, *roles, "control", "outside", "keep")}
        folder = work / DEFINITION_DIRS[harness]
        for role in roles:
            folder.mkdir(parents=True, exist_ok=True)
            tools = None if role in (AUTHOR, LEAF) else TOOLS.get(harness, (None, None))[role == REVIEWER]
            if role == AUTHOR and harness in AUTHOR_TOOLS:
                tools = AUTHOR_TOOLS[harness]
            text = role_file(harness, role, role.removeprefix("probe-"), tools, words[role])
            if tier and role == READER:
                text = text.replace("\n---\n\n", f"\nmodel: {tier}\n---\n\n", 1)
            (folder / (role + (".toml" if harness == "codex" else ".md"))).write_text(text)
        if worktree:
            subprocess.run(["git", "-C", str(work), "worktree", "add", "-q", "--orphan", "-b", "probe-outside",
                            str(work.parent / "outside")], check=True)
        fill = {"work": work, "root": work.parent, "control": words["control"], "outside": words["outside"],
                "keep": words["keep"], **{f"line_{key}": line_of(entry, key).replace("{work}", str(work))
                                          for key in briefs}}
        shared = work / ".git" / BRIEFS
        shared.mkdir(parents=True, exist_ok=True)
        for key, text in briefs.items():
            body = text.format(word=words[key], marker=marker_of(entry, key), tools=marker_of(entry, f"{key}-tools"),
                               together=together(entry, key, count), **fill)
            (shared / f"brief-{entry.lower()}-{key}.md").write_text(f"# Probe brief\n\n{body} Change nothing else.\n")
    return setup


def file_holds(path: Path, run: Finished, *uses: str) -> bool:
    """Whether the file holds the word the kit drew for each use: a brief's key or a role."""
    words, drawn = path.read_text(errors="replace").split() if path.is_file() else [], WORDS.get(run.codeword, {})
    return all(drawn.get(use) in words for use in uses)


def marker(run: Finished, entry: str, key: str, *uses: str) -> bool:
    return file_holds(run.work / marker_of(entry, key), run, key, *uses)


def tools_listed(run: Finished, entry: str, key: str) -> tuple[str, ...] | None:
    """The agent tools the agent of that key listed beside its brief's word; None when it listed nothing."""
    path = run.work / marker_of(entry, f"{key}-tools")
    if not file_holds(path, run, key):
        return None
    words = path.read_text(errors="replace").split()
    return tuple(tool for tool in AGENT_TOOLS if tool in words)


@dataclass(frozen=True)
class Call:
    """A tool_use item of an assistant event (Claude Code's format, which Cortex Code shares)."""
    id: str
    parent: str | None  # the event's parent_tool_use_id: the call that started the agent that made this one
    name: str
    input: dict


def tool_calls(events: list[dict]) -> list[Call]:
    """The stream's tool calls in order; one with no id or no input is left out."""
    calls = []
    for event in events:
        message = event.get("message")
        content = message.get("content") if event.get("type") == "assistant" and isinstance(message, dict) else None
        for item in content if isinstance(content, list) else ():
            if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("id") \
                    and isinstance(item.get("input"), dict):
                calls.append(Call(str(item["id"]), event.get("parent_tool_use_id") or None, str(item.get("name")),
                                  item["input"]))
    return calls


def call_results(events: list[dict]) -> dict[str, tuple[str, bool]]:
    """Each tool_result item by the id of its call: its content as text, and whether it is an error.

    Cortex Code gives a failed call's error as plain content with no flag, such as "task tool failed: ..." (#405).
    """
    found = {}
    for event in events:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else ():
            if isinstance(item, dict) and item.get("type") == "tool_result" and item.get("tool_use_id"):
                given = item.get("content")
                error = item.get("is_error") is True or (isinstance(given, str)
                                                         and re.match(r"\w+ tool failed:", given) is not None)
                found[str(item["tool_use_id"])] = (json.dumps(given), error)
    return found


def started(calls: list[Call], entry: str, key: str) -> Call | None:
    """The first task call, not a resume, whose prompt names the brief of that key."""
    brief = f"brief-{entry.lower()}-{key}.md"
    return next((call for call in calls if call.name == "task" and brief in str(call.input.get("prompt"))
                 and not call.input.get("resume")), None)


def agent_id(results: dict[str, tuple[str, bool]], call: Call | None) -> str | None:
    """The agentId the result of a successful call gives."""
    text, error = results.get(call.id, ("", True)) if call else ("", True)
    found = None if error else re.search(r"agentId\W+([A-Za-z0-9_-]+)", text)
    return found[1] if found else None


def waited(calls: list[Call], results: dict[str, tuple[str, bool]], call: Call | None) -> bool:
    """Whether an agent_output call with wait true names the agent the call started."""
    target = agent_id(results, call)
    return target is not None and any(c.name == "agent_output" and c.input.get("wait") is True
                                      and target in c.input.values() for c in calls)


def model_under(events: list[dict], call: Call) -> str | None:
    """The model of the last assistant event tied to the call by parent_tool_use_id."""
    found = None
    for event in events:
        message = event.get("message")
        if event.get("type") == "assistant" and event.get("parent_tool_use_id") == call.id \
                and isinstance(message, dict) and model_name(message.get("model")):
            found = message["model"]
    return found


def judge_k1(harness: str, run: Finished) -> tuple[str, str]:
    events = events_of(run.out)
    calls, results = tool_calls(events), call_results(events)
    facts = []
    for outer, leaf, label in (("fg", "fgleaf", "foreground"), ("bg", "bgleaf", "background")):
        if not marker(run, "K1", outer, AUTHOR):
            return "failed", f"no {label} agent of the author role ran"
        if marker(run, "K1", leaf, REVIEWER):
            return "failed", f"a {label} agent started an agent of the reviewer role"
        tools = tools_listed(run, "K1", outer)
        if tools is None:
            return "failed", f"the {label} author did not list its tools, so the nested start was not tried"
        if not {"task", "agent"} & set(tools):
            facts.append(f"the {label} author had none of {', '.join(AGENT_TOOLS[:2])}")
            continue
        own = started(calls, "K1", outer)
        tried = [call for call in calls if own and call.parent == own.id and call.name in ("task", "agent")]
        if not tried:
            return "failed", (f"the {label} author had {', '.join(tools)}, but the output shows no call of its "
                              f"to start an agent")
        if not all(results.get(call.id, ("", False))[1] for call in tried):
            return "failed", (f"the {label} author's call to start an agent ended in no error, yet no agent of the "
                              f"reviewer role wrote its marker")
        facts.append(f"the {label} author's call to start an agent was refused")
    if not waited(calls, results, started(calls, "K1", "bg")):
        return "failed", "the output shows no agent_output call that waits for the background author"
    return "seen", "neither a foreground nor a background agent could start an agent: " + "; ".join(facts)


def most_at_once(run: Finished, entry: str, keys: list[str]) -> int | None:
    """The longest list of live agents any of them wrote; None when one left no list."""
    lists = [run.work / f"probe-{entry.lower()}-seen-{key}.txt" for key in keys]
    if not all(path.is_file() for path in lists):
        return None
    return max(len(path.read_text(errors="replace").split()) for path in lists)


def two_leaves(entry: str, background: bool) -> Callable[[str, Finished], tuple[str, str]]:
    """K2 and K3: an author two layers above two foreground leaves (draft tests 2 and 3)."""
    mode = "background" if background else "foreground"

    def judge(harness: str, run: Finished) -> tuple[str, str]:
        if not marker(run, entry, "author", AUTHOR):
            return "failed", "no agent of the author role ran"
        ran = [key for key in ("first", "second") if marker(run, entry, key, LEAF)]
        if len(ran) < 2:
            return "failed", f"{len(ran)} of the 2 agents of the leaf role ran under the author"
        lists = [tools_listed(run, entry, key) for key in ran]
        if None in lists:
            return "failed", "an agent of the leaf role did not list its tools"
        kept = [tool for tool in AGENT_TOOLS if any(tool in tools for tools in lists)]
        if kept:
            return "failed", (f"an agent of the leaf role, two layers down, has {', '.join(kept)}, so the limit is "
                              f"deeper than 2")
        events = events_of(run.out)
        calls, results = tool_calls(events), call_results(events)
        author = started(calls, entry, "author")
        if author is None or author.parent is not None or author.input.get("run_in_background") is not background:
            return "failed", f"the output does not show the session starting the author in the {mode}"
        leaves = [started(calls, entry, key) for key in ("first", "second")]
        if any(leaf is None or leaf.parent != author.id or leaf.input.get("run_in_background") is not False
               for leaf in leaves):
            return "failed", ("the output does not show the author starting both agents of the leaf role in the "
                              "foreground")
        if background and not waited(calls, results, author):
            return "failed", "the output shows no agent_output call that waits for the background author"
        most = most_at_once(run, entry, ran)
        if most is None:
            return "failed", "an agent of the leaf role left no list of the agents running beside it"
        if not background:
            if most < 2:
                return "failed", "both agents of the leaf role ran under the author, but one after the other"
            return "seen", ("both agents of the leaf role ran at once under the foreground author, two layers down, "
                            "and neither had task, agent, agent_output or kill_agent")
        if marker(run, entry, "variant", AUTHOR):
            variant_author = started(calls, entry, "variant")
            inner = [started(calls, entry, key) for key in ("vfirst", "vsecond")]
            if variant_author is None or any(call is None or call.parent != variant_author.id
                                             or call.input.get("run_in_background") is not True for call in inner):
                return "failed", ("the output does not show the author for background inner calls starting both its "
                                  "agents in the background")
            count = sum(marker(run, entry, key, LEAF) for key in ("vfirst", "vsecond"))
            variant = f"with background inner calls, {count} of 2 agents of the leaf role ran"
        else:
            variant = "the author for background inner calls did not run"
        return "seen", (f"both foreground agents of the leaf role ran under the background author, "
                        f"{'at once' if most >= 2 else 'one after the other'}; {variant}")
    return judge


def called_back(run: Finished, entry: str) -> tuple[str, str] | None:
    """The failure of a call-back, if any: the second marker must hold the word only the first brief gave."""
    if marker(run, entry, "second", READER, "keep"):
        return None
    if marker(run, entry, "second", READER):
        return "failed", "the agent that answered lacks its first brief's word, so it was not the same agent"
    return "failed", "no agent answered the call-back"


def resumed(run: Finished, entry: str, calls: list[Call], target: str, after: int) -> tuple[str, str] | None:
    """The failure, if any, of a task call that resumes the agent, made after the call at index `after`."""
    again = next((n for n, call in enumerate(calls) if call.name == "task" and call.input.get("resume") == target),
                 None)
    if again is None:
        return "failed", "the output shows no task call that resumes that agent"
    if again < after:
        return "failed", "the agent was resumed before it was killed"
    text, error = call_results(events_of(run.out)).get(calls[again].id, ("", False))
    if error:  # with the harness's reason, its ids and paths left out
        content = json.loads(text or "null")
        if isinstance(content, list):
            content = " ".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        said = content if isinstance(content, str) else ""
        # A word goes when it holds a digit, a slash or an id the kit knows for that agent, quotes and all.
        known = "".join(f"|{re.escape(str(k))}" for k in (target, calls[again].id) if k)
        reason = " ".join(re.sub(rf"\S*(?:[\d/\\]{known})\S*", "...", said).split())[:200]
        return "failed", "the resume call failed" + (f": {reason}" if reason else "")
    return called_back(run, entry)


def judge_k4(harness: str, run: Finished) -> tuple[str, str]:
    if not marker(run, "K4", "first", READER):
        return "failed", "no agent of the reader role ran"
    if (run.work / "probe-k4-slept.txt").is_file():
        return "failed", "the agent was not killed: its sleep finished"
    events = events_of(run.out)
    calls, results = tool_calls(events), call_results(events)
    target = agent_id(results, started(calls, "K4", "first"))
    if target is None:
        return "failed", "the output shows no agentId for the agent"
    kills = [call for call in calls if call.name == "kill_agent"]
    if not kills:
        return "failed", "the output shows no kill_agent call"
    kill = next((call for call in kills if target in call.input.values()), None)
    if kill is None:
        return "failed", "the kill_agent call names another agent"
    if results.get(kill.id, ("", True))[1]:
        return "failed", "the kill_agent call did not succeed"
    return resumed(run, "K4", calls, target, calls.index(kill)) or \
        ("seen", "the killed agent resumed with its earlier context")


def judge_k5(harness: str, run: Finished) -> tuple[str, str]:
    if not marker(run, "K5", "first", READER):
        return "failed", "no agent of the reader role ran"
    events = events_of(run.out)
    calls, results = tool_calls(events), call_results(events)
    first = started(calls, "K5", "first")
    target = agent_id(results, first)
    if target is None:
        return "failed", "the output shows no agentId for the agent"
    failure = resumed(run, "K5", calls, target, 0)
    if failure:
        return failure
    again = next(call for call in calls if call.name == "task" and call.input.get("resume") == target)
    after, before = model_under(events, again), model_under(events, first)
    if after is None:
        return "failed", "no assistant event tied to the call that resumed the agent names a model"
    if before is None:
        return "failed", "no assistant event tied to the call that started the agent names a model"
    return "recorded", (f"the resumed agent ran on {after}, its first run on {before}, at assistant event "
                        f".message.model")


def judge_d3(harness: str, run: Finished) -> tuple[str, str]:
    ran = sum(marker(run, "D3", key, READER) for key in ("one", "two"))
    if ran < 2:
        return "failed", f"{ran} of the 2 agents asked for in one message ran"
    log = hook_log(run.work)  # Codex's output shows no agent start; its hook log does (#405)
    if not log:
        return "failed", no_input(run)
    starts, agents = len(starts_of(log)), len(agents_of(log))
    if (starts, agents) != (2, 2):
        return "failed", (f"both agents ran, but the hook log shows {starts} starts of the reader role and "
                          f"{agents} agents of it, not 2 and 2")
    # Two calls under way at once come from one model step: the next step waits for the calls before it.
    under_way = set()
    for event in events_of(run.out):
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if item.get("tool") != "spawn_agent" or not item.get("id"):
            continue
        if event.get("type") == "item.completed":
            break
        if event.get("type") == "item.started":
            under_way.add(item["id"])
    if len(under_way) >= 2:
        return "seen", ("both agents ran, and both spawn_agent calls started before either ended, so one model step "
                        "made them")
    if not any(isinstance(event.get("item"), dict) and event["item"].get("tool") == "spawn_agent"
               for event in events_of(run.out)):  # this Codex version's output shows no agent start (#405)
        return "recorded", ("both agents ran and the hook log shows 2 starts and 2 agents; the output shows no "
                            "spawn_agent item, so whether one model step made them was not measured")
    return "failed", ("both agents ran, but the output does not show both starts in one model step, so the step "
                      "was not measured")


def session_call(log: list[dict], tool: str, start: int) -> int | None:
    """The index in the hook inputs of the session's first call of that tool from `start` on. Codex's hook names
    a collaboration tool with a prefix, as collaborationspawn_agent (#405), so the name ends with the tool's."""
    calls = inputs(log)
    return next((n for n in range(start, len(calls)) if "agent_id" not in calls[n]
                 and str(calls[n].get("tool_name")).endswith(tool)), None)


def judge_d4(harness: str, run: Finished) -> tuple[str, str]:
    if not marker(run, "D4", "first", READER):
        return "failed", "no agent of the reader role ran"
    log = hook_log(run.work)  # Codex's output shows no agent start and no interrupt; its hook log does (#405)
    if not log:
        return "failed", no_input(run)
    calls, agents = inputs(log), agents_of(log)
    if not agents:
        return "failed", "the hook log shows no call of an agent of the reader role"
    target = agents[0]
    first = next(n for n, i in enumerate(calls) if str(i.get("agent_id")) == target)
    # The calls may name the agent by its agent_id or by the task_name its start gave it (#405).
    start = next((i for i in reversed(calls[:first]) if i in starts_of(log)), {})
    task = start.get("tool_input", {}).get("task_name")
    def named(n: int) -> bool:
        given = calls[n].get("tool_input")
        return holds(given, target) or (isinstance(task, str) and task in strings(given))
    stop = session_call(log, "interrupt_agent", first)
    if stop is None:
        return "failed", "the hook log shows no interrupt_agent call of the session's after the agent's first call"
    if not named(stop):
        return "failed", "the interrupt_agent call names another agent"
    again = session_call(log, "followup_task", stop)
    if again is None or not named(again):
        return "failed", "the hook log shows no followup_task call to the agent after its interrupt"
    if not any(str(i.get("agent_id")) == target for i in calls[again + 1:]):
        return "failed", "the hook log shows no call of the agent's after the follow-up"
    return called_back(run, "D4") or ("seen", "the interrupted agent answered the follow-up with its earlier "
                                              "context")


def judge_d5(harness: str, run: Finished) -> tuple[str, str]:
    if not marker(run, "D5", "inside", READER):
        return "failed", "no agent of the reader role ran"
    if file_holds(run.work.parent / "outside" / marker_of("D5", "outside"), run, "outside", READER):
        return "seen", "the agent wrote in its worktree outside the session's writable directories"
    return "failed", "the agent ran, but its file in the worktree outside the writable directories is missing"


def judge_cap(entry: str) -> Callable[[str, Finished], tuple[str, str]]:
    keys = [f"agent{n}" for n in range(1, CAP + 1)]

    def judge(harness: str, run: Finished) -> tuple[str, str]:
        ran = [key for key in keys if marker(run, entry, key, READER)]
        if len(ran) < CAP:
            return "failed", (f"{len(ran)} of the {CAP} agents ran, so a cap is not told apart from agents "
                              f"never started")
        most = most_at_once(run, entry, ran)
        if most is None:
            return "failed", "an agent left no list of the agents running beside it"
        if most >= CAP:
            return "recorded", f"no cap up to {CAP}: all {CAP} agents ran at once"
        # Fewer at once can be a slow start as well as a queue: the files show no limit, so none is named.
        return "recorded", (f"all {CAP} agents ran, at most {most} at once; nothing shows a limit or a queue, so no "
                            f"cap is named")
    return judge


def judge_r5(harness: str, run: Finished) -> tuple[str, str]:
    path = run.work / marker_of("R5", "user")
    if not path.is_file():
        return "failed", "no marker the brief names"
    if not file_holds(path, run, "user", USER_ROLE):
        return "failed", "the marker the brief names lacks the brief's word or the user-level role's word"
    return "seen", "an agent of the role defined only in ~/.cursor/agents/ wrote the marker its brief names"


def agent_hook_lines(run: Finished, role: str, key: str) -> list[dict]:
    """The hook log lines of the agent's control commands: the control word, its brief's word and its role's word."""
    drawn = WORDS.get(run.codeword, {})
    return [line for line in hook_log(run.work)
            if all(drawn.get(use) and drawn[use] in str(line.get("command")) for use in ("control", key, role))]


def tool_of(line: dict) -> str:
    call = (line.get("input") or {}).get("toolCall") if isinstance(line.get("input"), dict) else None
    name = call.get("name") if isinstance(call, dict) else None
    return name if isinstance(name, str) and re.fullmatch(r"[A-Za-z_]+", name) else "unnamed"


ENDINGS = ("refused", "failed", "wrote")  # how A2's agent says its write_file call ended
A2_BRIEF = (CONTROL + " Then write the word {word}, a space and your role word to the file {marker} in the folder "
            "{work} with the write_file tool, not with run_command. Then run the shell command `./control-probe.sh "
            "{control} {word} result` in the folder {work}, with your role word and then one word for how the "
            "write_file call ended: refused if the tool was refused or unavailable, failed if it failed another "
            "way, wrote if it wrote the file.")


def judge_a2(harness: str, run: Finished) -> tuple[str, str]:
    lines = agent_hook_lines(run, REVIEWER, "write")
    if not lines:
        return "failed", "no agent of the reviewer role ran a command the hook saw"
    target, role_word = marker_of("A2", "write"), WORDS.get(run.codeword, {}).get(REVIEWER)
    writes = [line for line in hook_log(run.work) if tool_of(line) == "write_file"
              and all(found and found in str(line.get("command")) for found in (target, role_word))]
    if (run.work / target).is_file():
        if not writes and any(tool_of(line) == "run_command" and target in str(line.get("command"))
                              for line in hook_log(run.work)):
            return "failed", "the agent wrote the file through run_command, not the withheld tool"
        return "failed", "the withheld tool wrote the file"
    said = []  # the first ending after `result` in each report the hook saw
    for line in lines:
        words = re.findall(r"[\w-]+", str(line.get("command")))
        said += [word for word in words[words.index("result"):] if word in ENDINGS][:1] if "result" in words else []
    if not writes:  # Antigravity takes a withheld tool away, so the agent has none to call (#405)
        if said[-1:] == ["refused"]:
            return "seen", ("the withheld write_file tool was absent: the agent made no call to it, wrote no file "
                            "and reported it could not")
        return "failed", "the agent made no write_file call and did not report it refused, so the tool's absence is " \
                         "not shown"
    if said[-1:] == ["refused"]:
        return "seen", "the agent's write_file call to the marker was refused, as it reported"
    if said[-1:] == ["failed"]:
        return "failed", "the agent's write_file call failed another way, as it reported, so no refusal is shown"
    return "failed", "the agent did not report how its write_file call ended, so no refusal is shown"


A3_CALLS = (("tiered", READER, "pro"), ("pro", AUTHOR, "pro"), ("flash", AUTHOR, "flash"))  # key, role, call's tier


def asked_tier(run: Finished, key: str) -> str | None:
    """The Model of the invoke_subagent call the hook saw for the brief of that key."""
    for line in hook_log(run.work):
        call = (line.get("input") or {}).get("toolCall") if isinstance(line.get("input"), dict) else None
        given = call.get("args") if isinstance(call, dict) else None
        if tool_of(line) == "invoke_subagent" and isinstance(given, dict) and f"brief-a3-{key}.md" in json.dumps(given):
            tiers = [value for name, value in given.items() if "model" in name.lower() and isinstance(value, str)]
            return tiers[0].lower() if tiers else None
    return None


def judge_a3(harness: str, run: Finished) -> tuple[str, str]:
    models = {}
    for key, role, tier in A3_CALLS:
        if not marker(run, "A3", key, role):
            return "failed", f"no agent of the {role.removeprefix('probe-')} role ran for the {key} brief"
        if asked_tier(run, key) != tier:
            return "failed", f"the hook saw no invoke_subagent call with Model {tier} for the {key} brief"
        lines = agent_hook_lines(run, role, key)
        if not lines:
            return "failed", f"the hook saw no command of the agent of the {key} brief"
        model = (lines[-1].get("input") or {}).get("modelName")
        if not model_name(model):
            return "failed", f"the hook input of the {key} brief's agent's command holds no model"
        models[key] = model
    tiered, pro, flash = models["tiered"], models["pro"], models["flash"]
    if pro == flash:
        return "failed", f"precedence could not be told: pro and flash both ran on {pro}"
    winner = {pro: "the call's tier won", flash: "the file's tier won"}.get(tiered)
    if winner is None:
        return "failed", (f"precedence could not be told: the agent whose file names flash ran on {tiered}, which "
                          f"neither pro ({pro}) nor flash ({flash}) gave")
    return "recorded", (f"{winner}: the agent whose file names flash, called with pro, ran on {tiered}; pro gave {pro} "
                        f"and flash {flash}")


def setup_r5(harness: str, work: Path, codeword: str) -> None:
    """The brief, and the role's file in ~/.cursor/agents/, named on standard error before it is made."""
    setup_limit("R5", {"user": WRITE}, roles=())(harness, work, codeword)
    WORDS[codeword][USER_ROLE] = f"{USER_ROLE}-{secrets.token_hex(4)}"
    text = role_file("cursor", USER_ROLE, "reader", None, WORDS[codeword][USER_ROLE])
    folder = Path.home() / ".cursor" / "agents"
    made = OUTSIDE.setdefault(codeword, [])
    # Ctrl-C waits while a folder or the file is made and recorded, so nothing is made unrecorded.
    blocked = hasattr(signal, "pthread_sigmask")
    for parent in (folder.parent, folder):
        if blocked:
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        try:
            parent.mkdir()
            made.append((parent, None))
        except FileExistsError:
            pass
        finally:
            if blocked:
                signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
    for _ in range(3):
        name = f"probe-r5-{secrets.token_hex(4)}.md"
        shown = f"~/.cursor/agents/{name}"
        print(f"probe_kit: R5 writes {shown} and removes it when the probe ends", file=sys.stderr, flush=True)
        if blocked:
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        try:
            handle = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            made.append((folder / name, shown))
        except FileExistsError:
            print(f"probe_kit: R5 leaves {shown}, which was there already, and picks another name", file=sys.stderr,
                  flush=True)
            continue
        finally:
            if blocked:
                signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
        with os.fdopen(handle, "w") as role:
            role.write(text)
        return
    raise KitError("R5 found no free file name in ~/.cursor/agents/")


def remove_outside(codeword: str) -> None:
    """Remove what the probe made outside its folder, last first; a folder only if it is empty."""
    for path, shown in reversed(OUTSIDE.pop(codeword, [])):
        if shown is None:
            try:
                path.rmdir()
            except OSError:
                pass
            continue
        path.unlink(missing_ok=True)
        print(f"probe_kit: R5 removed {shown}", file=sys.stderr, flush=True)


def depth(features: dict) -> str:
    return f"{DEPTH_VAR}={shlex.quote(json.dumps(features))}"


def start(role: str, background: str, entry: str, key: str) -> str:
    return f"subagent_type {role}, run_in_background {background} and the prompt: {line_of(entry, key)}"


def outer(leaf: str) -> str:
    """K1's author brief: list the agent tools, then try to start the leaf (draft test 1)."""
    return (WRITE + LIST_TOOLS + " If you have task or agent, call it once with subagent_type " + REVIEWER +
            ", run_in_background false and the prompt: {line_" + leaf + "} Report its reply or the exact error text.")


def author_brief(first: str, second: str, background: str) -> str:
    """K2 and K3's author brief: start two leaves in one message (draft tests 2 and 3)."""
    wait = " Then call agent_output with wait true for each." if background == "true" else ""
    return (WRITE + f" Then, in one message, make two task calls, both with subagent_type {LEAF} and "
            f"run_in_background {background}: the first with the prompt: {{line_{first}}} and the second with the "
            f"prompt: {{line_{second}}}{wait} Return both replies word for word.")


LEAF_BRIEF = WRITE + LIST_TOOLS + TOGETHER
WAIT = "Then call agent_output with wait true for it. "


def author_prompt(entry: str, background: bool) -> Callable[[str], str]:
    variant = (f"Then call the task tool once with {start(AUTHOR, 'true', entry, 'variant')} {WAIT}"
               if background else "")
    return lambda h: (f"Call the task tool once with {start(AUTHOR, str(background).lower(), entry, 'author')} "
                      f"{WAIT if background else ''}{variant}Then print the agents' replies word for word and stop. "
                      f"Do not open those files yourself.")


def resume_prompt(entry: str, kill: bool) -> Callable[[str], str]:
    first = start(READER, "true" if kill else "false", entry, "first")
    step = (f"Step 2: wait until the file {{work}}/{marker_of(entry, 'first')} exists, then call kill_agent with that "
            f"agentId. Step 3: " if kill else "Step 2: ")
    return lambda h: (f"Step 1: call the task tool with {first} Note the agentId in the result. {step}call the "
                      f"task tool again with resume set to that agentId, {start(READER, 'false', entry, 'second')} "
                      f"Print the second reply word for word. Do not open those files yourself, and do nothing else.")


def cap_prompt(tool: str, unit: str) -> Callable[[str], str]:
    entry = "R2" if tool == "Task" else "A4"
    lines = " ".join(f"{n}: {line_of(entry, f'agent{i}')}" for i, n in enumerate(("First", "Second", "Third",
                                                                                   "Fourth"), 1))
    return lambda h: (f"Start four agents of the role {READER} at once, with four {tool} calls in one {unit}, each "
                      f"in the background. Give each its own line, word for word, as its whole prompt. {lines} "
                      f"Then wait for all four. Do not open those files yourself, and do nothing else.")


# The arguments the prompts give spawn_agent besides the message; the tool also takes task_name, which the model
# fills, and offers the kit's roles as agent_type once codex_roles() loads them (#405).
CODEX_START = "agent_type {role}, fork_turns none"


def spawn_prompt(entry: str) -> Callable[[str], str]:
    return lambda h: (f"Call spawn_agent once with {CODEX_START.format(role=READER)} and the message: "
                      f"{line_of(entry, 'inside')} {CODEX_WAIT}Do not open that file yourself, and do nothing else.")


def a3_prompt(harness: str) -> str:
    calls = " ".join(f"Start one agent of the role {role} with invoke_subagent, with Model {tier}, and give it this "
                     f"line, word for word, as its whole prompt: {line_of('A3', key)}" for key, role, tier in A3_CALLS)
    return f"{calls} Do not open those files yourself, and do nothing else."


A3_BRIEF = CONTROL + " Then " + WRITE[0].lower() + WRITE[1:]
# Resume reads the saved session, and --private saves none, so K4 and K5 run without it (#405).
RESUMABLE = [part for part in COMMANDS["cortex"] if part != "--private"]
PROBES.update({
    "K1": Probe(lambda h: (f"Call the task tool once with {start(AUTHOR, 'false', 'K1', 'fg')} Then call the task "
                           f"tool once with {start(AUTHOR, 'true', 'K1', 'bg')} Then call agent_output with wait "
                           f"true for it. Do not open those files yourself, and do nothing else."),
                judge_k1, env=depth({}), setup=setup_limit("K1", {
                    "fg": outer("fgleaf"), "fgleaf": WRITE, "bg": outer("bgleaf"), "bgleaf": WRITE},
                    roles=(AUTHOR, REVIEWER))),
    "K2": Probe(author_prompt("K2", False), two_leaves("K2", False), env=depth({"maxSubagentDepth": 2}),
                setup=setup_limit("K2", {"author": author_brief("first", "second", "false"), "first": LEAF_BRIEF,
                                         "second": LEAF_BRIEF}, roles=(AUTHOR, LEAF), count=2)),
    "K3": Probe(author_prompt("K3", True), two_leaves("K3", True), env=depth({"maxSubagentDepth": 2}),
                setup=setup_limit("K3", {"author": author_brief("first", "second", "false"), "first": LEAF_BRIEF,
                                         "second": LEAF_BRIEF, "variant": author_brief("vfirst", "vsecond", "true"),
                                         "vfirst": WRITE, "vsecond": WRITE}, roles=(AUTHOR, LEAF), count=2)),
    "K4": Probe(resume_prompt("K4", True), judge_k4, command=RESUMABLE, setup=setup_limit("K4", {
        "first": KEEP + WRITE + FORGET + " Then run the bash command `sleep 300 && touch {work}/probe-k4-slept.txt`.",
        "second": RECALL})),
    "K5": Probe(resume_prompt("K5", False), judge_k5, command=RESUMABLE,
                setup=setup_limit("K5", {"first": KEEP + WRITE + FORGET, "second": RECALL})),
    "D3": Probe(lambda h: (f"In one message, make two spawn_agent calls, both with {CODEX_START.format(role=READER)}: "
                           f"the first with the message: {line_of('D3', 'one')} and the second with the "
                           f"message: {line_of('D3', 'two')} Then call wait_agent for both and end only when both "
                           f"have finished. Do not open those files yourself, and do nothing else."),
                judge_d3, hook=True, setup=setup_limit("D3", {"one": WRITE, "two": WRITE})),
    "D4": Probe(lambda h: (f"Step 1: call spawn_agent with {CODEX_START.format(role=READER)} and the message: "
                           f"{line_of('D4', 'first')} Wait for it with wait_agent. Step 2: call interrupt_agent for "
                           f"it. Step 3: send it this message with followup_task: {line_of('D4', 'second')} "
                           f"{CODEX_WAIT}Do not open those files yourself, and do nothing else."),
                judge_d4, hook=True, setup=setup_limit("D4", {"first": KEEP + WRITE + FORGET, "second": RECALL})),
    "D5": Probe(spawn_prompt("D5"), judge_d5, args=CODEX_NO_TMP, setup=setup_limit("D5", {
        "inside": WRITE + " Then write the word {outside}, a space and your role word to the file probe-d5-outside.txt "
                          "in your worktree, the folder {root}/outside."}, worktree=True)),
    "R2": Probe(cap_prompt("Task", "message"), judge_cap("R2"),
                setup=setup_limit("R2", {f"agent{n}": WRITE + TOGETHER for n in range(1, CAP + 1)}, count=CAP)),
    "R5": Probe(lambda h: (f"Start one agent of the role {USER_ROLE} and give it this line, word for word, as its "
                           f"whole prompt: {line_of('R5', 'user')} Do not open that file yourself, and do nothing "
                           f"else."), judge_r5, setup=setup_r5),
    "A2": Probe(lambda h: (f"Start one agent of the role {REVIEWER} with invoke_subagent and give it this line, word "
                           f"for word, as its whole prompt: {line_of('A2', 'write')} Do not open that file yourself, "
                           f"and do nothing else."), judge_a2, hook=True,
                setup=setup_limit("A2", {"write": A2_BRIEF}, roles=(REVIEWER,))),
    "A3": Probe(a3_prompt, judge_a3, hook=True, setup=setup_limit(
        "A3", {key: A3_BRIEF for key, _, _ in A3_CALLS}, roles=(READER, AUTHOR), tier="flash")),
    "A4": Probe(cap_prompt("invoke_subagent", "turn"), judge_cap("A4"),
                setup=setup_limit("A4", {f"agent{n}": WRITE + TOGETHER for n in range(1, CAP + 1)}, count=CAP)),
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
    except KeyboardInterrupt:  # each probe's finally has run; a traceback would print local paths
        print("probe_kit: interrupted", file=sys.stderr)
        return 130
    finally:
        if USER_LEVEL["made"]:  # the last line, after every other
            left, changed = USER_LEVEL["left"], USER_LEVEL["changed"]
            undone = ([f"remove {listed(left)}"] if left else []) + (
                [f"restore {listed(changed)} to what it held before"] if changed else [])
            print("probe_kit: the machine was left as it was" if not undone else
                  f"probe_kit: could not {' and '.join(undone)}; {'fix' if changed else 'remove'} by hand", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
