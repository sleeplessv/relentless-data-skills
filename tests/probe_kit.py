#!/usr/bin/env python3
"""Probe kit: run one harness headless through Herdr and judge each entry from the files it left.

Usage:
  python3 tests/probe_kit.py list
  python3 tests/probe_kit.py run HARNESS ENTRY... [--connection NAME] [--time-limit SECONDS] [--poll SECONDS]

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

Cortex Code needs --connection, the Snowflake connection its runs spend. The kit
passes it on the harness's command line only: it is not in the terminal name, it
is replaced by <connection> before any output reaches a file, and the kit never
prints it.

The kit judges from files: marker files, the output stream and the folder. The
raw output goes to probes/<run id>/ in the machine directory, $DELIVER_STATE_DIR
(default ~/.local/state/deliver). Each entry prints one line: the id, the
harness, seen, failed or recorded, and the fact in a few words. recorded is a
fact entry that was seen. A line holds no session id and no local path.

Exit status: 0 when every entry is seen or recorded, 1 when any failed, 2 when
hc or the harness command is missing or the command line is wrong.

The kit is never installed. Its tests are tests/test_probe_kit.py.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import threading
import shlex
import shutil
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
COMMANDS["claude"] = ["claude", "-p", "{prompt}", "--output-format", "stream-json", "--verbose",
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
    if probe.setup is not None:
        probe.setup(harness, root / "work", codeword)
    out, err = root / "out.jsonl", root / "err.txt"
    prompt = probe.prompt(harness).replace("{work}", str(root / "work"))
    argv = [part.replace("{prompt}", prompt) for part in COMMANDS[harness]]
    if harness == "cortex":
        argv += ["-c", args.connection]
    relayed = [sys.executable, str(Path(__file__).resolve()), "--relay", str(out), str(err), args.connection or "", *argv]
    line = f"{probe.env} {shlex.join(relayed)}".lstrip()
    name = f"probe-{harness}-{entry.lower()}-{os.getpid()}"
    address, ended = None, False
    try:
        started = hc("run", "--bg", "--no-notify", "--name", name, "--cwd", str(root / "work"), "bash", "-c", line)
        address = started.get("address")
        if address is None:
            return "failed", "hc run did not start the terminal"
        info = wait(address, args.time_limit, args.poll)
        ended = True
        for source in (out, err):
            text = source.read_text(errors="replace") if source.is_file() else ""
            (saved / f"{entry}-{harness}{source.suffix}").write_text(text)
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


def show_list() -> int:
    for entry, (harnesses, what) in ENTRIES.items():
        built = "" if entry in PROBES else " (not built)"
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
    args = parser.parse_args(argv)
    try:
        return show_list() if args.command == "list" else run(args)
    except KitError as error:
        print(f"probe_kit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
