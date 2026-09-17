#!/usr/bin/env python3
"""Check or bump skill versions against an explicit Git baseline."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError(f"expected major.minor.patch, got {value!r}")
    major, minor, patch = map(int, value.split("."))
    return major, minor, patch


def skill_names(paths: set[str]) -> set[str]:
    return {path.split("/")[1] for path in paths if len(path.split("/")) >= 3}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        args.base = git("rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}").strip()
    except subprocess.CalledProcessError:
        print("Cannot resolve baseline. Fetch origin and pass --base with an existing commit or ref.")
        return 1
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", args.base, "HEAD"],
                             cwd=ROOT, capture_output=True)
    if ancestor.returncode:
        print("The baseline must be an ancestor of HEAD. Merge or rebase onto the latest main first.")
        return 1
    skills_dir = ROOT / "skills"
    if skills_dir.is_symlink():
        print("skills: the skill root must not be a symlink")
        return 1
    if skills_dir.exists():
        for folder in sorted(skills_dir.iterdir()):
            if folder.is_symlink() or any((folder / name).is_symlink()
                                         for name in ("SKILL.md", "plugin.json")):
                print(f"{folder.name}: skill folders, SKILL.md, and plugin.json must not be symlinks")
                return 1
    untracked = git("ls-files", "--others", "--exclude-standard", "-z", "--",
                    "skills/*/SKILL.md", "skills/*/plugin.json")
    if untracked:
        print("Run git add on new skill files before checking or bumping versions.")
        return 1
    base_paths = set(git("ls-tree", "-r", "--name-only", "-z", args.base, "--", "skills").split("\0"))
    current_paths = {path for path in git("ls-files", "-z", "--", "skills").split("\0")
                     if path and (ROOT / path).exists()}
    changed = skill_names(set(git("diff", "--name-only", "--no-renames", "-z",
                                 args.base, "--", "skills").split("\0")))
    problems = []
    writes = []
    for name in sorted(skill_names(current_paths)):
        relative = f"skills/{name}/plugin.json"
        try:
            if relative not in current_paths or f"skills/{name}/SKILL.md" not in current_paths:
                raise ValueError("skill must contain tracked SKILL.md and plugin.json files")
            current = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            if not isinstance(current, dict) or current.get("name") != name:
                raise ValueError("plugin.json name must match the skill folder")
            if name not in skill_names(base_paths):
                if args.write:
                    current["version"] = "0.1.0"
                    writes.append((ROOT / relative, current))
                elif current.get("version") != "0.1.0":
                    problems.append(f"{name}: new skills must start at 0.1.0")
                continue
            current_version = version(current.get("version"))
            if name not in changed:
                continue
            if relative not in base_paths:
                raise ValueError("baseline skill is missing plugin.json")
            previous = json.loads(git("show", f"{args.base}:{relative}"))
            previous_version = version(previous.get("version"))
        except (ValueError, OSError) as error:
            problems.append(f"{name}: {error}")
            continue
        if current_version <= previous_version:
            if args.write:
                major, minor, patch = previous_version
                if args.bump == "major":
                    current["version"] = f"{major + 1}.0.0"
                elif args.bump == "minor":
                    current["version"] = f"{major}.{minor + 1}.0"
                else:
                    current["version"] = f"{major}.{minor}.{patch + 1}"
                writes.append((ROOT / relative, current))
            else:
                problems.append(f"{name}: bump version above {previous['version']}")
    for problem in problems:
        print(problem)
    if problems:
        return 1
    if args.write:
        for path, content in writes:
            path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{content['name']}: {content['version']}", flush=True)
        return subprocess.run([sys.executable, str(ROOT / "scripts/sync_registry.py"),
                               "--write"], cwd=ROOT).returncode
    print(f"skill versions OK ({len(changed)} changed skill folders)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
