"""Tests for scripts/gen_roles.py.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_gen_roles -v

Each test but the last copies the script into a throwaway folder and runs it
there, so the committed role files are never written. The last runs --check
against the real repo, as scripts/check.sh does.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "gen_roles.py"
READER = "skills/deliver/agents/deliver-reader.md"

READER_TEXT = """\
---
name: deliver-reader
description: Reads and searches files for a deliver session and returns what its brief asks for.
tools: Read, Grep, Glob
class: light
effort: high
---

Your brief is the prompt that started you. Read only what it asks for and return only what it asks for.
"""


class GenRolesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.root = Path(tmp)
        (self.root / "scripts").mkdir()
        shutil.copy2(SCRIPT, self.root / "scripts" / "gen_roles.py")

    def run_script(self, mode: str) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "gen_roles.py"), mode],
            capture_output=True, text=True, check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def test_write_creates_the_reader_file(self) -> None:
        self.assertEqual(self.run_script("--write"), (0, f"wrote {READER}\n"))
        self.assertEqual((self.root / READER).read_text(encoding="utf-8"), READER_TEXT)

    def test_check_passes_when_the_file_matches(self) -> None:
        self.run_script("--write")
        self.assertEqual(self.run_script("--check"), (0, "role files check OK (1 file(s)).\n"))

    def test_check_fails_and_names_a_file_that_differs(self) -> None:
        self.run_script("--write")
        (self.root / READER).write_text(READER_TEXT.replace("high", "low"), encoding="utf-8")
        self.assertEqual(
            self.run_script("--check"),
            (1, f"role files check FAILED: {READER} differs from what scripts/gen_roles.py writes.\n"
                "fix: edit ROLES in scripts/gen_roles.py, run python3 scripts/gen_roles.py --write and commit.\n"),
        )

    def test_committed_files_match(self) -> None:
        """CI runs the unit tests and not scripts/check.sh, so this test carries the check into CI."""
        proc = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual((proc.returncode, proc.stdout + proc.stderr), (0, "role files check OK (1 file(s)).\n"))


if __name__ == "__main__":
    unittest.main()
