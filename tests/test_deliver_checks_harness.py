"""Preflight's harness check (#458): the harness named from the environment, the adapter line,
the Claude Code checks skipped off Claude Code, the Cursor warning, and where the required
skills are found on each harness.

Every case runs `deliver.py preflight` at its command line in a throwaway world with a run mark,
a passing guard probe and a stack file that sets `check_command`. Each detection variable was
seen set beside `CLAUDECODE` on a real session (#381 entry X6), so every case sets `CLAUDECODE`.

    python3 -m unittest tests.test_deliver_checks_harness
"""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

harness = deliver_kit.load("checks_harness")
VARS = {"cortex-code": "CORTEX_SESSION_ID", "codex": "CODEX_THREAD_ID", "cursor": "CURSOR_AGENT",
        "antigravity": "ANTIGRAVITY_AGENT"}
ADAPTERS = {"cortex-code": "cortex.md", "codex": "codex.md", "cursor": "cursor.md", "antigravity": "antigravity.md"}
REQUIRED = ("code-review", "ponytail-review", "pr")
CURSOR_WARNING = ("warning: on Cursor the guard cannot tell an agent from the session, so only the text rule "
                  "keeps an agent from running deliver.py merge\n")


def install_everywhere(world) -> None:
    """Run `deliver.py install` for each harness, so preflight's install check (#459) passes."""
    for name in VARS:
        result = world.deliver("install", name, cwd=world.work)
        assert result.returncode == 0, result.stdout + result.stderr


class Harness(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark(run="run-5")
        self.world.probe()
        self.world.install_upstream()
        install_everywhere(self.world)
        deliver_kit.github_ok(self.world)
        (self.world.work / "docs" / "agents").mkdir(parents=True)
        (self.world.work / "docs" / "agents" / "stack.toml").write_text('check_command = "make check"\n',
                                                                        encoding="utf-8")

    def move_skills(self, folder: str, root: Path | None = None) -> None:
        """Move the installed stand-ins from Claude Code's skills folder to `<root>/<folder>`."""
        target = (root or self.world.home) / folder
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(self.world.home / ".claude" / "skills", target)

    def preflight(self, name: str | None, **env: str | None):
        return self.world.deliver("preflight", CLAUDECODE="1", **({VARS[name]: "x"} if name else {}), **env)

    def adapter_line(self, name: str) -> str:
        return f"adapter: {self.world.script.parent.parent / 'adapters' / ADAPTERS[name]}\n"

    def harness_saved(self) -> list[str]:
        return [r["harness"] for r in self.world.records()]

    def test_each_variable_names_its_harness_and_prints_its_adapter(self):
        self.move_skills(".agents/skills")
        for name in VARS:
            with self.subTest(name):
                result = self.preflight(name)
                warning = CURSOR_WARNING if name == "cursor" else ""
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f"{self.adapter_line(name)}{warning}Preflight passed.\n", ""))
                self.assertEqual(self.harness_saved()[-1], name)

    def test_the_adapter_files_exist(self):
        for name in ADAPTERS.values():
            self.assertTrue((harness.ADAPTERS / name).is_file(), name)

    def test_claude_code_when_no_variable_is_set_prints_no_adapter(self):
        result = self.preflight(None)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "Preflight passed.\n", ""))
        self.assertEqual(self.harness_saved(), ["claude-code"])

    def test_variables_are_tested_in_order(self):
        self.move_skills(".agents/skills")
        result = self.preflight("antigravity", CURSOR_AGENT="1", CODEX_THREAD_ID="t", CORTEX_SESSION_ID="s")
        self.assertEqual(result.stdout, f"{self.adapter_line('cortex-code')}Preflight passed.\n")
        result = self.preflight("antigravity", CURSOR_AGENT="1")
        self.assertEqual(result.stdout, f"{self.adapter_line('cursor')}{CURSOR_WARNING}Preflight passed.\n")
        self.assertEqual(self.harness_saved(), ["cortex-code", "cursor"])

    def test_an_empty_variable_is_unset(self):
        result = self.preflight(None, CODEX_THREAD_ID="")
        self.assertEqual(result.stdout, "Preflight passed.\n")
        self.assertEqual(self.harness_saved(), ["claude-code"])

    def test_the_claude_code_checks_do_not_run_off_claude_code(self):
        self.move_skills(".agents/skills")
        self.world.trust(self.world.work, False)
        result = self.preflight("codex", CLAUDE_CODE_EFFORT_LEVEL=None)
        self.assertEqual((result.returncode, result.stdout), (0, f"{self.adapter_line('codex')}Preflight passed.\n"))
        result = self.preflight(None, CLAUDE_CODE_EFFORT_LEVEL=None)
        self.assertEqual((result.returncode, result.stdout.splitlines()[0]), (
            10, f"REFUSED preflight.untrusted: Claude Code does not trust {self.world.work}: "
                f"{self.world.home / '.claude.json'} records no accepted trust dialog for it"))

    def test_a_stop_off_claude_code_still_prints_the_adapter_line(self):
        self.move_skills(".agents/skills")
        shutil.rmtree(self.world.home / ".agents" / "skills" / "pr")
        result = self.preflight("codex")
        self.assertEqual((result.returncode, result.stdout), (10, (
            f"{self.adapter_line('codex')}"
            "REFUSED preflight.missing-skill: a required upstream skill is not installed: pr\n"
            "Next: install pr, then run deliver.py preflight\n")))
        self.assertEqual([(s["code"], s["harness"]) for s in self.world.state_lines("preflight-stops.jsonl")],
                         [("preflight.missing-skill", "codex")])


class RequiredSkillsOffClaudeCode(unittest.TestCase):
    """`~/.agents/skills`, then the harness's user folders, then its project folders (#189 table)."""

    FOUND = {
        "cortex-code": [("home", ".snowflake/cortex/skills"), ("home", ".claude/skills"),
                        ("work", ".cortex/skills"), ("work", ".claude/skills"), ("work", ".agents/skills")],
        "codex": [("work", ".agents/skills")],
        "cursor": [("home", ".cursor/skills"), ("home", ".claude/skills"), ("home", ".codex/skills"),
                   ("work", ".agents/skills"), ("work", ".cursor/skills"), ("work", ".claude/skills"),
                   ("work", ".codex/skills")],
        "antigravity": [("home", ".gemini/config/skills"), ("work", ".agents/skills")],
    }

    def world(self):
        world = deliver_kit.World(self.addCleanup)
        world.write_mark(run="run-6")
        world.probe()
        world.install_upstream()
        install_everywhere(world)
        deliver_kit.github_ok(world)
        (world.work / "docs" / "agents").mkdir(parents=True)
        (world.work / "docs" / "agents" / "stack.toml").write_text('check_command = "make check"\n', encoding="utf-8")
        return world

    def run_on(self, world, name: str):
        return world.deliver("preflight", CLAUDECODE="1", **{VARS[name]: "x"})

    def test_found_in_every_folder_of_each_harness(self):
        for name, places in self.FOUND.items():
            for where, folder in [("home", ".agents/skills"), *places]:
                with self.subTest(harness=name, folder=f"{where}/{folder}"):
                    world = self.world()
                    target = getattr(world, where) / folder
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(world.home / ".claude" / "skills", target)
                    result = self.run_on(world, name)
                    self.assertEqual((result.returncode, result.stdout.splitlines()[-1]), (0, "Preflight passed."))

    def test_claude_codes_folder_does_not_count_on_codex(self):
        world = self.world()
        result = self.run_on(world, "codex")
        self.assertEqual((result.returncode, result.stdout.splitlines()[-2:]), (10, [
            "REFUSED preflight.missing-skill: a required upstream skill is not installed: "
            "code-review, ponytail-review, pr",
            "Next: install code-review, ponytail-review, pr, then run deliver.py preflight",
        ]))

    def test_the_agents_folder_wins_over_the_harness_folders(self):
        world = self.world()
        shutil.copytree(world.home / ".claude" / "skills", world.home / ".gemini" / "config" / "skills")
        shutil.move(world.home / ".claude" / "skills", world.home / ".agents" / "skills")
        (world.home / ".gemini" / "config" / "skills" / "pr" / "SKILL.md").write_text("edited\n", encoding="utf-8")
        result = self.run_on(world, "antigravity")
        adapter = world.script.parent.parent / "adapters" / "antigravity.md"
        self.assertEqual((result.returncode, result.stdout), (0, f"adapter: {adapter}\nPreflight passed.\n"))


if __name__ == "__main__":
    unittest.main()
