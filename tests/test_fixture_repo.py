"""Test the fixture repo's source in tests/fixture-repo.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_fixture_repo -v

The fixture repo is the repo the cross-harness test's runs work on (GLOSSARY.md). Its source is
the folder tests/fixture-repo. The folder name has a hyphen, so it is not a Python package, and
this repo's `unittest discover -s tests` does not run the fixture's own tests.

A test that runs the check command first copies the folder to a temporary directory and runs the
command there, with PYTHONDONTWRITEBYTECODE=1, so nothing is written into the source folder.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixture-repo"
TIMEOUT = 120  # seconds for one run of the check command

# Every file in the fixture: the parts #188 rule 11 lists, and the modules and their tests.
EXPECTED_FILES = {
    ".github/workflows/check.yml",
    "AGENTS.md",
    "calc.py",
    "docs/agents/stack.toml",
    "fmt.py",
    "tasks/small-edit.md",
    "tasks/spec.md",
    "test_calc.py",
    "test_fmt.py",
}


def check_command(root: Path) -> str:
    with open(root / "docs/agents/stack.toml", "rb") as f:
        return tomllib.load(f)["check"]


def run_check(root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(shlex.split(check_command(root)), cwd=root, env=env, capture_output=True,
                          text=True, timeout=TIMEOUT)


def ticket_files(spec: str, ticket: str) -> list[set[str]]:
    """Return the files each `Files:` line in the ticket's section names, one set per line."""
    section = re.search(rf"^## Ticket {ticket}\n(.*?)(?=^## |\Z)", spec, re.M | re.S)
    if section is None:
        return []
    return [set(re.findall(r"`([^`]+)`", line))
            for line in re.findall(r"^Files: (`[^`]+`(?:, `[^`]+`)*)$", section.group(1), re.M)]


def edit_line(text: str, label: str) -> str:
    """Return the one line of code in the fenced block under `<label>:`."""
    match = re.search(rf"^{label}:\n\n```python\n(.*)\n```$", text, re.M)
    if match is None:
        raise AssertionError(f"small-edit.md has no one-line block under {label}:")
    return match.group(1)


class FixtureRepoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.copy = Path(tmp.name) / "fixture-repo"
        shutil.copytree(FIXTURE, self.copy, ignore=shutil.ignore_patterns("__pycache__"))

    def assert_check_passes(self):
        result = run_check(self.copy)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_folder_holds_every_part(self):
        files = {p.relative_to(self.copy).as_posix() for p in self.copy.rglob("*") if p.is_file()}
        self.assertEqual(files, EXPECTED_FILES)

    def test_stack_toml_holds_only_the_check_command(self):
        with open(self.copy / "docs/agents/stack.toml", "rb") as f:
            self.assertEqual(tomllib.load(f), {"check": "python3 -m unittest -v"})

    def test_ci_workflow_has_one_job_that_runs_the_check_command(self):
        workflow = (self.copy / ".github/workflows/check.yml").read_text()
        self.assertEqual(re.findall(r"^\s+runs-on: ", workflow, re.M), ["    runs-on: "])
        self.assertEqual(re.findall(r"^\s+(?:- )?run: (.*)$", workflow, re.M), [check_command(self.copy)])

    def test_agents_md_ends_with_an_empty_agent_runs_heading(self):
        self.assertTrue((self.copy / "AGENTS.md").read_text().endswith("\n\n## Agent runs\n"))

    def test_check_command_passes_on_a_copy(self):
        self.assert_check_passes()

    def test_small_edit_applied_by_hand_still_passes(self):
        text = (self.copy / "tasks/small-edit.md").read_text()
        target = self.copy / re.search(r"^File: `([^`]+)`$", text, re.M).group(1)
        before, after = edit_line(text, "Before"), edit_line(text, "After")
        source = target.read_text()
        self.assertEqual(source.count(before), 1)
        self.assertNotEqual(before, after)
        target.write_text(source.replace(before, after))
        self.assert_check_passes()

    def test_tickets_a_and_b_name_separate_files(self):
        spec = (self.copy / "tasks/spec.md").read_text()
        files_a, files_b = ticket_files(spec, "A"), ticket_files(spec, "B")
        self.assertEqual(files_a, [{"calc.py", "test_calc.py"}])
        self.assertEqual(files_b, [{"fmt.py", "test_fmt.py"}])
        self.assertEqual(files_a[0] & files_b[0], set())
        # Neither ticket creates a file, so every file it names exists in the fixture.
        for name in files_a[0] | files_b[0]:
            self.assertTrue((self.copy / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
