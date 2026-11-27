"""The small test: counted lines, the critical lists, the dependents command and the door.

small_test.py is called by `ready` and imports only settings and core, so these tests load it
alone. Each class shares one throwaway world; each test cuts its own branch from `main` in a
worktree and measures it against `main`.

    python3 -m unittest tests.test_deliver_small_test
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

small_test = deliver_kit.load("small_test")
settings = deliver_kit.load("settings")


def lines(n: int, word: str = "line") -> str:
    return "".join(f"{word} {i}\n" for i in range(n))


class Case(unittest.TestCase):
    """One world per class. `main` holds the files of `SEED`."""

    SEED = {"src/app.py": lines(10), "tests/test_app.py": lines(10)}

    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        for name, content in cls.SEED.items():
            cls.world.commit(cls.world.work, name, content, f"chore: add {name}")
        cls.branches = 0

    def branch(self, changes: dict[str, str | None]) -> Path:
        """A worktree on a new branch from main with one commit; a change of None removes the file."""
        type(self).branches += 1
        tree = self.world.worktree(f"tree-{self.branches}", f"branch-{self.branches}")
        for name, content in changes.items():
            if content is None:
                self.world.git(tree, "rm", "-q", name)
            else:
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                self.world.git(tree, "add", name)
        self.world.git(tree, "commit", "-q", "-m", "feat: change")
        return tree

    def stack(self, text: str = "") -> dict:
        """Settings as settings.load merges them from a stack settings file holding `text`."""
        folder = Path(tempfile.mkdtemp(prefix="deliver-stack-"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "docs" / "agents").mkdir(parents=True)
        (folder / "docs" / "agents" / "stack.toml").write_text(text, encoding="utf-8")
        return settings.load(folder)[0]

    def measure(self, changes: dict[str, str | None], stack: str = "", door: str | None = "two-way",
                proofs: dict[str, str] | None = None) -> dict:
        tree = self.branch(changes)
        return small_test.measure(tree, "main", self.stack(stack), door, proofs or {"R1": "tests.test_app passes"})


class Result(Case):
    def test_a_short_low_risk_two_way_change_passes_with_everything_measured(self):
        self.assertEqual(self.measure({"src/app.py": lines(10) + lines(3, "new")}), {
            "passed": True,
            "reason": "small edit: a two-way door, 3 lines and a low blast radius",
            "small_test": {"lines": 3, "critical_paths": [], "dependents": None},
            "door": "two-way",
            "door_paths": [],
        })


class Lines(Case):
    def counted(self, changes: dict[str, str | None], stack: str = "") -> tuple[int, bool, str]:
        result = self.measure(changes, stack)
        return result["small_test"]["lines"], result["passed"], result["reason"]

    def test_fifty_lines_pass_and_fifty_one_fail(self):
        self.assertEqual(self.counted({"src/new.py": lines(50)}),
                         (50, True, "small edit: a two-way door, 50 lines and a low blast radius"))
        self.assertEqual(self.counted({"src/new.py": lines(51)}),
                         (51, False, "needs review: 51 lines, over the limit of 50"))

    def test_generated_files_and_newly_added_test_files_are_left_out(self):
        cases = {
            "a generated file": ({"src/app.py": lines(11), "data/cache.lock": lines(60)}, "", 1),
            "a new file in a test folder": ({"src/app.py": lines(11), "tests/test_new.py": lines(60)}, "", 1),
            "a new test file outside one": ({"src/app.py": lines(11), "src/test_util.py": lines(60)}, "", 1),
            "a repo's own generated pattern": (
                {"src/app.py": lines(11), "gen/api.py": lines(60)}, '[small_edit]\nexclude_generated = ["gen/**"]\n', 1),
            "a repo's own test pattern": (
                {"src/app.py": lines(11), "spec/app_spec.rb": lines(60)}, '[small_edit]\nexclude_tests = ["spec/**"]\n', 1),
        }
        for name, (changes, stack, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.counted(changes, stack)[0], expected)

    def test_changed_and_removed_test_lines_count(self):
        self.assertEqual(self.counted({"tests/test_app.py": lines(10) + lines(60, "more")})[0], 60)
        self.assertEqual(self.counted({"tests/test_app.py": None})[0], 10)

    def test_a_binary_file_adds_no_lines(self):
        self.assertEqual(self.counted({"src/app.py": lines(11), "img/logo.png": "\0PNG\0" * 100})[0], 1)


def sample(pattern: str) -> str:
    """One path a lists.toml glob matches: each `**` becomes a folder and each `*` a name."""
    return pattern.replace("**", "deep").replace("*", "x")


class Critical(Case):
    def test_a_critical_path_gives_high_blast_radius(self):
        self.assertEqual(self.measure({"docs/agents/stack.toml": "check_slots = 1\n"}), {
            "passed": False,
            "reason": "needs review: high blast radius, critical paths changed: docs/agents/stack.toml",
            "small_test": {"lines": 1, "critical_paths": ["docs/agents/stack.toml"], "dependents": None},
            "door": "two-way",
            "door_paths": [],
        })

    def test_every_default_critical_pattern_matches(self):
        samples = {pattern: sample(pattern) for pattern in settings.read_lists()["critical_paths"]}
        hit = self.measure({path: "x\n" for path in samples.values()})["small_test"]["critical_paths"]
        for pattern, path in samples.items():
            with self.subTest(pattern):
                self.assertTrue(small_test.path_matches(path, [pattern]), path)
                self.assertIn(path, hit)
        self.assertEqual(sorted(hit), sorted(set(samples.values())))

    def test_the_stack_settings_file_agents_md_and_an_added_pattern_are_critical(self):
        stack = '[small_edit]\ncritical_paths = ["billing/**"]\n'
        for path in ("docs/agents/stack.toml", "AGENTS.md", "billing/rates.py"):
            with self.subTest(path):
                self.assertEqual(self.measure({path: "x\n"}, stack)["small_test"]["critical_paths"], [path])

    def test_a_path_on_no_list_is_not_critical(self):
        self.assertEqual(self.measure({"billing/rates.py": "x\n"})["small_test"]["critical_paths"], [])


if __name__ == "__main__":
    unittest.main()
