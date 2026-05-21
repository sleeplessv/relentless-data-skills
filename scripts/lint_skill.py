#!/usr/bin/env python3
"""SKILL.md linter.

Checks the skill's own integrity: required frontmatter keys, a "Use when"
trigger clause in the description, the 1024-char description cap, and the
SKILL.md line budget. Standard library only.

Exit code 0 = clean, 1 = lint errors.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "prefect-skill" / "SKILL.md"
REQUIRED_KEYS = ("name", "description", "license")
LINE_BUDGET = 120
DESC_MAX = 1024


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        raise SystemExit("SKILL.md must open with a YAML frontmatter block (---).")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SystemExit("SKILL.md frontmatter is not closed with ---.")
    fm: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#", "-")):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm


def main() -> int:
    text = SKILL.read_text(encoding="utf-8")
    errors: list[str] = []

    fm = parse_frontmatter(text)
    for key in REQUIRED_KEYS:
        if not fm.get(key):
            errors.append(f"missing/empty frontmatter key: {key}")

    desc = fm.get("description", "")
    if "use when" not in desc.lower():
        errors.append("description must contain a 'Use when ...' trigger clause")
    if len(desc) > DESC_MAX:
        errors.append(f"description is {len(desc)} chars (max {DESC_MAX})")

    n_lines = len(text.splitlines())
    if n_lines > LINE_BUDGET:
        errors.append(f"SKILL.md is {n_lines} lines (budget {LINE_BUDGET})")

    if errors:
        print("SKILL.md lint FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"SKILL.md lint OK ({n_lines} lines, description {len(desc)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
