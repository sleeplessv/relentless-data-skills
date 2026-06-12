#!/usr/bin/env python3
"""SKILL.md linter.

Lints every ``skills/*/SKILL.md`` for its own integrity: required frontmatter
keys, a "Use when" trigger clause in the description, the 1024-char description
cap, the SKILL.md line budget, and YAML-safe frontmatter values (an unquoted
``: `` or `` #`` makes the YAML block unparseable, and ``npx skills`` then
drops the skill silently). Standard library only.

Exit code 0 = all clean, 1 = at least one skill has lint errors.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
REQUIRED_KEYS = ("name", "description")
LINE_BUDGET = 150
DESC_MAX = 1024


def parse_frontmatter(text: str, where: str) -> dict[str, str]:
    if not text.startswith("---"):
        raise SystemExit(f"{where}: must open with a YAML frontmatter block (---).")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SystemExit(f"{where}: frontmatter is not closed with ---.")
    fm: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#", "-")):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm


def lint(skill_md: Path) -> list[str]:
    rel = skill_md.relative_to(SKILLS_DIR.parent)
    text = skill_md.read_text(encoding="utf-8")
    errors: list[str] = []

    fm = parse_frontmatter(text, str(rel))
    for key in REQUIRED_KEYS:
        if not fm.get(key):
            errors.append(f"missing/empty frontmatter key: {key}")

    for key, value in fm.items():
        if not value.startswith(('"', "'")) and (": " in value or " #" in value):
            errors.append(
                f"frontmatter {key} is not YAML-safe: unquoted ': ' or ' #' breaks "
                "the YAML block and npx skills drops the skill silently — quote the value"
            )

    desc = fm.get("description", "")
    if "use when" not in desc.lower():
        errors.append("description must contain a 'Use when ...' trigger clause")
    if len(desc) > DESC_MAX:
        errors.append(f"description is {len(desc)} chars (max {DESC_MAX})")

    n_lines = len(text.splitlines())
    if n_lines > LINE_BUDGET:
        errors.append(f"SKILL.md is {n_lines} lines (budget {LINE_BUDGET})")

    if errors:
        print(f"{rel}: FAILED")
        for err in errors:
            print(f"  - {err}")
    else:
        print(f"{rel}: OK ({n_lines} lines, description {len(desc)} chars)")
    return errors


def main() -> int:
    skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    if not skill_files:
        raise SystemExit(f"no skills found under {SKILLS_DIR}/*/SKILL.md")

    total_errors = 0
    for skill_md in skill_files:
        total_errors += len(lint(skill_md))

    if total_errors:
        print(f"\nSKILL.md lint FAILED ({total_errors} error(s) across {len(skill_files)} skill(s)).")
        return 1
    print(f"\nSKILL.md lint OK ({len(skill_files)} skill(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
