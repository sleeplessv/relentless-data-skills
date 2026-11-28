#!/usr/bin/env python3
"""Write deliver's role files and the other harnesses' files from ROLES.

Each role file is written from four fields: its tool limits, the pointer to its brief, its model
class and its effort. No file names a model, because `router` picks the model for a class, and
the Claude Code file has no `skills:` field, because Claude Code silently drops a preload of a
skill closed to model invocation. Claude Code ignores the `class` key; it is there for the
session that starts the role.

The four other harnesses (spec #457, "What each harness's files hold") each get, in
`skills/deliver/harness/<harness>/`, every role's file in that harness's form and the guard's
registration in that harness's hook-file form, which `deliver.py install` copies and merges:

- Cortex Code: Markdown, the tools in lowercase; no effort, as effort is one per process.
- Codex: TOML with the effort; no tools, as a Codex file cannot withhold one.
- Cursor: Markdown with no tools (`readonly` refuses every shell command) and no effort, which
  lives in the model id there.
- Antigravity: Markdown, the tools in Antigravity's names and the tier `inherit`; no effort.

Modes:

- ``--write``  write each file
- ``--check``  exit 1, naming each file, when a committed file differs
               from what ``--write`` would write

Standard library only. Exit code 0 = in sync or written, 1 = differs or bad usage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = Path("skills/deliver/agents")
HARNESS_DIR = Path("skills/deliver/harness")

# One entry per role. Add a role by adding an entry.
ROLES = {
    "deliver-reader": {
        "description": "Reads and searches files for a deliver session and returns what its brief asks for.",
        "tools": ("Read", "Grep", "Glob"),
        "class": "light",
        "effort": "high",
        "brief": "Your brief is the prompt that started you. "
                 "Read only what it asks for and return only what it asks for.",
    },
}
# Antigravity's name for each tool a role may hold, or None where no name was seen on a real run:
# a misspelled name in `tools` can hang the agent, as Antigravity's documentation says (#248's research).
ANTIGRAVITY_TOOLS = {"Read": "view_file", "Grep": None, "Glob": None}
# The registered hook command. `deliver.py install` puts the guard's path, shell-quoted, in place of
# @GUARD@ (install.GUARD_SLOT). Like the plugin's command, it exits 0 silently when the guard file is
# gone or no Python 3.13 is found. It passes no argument: the guard tells the harness from its input.
# The marker `deliver_guard=` is how install finds its own entry.
GUARD_COMMAND = (
    'deliver_guard=@GUARD@; [ -f "$deliver_guard" ] || exit 0; if command -v uv >/dev/null 2>&1; then '
    'exec uv run --python 3.13 --no-project --quiet "$deliver_guard"; fi; '
    "python3 -c 'import sys; sys.exit(sys.version_info < (3, 13))' 2>/dev/null || exit 0; "
    'exec python3 "$deliver_guard"'
)


def render(name: str, role: dict) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {role['description']}\n"
        f"tools: {', '.join(role['tools'])}\n"
        f"class: {role['class']}\n"
        f"effort: {role['effort']}\n"
        "---\n"
        "\n"
        f"{role['brief']}\n"
    )


def markdown(name: str, role: dict, *extra: str) -> str:
    return "".join(("---\n", f"name: {name}\n", f"description: {role['description']}\n",
                    *(f"{line}\n" for line in extra), "---\n", "\n", f"{role['brief']}\n"))


def render_cortex(name: str, role: dict) -> str:
    return markdown(name, role, f"tools: [{', '.join(tool.lower() for tool in role['tools'])}]")


def render_codex(name: str, role: dict) -> str:
    return (f"name = {json.dumps(name)}\ndescription = {json.dumps(role['description'])}\n"
            f"model_reasoning_effort = {json.dumps(role['effort'])}\n"
            f'developer_instructions = """\n{role["brief"]}\n"""\n')


def render_cursor(name: str, role: dict) -> str:
    return markdown(name, role)


def render_antigravity(name: str, role: dict) -> str:
    tools = [ANTIGRAVITY_TOOLS[tool] for tool in role["tools"] if ANTIGRAVITY_TOOLS[tool]]
    return markdown(name, role, f"tools: [{', '.join(tools)}]", "model: inherit")


def hook_entry(matcher: str, **extra: object) -> dict:
    command = {"type": "command", "command": GUARD_COMMAND, **extra}
    return {"matcher": matcher, "hooks": [command]}


# Per harness: the role file's suffix, its renderer, and the guard's registration in its hook-file form.
HARNESSES = {
    "cortex": (".md", render_cortex, {"hooks": {"PreToolUse": [hook_entry("bash")]}}),
    "codex": (".toml", render_codex, {"hooks": {"PreToolUse": [hook_entry("", timeout=20)]}}),
    "cursor": (".md", render_cursor, {"version": 1, "hooks": {
        "beforeShellExecution": [{"command": GUARD_COMMAND}]}}),
    "antigravity": (".md", render_antigravity,
                    {"deliver-guard": {"PreToolUse": [hook_entry("", timeout=20)]}}),
}


def targets() -> dict[Path, bytes]:
    files = {AGENTS_DIR / f"{name}.md": render(name, role) for name, role in ROLES.items()}
    for harness, (suffix, renderer, _) in HARNESSES.items():
        files |= {HARNESS_DIR / harness / f"{name}{suffix}": renderer(name, role) for name, role in ROLES.items()}
    for harness, (_, _, hooks) in HARNESSES.items():
        files[HARNESS_DIR / harness / "hooks.json"] = json.dumps(hooks, indent=2) + "\n"
    return {path: text.encode() for path, text in files.items()}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else None
    if mode not in ("--write", "--check"):
        print(f"usage: {Path(sys.argv[0]).name} --write | --check")
        return 1

    # Bytes, not text: reading text would hide CRLF drift and crash on bytes that are not UTF-8.
    files = targets()
    stale = [
        path for path, data in files.items()
        if not (REPO_ROOT / path).is_file() or (REPO_ROOT / path).read_bytes() != data
    ]

    if mode == "--check":
        for path in stale:
            print(f"role files check FAILED: {path} differs from what scripts/gen_roles.py writes.")
        if stale:
            print("fix: run python3 scripts/gen_roles.py --write and commit. To change a role, edit ROLES there first.")
            return 1
        print(f"role files check OK ({len(files)} file(s)).")
        return 0

    for path in stale:
        (REPO_ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (REPO_ROOT / path).write_bytes(files[path])
        print(f"wrote {path}")
    if not stale:
        print("already in sync, nothing to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
