"""Tests for skills/statusline/scripts/statusline.sh.

Runs the script as Claude Code does: status line JSON on stdin, output on
stdout. Each test builds a throwaway git repo on a chosen branch and a fresh
PR cache, so the script never refreshes it, and puts a stub gh on PATH, so
nothing reaches the network. Run from the repo root:

    python3 -m unittest tests.test_statusline -v
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "statusline" / "scripts" / "statusline.sh"
REPO_URL = "https://github.com/acme/widgets"
CHIP = "\x1b[48;2;215;119;87;38;2;255;255;255m"
ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")


def pr(number, closes=(), branch=None, draft=False, fork=False):
    """One entry of the cache, shaped like gh pr list --json output."""
    return {
        "number": number,
        "url": f"{REPO_URL}/pull/{number}",
        "isDraft": draft,
        "isCrossRepository": fork,
        "headRefName": branch or f"branch-{number}",
        "statusCheckRollup": [],
        "closingIssuesReferences": [
            {"number": n, "url": f"{REPO_URL}/issues/{n}"} for n in closes
        ],
    }


class StatuslineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text("#!/bin/sh\nexit 1\n")
        gh.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
        }

    def render(self, branch, prs):
        """Run the script on `branch` with `prs` cached. Return the second line."""
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q", "-b", branch], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        key = subprocess.run(
            ["cksum"], input=str(self.repo), capture_output=True, text=True, check=True
        ).stdout.split()[0]
        cache_dir = self.tmp / "cache" / "claude-statusline"
        cache_dir.mkdir(parents=True)
        (cache_dir / f"prs-v2-{key}.json").write_text(json.dumps(prs))
        stdin = json.dumps({"model": {"display_name": "M"}, "workspace": {"current_dir": str(self.repo)}})
        out = subprocess.run(
            ["sh", str(SCRIPT)], input=stdin, capture_output=True, text=True, env=self.env, check=True
        ).stdout
        lines = out.split("\n")
        return lines[1] if len(lines) > 1 else ""

    def test_closed_issue_shows_as_chip_after_its_pr(self):
        line = self.render("main", [pr(96, closes=[48])])
        self.assertIn(f"{CHIP}\x1b]8;;{REPO_URL}/issues/48\x1b\\ 48 ", line)
        self.assertEqual(ANSI.sub("", line), "#96  48  | PRs ✓1")

    def test_pr_that_closes_nothing_shows_an_amber_empty_set(self):
        line = self.render("main", [pr(97), pr(96, closes=[46, 49])])
        self.assertIn("\x1b[38;2;255;191;0m∅\x1b[0m", line)
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
