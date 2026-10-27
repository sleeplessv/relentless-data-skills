"""Tests for skills/statusline/scripts/statusline.sh.

Runs the script as Claude Code does: status line JSON on stdin, output on
stdout. Each test builds a throwaway git repo on a chosen branch and a fresh
PR cache through tests/statusline_fixture.py. Run from the repo root:

    python3 -m unittest tests.test_statusline -v
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

# CI runs discover -s tests, which puts tests/ on the path; the module form
# above does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from statusline_fixture import REPO_URL, pr, run_statusline  # noqa: E402

CHIP = "\x1b[48;2;215;119;87;38;2;26;26;26m"
ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")


class StatuslineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def render(self, branch, prs):
        """Run the script on `branch` with `prs` cached. Return the second line."""
        lines = run_statusline(self.tmp, branch, prs, {"model": {"display_name": "M"}})
        return lines[1] if len(lines) > 1 else ""

    def test_closed_issue_shows_as_chip_after_its_pr(self):
        line = self.render("main", [pr(96, closes=[48])])
        self.assertIn(f"{CHIP}\x1b]8;;{REPO_URL}/issues/48\x1b\\ 48 ", line)
        self.assertEqual(ANSI.sub("", line), "#96  48  | PRs ✓1")

    def test_pr_that_closes_nothing_shows_a_dim_empty_set(self):
        line = self.render("main", [pr(97), pr(96, closes=[46, 49])])
        self.assertIn("\x1b[2m∅\x1b[0m", line)
        self.assertEqual(ANSI.sub("", line), "#97 ∅ #96  46   49  | PRs ✓2")

    def test_current_branch_pr_is_bracketed(self):
        line = self.render("ticket-48-trim", [pr(97), pr(96, closes=[48], branch="ticket-48-trim")])
        self.assertIn("\x1b[1m[\x1b[0m", line)
        self.assertEqual(ANSI.sub("", line), "#97 ∅ [#96  48 ] | PRs ✓2")

    def test_current_branch_pr_shows_past_the_list_limit(self):
        prs = [pr(n) for n in range(99, 93, -1)] + [pr(90, closes=[12], branch="mine")]
        line = self.render("mine", prs)
        self.assertEqual(
            ANSI.sub("", line), "#99 ∅ #98 ∅ #97 ∅ #96 ∅ #95 ∅ [#90  12 ] +1 | PRs ✓7"
        )

    def test_branch_without_pr_shows_issue_from_its_name(self):
        line = self.render("ticket-51-profile", [pr(97)])
        self.assertIn(f"{CHIP}\x1b]8;;{REPO_URL}/issues/51\x1b\\ 51 ", line)
        self.assertEqual(ANSI.sub("", line), "on  51  (no PR) | #97 ∅ | PRs ✓1")

    def test_branch_issue_shows_when_repo_has_no_prs(self):
        line = self.render("me/ticket-51-profile", [])
        self.assertEqual(ANSI.sub("", line), "on  51  (no PR)")

    def test_number_later_in_branch_name_is_not_an_issue(self):
        for branch in ("release-2026", "fix-2fa-login", "bump-node-20", "release/2026", "feature/2026-q1"):
            with self.subTest(branch=branch):
                self.setUp()
                self.assertEqual(ANSI.sub("", self.render(branch, [pr(97)])), "#97 ∅ | PRs ✓1")

    def test_fork_pr_from_a_same_named_branch_is_not_the_current_pr(self):
        line = self.render("main", [pr(97, closes=[5], branch="main", fork=True)])
        self.assertEqual(ANSI.sub("", line), "#97  5  | PRs ✓1")


if __name__ == "__main__":
    unittest.main()
