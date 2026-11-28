"""skills/deliver/review.md: its deliver.py commands, run in the order it lists them, take a change to a ready PR.

The test reads every `deliver.py …` code span of review.md, in order, and runs each through
deliver.py in a throwaway world of tests/deliver_kit.py, with its bare remote, the stand-in gh and
the stand-in scan of tests/test_deliver_ready.py. Reviewers' reports are made up and written into
`.deliver/`. The change fails the small test on its size, so `ready` first refuses
`ready.needs-review`, whose text names review.md's path.

    python3 -m unittest tests.test_deliver_review_text
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402
from test_deliver_ready import SCAN_STUB  # noqa: E402

REVIEW = deliver_kit.REPO_ROOT / "skills" / "deliver" / "review.md"
HARNESSES = re.compile(r"claude|cortex|codex|cursor|antigravity", re.IGNORECASE)
COMMANDS = [
    "deliver.py brief requirements --model <id>",
    "deliver.py brief defect --model <id>",
    "deliver.py save review <role>",
    "deliver.py settle F<n> --check <command>",
    "deliver.py settle F<n> --unsettled",
    "deliver.py follow-up F<n>",
    "deliver.py check -- <command>",
    "deliver.py pr",
    "deliver.py brief callback <role>",
    "deliver.py save callback <role>",
    "deliver.py ready",
]
URL = "https://github.com/owner/repo/pull/12"
ISSUE = "https://github.com/owner/repo/issues/31"
CHECK = "echo ok"
GREP = "grep -q three table.py"
TABLE = "".join(f"row {n} = {n}\n" for n in range(1, 61))
PLAN = f"""\
| # | Requirement | Proof |
|---|---|---|
| R1 | table.py holds sixty rows | `{CHECK}` |

door: two-way — one new file; nothing deploys on merge
"""


def commands() -> list[str]:
    """Each code span of review.md that is a deliver.py command, in the order the text gives them."""
    return [span for span in re.findall(r"`([^`]+)`", REVIEW.read_text(encoding="utf-8"))
            if span.startswith("deliver.py ")]


class ReviewText(unittest.TestCase):
    def test_review_md_names_no_harness(self):
        self.assertEqual(HARNESSES.findall(REVIEW.read_text(encoding="utf-8")), [])

    def test_review_md_lists_the_commands_the_scripts_take(self):
        self.assertEqual(commands(), COMMANDS)


class FollowReview(unittest.TestCase):
    """A change that needs both reviews, from `ready.needs-review` through review.md's commands to a ready PR."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.install_upstream()
        (self.world.root / "plugin" / "scripts" / "scan.py").write_text(SCAN_STUB, encoding="utf-8")
        self.work = self.world.work
        self.world.git(self.work, "switch", "-q", "-c", "feat/table")
        self.world.write_mark(branch="feat/table")
        self.world.add_record("feat/table", "preflight", run="run-1", result="pass", stops=[], warnings=[],
                              harness="claude-code")
        for kind, text in (("request", "Source: conversation\n\nAdd table.py.\n"),
                           ("requirements", "- R1: sixty rows\n"), ("summary", "Adds table.py.\n"), ("plan", PLAN)):
            self.world.save_text("feat/table", kind, text)
        self.head = self.world.commit(self.work, "table.py", TABLE, "feat: table")

    def deliver(self, *args: str, code: int = 0) -> str:
        result = self.world.deliver(*args, TMPDIR=str(self.world.root))
        self.assertEqual(result.returncode, code, f"deliver.py {' '.join(args)}: {result.stdout}{result.stderr}")
        self.assertNotIn("Traceback", result.stderr)
        return result.stdout

    def report(self, kind: str, text: str) -> None:
        (self.work / ".deliver").mkdir(exist_ok=True)
        (self.work / ".deliver" / f"{kind}.md").write_text(text, encoding="utf-8")

    def github(self, opened: bool) -> None:
        """GitHub's answers once `deliver.py pr` has pushed `self.head`."""
        deliver_kit.reset_gh(self.world)
        self.world.gh_answer(["repo", "view"], "main\n")
        self.world.gh_answer(["pr", "list"], json.dumps([{"number": 12, "url": URL}] if opened else []))
        self.world.gh_answer(["pr", "create"], f"{URL}\n")
        self.world.gh_answer(["pr", "edit"], "")
        self.world.gh_answer(["pr", "ready"], "")
        self.world.gh_answer(["pr", "view", "12", "--json", "headRefOid", "--jq", ".headRefOid"], f"{self.head}\n")
        self.world.gh_answer(["pr", "view"], json.dumps({"headRefOid": self.head, "baseRefName": "main"}))
        self.world.gh_answer(["issue", "create"], f"{ISSUE}\n")

    # One step per command of review.md, keyed by the command as the text gives it.
    def brief_requirements(self):
        self.deliver("brief", "requirements", "--model", "sonnet")

    def brief_defect(self):
        self.deliver("brief", "defect", "--model", "session")

    def save_review(self):
        self.report("review", f"R1: met\nF1: table.py:3: row 3 has no comment. Evidence: `{GREP}` fails\n"
                              "F2: table.py:5: row 5 may confuse. Evidence: none\n")
        self.deliver("save", "review", "requirements")
        self.report("review", "F1: table.py:7: row 7 is odd. Evidence: none\n"
                              "F2: README.md:1: the seed is stale. Evidence: breaks the house style\n")
        self.deliver("save", "review", "defect")

    def settle_check(self):
        self.deliver("settle", "F2", "--check", CHECK)

    def settle_unsettled(self):
        self.deliver("settle", "F3", "--unsettled")

    def follow_up(self):
        self.deliver("follow-up", "F4")

    def check(self):
        self.head = self.world.commit(self.work, "table.py", TABLE.replace("row 3 = 3\n", "row 3 = 3  # three\n"),
                                      "fix: a comment on row 3")
        self.deliver("check", "--", CHECK)
        self.deliver("check", "--", GREP)

    def pr(self):
        self.github(opened=True)
        self.deliver("pr")

    def brief_callback(self):
        self.deliver("brief", "callback", "requirements")

    def save_callback(self):
        self.report("callback", "F1: resolved\n")
        saved = self.deliver("save", "callback", "requirements")
        self.assertIn(f"Next: nothing; it is fixed in {self.head[:7]}", saved)

    def ready(self):
        self.deliver("ready")

    STEPS = dict(zip(COMMANDS, (brief_requirements, brief_defect, save_review, settle_check, settle_unsettled,
                                follow_up, check, pr, brief_callback, save_callback, ready)))

    def test_the_commands_of_review_md_in_order_reach_a_ready_pr(self):
        self.deliver("check", "--", CHECK)
        self.github(opened=False)
        self.deliver("pr")
        refused = self.world.deliver("ready", TMPDIR=str(self.world.root))
        self.assertEqual(refused.returncode, 10, refused.stderr)
        self.assertTrue(refused.stdout.startswith("REFUSED ready.needs-review: "), refused.stdout)
        plugin_review = self.world.root / "plugin" / "review.md"
        self.assertIn(str(plugin_review), refused.stdout)
        self.assertEqual(plugin_review.read_text(encoding="utf-8"), REVIEW.read_text(encoding="utf-8"))
        self.assertIn("deliver.py brief requirements --model <id>", refused.stdout)

        for command in commands():
            self.STEPS[command](self)
        self.assertIn(["pr", "ready", "12"], [c["args"] for c in self.world.gh_calls()])
        ready = [r for r in self.world.records("feat/table") if r["event"] == "ready"]
        self.assertEqual((ready[-1]["commit"], ready[-1]["result"]), (self.head, "single ticket"))


if __name__ == "__main__":
    unittest.main()
