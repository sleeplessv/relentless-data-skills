"""Exercise scripts/word_count.py, the rule gate's word-count lint, on temporary path maps.

Each test writes a path map and the files it lists into a temporary folder, runs the
lint on that map as a subprocess, and checks the exit code and every output line.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "word_count.py"


class TestWordCount(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name: str, words: int) -> str:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(" ".join(["word"] * words) + "\n", encoding="utf-8")
        return str(path)

    def lint(self, *rows: str) -> subprocess.CompletedProcess[str]:
        path_map = self.root / "path-map.toml"
        path_map.write_text("\n".join(rows), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(path_map)],
            capture_output=True, text=True, check=False,
        )

    @staticmethod
    def row(name: str, files: list[str], limit: int | None = None) -> str:
        listed = ", ".join(f'"{f}"' for f in files)
        text = f'[[path]]\nname = "{name}"\nfiles = [{listed}]\n'
        return text if limit is None else text + f"limit = {limit}\n"

    def test_row_with_no_limit_is_printed_and_passes(self) -> None:
        a, b = self.write("a.md", 3), self.write("b.md", 4)
        result = self.lint(self.row("small edit", [a, b]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["small edit: 7 words, no limit"])
        self.assertEqual(result.stderr, "")

    def test_row_under_its_limit_passes(self) -> None:
        result = self.lint(self.row("small edit", [self.write("a.md", 9)], limit=10))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["small edit: 9 words, limit 10"])
        self.assertEqual(result.stderr, "")

    def test_row_at_its_limit_passes(self) -> None:
        result = self.lint(self.row("small edit", [self.write("a.md", 10)], limit=10))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["small edit: 10 words, limit 10"])
        self.assertEqual(result.stderr, "")

    def test_row_over_its_limit_is_refused_with_one_line(self) -> None:
        result = self.lint(self.row("small edit", [self.write("a.md", 11)], limit=10))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.splitlines(), ["small edit: 11 words, over its limit of 10"])

    def test_every_row_is_checked_after_one_is_refused(self) -> None:
        result = self.lint(
            self.row("small edit", [self.write("a.md", 11)], limit=10),
            self.row("single ticket", [self.write("b.md", 5)]),
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.splitlines(), ["single ticket: 5 words, no limit"])
        self.assertEqual(result.stderr.splitlines(), ["small edit: 11 words, over its limit of 10"])

    def test_relative_path_resolves_from_the_repo_root(self) -> None:
        words = len((REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
        result = self.lint(self.row("small edit", ["AGENTS.md"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [f"small edit: {words} words, no limit"])

    def test_missing_file_is_an_error_not_a_zero(self) -> None:
        missing = str(self.root / "agents" / "reader.md")
        result = self.lint(self.row("small edit", [self.write("a.md", 3), missing]))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.splitlines(), [f"small edit: missing file {missing}"])

    def test_listed_script_is_refused_not_counted(self) -> None:
        for script in ("scripts/run.md", "hooks/guard.py", "bin/start.sh"):
            with self.subTest(script=script):
                listed = self.write(script, 3)
                result = self.lint(self.row("small edit", [self.write("a.md", 3), listed]))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr.splitlines(),
                    [f"small edit: lists script {listed}, scripts are not counted"],
                )


class TestPathMap(unittest.TestCase):
    def test_small_edit_row_lists_its_two_files_and_its_limit(self) -> None:
        with (REPO_ROOT / "docs" / "path-map.toml").open("rb") as path_map:
            rows = tomllib.load(path_map)["path"]
        self.assertEqual(
            rows,
            [{
                "name": "small edit",
                "files": ["skills/deliver/SKILL.md", "skills/deliver/agents/deliver-reader.md"],
                "limit": 534,
            }],
        )


if __name__ == "__main__":
    unittest.main()
