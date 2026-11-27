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


if __name__ == "__main__":
    unittest.main()
