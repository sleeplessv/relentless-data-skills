"""The small test: counted lines, the critical lists, the dependents command and the door.

small_test.py is meant for `ready`, which does not call it yet. Of the program's modules it
imports only core, so these tests load it alone. Each class shares one throwaway world; each
test cuts its own branch from `main` in a worktree and measures it against `main`.

    python3 -m unittest tests.test_deliver_small_test
"""
from __future__ import annotations

import json
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

small_test = deliver_kit.load("small_test")
settings = deliver_kit.load("settings")


MOVE = "move from "


def lines(n: int, word: str = "line") -> str:
    return "".join(f"{word} {i}\n" for i in range(n))


class Case(unittest.TestCase):
    """One world per class. `main` holds the files of `SEED`."""

    SEED = {"src/app.py": lines(10), "tests/test_app.py": lines(10), "src/big.py": lines(60),
            "config/old.py": lines(5)}

    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        for name, content in cls.SEED.items():
            cls.world.commit(cls.world.work, name, content, f"chore: add {name}")
        cls.branches = 0

    def branch(self, changes: dict[str, str | None]) -> Path:
        """A worktree on a new branch from main with one commit.

        A change of None removes the file; MOVE + an old name moves that file here first.
        """
        type(self).branches += 1
        tree = self.world.worktree(f"tree-{self.branches}", f"branch-{self.branches}")
        for name, content in changes.items():
            if content is None:
                self.world.git(tree, "rm", "-q", name)
            elif content.startswith(MOVE):
                (tree / name).parent.mkdir(parents=True, exist_ok=True)
                self.world.git(tree, "mv", content[len(MOVE):], name)
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

    def test_a_moved_file_counts_only_its_changed_lines(self):
        self.assertEqual(self.counted({"lib/big.py": MOVE + "src/big.py"}),
                         (0, True, "small edit: a two-way door, 0 lines and a low blast radius"))
        self.assertEqual(self.counted({"lib/big.py": MOVE + "src/big.py", "src/app.py": lines(61)}),
                         (51, False, "needs review: 51 lines, over the limit of 50"))
        tree = self.branch({"lib/big.py": MOVE + "src/big.py"})
        (tree / "lib/big.py").write_text(lines(59) + "edited\n", encoding="utf-8")
        self.world.git(tree, "commit", "-q", "-am", "feat: edit")
        self.assertEqual(small_test.measure(tree, "main", self.stack(), "two-way", {})["small_test"]["lines"], 2)

    def test_a_file_moved_to_a_generated_name_is_left_out(self):
        tree = self.branch({"data/big.lock": MOVE + "src/big.py"})
        (tree / "data/big.lock").write_text(lines(59) + "edited\n", encoding="utf-8")
        self.world.git(tree, "commit", "-q", "-am", "feat: edit")
        self.assertEqual(small_test.measure(tree, "main", self.stack(), "two-way", {})["small_test"]["lines"], 0)

    def test_a_renamed_test_file_is_not_newly_added(self):
        self.assertEqual(self.counted({"tests/test_main.py": MOVE + "tests/test_app.py"}, "")[0], 0)
        tree = self.branch({"tests/test_main.py": MOVE + "tests/test_app.py"})
        (tree / "tests/test_main.py").write_text(lines(9) + "edited\n", encoding="utf-8")
        self.world.git(tree, "commit", "-q", "-am", "feat: edit")
        self.assertEqual(small_test.measure(tree, "main", self.stack(), "two-way", {})["small_test"]["lines"], 2)

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

    def test_both_names_of_a_moved_file_meet_the_lists(self):
        stack = '[one_way]\npaths = ["infra/**"]\n'
        result = self.measure({"src/old.py": MOVE + "config/old.py", "infra/big.py": MOVE + "src/big.py"}, stack)
        self.assertEqual((result["small_test"]["lines"], result["small_test"]["critical_paths"], result["door_paths"]),
                         (0, ["config/old.py"], ["infra/big.py"]))

    def test_a_path_on_no_list_is_not_critical(self):
        self.assertEqual(self.measure({"billing/rates.py": "x\n"})["small_test"]["critical_paths"], [])


DEPENDENTS = """\
import json, sys
calls, code, out, paths = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4:]
with open(calls, "a") as f:
    f.write(json.dumps(paths) + "\\n")
sys.stdout.write(out)
sys.exit(code)
"""


class Dependents(Case):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = cls.world.root / "dependents.py"
        cls.script.write_text(DEPENDENTS, encoding="utf-8")
        cls.calls = cls.world.root / "dependents-calls.jsonl"

    def stand_in(self, out: str, code: int = 0, limit: int | None = None) -> str:
        """Stack settings naming a stand-in dependents command that prints `out` and exits `code`."""
        command = shlex.join([sys.executable, "-I", str(self.script), str(self.calls), str(code), out])
        text = f"[small_edit]\ndependents_command = {json.dumps(command)}\n"
        return text + (f"dependents_limit = {limit}\n" if limit is not None else "")

    def judged(self, out: str, code: int = 0, limit: int | None = None) -> tuple[dict | None, str]:
        result = self.measure({"src/app.py": lines(11)}, self.stand_in(out, code, limit))
        return result["small_test"]["dependents"], result["reason"]

    def test_an_empty_dependents_command_adds_no_clause(self):
        result = self.measure({"src/app.py": lines(11)})
        self.assertEqual((result["small_test"]["dependents"], result["passed"]), (None, True))

    def test_the_command_gets_every_changed_path(self):
        self.calls.unlink(missing_ok=True)
        self.measure({"src/app.py": None, "src/new.py": "x\n", "data/cache.lock": "x\n"}, self.stand_in("0\n"))
        self.assertEqual(deliver_kit.read_lines(self.calls), [["data/cache.lock", "src/app.py", "src/new.py"]])

    def test_the_command_gets_both_names_of_a_moved_file(self):
        self.calls.unlink(missing_ok=True)
        self.measure({"lib/big.py": MOVE + "src/big.py"}, self.stand_in("0\n"))
        self.assertEqual(deliver_kit.read_lines(self.calls), [["lib/big.py", "src/big.py"]])

    def test_a_count_up_to_the_limit_is_low(self):
        self.assertEqual(self.judged("5\n"), ({"count": 5, "feeds": []},
                                              "small edit: a two-way door, 1 line and a low blast radius"))
        self.assertEqual(self.judged("6\n", limit=6), ({"count": 6, "feeds": []},
                                                       "small edit: a two-way door, 1 line and a low blast radius"))

    def test_a_count_over_the_limit_is_high(self):
        self.assertEqual(self.judged("6\n"), (
            {"count": 6, "feeds": []},
            "needs review: high blast radius, the change feeds 6 dependents, over the limit of 5"))

    def test_a_named_report_or_exposure_is_high(self):
        self.assertEqual(self.judged("1\nreport weekly_revenue\n"), (
            {"count": 1, "feeds": ["report weekly_revenue"]},
            "needs review: high blast radius, the change feeds report weekly_revenue"))
        self.assertEqual(self.judged("0\nexposure kpi_dashboard\n\nexposure board_pack\n"), (
            {"count": 0, "feeds": ["exposure kpi_dashboard", "exposure board_pack"]},
            "needs review: high blast radius, the change feeds exposure kpi_dashboard, exposure board_pack"))

    def test_a_failing_command_is_high(self):
        cases = {
            "a non-zero exit": (("2\n", 3), "exit 3"),
            "no count": (("many\n", 0), "it printed no count"),
            "no output": (("", 0), "it printed no count"),
            "a negative count": (("-1\n", 0), "it printed no count"),
        }
        for name, ((out, code), error) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.judged(out, code), (
                    {"error": error}, f"needs review: high blast radius, the dependents command failed: {error}"))


class Door(Case):
    def door(self, changes: dict[str, str | None], door: str | None, stack: str = "") -> tuple:
        result = self.measure(changes, stack, door)
        return result["door"], result["door_paths"], result["passed"], result["reason"]

    def test_a_one_way_door_line_stays_one_way(self):
        self.assertEqual(self.door({"src/app.py": lines(11)}, "one-way"),
                         ("one-way", [], False, "needs review: the plan's door is one-way"))

    def test_a_missing_or_unknown_door_line_is_one_way(self):
        reason = "needs review: the plan names no two-way or one-way door, so the door is one-way"
        for door in (None, "two way", ""):
            with self.subTest(door):
                self.assertEqual(self.door({"src/app.py": lines(11)}, door), ("one-way", [], False, reason))

    def test_a_default_one_way_path_raises_two_way_and_is_named(self):
        self.assertEqual(self.door({"src/app.py": lines(11), ".github/ISSUE_TEMPLATE/bug.md": "x\n"}, "two-way"), (
            "one-way", [".github/ISSUE_TEMPLATE/bug.md"], False,
            "needs review: one-way paths changed: .github/ISSUE_TEMPLATE/bug.md"))

    def test_a_repo_one_way_path_raises_two_way_and_is_named(self):
        stack = '[one_way]\npaths = ["infra/**"]\n'
        self.assertEqual(self.door({"infra/main.tf": "x\n", "src/app.py": lines(11)}, "two-way", stack), (
            "one-way", ["infra/main.tf"], False, "needs review: one-way paths changed: infra/main.tf"))

    def test_nothing_lowers_a_one_way_door(self):
        self.assertEqual(self.door({"infra/main.tf": "x\n"}, "one-way", '[one_way]\npaths = ["infra/**"]\n'), (
            "one-way", ["infra/main.tf"], False,
            "needs review: the plan's door is one-way; one-way paths changed: infra/main.tf"))


class Proofs(Case):
    def judged(self, proofs: dict[str, str]) -> tuple[bool, str]:
        result = self.measure({"src/app.py": lines(11)}, proofs=proofs)
        return result["passed"], result["reason"]

    def test_no_check_exists_meaning_unchanged_passes(self):
        for proof in ("no check exists, meaning unchanged", " No check exists, meaning unchanged \n"):
            with self.subTest(proof):
                self.assertEqual(self.judged({"R1": "tests.test_app passes", "R2": proof}),
                                 (True, "small edit: a two-way door, 1 line and a low blast radius"))

    def test_any_other_no_check_exists_proof_fails(self):
        self.assertEqual(self.judged({
            "R1": "no check exists",
            "R2": "tests.test_app passes",
            "R3": "no check exists, judged by review",
            "R4": "tests.test_app passes; No check exists for the help text",
        }), (False, 'needs review: requirements with no check, not recorded '
                    '"no check exists, meaning unchanged": R1, R3, R4'))


if __name__ == "__main__":
    unittest.main()
