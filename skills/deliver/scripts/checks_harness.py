"""Which harness the session runs on, and what preflight does about it (#189 rules 2, 3, 13; spec #457).

`detect` names the harness from the environment; preflight calls it before its first check and
saves the answer in the `preflight` record. It tests `DETECTION` in order, then falls back to
Claude Code: a harness started from a Claude Code session inherits `CLAUDECODE`, so that
variable decides nothing. Each variable was seen set beside `CLAUDECODE` on a real session (#381
entry X6). On the four harnesses of `DETECTION`, preflight prints the path `adapter` gives and
skips the checks of `checks_claude`; Claude Code has no adapter. `check_cursor_guard` warns on
Cursor that the guard cannot tell an agent from the session.

`SKILL_FOLDERS` is where `deps.find` looks for an installed skill off Claude Code: `~/.agents/skills`,
where `npx skills add -g` puts it, then the harness's own user folders, then its project
folders in the checkout (#189 table, installed-skills row; spec #457 reading 7).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

CLAUDE_CODE = "claude-code"
ADAPTERS = Path(__file__).resolve().parent.parent / "adapters"
# (variable, harness, adapter file), in the order they are tested. Keep the names in step with
# guard.HARNESS_VARS, which the guard uses.
DETECTION = (
    ("CORTEX_SESSION_ID", "cortex-code", "cortex.md"),
    ("CODEX_THREAD_ID", "codex", "codex.md"),
    ("CURSOR_AGENT", "cursor", "cursor.md"),
    ("ANTIGRAVITY_AGENT", "antigravity", "antigravity.md"),
)
# harness: (user folders under the home folder, project folders under the checkout)
SKILL_FOLDERS = {
    "cortex-code": ((".snowflake/cortex/skills", ".claude/skills"),
                    (".cortex/skills", ".claude/skills", ".agents/skills")),
    "codex": ((), (".agents/skills",)),
    "cursor": ((".cursor/skills", ".claude/skills", ".codex/skills"),
               (".agents/skills", ".cursor/skills", ".claude/skills", ".codex/skills")),
    "antigravity": ((".gemini/config/skills",), (".agents/skills",)),
}
CURSOR_WARNING = ("on Cursor the guard cannot tell an agent from the session, so only the text rule "
                  "keeps an agent from running deliver.py merge")


def detect() -> str:
    """The harness this process runs on, from its environment."""
    return next((harness for var, harness, _ in DETECTION if os.environ.get(var)), CLAUDE_CODE)


def adapter(harness: str) -> Path | None:
    return next((ADAPTERS / name for _, h, name in DETECTION if h == harness), None)


def skill_roots(harness: str, checkout: Path | None) -> list[Path]:
    """The folders that hold installed skills off Claude Code, in the order they are searched."""
    home = Path.home()
    user, project = SKILL_FOLDERS[harness]
    return [home / ".agents/skills", *(home / f for f in user), *(checkout / f for f in project if checkout)]


def check_cursor_guard(ctx):
    """Preflight: warn on Cursor, whose hook input does not say which agent calls (#189 rule 13)."""
    # The result types come from the module that made `ctx`, as in check_guard.
    return sys.modules[type(ctx).__module__].Warn(CURSOR_WARNING) if ctx.harness == "cursor" else None
