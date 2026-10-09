"""Exercise the SKILL.md linter's frontmatter-key and side-effect rules on temporary skill trees."""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lint_skill  # noqa: E402

DESC = "Does a thing. Use when the user asks for the thing."


class TestLintSkill(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.skills = Path(temporary.name) / "skills"
        self.skills.mkdir()

    def add_skill(self, name: str, frontmatter: str, body: str = "# Skill\n") -> Path:
        folder = self.skills / name
        folder.mkdir()
        skill_md = folder / "SKILL.md"
        skill_md.write_text(f"---\nname: {name}\n{frontmatter}---\n\n{body}", encoding="utf-8")
        return skill_md

    def lint(self, skill_md: Path) -> list[str]:
        with contextlib.redirect_stdout(io.StringIO()):
            return lint_skill.lint(skill_md, self.skills)

    def lint_dir(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return lint_skill.lint_dir(self.skills)

    def test_unknown_key_rejected(self) -> None:
        skill_md = self.add_skill(
            "typo", f"description: {DESC}\ndisable-model-invokation: true\n"
        )
        errors = self.lint(skill_md)
        self.assertTrue(any("unknown frontmatter key: disable-model-invokation" in e for e in errors))
        self.assertEqual(self.lint_dir(), 1)

    def test_known_keys_accepted(self) -> None:
        skill_md = self.add_skill(
            "known",
            "description: Runs the flow on request.\n"
            "argument-hint: <ticket>\n"
            "disable-model-invocation: true\n"
            "allowed-tools: Bash Read\n"
            "license: MIT\n"
            "metadata:\n"
            "  version: 1.2.3\n",
        )
        self.assertEqual(self.lint(skill_md), [])
        self.assertEqual(self.lint_dir(), 0)

    def test_side_effect_command_in_model_invocable_skill_fails(self) -> None:
        skill_md = self.add_skill("pusher", f"description: {DESC}\n")
        refs = skill_md.parent / "references"
        refs.mkdir()
        (refs / "flow.md").write_text("Then run:\n\n    gh pr merge 12 --squash\n", encoding="utf-8")
        errors = self.lint(skill_md)
        self.assertEqual(len(errors), 1)
        self.assertIn("references/flow.md: gh pr merge", errors[0])
        self.assertEqual(self.lint_dir(), 1)

    def test_side_effect_command_in_user_only_skill_passes(self) -> None:
        skill_md = self.add_skill(
            "shipper",
            "description: Pushes and opens a PR.\ndisable-model-invocation: true\n",
            body="git push -u origin HEAD\ngh pr create --fill\n",
        )
        self.assertEqual(self.lint(skill_md), [])

    def test_side_effect_command_in_allowlisted_skill_passes(self) -> None:
        name = next(iter(lint_skill.SIDE_EFFECT_ALLOWLIST))
        skill_md = self.add_skill(name, f"description: {DESC}\n", body="git push\n")
        self.assertEqual(self.lint(skill_md), [])

    def test_allowlist_entries_carry_reasons(self) -> None:
        for name, reason in lint_skill.SIDE_EFFECT_ALLOWLIST.items():
            self.assertTrue(reason.strip(), name)


if __name__ == "__main__":
    unittest.main()
