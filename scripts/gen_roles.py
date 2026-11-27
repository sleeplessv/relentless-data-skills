#!/usr/bin/env python3
"""Write deliver's role files from ROLES.

Each role file holds four fields: its tool limits, the pointer to its brief,
its model class and its effort. It names no model, because `router` picks the
model for a class, and no `skills:` field, because Claude Code silently drops
a preload of a skill closed to model invocation. Claude Code ignores the
`class` key; it is there for the session that starts the role.

Modes:

- ``--write``  write each role file
- ``--check``  exit 1, naming each file, when a committed role file differs
               from what ``--write`` would write

Standard library only. Exit code 0 = in sync or written, 1 = differs or bad usage.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = Path("skills/deliver/agents")

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


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else None
    if mode not in ("--write", "--check"):
        print(f"usage: {Path(sys.argv[0]).name} --write | --check")
        return 1

    # Bytes, not text: reading text would hide CRLF drift and crash on bytes that are not UTF-8.
    targets = {AGENTS_DIR / f"{name}.md": render(name, role).encode() for name, role in ROLES.items()}
    stale = [
        path for path, data in targets.items()
        if not (REPO_ROOT / path).is_file() or (REPO_ROOT / path).read_bytes() != data
    ]

    if mode == "--check":
        for path in stale:
            print(f"role files check FAILED: {path} differs from what scripts/gen_roles.py writes.")
        if stale:
            print("fix: run python3 scripts/gen_roles.py --write and commit. To change a role, edit ROLES there first.")
            return 1
        print(f"role files check OK ({len(targets)} file(s)).")
        return 0

    for path in stale:
        (REPO_ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (REPO_ROOT / path).write_bytes(targets[path])
        print(f"wrote {path}")
    if not stale:
        print("already in sync, nothing to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
