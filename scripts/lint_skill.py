#!/usr/bin/env python3
"""SKILL.md linter.

Lints every ``skills/*/SKILL.md`` for its own integrity:

- required frontmatter keys (``name``, ``description``);
- only known frontmatter keys (``ALLOWED_KEYS``), so a typo such as
  ``disable-model-invokation`` fails instead of being silently ignored;
- a "Use when" trigger clause in the description (skipped for skills with
  ``disable-model-invocation: true``, whose descriptions should not carry
  trigger wording the model would never act on);
- the 1024-char description cap and the SKILL.md line budget;
- YAML-safe frontmatter values (an unquoted ``: `` or `` #`` makes the YAML
  block unparseable, and ``npx skills`` then drops the skill silently);
- outward side effects: a skill whose files (SKILL.md and everything under its
  folder) contain a command that acts on shared state (``SIDE_EFFECT_COMMANDS``,
  e.g. ``gh pr merge``, ``git push``) must set ``disable-model-invocation: true``
  or be listed in ``SIDE_EFFECT_ALLOWLIST`` with a reason.

Standard library only.

Exit code 0 = all clean, 1 = at least one skill has lint errors.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
REQUIRED_KEYS = ("name", "description")
# Deliberately stricter than the docs' 500-line guidance: the tight budget keeps
# pressure on moving detail into references/ (progressive disclosure), so the
# always-loaded SKILL.md stays short.
LINE_BUDGET = 150
DESC_MAX = 1024

# Top-level SKILL.md frontmatter keys documented in the Claude Code skills
# frontmatter reference (https://code.claude.com/docs/en/skills), which also
# covers the Agent Skills open-standard keys (license, compatibility, metadata,
# allowed-tools). Nested keys (e.g. under metadata:) are indented and not checked.
ALLOWED_KEYS = frozenset({
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
})

# Commands that act outward on shared state (remote branches, PRs, issues).
SIDE_EFFECT_COMMANDS = (
    "git push",
    "gh pr create",
    "gh pr merge",
    "gh pr comment",
    "gh pr edit",
    "gh pr review",
    "gh issue create",
    "gh issue comment",
    "gh issue edit",
    "gh issue close",
    "gh release create",
)
SIDE_EFFECT_RE = re.compile(
    r"\b(" + "|".join(re.escape(c).replace(r"\ ", r"\s+") for c in SIDE_EFFECT_COMMANDS) + r")\b"
)

# Model-invocable skills allowed to carry side-effect commands, with the reason
# the model may still load them. Keyed by skill folder name.
SIDE_EFFECT_ALLOWLIST = {
    "smart-git-commit": "pushes only when the user asked for a push or a calling skill's workflow includes it",
}

SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".venv", "venv"})


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


def side_effect_hits(skill_dir: Path) -> list[str]:
    """Return ``relpath: command`` for each side-effect command in the skill's files."""
    hits: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        rel_parts = path.relative_to(skill_dir).parts
        if not path.is_file() or any(p in SKIP_DIRS or p.startswith(".") for p in rel_parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = sorted({" ".join(m.group(1).split()) for m in SIDE_EFFECT_RE.finditer(text)})
        hits.extend(f"{path.relative_to(skill_dir)}: {cmd}" for cmd in found)
    return hits


def lint(skill_md: Path, skills_dir: Path = SKILLS_DIR) -> list[str]:
    rel = skill_md.relative_to(skills_dir.parent)
    text = skill_md.read_text(encoding="utf-8")
    errors: list[str] = []

    fm = parse_frontmatter(text, str(rel))
    for key in REQUIRED_KEYS:
        if not fm.get(key):
            errors.append(f"missing/empty frontmatter key: {key}")

    for key in fm:
        if key not in ALLOWED_KEYS:
            errors.append(
                f"unknown frontmatter key: {key} — not a documented SKILL.md key "
                "(typo?); see ALLOWED_KEYS in scripts/lint_skill.py"
            )

    for key, value in fm.items():
        if not value.startswith(('"', "'")) and (": " in value or " #" in value):
            errors.append(
                f"frontmatter {key} is not YAML-safe: unquoted ': ' or ' #' breaks "
                "the YAML block and npx skills drops the skill silently — quote the value"
            )

    desc = fm.get("description", "")
    user_only = fm.get("disable-model-invocation", "").lower() == "true"
    if user_only and "use when" in desc.lower():
        errors.append(
            "description has a 'Use when ...' trigger clause but the skill sets "
            "disable-model-invocation: true — drop the trigger wording"
        )
    if not user_only and "use when" not in desc.lower():
        errors.append("description must contain a 'Use when ...' trigger clause")
    if len(desc) > DESC_MAX:
        errors.append(f"description is {len(desc)} chars (max {DESC_MAX})")

    n_lines = len(text.splitlines())
    if n_lines > LINE_BUDGET:
        errors.append(f"SKILL.md is {n_lines} lines (budget {LINE_BUDGET})")

    skill_name = skill_md.parent.name
    if not user_only and skill_name not in SIDE_EFFECT_ALLOWLIST:
        hits = side_effect_hits(skill_md.parent)
        if hits:
            errors.append(
                "outward side-effect commands found but the skill is model-invocable: "
                + "; ".join(hits)
                + " — set disable-model-invocation: true or add the skill to "
                "SIDE_EFFECT_ALLOWLIST in scripts/lint_skill.py with a reason"
            )

    if errors:
        print(f"{rel}: FAILED")
        for err in errors:
            print(f"  - {err}")
    else:
        print(f"{rel}: OK ({n_lines} lines, description {len(desc)} chars)")
    return errors


def lint_dir(skills_dir: Path) -> int:
    """Lint every ``<skills_dir>/*/SKILL.md``; return the process exit code."""
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        raise SystemExit(f"no skills found under {skills_dir}/*/SKILL.md")

    total_errors = 0
    for skill_md in skill_files:
        total_errors += len(lint(skill_md, skills_dir))

    if total_errors:
        print(f"\nSKILL.md lint FAILED ({total_errors} error(s) across {len(skill_files)} skill(s)).")
        return 1
    print(f"\nSKILL.md lint OK ({len(skill_files)} skill(s)).")
    return 0


def main() -> int:
    return lint_dir(SKILLS_DIR)


if __name__ == "__main__":
    sys.exit(main())
