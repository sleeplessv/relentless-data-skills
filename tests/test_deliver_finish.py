"""deliver.py finish: the state line, the cleanup guards, the run mark, and a second run.

Each test runs deliver.py finish in the clone of a throwaway world from tests/deliver_kit.py, on a
branch of its own pushed to the bare remote, with the records written by hand and GitHub played
by the stand-in gh.

    python3 -m unittest tests.test_deliver_finish
"""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402
from test_deliver_merge import AFTER, DEFAULT, PASS, answer  # noqa: E402

KEPT_MARK = "Kept the run mark, so deliver.py finish can finish the cleanup.\n"
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
        w.add_record(name, "start", run="run-1", branch_created=created)
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

    def events(self, branch: str) -> list:
        return [(r["event"], r.get("waiting")) for r in self.world.records(branch)]

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
        self.assert_ends(self.finish(), 0, "#416 ready, waits for you: PR #12\n"
                                           "Kept feat/later and its records: PR #12 is open, not merged.\n")
        self.assertEqual((self.mark().exists(), self.on(), self.tips("feat/later")), (False, "feat/later", (head, head)))
        self.assertEqual(self.events("feat/later")[-1], ("finish", True))
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the remote branch origin/feat/later, the local branch feat/later and the records of feat/later.\n"))
        self.assertEqual((self.on(), self.tips("feat/later"), self.world.records("feat/later")), ("main", ("", ""), []))
        self.assertNotIn("branch.feat/later.", self.world.git(self.world.work, "config", "--list"))
        self.assert_ends(self.finish(), 10, NO_MARK)

    def test_a_ready_pr_left_to_the_owner_says_why(self):
        head = self.branch("feat/waits")
        self.world.add_record("feat/waits", "merge", commit=head, method=None,
                              merge_line="merge: withheld, stop at ready was given at start")
        self.github(head, "OPEN")
        self.assert_ends(self.finish(), 0, "#416 ready, waits for you (withheld, stop at ready was given at start): "
                                           "PR #12\nKept feat/waits and its records: PR #12 is open, not merged.\n")

    def test_a_draft_pr(self):
        head = self.branch("feat/draft", ready=None)
        self.github(head, "OPEN")
        self.assert_ends(self.finish(), 0, "#416 draft: PR #12\nKept feat/draft and its records: PR #12 is open, not merged.\n")

    def test_a_draft_that_needs_a_review(self):
        head = self.branch("feat/review", ready="needs review")
        self.github(head, "OPEN")
        self.assert_ends(self.finish(), 0, "#416 draft, needs a review: PR #12\n"
                                           "Kept feat/review and its records: PR #12 is open, not merged.\n")

    def test_a_pr_closed_unmerged(self):
        head = self.branch("feat/closed")
        self.github(head, "CLOSED")
        self.assert_ends(self.finish(), 0, "#416 closed unmerged: PR #12\n"
                                           "Kept feat/closed and its records: PR #12 is closed, not merged.\n")
        self.assertEqual(self.events("feat/closed")[-1], ("finish", False))
        self.assert_ends(self.finish(), 10, NO_MARK)

    def test_not_started_when_no_pr_was_opened(self):
        self.branch("feat/no-pr", pr=False)
        self.world.gh_answer(DEFAULT, "main\n")
        self.assert_ends(self.finish(), 0, "#416 not started: no PR was opened\n"
                                           "Kept feat/no-pr and its records: no PR was opened.\n")
        self.assertFalse(self.mark().exists())
        self.assert_ends(self.finish(), 10, NO_MARK)

    def test_a_run_with_no_ticket_names_its_branch(self):
        head = self.branch("feat/talk", request="Source: conversation\n\nFix the typo.\n")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "feat/talk merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the remote branch origin/feat/talk, the local branch feat/talk and the records of feat/talk.\n"))

    def test_kept_when_this_run_did_not_create_the_branch(self):
        head = self.branch("feat/theirs", created=False)
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, "#416 merged: PR #12\nSwitched this checkout to main.\n"
                                           "Kept feat/theirs and its records: this run did not create it.\n")
        self.assertEqual(self.tips("feat/theirs"), (head, head))
        self.assertEqual(self.events("feat/theirs"), [("start", None), ("pr", None), ("ready", None), ("finish", False)])

    def test_kept_when_the_local_tip_is_ahead_of_the_pr_head(self):
        # The PR's head is an ancestor of the local tip: an ancestry test would delete the branch.
        head = self.branch("feat/ahead")
        ahead = self.world.commit(self.world.work, "late.txt", "late\n", "fix: a commit after the merge")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            f"Kept feat/ahead and its records: the local tip {ahead[:7]} is not the PR's head {head[:7]}.\n"
            + KEPT_MARK))
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
            f"Kept feat/pushed and its records: the remote tip {pushed[:7]} is not the PR's head {head[:7]}.\n"
            + KEPT_MARK))
        self.assertEqual(self.tips("feat/pushed"), (head, pushed))

    def test_kept_when_the_checkout_has_an_untracked_file(self):
        head = self.branch("feat/dirty")
        stray = self.world.work / "stray.txt"
        stray.write_text("not committed\n", encoding="utf-8")
        self.addCleanup(stray.unlink)
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            f"#416 merged: PR #12\nKept feat/dirty and its records: {self.world.work} has changed or untracked files.\n"))
        self.assertEqual((self.on(), self.tips("feat/dirty")), ("feat/dirty", (head, head)))

    def test_kept_when_another_worktree_has_the_branch(self):
        head = self.branch("feat/elsewhere")
        self.world.git(self.world.work, "switch", "-q", "main")
        tree = self.world.root / "elsewhere"
        self.world.git(self.world.work, "worktree", "add", "-q", str(tree), "feat/elsewhere")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, f"#416 merged: PR #12\nKept feat/elsewhere and its records: it is checked out in {tree}.\n"
                         + KEPT_MARK)
        self.assertEqual(self.tips("feat/elsewhere"), (head, head))

    def test_a_remote_branch_github_already_deleted_is_not_a_failed_guard(self):
        head = self.branch("feat/auto-deleted")
        self.world.git(self.world.origin, "update-ref", "-d", "refs/heads/feat/auto-deleted")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the local branch feat/auto-deleted and the records of feat/auto-deleted.\n"))

    def test_untracked_files_count_whatever_status_shows_untracked_files_says(self):
        head = self.branch("feat/hidden")
        self.world.git(self.world.work, "config", "status.showUntrackedFiles", "no")
        self.addCleanup(self.world.git, self.world.work, "config", "--unset", "status.showUntrackedFiles")
        stray = self.world.work / "hidden.txt"
        stray.write_text("not committed\n", encoding="utf-8")
        self.addCleanup(stray.unlink)
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            f"#416 merged: PR #12\nKept feat/hidden and its records: {self.world.work} has changed or untracked files.\n"))

    def test_a_checkout_on_another_branch_is_held_by_the_clean_tree_guard(self):
        head = self.branch("feat/away")
        self.world.git(self.world.work, "switch", "-q", "-c", "feat/third")
        stray = self.world.work / "stray.txt"
        stray.write_text("not committed\n", encoding="utf-8")
        self.addCleanup(stray.unlink)
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            f"#416 merged: PR #12\nKept feat/away and its records: {self.world.work} has changed or untracked files.\n"
            + KEPT_MARK))
        self.assertTrue(self.mark().exists())
        self.assertEqual((self.on(), self.tips("feat/away")), ("feat/third", (head, head)))

    def test_a_clean_checkout_on_another_branch_stays_there(self):
        head = self.branch("feat/left")
        self.world.git(self.world.work, "switch", "-q", "-c", "feat/stay")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\n"
            "Removed the remote branch origin/feat/left, the local branch feat/left and the records of feat/left.\n"))
        self.assertEqual((self.on(), self.tips("feat/left"), self.mark().exists()), ("feat/stay", ("", ""), False))

    def test_the_default_branch_is_kept_and_named(self):
        self.world.write_mark(branch="main")
        self.world.add_record("main", "start", run="run-1", branch_created=False)
        self.world.add_record("main", "pr", number=12, url="https://github.com/owner/repo/pull/12")
        self.addCleanup(shutil.rmtree, self.world.work / ".git" / "deliver" / "branches" / "main")
        self.github(self.world.git(self.world.work, "rev-parse", "HEAD"), "MERGED")
        self.assert_ends(self.finish(), 0, "main merged: PR #12\nKept main and its records: main is the default branch.\n")
        self.assertEqual(self.mark().exists(), False)

    def test_an_earlier_run_does_not_say_this_run_created_the_branch(self):
        head = self.branch("feat/reused")
        self.world.add_record("feat/reused", "start", run="run-2", branch_created=False)
        self.world.add_record("feat/reused", "pr", number=12, url="https://github.com/owner/repo/pull/12")
        self.world.write_mark(run="run-2", branch="feat/reused")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, ("#416 merged: PR #12\nSwitched this checkout to main.\n"
                                            "Kept feat/reused and its records: this run did not create it.\n"))
        self.assertEqual(self.tips("feat/reused"), (head, head))

    def test_finish_no_mark_with_records_of_a_run_that_never_finished(self):
        self.branch("feat/saved-only", pr=False, ready=None)
        self.mark().unlink()
        self.world.add_record("feat/saved-only", "save", kind="plan", file="plan.md", commit=None)
        self.assert_ends(self.finish(), 10, NO_MARK)
        self.assertEqual(self.world.gh_calls(), [])

    def test_another_branchs_records_below_this_one_stay(self):
        head = self.branch("topic")
        self.world.add_record("topic/child", "start", run="run-0", branch_created=True)
        self.addCleanup(self.world.git, self.world.work, "update-ref", "-d", "refs/heads/topic/child")
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the remote branch origin/topic, the local branch topic and the records of topic.\n"))
        folder = self.world.work / ".git" / "deliver" / "branches" / "topic"
        self.assertEqual(sorted(p.name for p in folder.rglob("*")), ["child", "records.jsonl"])
        self.assertEqual(self.events("topic/child"), [("start", None)])

    def test_records_that_cannot_be_removed_are_named_and_the_run_stays_findable(self):
        head = self.branch("feat/stuck")
        folder = self.world.work / ".git" / "deliver" / "branches" / "feat" / "stuck"
        folder.chmod(0o500)
        self.addCleanup(lambda: folder.exists() and folder.chmod(0o700))
        self.github(head, "MERGED")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the remote branch origin/feat/stuck and the local branch feat/stuck.\n"
            f"Kept the records of feat/stuck: [Errno 13] Permission denied: '{folder / 'request.md'}'.\n"
            + KEPT_MARK))
        self.assertEqual(json.loads(self.mark().read_text())["branch"], "feat/stuck")
        folder.chmod(0o700)
        self.assert_ends(self.finish(), 0, "#416 merged: PR #12\nRemoved the records of feat/stuck.\n")
        self.assertEqual((self.mark().exists(), folder.exists()), (False, False))

    def test_a_refused_remote_deletion_is_kept_and_a_later_finish_completes_it(self):
        head = self.branch("feat/guarded")
        self.world.git(self.world.origin, "config", "receive.denyDeletes", "true")
        self.addCleanup(self.world.git, self.world.origin, "config", "--unset", "receive.denyDeletes")
        self.github(head, "MERGED")
        result = self.finish()
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines()[0], "#416 merged: PR #12")
        self.assertEqual(result.stdout.splitlines()[1:], [
            "Kept feat/guarded and its records: git push origin --delete feat/guarded failed: "
            "remote: error: denying ref deletion for refs/heads/feat/guarded "
            f"To {self.world.origin} ! [remote rejected] feat/guarded (deletion prohibited) "
            f"error: failed to push some refs to '{self.world.origin}'."])
        self.assertEqual((self.on(), self.tips("feat/guarded"), self.mark().exists()),
                         ("feat/guarded", (head, head), False))
        self.assertEqual(self.events("feat/guarded")[-1], ("finish", True))
        self.world.git(self.world.origin, "config", "--unset", "receive.denyDeletes")
        self.addCleanup(self.world.git, self.world.origin, "config", "receive.denyDeletes", "false")
        self.assert_ends(self.finish(), 0, (
            "#416 merged: PR #12\nSwitched this checkout to main.\n"
            "Removed the remote branch origin/feat/guarded, the local branch feat/guarded "
            "and the records of feat/guarded.\n"))


if __name__ == "__main__":
    unittest.main()
