"""Tests for scripts/gen_roles.py.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_gen_roles -v

setUp copies the script into a throwaway folder for every test. All tests but
test_committed_files_match run that copy, so the committed role files are never
written; test_committed_files_match runs --check on this checkout.
"""
from __future__ import annotations

import json
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

BRIEF = "Your brief is the prompt that started you. Read only what it asks for and return only what it asks for.\n"
DESCRIPTION = "Reads and searches files for a deliver session and returns what its brief asks for."
# The reader's file on each other harness, in that harness's form (spec #457, "What each harness's files hold"):
# no model, tools withheld on Cortex Code and Antigravity only, effort high on Codex only, tier inherit on Antigravity.
HARNESS_READERS = {
    "skills/deliver/harness/cortex/deliver-reader.md":
        f"---\nname: deliver-reader\ndescription: {DESCRIPTION}\ntools: [read, grep, glob]\n---\n\n{BRIEF}",
    "skills/deliver/harness/codex/deliver-reader.toml":
        f'name = "deliver-reader"\ndescription = "{DESCRIPTION}"\nmodel_reasoning_effort = "high"\n'
        f'developer_instructions = """\n{BRIEF}"""\n',
    "skills/deliver/harness/cursor/deliver-reader.md":
        f"---\nname: deliver-reader\ndescription: {DESCRIPTION}\n---\n\n{BRIEF}",
    "skills/deliver/harness/antigravity/deliver-reader.md":
        f"---\nname: deliver-reader\ndescription: {DESCRIPTION}\ntools: [view_file]\nmodel: inherit\n---\n\n{BRIEF}",
}
REVIEWER_BRIEF = ("Your prompt names a brief file. Read it and follow it. "
                  "Edit no file, start no agent, and never run `deliver.py merge`.\n")
REVIEWERS = {
    "deliver-requirements-reviewer": ("standard", "Checks a deliver change against its requirements, as its brief file asks."),
    "deliver-defect-reviewer": ("strong", "Looks for defects in a deliver change, as its brief file asks."),
}


def reviewer_files(name: str, kind: str, description: str) -> dict[str, str]:
    """A reviewer's file on each of the five harnesses: the reader's form with the shell added (spec #479)."""
    head = f"---\nname: {name}\ndescription: {description}\n"
    return {
        f"skills/deliver/agents/{name}.md":
            f"{head}tools: Read, Grep, Glob, Bash\nclass: {kind}\neffort: high\n---\n\n{REVIEWER_BRIEF}",
        f"skills/deliver/harness/cortex/{name}.md": f"{head}tools: [read, grep, glob, bash]\n---\n\n{REVIEWER_BRIEF}",
        f"skills/deliver/harness/codex/{name}.toml":
            f'name = "{name}"\ndescription = "{description}"\nmodel_reasoning_effort = "high"\n'
            f'developer_instructions = """\n{REVIEWER_BRIEF}"""\n',
        f"skills/deliver/harness/cursor/{name}.md": f"{head}---\n\n{REVIEWER_BRIEF}",
        f"skills/deliver/harness/antigravity/{name}.md":
            f"{head}tools: [view_file, run_command]\nmodel: inherit\n---\n\n{REVIEWER_BRIEF}",
    }


REVIEWER_FILES = {path: text for name, (kind, description) in REVIEWERS.items()
                  for path, text in reviewer_files(name, kind, description).items()}
SUFFIX = {"cortex": ".md", "codex": ".toml", "cursor": ".md", "antigravity": ".md"}
HOOK_FILES = [f"skills/deliver/harness/{h}/hooks.json" for h in SUFFIX]
ROLE_NAMES = ("deliver-reader", *REVIEWERS)
# In the order --write writes them: Claude Code's role files, each harness's role files, then the hook files.
ALL_FILES = [*(f"skills/deliver/agents/{name}.md" for name in ROLE_NAMES),
             *(f"skills/deliver/harness/{h}/{name}{suffix}" for h, suffix in SUFFIX.items() for name in ROLE_NAMES),
             *HOOK_FILES]


def failed(path: str) -> str:
    return (f"role files check FAILED: {path} differs from what scripts/gen_roles.py writes.\n"
            "fix: run python3 scripts/gen_roles.py --write and commit. To change a role, edit ROLES there first.\n")


FAILED = failed(READER)


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
        self.assertEqual(self.run_script("--write"), (0, "".join(f"wrote {path}\n" for path in ALL_FILES)))
        self.assertEqual((self.root / READER).read_bytes(), READER_TEXT.encode())

    def test_write_creates_each_harness_reader_file_in_its_form(self) -> None:
        self.run_script("--write")
        for path, text in HARNESS_READERS.items():
            with self.subTest(path):
                self.assertEqual((self.root / path).read_text(), text)

    def test_write_creates_each_reviewer_file_in_its_harness_form(self) -> None:
        """No model; effort on Claude Code and Codex only; the shell kept on all five (spec #479)."""
        self.run_script("--write")
        for path, text in REVIEWER_FILES.items():
            with self.subTest(path):
                self.assertEqual((self.root / path).read_text(), text)

    def test_write_creates_each_harness_hook_file_in_its_form(self) -> None:
        self.run_script("--write")
        hooks = {h: json.loads((self.root / f"skills/deliver/harness/{h}/hooks.json").read_text())
                 for h in ("cortex", "codex", "cursor", "antigravity")}
        commands = {}
        for harness, data in hooks.items():
            with self.subTest(harness):
                if harness == "cursor":
                    self.assertEqual(data["version"], 1)
                    [entry] = data["hooks"]["beforeShellExecution"]
                    commands[harness] = entry["command"]
                    continue
                [group] = data["deliver-guard"]["PreToolUse"] if harness == "antigravity" else data["hooks"]["PreToolUse"]
                self.assertEqual(group["matcher"], "bash" if harness == "cortex" else "")
                [hook] = group["hooks"]
                self.assertEqual(hook["type"], "command")
                commands[harness] = hook["command"]
        for harness, command in commands.items():
            with self.subTest(harness):
                self.assertTrue(command.startswith('deliver_guard=@GUARD@; [ -f "$deliver_guard" ] || exit 0; '))
                self.assertTrue(command.endswith('exec python3 "$deliver_guard"'))

    def test_check_fails_on_a_hand_edit_to_any_file(self) -> None:
        self.run_script("--write")
        for path in ALL_FILES:
            with self.subTest(path):
                original = (self.root / path).read_bytes()
                (self.root / path).write_bytes(original + b"\n")
                self.assertEqual(self.run_script("--check"), (1, failed(path)))
                (self.root / path).write_bytes(original)

    def test_check_passes_when_the_file_matches(self) -> None:
        self.run_script("--write")
        self.assertEqual(self.run_script("--check"), (0, f"role files check OK ({len(ALL_FILES)} file(s)).\n"))

    def test_check_fails_and_names_a_file_that_differs(self) -> None:
        self.run_script("--write")
        (self.root / READER).write_bytes(READER_TEXT.replace("high", "low").encode())
        self.assertEqual(self.run_script("--check"), (1, FAILED))

    def test_check_fails_and_write_restores_on_byte_drift(self) -> None:
        drifts = {
            "CRLF line endings": READER_TEXT.replace("\n", "\r\n").encode(),
            "bare CR line endings": READER_TEXT.replace("\n", "\r").encode(),
            "bytes that are not UTF-8": READER_TEXT.encode() + b"\xff",
        }
        self.run_script("--write")
        for label, drifted in drifts.items():
            with self.subTest(label):
                (self.root / READER).parent.mkdir(parents=True, exist_ok=True)
                (self.root / READER).write_bytes(drifted)
                self.assertEqual(self.run_script("--check"), (1, FAILED))
                self.assertEqual(self.run_script("--write"), (0, f"wrote {READER}\n"))
                self.assertEqual((self.root / READER).read_bytes(), READER_TEXT.encode())

    def test_committed_files_match(self) -> None:
        """Run the check in every CI run.

        ci.yml's tests job runs the unit tests and not scripts/check.sh, so this test runs the check there.
        """
        proc = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual((proc.returncode, proc.stdout + proc.stderr), (0, f"role files check OK ({len(ALL_FILES)} file(s)).\n"))


if __name__ == "__main__":
    unittest.main()
