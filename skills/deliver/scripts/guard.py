#!/usr/bin/env python3
"""deliver's guard: a PreToolUse hook on the shell tool (#256 rules 12 to 16, #213 X7).

`hooks/hooks.json` registers it, through `uv`, or else a `python3` of 3.13 or later; with neither
it does not run. It reads Claude Code's hook input on standard input and finds
a run mark (`deliver-mark.json` in the checkout's own git directory) by walking up from the
input's `cwd` and from its own working directory to the nearest `.git`. It starts no `git`
process and imports nothing of the program, so a broken program never breaks it.

With no mark it exits 0 silently. With a mark it refuses, as a `deny` on standard output:

- a raw `gh pr merge` or `gh pr ready`, to every agent; `PROBE` is one such command;
- `deliver.py merge` when the input carries `agent_id`, so only the owner's session merges;
- a command on the one-way list (`lists.toml`, then the repo's `[one_way] extra`), and
  `deliver.py accept` and `deliver.py waive reach`, which wait for the owner.

It never answers ask. A refusal gives the exact command, names the mark file and the `finish`
command, and appends one line to `guard-refusals.jsonl` in `$DELIVER_STATE_DIR`: time, guard,
command class, `permission_mode` and run id, and no session id.

Commands are read as shell words, so text inside quotes never matches. Where the words cannot
be read, or the text holds `$(` or a backtick, the raw text is searched as well, so a doubt
refuses rather than lets a command through. A command wrapped in `bash -c` or `ssh` is not
read: the guard stops habit, not a deliberate bypass. Input it cannot read exits 0.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = "deliver-mark.json"
LOG = "guard-refusals.jsonl"
STACK = "docs/agents/stack.toml"
# A raw `gh pr merge` with a flag `gh` rejects, so it changes nothing if the guard is off.
PROBE = "gh pr merge --deliver-guard-probe"
DELIVER = f"uv run --python 3.13 --no-project {HERE / 'deliver.py'}"
OWNER = "This command waits for the owner. Ask the owner to run it."
REASONS = {
    "probe": "This is the guard probe; its refusal shows the guard is on. Run `deliver.py preflight` next.",
    "gh pr merge": "A raw `gh pr merge` is refused in a deliver run. Merge with `deliver.py merge`.",
    "gh pr ready": "A raw `gh pr ready` is refused in a deliver run. Mark the PR ready with `deliver.py ready`.",
    "deliver.py merge": "`deliver.py merge` is refused to an agent the session started. Only the session merges.",
    "deliver.py accept": OWNER,
    "deliver.py waive reach": OWNER,
    "one-way": OWNER,
}
GUARDS = {"probe": "raw-pr", "gh pr merge": "raw-pr", "gh pr ready": "raw-pr", "deliver.py merge": "agent-merge"}
PUNCTUATION = frozenset("();<>|&")
# Searched in the raw text when the words are in doubt.
RAW = {
    "gh pr": re.compile(r"\bgh\b[^;&|\n]*?\spr\s+(merge|ready)\b"),
    "deliver.py": re.compile(r"\bdeliver\.py[\s\x27\"]+(merge|accept|waive\s+reach)\b"),
}


def find_mark(start: Path) -> tuple[Path, Path] | None:
    """The checkout and mark file of the nearest `.git` above `start`, if that checkout is marked."""
    for folder in (start, *start.parents):
        dot_git = folder / ".git"
        if dot_git.is_dir():
            git_dir = dot_git
        elif dot_git.is_file():
            try:
                line = dot_git.read_text(encoding="utf-8").strip()
            except (OSError, ValueError):
                return None
            if not line.startswith("gitdir:"):
                return None
            git_dir = folder / line.removeprefix("gitdir:").strip()
        else:
            continue
        mark = git_dir / MARK
        return (folder, mark) if mark.is_file() else None
    return None


def words(command: str) -> list[str] | None:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def verbs(command: str) -> set[str]:
    """The guarded classes of `gh pr` and `deliver.py` the command runs: "gh pr merge", ..."""
    found = set()
    ws = words(command)
    for i, word in enumerate(ws or []):
        name = word.rsplit("/", 1)[-1]
        rest = ws[i + 1:]
        if name == "gh":
            for j, arg in enumerate(rest):
                if arg and set(arg) <= PUNCTUATION:
                    break
                if arg == "pr" and rest[j + 1:j + 2] in (["merge"], ["ready"]):
                    found.add(f"gh pr {rest[j + 1]}")
                    break
        elif name == "deliver.py" and rest[:1] in (["merge"], ["accept"]):
            found.add(f"deliver.py {rest[0]}")
        elif name == "deliver.py" and rest[:2] == ["waive", "reach"]:
            found.add("deliver.py waive reach")
    if ws is None or "$(" in command or "`" in command:
        found |= {f"gh pr {m}" for m in RAW["gh pr"].findall(command)}
        found |= {"deliver.py " + " ".join(m.split()) for m in RAW["deliver.py"].findall(command)}
    return found


def one_way(command: str, checkout: Path) -> bool:
    with (HERE / "lists.toml").open("rb") as f:
        patterns = tomllib.load(f)["one_way_commands"]
    try:
        with (checkout / STACK).open("rb") as f:
            extra = tomllib.load(f).get("one_way", {}).get("extra", [])
        if isinstance(extra, list):
            patterns += [p for p in extra if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        pass
    for pattern in patterns:
        try:
            if re.search(pattern, command):
                return True
        except re.error:
            continue
    return False


def classify(command: str, agent: bool, checkout: Path) -> str | None:
    """The class of the first guard that refuses the command, or None."""
    if command.strip() == PROBE:
        return "probe"
    found = verbs(command)
    for cls in ("gh pr merge", "gh pr ready"):
        if cls in found:
            return cls
    if agent and "deliver.py merge" in found:
        return "deliver.py merge"
    if one_way(command, checkout):
        return "one-way"
    for cls in ("deliver.py accept", "deliver.py waive reach"):
        if cls in found:
            return cls
    return None


def log(cls: str, mark: Path, permission_mode: object) -> None:
    try:
        run = json.loads(mark.read_text(encoding="utf-8")).get("run")
    except (OSError, ValueError, AttributeError):
        run = None
    state = Path(os.environ.get("DELIVER_STATE_DIR") or Path.home() / ".local" / "state" / "deliver")
    line = {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "guard": GUARDS.get(cls, "owner"),
            "class": cls, "permission_mode": permission_mode, "run": run}
    try:
        state.mkdir(parents=True, exist_ok=True)
        with (state / LOG).open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
        command = data["tool_input"]["command"]
    except (ValueError, TypeError, KeyError):
        return 0
    if not isinstance(command, str):
        return 0
    starts = [Path(data["cwd"])] if isinstance(data.get("cwd"), str) else []
    found = next(filter(None, (find_mark(s) for s in [*starts, Path.cwd()])), None)
    if found is None:
        return 0
    checkout, mark = found
    cls = classify(command, "agent_id" in data, checkout)
    if cls is None:
        return 0
    log(cls, mark, data.get("permission_mode"))
    reason = (
        f"deliver guard refused this command:\n{command}\n{REASONS[cls]}\n"
        f"A deliver run is in progress here (run mark: {mark}). "
        f"If none should be, end it with `{DELIVER} finish`."
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
