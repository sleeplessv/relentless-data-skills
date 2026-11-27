"""deliver.py finish: the state line, the cleanup guards, the run mark, and a second run.

Each test runs deliver.py finish in the clone of a throwaway world from tests/deliver_kit.py, on a
branch of its own pushed to the bare remote, with the records written by hand and GitHub played
by the stand-in gh.

    python3 -m unittest tests.test_deliver_finish
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402
from test_deliver_merge import AFTER, DEFAULT, PASS, answer  # noqa: E402

NO_MARK = "REFUSED finish.no-mark: no run mark in this checkout, so no run is in progress here\nNext: deliver.py start\n"


class Finish(unittest.TestCase):
    """A shared world whose clone goes back to main before each test, which cuts its own branch."""

    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)

    def setUp(self):
        self.world.gh_reset()
        self.world.git(self.world.work, "switch", "-q", "main")

    def branch(self, name: str, *, created: bool = True, request: str = "Source: ticket #416\n\nBuild merge.\n",
               pr: bool = True, ready: str | None = "small edit") -> str:
        """Cut, commit and push a branch in the clone, mark it, and save its records."""
        w = self.world
        w.git(w.work, "switch", "-q", "-c", name)
        head = w.commit(w.work, f"{name}.txt", "x\n", f"fix: {name}")
        w.git(w.work, "push", "-q", "-u", "origin", name)
        w.write_mark(branch=name)
        w.save_text(name, "request", request)
        w.add_record(name, "start", branch_created=created)
        if pr:
            w.add_record(name, "pr", number=12, url="https://github.com/owner/repo/pull/12")
        if ready:
            w.add_record(name, "ready", commit=head, result=ready, door="two-way")
        return head

    def github(self, head: str, state: str, *, once: bool = False) -> None:
        self.world.gh_answer(AFTER, json.dumps({"state": state, "headRefOid": head}), once=once)
        self.world.gh_answer(DEFAULT, "main\n", once=once)

    def finish(self):
        return self.world.deliver("finish")

    def assert_ends(self, result, code: int, stdout: str):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, ""))

    def tips(self, branch: str) -> tuple[str, str]:
        ref = f"refs/heads/{branch}"
        return (self.world.git(self.world.work, "for-each-ref", "--format=%(objectname)", ref),
                self.world.git(self.world.origin, "for-each-ref", "--format=%(objectname)", ref))

    def mark(self) -> Path:
        return self.world.work / ".git" / "deliver-mark.json"

    def on(self) -> str:
        return self.world.git(self.world.work, "branch", "--show-current")

    def test_after_a_merge_prints_merged_removes_the_records_and_the_mark(self):
        head = self.branch("feat/done")
        answer(self.world, head, checks=PASS)
        self.assertEqual(self.world.deliver("merge").returncode, 0)
        self.assertEqual((self.on(), self.tips("feat/done")), ("main", ("", "")))
        self.assert_ends(self.finish(), 0, "#416 merged: PR #12\nRemoved the records of feat/done.\n")
        self.assertEqual((self.world.records("feat/done"), self.mark().exists(), self.on()), ([], False, "main"))
        self.assert_ends(self.finish(), 10, NO_MARK)

    def test_run_again_after_the_owner_merges_it_cleans_up(self):
        head = self.branch("feat/later")
        self.github(head, "OPEN", once=True)
        self.assert_ends(self.finish(), 0, "#416 ready, waits for you (merge not run): PR #12\n"
                                           "Kept feat/later: PR #12 is open, not merged.\n")
        self.assertEqual((self.mark().exists(), self.on(), self.tips("feat/later")), (False, "feat/later", (head, head)))
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the local branch feat/later, the remote branch origin/feat/later and the records of feat/later.\n"))
        self.assertEqual((self.on(), self.tips("feat/later"), self.world.records("feat/later")), ("main", ("", ""), []))
        self.assertNotIn("branch.feat/later.", self.world.git(self.world.work, "config", "--list"))
        self.assert_ends(self.finish(), 10, NO_MARK)

    def test_a_ready_pr_left_to_the_owner_says_why(self):
        head = self.branch("feat/waits")
        self.world.add_record("feat/waits", "merge", commit=head, method=None,
                              merge_line="merge: withheld, stop at ready was given at start")
        self.github(head, "OPEN")
        self.assert_ends(self.finish(), 0, "#416 ready, waits for you (withheld, stop at ready was given at start): "
                                           "PR #12\nKept feat/waits: PR #12 is open, not merged.\n")

    def test_a_draft_pr(self):
        head = self.branch("feat/draft", ready=None)
        self.github(head, "OPEN")
        self.assert_ends(self.finish(), 0, "#416 draft: PR #12\nKept feat/draft: PR #12 is open, not merged.\n")

    def test_a_draft_that_needs_a_review(self):
        head = self.branch("feat/review", ready="needs review")
        self.github(head, "OPEN")
        self.assert_ends(self.finish(), 0, "#416 draft, needs a review: PR #12\n"
                                           "Kept feat/review: PR #12 is open, not merged.\n")

    def test_a_pr_closed_unmerged(self):
        head = self.branch("feat/closed")
        self.github(head, "CLOSED")
        self.assert_ends(self.finish(), 0, "#416 closed unmerged: PR #12\nKept feat/closed: PR #12 is closed, not merged.\n")

    def test_not_started_when_no_pr_was_opened(self):
        self.branch("feat/no-pr", pr=False)
        self.world.gh_answer(DEFAULT, "main\n")
        self.assert_ends(self.finish(), 0, "#416 not started: no PR was opened\nKept feat/no-pr: no PR was opened.\n")
        self.assertFalse(self.mark().exists())

    def test_a_run_with_no_ticket_names_its_branch(self):
        head = self.branch("feat/talk", request="Source: conversation\n\nFix the typo.\n")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "feat/talk merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the local branch feat/talk, the remote branch origin/feat/talk and the records of feat/talk.\n"))

    def test_kept_when_this_run_did_not_create_the_branch(self):
        head = self.branch("feat/theirs", created=False)
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, "#416 merged: PR #12\nSwitched this checkout to main.\n"
                                           "Kept feat/theirs: this run did not create it.\n")
        self.assertEqual(self.tips("feat/theirs"), (head, head))
        self.assertEqual(len(self.world.records("feat/theirs")), 3)

    def test_kept_when_the_local_tip_is_ahead_of_the_pr_head(self):
        # The PR's head is an ancestor of the local tip: an ancestry test would delete the branch.
        head = self.branch("feat/ahead")
        ahead = self.world.commit(self.world.work, "late.txt", "late\n", "fix: a commit after the merge")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            f"Kept feat/ahead: the local tip {ahead[:7]} is not the PR's head {head[:7]}.\n"))
        self.assertEqual(self.tips("feat/ahead"), (ahead, head))

    def test_kept_when_the_remote_tip_differs(self):
        head = self.branch("feat/pushed")
        other = self.world.worktree("pusher", "pusher")
        self.world.git(other, "reset", "-q", "--hard", head)
        pushed = self.world.commit(other, "p.txt", "p\n", "fix: pushed from elsewhere")
        self.world.git(other, "push", "-q", "origin", "HEAD:refs/heads/feat/pushed")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            f"Kept feat/pushed: the remote tip {pushed[:7]} is not the PR's head {head[:7]}.\n"))
        self.assertEqual(self.tips("feat/pushed"), (head, pushed))

    def test_kept_when_the_checkout_has_an_untracked_file(self):
        head = self.branch("feat/dirty")
        stray = self.world.work / "stray.txt"
        stray.write_text("not committed\n", encoding="utf-8")
        self.addCleanup(stray.unlink)
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            f"#416 merged: PR #12\nKept feat/dirty: {self.world.work} has changed or untracked files.\n"))
        self.assertEqual((self.on(), self.tips("feat/dirty")), ("feat/dirty", (head, head)))

    def test_kept_when_another_worktree_has_the_branch(self):
        head = self.branch("feat/elsewhere")
        self.world.git(self.world.work, "switch", "-q", "main")
        tree = self.world.root / "elsewhere"
        self.world.git(self.world.work, "worktree", "add", "-q", str(tree), "feat/elsewhere")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, f"#416 merged: PR #12\nKept feat/elsewhere: it is checked out in {tree}.\n")
        self.assertEqual(self.tips("feat/elsewhere"), (head, head))

    def test_a_remote_branch_github_already_deleted_is_not_a_failed_guard(self):
        head = self.branch("feat/auto-deleted")
        self.world.git(self.world.origin, "update-ref", "-d", "refs/heads/feat/auto-deleted")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the local branch feat/auto-deleted and the records of feat/auto-deleted.\n"))


if __name__ == "__main__":
    unittest.main()
