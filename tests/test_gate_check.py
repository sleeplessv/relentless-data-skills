"""Test scripts/gate_check.py, the rule gate's CI check, at its command line.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_gate_check -v

Each test writes a PR body and a changed-file list into a temporary folder and runs
the script there against a throwaway git repository made once for the class. The
repository has two commits: `bare` has no `skills/deliver/` and `held` has one.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gate_check.py"
GIT = shutil.which("git")


@unittest.skipUnless(GIT, "git is not on PATH")
class GateCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        git = ["git", "-C", str(cls.repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "init", "-q"], check=True)
        (cls.repo / "README.md").write_text("x\n")
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "bare"], check=True)
        subprocess.run([*git, "tag", "bare"], check=True)
        (cls.repo / "skills" / "deliver").mkdir(parents=True)
        (cls.repo / "skills" / "deliver" / "SKILL.md").write_text("x\n")
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "held"], check=True)
        subprocess.run([*git, "tag", "held"], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def gate(self, body: str | None, *, base: str = "main", base_rev: str = "held",
             changed: tuple[str, ...] = ("skills/deliver/SKILL.md",)) -> tuple[int, str, str]:
        """Run the script as CI does; return its exit code, stdout and stderr."""
        work = Path(tempfile.mkdtemp(dir=self.tmp.name))
        (work / "body.md").write_text(body or "", newline="")
        (work / "changed").write_bytes(b"".join(path.encode() + b"\0" for path in changed))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--body", str(work / "body.md"), "--base", base,
             "--default-branch", "main", "--base-rev", base_rev, "--changed", str(work / "changed")],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout, result.stderr

    def test_silent_when_base_is_not_the_default_branch(self) -> None:
        self.assertEqual(
            self.gate(None, base="feature/deliver-stage-3"),
            (0, "gate_check: not checked: the base feature/deliver-stage-3 is not the default branch main.\n", ""))

    def test_silent_when_no_changed_file_is_under_skills_deliver(self) -> None:
        self.assertEqual(
            self.gate(None, changed=("README.md", "skills/deliver-old/SKILL.md", "docs/skills/deliver/x.md")),
            (0, "gate_check: not checked: no changed file is under skills/deliver/.\n", ""))

    def test_silent_when_the_base_has_no_skills_deliver(self) -> None:
        self.assertEqual(
            self.gate(None, base_rev="bare"),
            (0, "gate_check: not checked: the base has no skills/deliver/.\n", ""))

    def test_refuses_a_body_with_no_block(self) -> None:
        self.assertEqual(
            self.gate("## Summary\n\nchange kind: repair\n"),
            (1, "", "gate_check: refused: the PR body has no ## Change kind heading.\n"))


if __name__ == "__main__":
    unittest.main()
