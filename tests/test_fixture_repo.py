"""Test the fixture repo's source in tests/fixture-repo.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_fixture_repo -v

The fixture repo is the repo the cross-harness test's runs work on (GLOSSARY.md). Its source is
the folder tests/fixture-repo. The folder has no __init__.py, so this repo's
`unittest discover -s tests` does not descend into it and does not run the fixture's own tests.

A test that runs the check command first copies the folder to a temporary directory and runs the
command there, with PYTHONDONTWRITEBYTECODE=1, so nothing is written into the source folder.

The small test's case runs deliver's own `small_test.measure` and `settings.load` on a throwaway
repo seeded with the fixture, as `ready` would on the finished branch.
"""
from __future__ import annotations

import itertools
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixture-repo"
TIMEOUT = 120  # seconds for one run of the check command

# Every file in the fixture: the parts #188 rule 11 lists, and the modules and their tests.
# The copy leaves out __pycache__ and .DS_Store, which .gitignore keeps out of the repo.
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
        return tomllib.load(f)["check_command"]


def run_check(root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(shlex.split(check_command(root)), cwd=root, env=env, capture_output=True,
                          text=True, timeout=TIMEOUT)


def ticket(spec: str, name: str) -> tuple[set[str], str]:
    """Return the files a ticket's section declares and the section's text without that line.

    A section holds exactly one line that starts with `Files:`, and that whole line must read
    `Files: ` followed by backticked file names separated by `, `.
    """
    section = re.search(rf"^## Ticket {name}\n(.*?)(?=^## |\Z)", spec, re.M | re.S)
    if section is None:
        raise AssertionError(f"spec.md has no section for ticket {name}")
    declarations = re.findall(r"^Files:.*$", section.group(1), re.M)
    if len(declarations) != 1:
        raise AssertionError(f"ticket {name} has {len(declarations)} Files: lines, not one")
    if not re.fullmatch(r"Files: `[^`]+`(?:, `[^`]+`)*", declarations[0]):
        raise AssertionError(f"ticket {name} has a Files: line this test cannot read: {declarations[0]!r}")
    return set(re.findall(r"`([^`]+)`", declarations[0])), section.group(1).replace(declarations[0], "")


def workflow_job(workflow: str) -> list[str]:
    """Return the lines of the one job under the workflow's top-level `jobs:` key.

    A strict reading of this one file, with no YAML library. Blank and comment lines are dropped.
    The file has exactly one `jobs:` line in column 0. The lines after it, up to the next line in
    column 0, are the jobs block. The block's first line is the one job's name, indented two
    spaces, and every later line in the block is indented at least four spaces.
    """
    lines = [line for line in workflow.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    starts = [i for i, line in enumerate(lines) if line == "jobs:"]
    if len(starts) != 1:
        raise AssertionError(f"workflow has {len(starts)} top-level jobs: keys, not one")
    block = list(itertools.takewhile(lambda line: line.startswith(" "), lines[starts[0] + 1:]))
    if not block or not re.fullmatch(r"  [A-Za-z0-9_-]+:", block[0]):
        raise AssertionError("the jobs block does not start with a job name")
    if not all(line.startswith("    ") for line in block[1:]):
        raise AssertionError("the jobs block holds more than one job, or a line this test cannot read")
    return block[1:]


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
        shutil.copytree(FIXTURE, self.copy, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))

    def assert_check_passes(self):
        result = run_check(self.copy)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_folder_holds_every_part(self):
        files = {p.relative_to(self.copy).as_posix() for p in self.copy.rglob("*") if p.is_file()}
        self.assertEqual(files, EXPECTED_FILES)

    def test_stack_toml_holds_the_check_command_and_one_critical_path(self):
        with open(self.copy / "docs/agents/stack.toml", "rb") as f:
            self.assertEqual(tomllib.load(f), {"check_command": "python3 -m unittest -v",
                                               "small_edit": {"critical_paths": ["test_calc.py"]}})

    def test_ticket_a_fails_the_small_test_and_the_small_edit_passes_it(self):
        small_test, settings = deliver_kit.load("small_test"), deliver_kit.load("settings")
        world = deliver_kit.World(self.addCleanup)
        for path in sorted(p for p in self.copy.rglob("*") if p.is_file()):
            world.commit(world.work, path.relative_to(self.copy).as_posix(), path.read_text(), "chore: seed")

        def measure(branch: str, changes: dict[str, str]) -> dict:
            tree = world.worktree(branch, branch)
            for name, text in changes.items():
                (tree / name).write_text(text)
            world.git(tree, "commit", "-q", "-am", "feat: change")
            return small_test.measure(tree, "main", settings.load(tree)[0], "two-way", {})

        calc, tests = (self.copy / "calc.py").read_text(), (self.copy / "test_calc.py").read_text()
        ticket_a = measure("ticket-a", {  # a made-up change that does ticket A
            "calc.py": calc + '\n\ndef multiply(a, b):\n    """Return a * b."""\n    return a * b\n',
            "test_calc.py": tests.replace("from calc import add, subtract", "from calc import add, multiply, subtract")
            .replace("    def test_subtract(self):", "    def test_multiply(self):\n"
                     "        self.assertEqual(multiply(4, 3), 12)\n\n    def test_subtract(self):"),
        })
        self.assertFalse(ticket_a["passed"])
        self.assertEqual(ticket_a["small_test"]["critical_paths"], ["test_calc.py"])
        self.assertIn("critical paths changed: test_calc.py", ticket_a["reason"])
        text = (self.copy / "tasks/small-edit.md").read_text()
        small = measure("small-edit", {"calc.py": calc.replace(edit_line(text, "Before"), edit_line(text, "After"))})
        self.assertTrue(small["passed"], small["reason"])

    def test_ci_workflow_has_one_job_that_runs_the_check_command(self):
        job = workflow_job((self.copy / ".github/workflows/check.yml").read_text())
        self.assertEqual(len([line for line in job if re.fullmatch(r"    runs-on: \S+", line)]), 1)
        runs = [m.group(1) for line in job if (m := re.fullmatch(r"\s+(?:- )?run: (.*)", line))]
        self.assertEqual(runs, [check_command(self.copy)])

    def test_agents_md_ends_with_an_empty_agent_runs_heading(self):
        self.assertTrue((self.copy / "AGENTS.md").read_text().endswith("\n\n## Agent runs\n"))

    def test_small_edit_applied_by_hand_still_passes(self):
        text = (self.copy / "tasks/small-edit.md").read_text()
        target = self.copy / re.search(r"^File: `([^`]+)`$", text, re.M).group(1)
        before, after = edit_line(text, "Before"), edit_line(text, "After")
        self.assertNotEqual(before, after)
        # The whole before line, indentation included, is one line of the file, exactly once,
        # and the whole after line takes its place.
        lines = target.read_text().split("\n")
        self.assertEqual(lines.count(before), 1)
        lines[lines.index(before)] = after
        target.write_text("\n".join(lines))
        self.assert_check_passes()

    def test_check_passes_on_a_copy_and_tickets_a_and_b_name_separate_files(self):
        self.assert_check_passes()
        spec = (self.copy / "tasks/spec.md").read_text()
        (files_a, task_a), (files_b, task_b) = ticket(spec, "A"), ticket(spec, "B")
        self.assertEqual(files_a, {"calc.py", "test_calc.py"})
        self.assertEqual(files_b, {"fmt.py", "test_fmt.py"})
        self.assertEqual(files_a & files_b, set())
        # Each ticket says what to do, besides naming its files.
        self.assertRegex(task_a, r"\w")
        self.assertRegex(task_b, r"\w")
        # Neither ticket creates a file, so every file it names exists in the fixture.
        for name in files_a | files_b:
            self.assertTrue((self.copy / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
