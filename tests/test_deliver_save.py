"""deliver.py save: moving the author's texts into the records, and reading the check plan.

Every test runs deliver.py at its command line in a throwaway world from tests/deliver_kit.py; the
plan reader's tests also call `plan.read` on the saved plan.

    python3 -m unittest tests.test_deliver_save
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

AT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
TABLE = """\
## Requirements and check plan
| # | Requirement | Proof |
|---|---|---|
| R1 | `check` saves every run | `python3 -m unittest tests.test_deliver_check` |
| R2 | README states the slot | review: README "Checks" states the slot |
"""
PLAN = TABLE + """
Assumptions
- A1 (R1): the kit's world needs no network. Tested by the test run: held.

door: two-way — new scripts, a revert removes them
"""


def bad_plan(error: str) -> str:
    return (f"REFUSED save.bad-plan: the plan cannot be read: {error}\n"
            "Next: fix .deliver/plan.md, then run deliver.py save plan\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark()
        self.head = self.world.git(self.world.work, "rev-parse", "HEAD")
        self.saved = self.world.work / ".git" / "deliver" / "branches" / "main"

    def drop(self, kind: str, text: str) -> Path:
        path = self.world.work / ".deliver" / f"{kind}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def assert_ends(self, result, code, stdout, stderr=""):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, stderr))

    def assert_record(self, record: dict, **fields):
        self.assertEqual(list(record), ["event", "at", "kind", "file", "commit"])
        self.assertRegex(record["at"], AT)
        self.assertEqual({k: v for k, v in record.items() if k != "at"}, {"event": "save", **fields})


class Save(Base):
    def test_each_kind_is_moved_and_recorded_with_the_commit(self):
        for kind, text in (("request", "Fix the typo.\n"), ("requirements", "- R1: no typo\n"), ("plan", PLAN),
                           ("summary", "Fixes the typo.\n")):
            with self.subTest(kind):
                source = self.drop(kind, text)
                result = self.world.deliver("save", kind)
                door = "door: two-way (new scripts, a revert removes them)\n" if kind == "plan" else ""
                self.assert_ends(result, 0, f"Saved {kind}.md at {self.head[:7]}.\n{door}")
                self.assertFalse(source.exists())
                self.assertEqual((self.saved / f"{kind}.md").read_text(encoding="utf-8"), text)
                self.assert_record(self.world.records()[-1], kind=kind, file=f"{kind}.md", commit=self.head)
        self.assertEqual(len(self.world.records()), 4)
        self.assertEqual(self.world.git(self.world.work, "status", "--porcelain"), "")

    def test_a_changed_tracked_file_ties_the_save_to_no_commit(self):
        (self.world.work / "README.md").write_text("changed\n", encoding="utf-8")
        self.drop("summary", "Changed the README.\n")
        self.assert_ends(self.world.deliver("save", "summary"), 0, "Saved summary.md tied to no commit.\n")
        self.assert_record(self.world.records()[0], kind="summary", file="summary.md", commit=None)

    def test_git_status_failing_ties_the_save_to_no_commit(self):
        (self.world.work / ".git" / "index").write_bytes(b"not an index")
        self.drop("summary", "Saved with a broken index.\n")
        self.assert_ends(self.world.deliver("save", "summary"), 0, "Saved summary.md tied to no commit.\n")
        self.assert_record(self.world.records()[0], kind="summary", file="summary.md", commit=None)

    def test_a_later_save_replaces_the_file_and_adds_a_record(self):
        self.drop("summary", "first\n")
        self.world.deliver("save", "summary")
        self.drop("summary", "second\n")
        self.world.deliver("save", "summary")
        self.assertEqual((self.saved / "summary.md").read_text(encoding="utf-8"), "second\n")
        self.assertEqual([r["kind"] for r in self.world.records()], ["summary", "summary"])

    def test_save_missing_file(self):
        self.assert_ends(self.world.deliver("save", "request"), 10,
                         "REFUSED save.missing-file: there is no .deliver/request.md to save\n"
                         "Next: write .deliver/request.md, then run deliver.py save request\n")
        self.assertEqual(self.world.records(), [])

    def test_an_unknown_kind_is_a_usage_error(self):
        for args in ((), ("review",), ("plan", "summary")):
            with self.subTest(args):
                result = self.world.deliver("save", *args)
                self.assert_ends(result, 2, "", (
                    "deliver.py: save takes one kind, one of request, requirements, plan, summary, or review and a "
                    "role, one of requirements, defect\n\n"
                    f"{deliver_kit.load('deliver').USAGE}\n"))


class SavePlan(Base):
    def save_plan(self, text: str):
        self.drop("plan", text)
        return self.world.deliver("save", "plan")

    def assert_refused(self, text: str, stdout: str):
        self.assert_ends(self.save_plan(text), 10, stdout)
        self.assertTrue((self.world.work / ".deliver" / "plan.md").exists())
        self.assertEqual(self.world.records(), [])

    def test_save_no_proof(self):
        text = TABLE.replace("review: README \"Checks\" states the slot", "") + "| R3 | c | — |\n| R4 | d | - |\n"
        self.assert_refused(text, "REFUSED save.no-proof: a requirement has no proof: R2, R3, R4\n"
                                  "Next: name a proof for each in .deliver/plan.md, then run deliver.py save plan\n")

    def test_save_bad_plan_without_one_requirements_table(self):
        for text, count in (("door: two-way — x\n", 0), (TABLE + "\n" + TABLE, 2),
                            (TABLE.replace("| # |", "| No |"), 0)):
            with self.subTest(count=count):
                self.assert_refused(text, bad_plan(
                    f"the plan needs one table headed | # | Requirement | Proof |, and it has {count}"))

    def test_save_bad_plan_with_a_malformed_table(self):
        cases = {
            "the header is not followed by a separator row": (
                TABLE.replace("|---|---|---|\n", ""),
                "line 3: the table's header is not followed by a separator row"),
            "a row with four cells": (
                TABLE.replace("| R2 | README", "| R2 | a | README"),
                "line 5: a row has 3 cells, and this one has 4"),
            "a row with two cells": (
                TABLE.replace("| R2 | README states the slot |", "| R2 |"),
                "line 5: a row has 3 cells, and this one has 2"),
            "a gap in the numbers": (
                TABLE.replace("| R2 |", "| R3 |"),
                "line 5: the requirement is numbered 'R3', where R2 comes next"),
            "a number not written R<n>": (
                TABLE.replace("| R1 |", "| 1 |"),
                "line 4: the requirement is numbered '1', where R1 comes next"),
            "an empty requirement": (
                TABLE.replace("README states the slot", ""),
                "line 5: R2 has no requirement text"),
            "no row": (
                "| # | Requirement | Proof |\n|---|---|---|\n\ndoor: two-way — x\n",
                "the table has no requirement"),
        }
        for name, (text, error) in cases.items():
            with self.subTest(name):
                self.assert_refused(text, bad_plan(error))

    def test_save_bad_plan_with_a_door_line_it_cannot_read(self):
        cases = {
            "door: maybe — unsure": "line 7",
            "Door: two-way — a capital": "line 7",
            "- door: two-way — in a list": "line 7",
            "**door:** two-way — in bold": "line 7",
            "door = one-way — another sign": "line 7",
            "door: two-way": "line 7",
            "door: two-way —": "line 7",
            "door: two-ways — a plural": "line 7",
        }
        for line, where in cases.items():
            with self.subTest(line):
                self.assert_refused(TABLE + "\n" + line + "\n", bad_plan(
                    f"{where}: the door line reads 'door: two-way' or 'door: one-way', a separator and a reason"))

    def test_save_bad_plan_with_two_door_lines(self):
        self.assert_refused(TABLE + "\ndoor: two-way — one\ndoor: one-way — two\n",
                            bad_plan("the plan has 2 door lines, on lines 7, 8"))

    def test_door_line_with_each_separator(self):
        for separator in (" — ", " – ", " - ", ": ", "; ", ", "):
            for door in ("two-way", "one-way"):
                with self.subTest(separator=separator, door=door):
                    result = self.save_plan(f"{TABLE}\ndoor: {door}{separator}the reason\n")
                    self.assert_ends(result, 0, f"Saved plan.md at {self.head[:7]}.\ndoor: {door} (the reason)\n")

    def test_a_plan_with_no_door_line_is_one_way(self):
        self.assert_ends(self.save_plan(TABLE), 0,
                         f"Saved plan.md at {self.head[:7]}.\ndoor: one-way (the plan has no door line)\n")
        read = deliver_kit.load("plan").read(self.run_())
        self.assertEqual((read.door, read.door_reason), ("one-way", "the plan has no door line"))

    def test_a_heading_named_door_is_not_a_door_line(self):
        result = self.save_plan(TABLE + "\n## Door\n\ndoor: two-way — the reason\n")
        self.assert_ends(result, 0, f"Saved plan.md at {self.head[:7]}.\ndoor: two-way (the reason)\n")

    def test_a_door_line_in_a_fenced_block_is_not_the_door(self):
        for fence in ("```", "~~~text", "````"):
            with self.subTest(fence):
                close = fence.rstrip("text")
                result = self.save_plan(f"{TABLE}\nAn earlier plan said:\n\n{fence}\ndoor: two-way — easy to undo\n{close}\n")
                self.assert_ends(result, 0, f"Saved plan.md at {self.head[:7]}.\ndoor: one-way (the plan has no door line)\n")
                read = deliver_kit.load("plan").read(self.run_())
                self.assertEqual((read.door, read.door_reason), ("one-way", "the plan has no door line"))

    def test_a_table_in_a_fenced_block_is_not_the_table(self):
        example = "~~~\n| # | Requirement | Proof |\n|---|---|---|\n| R1 | an example | — |\n~~~\n"
        self.assert_ends(self.save_plan(f"{TABLE}\n{example}\ndoor: two-way — the reason\n"), 0,
                         f"Saved plan.md at {self.head[:7]}.\ndoor: two-way (the reason)\n")
        self.assertEqual([r.number for r in deliver_kit.load("plan").read(self.run_()).requirements], ["R1", "R2"])

    def test_read_returns_the_saved_requirements_proofs_and_door(self):
        plan = deliver_kit.load("plan")
        self.assertIsNone(plan.read(self.run_()))
        text = PLAN.replace("| R2 | README states the slot | review: README \"Checks\" states the slot |",
                            "| R2 | a \\| b | `grep -c x a.txt \\| wc -l` |")
        self.assertEqual(self.save_plan(text).returncode, 0)
        self.assertEqual(plan.read(self.run_()), plan.Plan(
            [plan.Requirement("R1", "`check` saves every run", "`python3 -m unittest tests.test_deliver_check`"),
             plan.Requirement("R2", "a | b", "`grep -c x a.txt | wc -l`")],
            "two-way", "new scripts, a revert removes them"))

    def test_a_separator_with_colons_and_no_trailing_pipe_is_read(self):
        text = TABLE.replace("|---|---|---|", "| :-- | --- | ---:")
        self.assertEqual(self.save_plan(text).returncode, 0)

    def run_(self):
        return deliver_kit.load("core").find_run(self.world.work)


if __name__ == "__main__":
    unittest.main()
