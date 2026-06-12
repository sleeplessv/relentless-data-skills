#!/usr/bin/env python3
"""Registry generator.

Each skill's ``skills/<skill>/plugin.json`` is the single source of truth
for its name, version, and description. This script projects that data onto
the two registry surfaces a user discovers skills from:

- the ``plugins`` array in ``.claude-plugin/marketplace.json``
- the skills table in the root ``README.md``, between the
  ``<!-- skills-table:begin -->`` / ``<!-- skills-table:end -->`` markers

Modes:

- ``--write``  regenerate both files in place
- ``--check``  fail (exit 1) if the committed files differ from what
               ``--write`` would produce — the CI guard against hand-edits
               and skills landing unregistered

Standard library only. Exit code 0 = in sync / written, 1 = problems.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
README = REPO_ROOT / "README.md"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"

TABLE_BEGIN = "<!-- skills-table:begin -->"
TABLE_END = "<!-- skills-table:end -->"

REQUIRED_KEYS = ("name", "version", "description")

# Marketplace entry key order; plugin.json keys not listed here are appended
# in their original order.
ENTRY_KEY_ORDER = (
    "name",
    "source",
    "description",
    "version",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
)


def load_skills() -> tuple[list[dict], list[str]]:
    """Read every skills/*/plugin.json, sorted by directory name."""
    skills: list[dict] = []
    problems: list[str] = []
    for skill_dir in sorted(d for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file()):
        plugin_json = skill_dir / "plugin.json"
        if not plugin_json.is_file():
            problems.append(f"{skill_dir.name}: skills/{skill_dir.name}/plugin.json is missing")
            continue
        plugin = json.loads(plugin_json.read_text(encoding="utf-8"))
        for key in REQUIRED_KEYS:
            if not plugin.get(key):
                problems.append(f"{skill_dir.name}: plugin.json is missing {key!r}")
        if plugin.get("name") != skill_dir.name:
            problems.append(
                f"{skill_dir.name}: plugin.json name is {plugin.get('name')!r}, "
                f"expected the directory name {skill_dir.name!r}"
            )
        skills.append(plugin)
    return skills, problems


def render_marketplace(skills: list[dict]) -> str:
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    plugins = []
    for plugin in skills:
        entry = dict(plugin)
        entry["source"] = f"./skills/{plugin['name']}"
        ordered = {k: entry.pop(k) for k in ENTRY_KEY_ORDER if k in entry}
        ordered.update(entry)
        plugins.append(ordered)
    marketplace["plugins"] = plugins
    return json.dumps(marketplace, indent=2, ensure_ascii=False) + "\n"


def render_table(skills: list[dict]) -> str:
    lines = ["| Skill | What it does |", "| --- | --- |"]
    for plugin in skills:
        name = plugin["name"]
        description = " ".join(str(plugin["description"]).split()).replace("|", "\\|")
        lines.append(f"| [`{name}`](skills/{name}/) | {description} |")
    return "\n".join(lines)


def render_readme(skills: list[dict]) -> str:
    text = README.read_text(encoding="utf-8")
    begin = text.find(TABLE_BEGIN)
    end = text.find(TABLE_END)
    if begin == -1 or end == -1 or end < begin:
        raise SystemExit(
            f"README.md is missing the {TABLE_BEGIN} / {TABLE_END} markers "
            "around the skills table — restore them before regenerating."
        )
    head = text[: begin + len(TABLE_BEGIN)]
    tail = text[end:]
    return f"{head}\n{render_table(skills)}\n{tail}"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else None
    if mode not in ("--write", "--check"):
        print(f"usage: {Path(sys.argv[0]).name} --write | --check")
        return 1

    skills, problems = load_skills()
    if problems:
        print(f"registry sync FAILED ({len(problems)} problem(s)):\n")
        for p in problems:
            print(f"  - {p}")
        return 1

    targets = {
        MARKETPLACE: render_marketplace(skills),
        README: render_readme(skills),
    }
    stale = [path for path, generated in targets.items() if path.read_text(encoding="utf-8") != generated]

    if mode == "--check":
        if stale:
            names = ", ".join(str(p.relative_to(REPO_ROOT)) for p in stale)
            print(f"registry check FAILED: {names} out of sync with skills/*/plugin.json.")
            print("fix: edit the skill's plugin.json, then run scripts/sync_registry.py --write and commit.")
            return 1
        print(f"registry check OK ({len(skills)} skill(s), README + marketplace generated from plugin.json).")
        return 0

    for path in stale:
        path.write_text(targets[path], encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    if not stale:
        print("already in sync, nothing to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
