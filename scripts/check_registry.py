#!/usr/bin/env python3
"""Registry cross-check.

Every skill directory (``skills/*/SKILL.md``) must be registered in both
places a user discovers skills from:

- the skills table in the root ``README.md``
- a plugin entry in ``.claude-plugin/marketplace.json``

and each marketplace entry must mirror the skill's own ``plugin.json``
(name, version, description) and point at a directory that exists. This
catches the recurring gap where a new skill lands without its registry
entries, and the slower drift where a skill's plugin.json is updated but
the marketplace copy is not.

Standard library only. Exit code 0 = registries consistent, 1 = gaps found.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
README = REPO_ROOT / "README.md"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"

# Rows in the README skills table: [`<skill>`](skills/<skill>/)
README_ROW_RE = re.compile(r"\[`([\w-]+)`\]\(skills/([\w-]+)/\)")

MIRRORED_KEYS = ("name", "version", "description")


def main() -> int:
    problems: list[str] = []

    skill_dirs = sorted(
        d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file()
    )

    readme_rows = {m.group(1) for m in README_ROW_RE.finditer(README.read_text(encoding="utf-8"))}

    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    entries = {p["name"]: p for p in marketplace.get("plugins", [])}

    for skill in skill_dirs:
        if skill not in readme_rows:
            problems.append(f"{skill}: no row in the root README skills table")
        if skill not in entries:
            problems.append(f"{skill}: no plugin entry in marketplace.json")

    for name, entry in sorted(entries.items()):
        source = entry.get("source", "")
        if source != f"./skills/{name}":
            problems.append(f"{name}: marketplace source is {source!r}, expected './skills/{name}'")
        if name not in skill_dirs:
            problems.append(f"{name}: marketplace entry has no skills/{name}/SKILL.md")
            continue
        plugin_json = SKILLS_DIR / name / "plugin.json"
        if not plugin_json.is_file():
            problems.append(f"{name}: skills/{name}/plugin.json is missing")
            continue
        plugin = json.loads(plugin_json.read_text(encoding="utf-8"))
        for key in MIRRORED_KEYS:
            if entry.get(key) != plugin.get(key):
                problems.append(
                    f"{name}: marketplace {key} drifted from plugin.json\n"
                    f"    marketplace: {entry.get(key)!r}\n"
                    f"    plugin.json: {plugin.get(key)!r}"
                )

    if problems:
        print(f"registry check FAILED ({len(problems)} problem(s)):\n")
        for p in problems:
            print(f"  - {p}")
        print(
            "\nfix: add the missing README row / marketplace entry, or re-copy "
            "the drifted fields from the skill's plugin.json (it is the source of truth)."
        )
        return 1

    print(f"registry check OK ({len(skill_dirs)} skill(s) in README + marketplace, in sync with plugin.json).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
