"""deliver.py merge: each refusal, the CI reading, the merge method, the merge line and the cleanup after it.

Each test runs deliver.py merge in the clone of a throwaway world from tests/deliver_kit.py, on a
branch of its own pushed to the bare remote, with the records written by hand and GitHub played
by the stand-in gh.

    python3 -m unittest tests.test_deliver_merge
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

VIEW = ["pr", "view", "12", "--json", "state,headRefOid,baseRefName,mergeStateStatus,mergeable,reviewDecision,body"]
CHECKS = ["pr", "checks", "12", "--json", "name,bucket"]
AFTER = ["pr", "view", "12", "--json", "state,headRefOid"]
DEFAULT = ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]
BLOCK = "<details><summary>Measurement</summary>\n\n```text\nversion: 0.1.0\npath: small edit\n{merge}```\n\n</details>\n"
BODY = "## Summary\n\nFix the typo.\n\n" + BLOCK.format(merge="")
PASS = [{"name": "tests", "bucket": "pass"}]
NEXT_BACK = "Next: git pull --no-rebase origin main, then deliver.py check, deliver.py pr and deliver.py ready again\n"


def answer(w: deliver_kit.World, head: str, *, state: str = "OPEN", merge_state: str = "CLEAN",
           mergeable: str = "MERGEABLE", review: str = "", body: str = BODY, checks: list | None = None,
           after: str = "MERGED") -> None:
    """Save GitHub's answers for one merge of PR #12 at the head commit."""
    w.gh_answer(VIEW, json.dumps({"state": state, "headRefOid": head, "baseRefName": "main",
                                  "mergeStateStatus": merge_state, "mergeable": mergeable,
                                  "reviewDecision": review, "body": body}))
    if checks is not None:
        w.gh_answer(CHECKS, json.dumps(checks))
    w.gh_answer(["pr", "merge"])
    w.gh_answer(AFTER, json.dumps({"state": after, "headRefOid": head}))
    w.gh_answer(["pr", "edit"])
    w.gh_answer(DEFAULT, "main\n")


class MergeWorld(unittest.TestCase):
    """A shared world whose clone goes back to main before each test, which cuts its own branch."""

    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        cls.tmp = cls.world.root / "tmp"
        cls.tmp.mkdir()

    def setUp(self):
        self.world.gh_reset()
        self.world.git(self.world.work, "switch", "-q", "main")

    def branch(self, name: str, *, created: bool = True, ready: str | None = "small edit", door: str = "two-way",
               files: dict[str, str] | None = None, **start: object) -> str:
        """Cut, commit and push a branch in the clone, mark it, and save its start, pr and ready records."""
        w = self.world
        w.git(w.work, "switch", "-q", "-c", name)
        for path, text in (files or {}).items():
            w.commit(w.work, path, text, f"chore: add {path}")
        head = w.commit(w.work, f"{name}.txt", "x\n", f"fix: {name}")
        w.git(w.work, "push", "-q", "-u", "origin", name)
        w.write_mark(branch=name)
        w.add_record(name, "start", branch_created=created, **start)
        w.add_record(name, "pr", number=12, url="https://github.com/owner/repo/pull/12")
        if ready:
            w.add_record(name, "ready", commit=head, result=ready, door=door)
        return head

    def answer(self, head: str, **kwargs) -> None:
        answer(self.world, head, **kwargs)

    def merge(self):
        return self.world.deliver("merge", TMPDIR=str(self.tmp))

    def assert_ends(self, result, code: int, stdout: str, stderr: str = ""):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, stderr))

    def calls(self) -> list[list[str]]:
        """The recorded gh calls, with a --body-file path shown as <file>."""
        return [[("<file>" if c["args"][i - 1:i] == ["--body-file"] else a) for i, a in enumerate(c["args"])]
                for c in self.world.gh_calls()]

    def body_sent(self) -> str:
        [body] = [c["body"] for c in self.world.gh_calls() if "body" in c]
        return body

    def merge_records(self, branch: str) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "at"} for r in self.world.records(branch) if r["event"] == "merge"]

    def tips(self, branch: str) -> tuple[str, str]:
        """The local and the remote tip of a branch, empty where it does not exist."""
        ref = f"refs/heads/{branch}"
        return (self.world.git(self.world.work, "for-each-ref", "--format=%(objectname)", ref),
                self.world.git(self.world.origin, "for-each-ref", "--format=%(objectname)", ref))

    def assert_untouched(self, branch: str, head: str):
        """A refusal that sends the PR back merged nothing, wrote nothing and removed nothing."""
        self.assertEqual(self.tips(branch), (head, head))
        self.assertEqual(self.world.git(self.world.work, "branch", "--show-current"), branch)
        self.assertEqual(self.merge_records(branch), [])
        self.assertNotIn("merge", [c[1] for c in self.calls()])


class Merge(MergeWorld):
    def test_merges_with_squash_writes_the_line_and_cleans_up(self):
        head = self.branch("feat/merge")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 0, (
            f"Merged PR #12 with squash at {head[:7]}.\n"
            "Switched this checkout to main.\n"
            "Removed the local branch feat/merge and the remote branch origin/feat/merge.\n"))
        self.assertEqual(self.calls(), [
            VIEW, CHECKS, ["pr", "merge", "12", "--squash", "--match-head-commit", head], AFTER,
            ["pr", "edit", "12", "--body-file", "<file>"], DEFAULT,
        ])
        self.assertEqual(self.body_sent(), "## Summary\n\nFix the typo.\n\n" + BLOCK.format(
            merge="merge: by the session, squash\n"))
        self.assertEqual(self.merge_records("feat/merge"), [
            {"event": "merge", "commit": head, "method": "squash", "merge_line": "merge: by the session, squash"}])
        self.assertEqual(self.tips("feat/merge"), ("", ""))
        self.assertEqual(self.world.git(self.world.work, "branch", "--show-current"), "main")
        self.assertNotIn("branch.feat/merge.", self.world.git(self.world.work, "config", "--list"))
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertTrue((self.world.work / ".git" / "deliver-mark.json").is_file())

    def test_replaces_a_merge_line_already_in_the_block(self):
        head = self.branch("feat/replace")
        self.answer(head, checks=PASS, body="## Summary\r\n\r\nFix.\r\n\r\n" + BLOCK.format(
            merge="merge: pending\n").replace("\n", "\r\n"))
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.body_sent(), "## Summary\n\nFix.\n\n" + BLOCK.format(
            merge="merge: by the session, squash\n"))

    def test_adds_the_block_when_the_description_has_none(self):
        head = self.branch("feat/no-block")
        self.answer(head, checks=PASS, body="## Summary\n\nFix.\n")
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.body_sent(), (
            "## Summary\n\nFix.\n\n<details><summary>Measurement</summary>\n\n```text\n"
            "merge: by the session, squash\n```\n\n</details>\n"))

    def test_pending_ci_waits_then_merges(self):
        head = self.branch("feat/pending")
        self.world.gh_answer(CHECKS, json.dumps([{"name": "tests", "bucket": "pending"},
                                                 {"name": "lint", "bucket": "pass"}]), once=True)
        self.world.gh_answer(["pr", "checks", "12", "--watch"], exit=8)
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 0, (
            f"Waiting for pending checks on PR #12: tests.\nMerged PR #12 with squash at {head[:7]}.\n"
            "Switched this checkout to main.\n"
            "Removed the local branch feat/pending and the remote branch origin/feat/pending.\n"))
        self.assertEqual(self.calls()[:5], [VIEW, CHECKS, ["pr", "checks", "12", "--watch"], CHECKS,
                                            ["pr", "merge", "12", "--squash", "--match-head-commit", head]])

    def test_no_checks_and_no_ci_records_checks_none_reported(self):
        head = self.branch("feat/no-ci")
        self.world.gh_answer(CHECKS, stderr="no checks reported on the 'feat/no-ci' branch\n", exit=1)
        self.world.gh_answer(["run", "list"], "[]\n")
        self.answer(head)
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.calls()[:3], [VIEW, CHECKS, ["run", "list", "--commit", head, "--json", "databaseId"]])
        line = "merge: by the session, squash, checks: none reported"
        self.assertEqual(self.body_sent(), "## Summary\n\nFix the typo.\n\n" + BLOCK.format(merge=line + "\n"))
        self.assertEqual(self.merge_records("feat/no-ci")[0]["merge_line"], line)

    def test_a_branch_this_run_did_not_create_is_kept_and_named(self):
        head = self.branch("feat/not-ours", created=False)
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 0, (
            f"Merged PR #12 with squash at {head[:7]}.\n"
            "Switched this checkout to main.\n"
            "Kept feat/not-ours: this run did not create it.\n"))
        self.assertEqual(self.tips("feat/not-ours"), (head, head))

    def test_merge_no_pr(self):
        w = self.world
        w.git(w.work, "switch", "-q", "-c", "feat/no-pr")
        w.write_mark(branch="feat/no-pr")
        self.assert_ends(self.merge(), 10, "REFUSED merge.no-pr: the records of feat/no-pr hold no PR\n"
                                           "Next: deliver.py pr\n")
        self.assertEqual(self.calls(), [])

    def test_merge_not_open(self):
        head = self.branch("feat/closed")
        self.answer(head, state="MERGED")
        self.assert_ends(self.merge(), 10, "REFUSED merge.not-open: PR #12 is merged, not open\n"
                                           "Next: deliver.py finish\n")
        self.assertEqual(self.calls(), [VIEW])

    def test_merge_not_ready(self):
        head = self.branch("feat/moved")
        moved = self.world.commit(self.world.work, "more.txt", "y\n", "fix: more")
        self.world.git(self.world.work, "push", "-q", "origin", "feat/moved")
        self.answer(moved, checks=PASS)
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.not-ready: `ready` has not passed on the PR's head commit {moved[:7]}\n"
            "Next: deliver.py ready\n"))
        self.assertNotEqual(head, moved)
        self.assert_untouched("feat/moved", moved)

    def test_merge_not_ready_when_ready_found_it_needs_a_review(self):
        head = self.branch("feat/needs-review", ready="needs review")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.not-ready: `ready` has not passed on the PR's head commit {head[:7]}\n"
            "Next: deliver.py ready\n"))
        self.assert_untouched("feat/needs-review", head)

    def test_merge_not_ready_with_no_ready_record(self):
        head = self.branch("feat/no-ready", ready=None)
        self.answer(head, checks=PASS)
        self.assertEqual(self.merge().returncode, 10)
        self.assert_untouched("feat/no-ready", head)

    def assert_left_with_line(self, branch: str, head: str, line: str):
        self.assertEqual(self.calls(), [VIEW, ["pr", "edit", "12", "--body-file", "<file>"]])
        self.assertEqual(self.body_sent(), "## Summary\n\nFix the typo.\n\n" + BLOCK.format(merge=line + "\n"))
        self.assertEqual(self.merge_records(branch), [
            {"event": "merge", "commit": head, "method": None, "merge_line": line}])
        self.assertEqual(self.tips(branch), (head, head))

    def test_merge_one_way(self):
        head = self.branch("feat/one-way", door="one-way")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, "REFUSED merge.one-way: the door is one-way, so the owner merges PR #12\n"
                                           "Next: deliver.py finish\n")
        self.assert_left_with_line("feat/one-way", head, "merge: left to the owner, one-way door")

    def test_merge_withheld_by_the_stop_at_ready_setting(self):
        head = self.branch("feat/setting", files={"docs/agents/stack.toml": "stop_at_ready = true\n"})
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.withheld: the merge is withheld: stop_at_ready is set in docs/agents/stack.toml\n"
            "Next: deliver.py finish\n"))
        self.assert_left_with_line("feat/setting", head,
                                   "merge: withheld, stop_at_ready is set in docs/agents/stack.toml")

    def test_merge_withheld_by_stop_at_ready_given_at_start(self):
        head = self.branch("feat/said", stop_at_ready=True)
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.withheld: the merge is withheld: stop at ready was given at start\n"
            "Next: deliver.py finish\n"))
        self.assert_left_with_line("feat/said", head, "merge: withheld, stop at ready was given at start")

    def test_merge_withheld_by_branch_rules_needing_an_approval(self):
        head = self.branch("feat/approval")
        self.answer(head, checks=PASS, review="REVIEW_REQUIRED", merge_state="BLOCKED")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.withheld: the merge is withheld: the branch rules need an approval the agent cannot give\n"
            "Next: deliver.py finish\n"))
        self.assert_left_with_line("feat/approval", head,
                                   "merge: withheld, the branch rules need an approval the agent cannot give")
        self.assertNotIn("--admin", [a for c in self.calls() for a in c])

    def test_merge_bad_settings(self):
        head = self.branch("feat/bad-settings", files={"docs/agents/stack.toml": "stop_at_ready = 'yes'\n"})
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.bad-settings: the stack settings cannot be read: "
            "docs/agents/stack.toml: stop_at_ready must be bool\n"
            "Next: fix docs/agents/stack.toml, then deliver.py merge\n"))
        self.assert_untouched("feat/bad-settings", head)

    def test_merge_behind(self):
        head = self.branch("feat/behind")
        self.answer(head, checks=PASS, merge_state="BEHIND")
        self.assert_ends(self.merge(), 10, "REFUSED merge.behind: PR #12 is behind main, so it goes back to its author\n"
                         + NEXT_BACK)
        self.assert_untouched("feat/behind", head)

    def test_merge_conflicting(self):
        head = self.branch("feat/conflict")
        self.answer(head, checks=PASS, merge_state="DIRTY", mergeable="CONFLICTING")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.conflicting: PR #12 conflicts with main, so it goes back to its author\n" + NEXT_BACK))
        self.assert_untouched("feat/conflict", head)

    def test_merge_ci_red(self):
        head = self.branch("feat/red")
        self.answer(head, checks=[{"name": "tests", "bucket": "fail"}, {"name": "lint", "bucket": "pending"},
                                  {"name": "build", "bucket": "cancel"}])
        self.assert_ends(self.merge(), 10, f"REFUSED merge.ci-red: CI is red on {head[:7]}: tests, build\n" + NEXT_BACK)
        self.assertEqual(self.calls(), [VIEW, CHECKS])
        self.assert_untouched("feat/red", head)

    def test_merge_ci_unknown_when_a_workflow_runs_on_pull_request(self):
        head = self.branch("feat/ci-late", files={".github/workflows/ci.yml": "on:\n  pull_request:\njobs: {}\n"})
        self.world.gh_answer(CHECKS, stderr="no checks reported on the 'feat/ci-late' branch\n", exit=1)
        self.world.gh_answer(["run", "list"], "[]\n")
        self.answer(head)
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.ci-unknown: GitHub reports no checks on {head[:7]}, but "
            ".github/workflows/ci.yml runs on pull_request, so CI may not have started yet\n"
            "Next: deliver.py merge\n"))
        self.assert_untouched("feat/ci-late", head)

    def test_merge_ci_unknown_when_a_workflow_run_is_listed(self):
        head = self.branch("feat/ci-run")
        self.world.gh_answer(CHECKS, stderr="no checks reported on the 'feat/ci-run' branch\n", exit=1)
        self.world.gh_answer(["run", "list"], '[{"databaseId": 99}]\n')
        self.answer(head)
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.ci-unknown: GitHub reports no checks on {head[:7]}, but "
            "a workflow run is listed for it, so CI may not have started yet\nNext: deliver.py merge\n"))
        self.assert_untouched("feat/ci-run", head)

    def test_a_workflow_on_push_only_is_not_a_sign_of_pr_ci(self):
        head = self.branch("feat/push-ci", files={".github/workflows/ci.yml": "# pull_request is off\non: push\n"})
        self.world.gh_answer(CHECKS, stderr="no checks reported on the 'feat/push-ci' branch\n", exit=1)
        self.world.gh_answer(["run", "list"], "[]\n")
        self.answer(head)
        self.assertEqual(self.merge().returncode, 0)

    def test_merge_not_merged(self):
        head = self.branch("feat/queued")
        self.world.gh_answer(["pr", "merge"], stderr="Head branch was modified.\n", exit=1)
        self.answer(head, checks=PASS, after="OPEN")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.not-merged: gh pr merge did not merge PR #12: GitHub shows it open\n"
            "Next: gh pr view 12\n"), "Head branch was modified.\n")
        self.assertEqual(self.calls(), [VIEW, CHECKS, ["pr", "merge", "12", "--squash", "--match-head-commit", head],
                                        AFTER])
        self.assertEqual(self.merge_records("feat/queued"), [])
        self.assertEqual(self.tips("feat/queued"), (head, head))


class Method(unittest.TestCase):
    """The merge method read from the base branch's history, each in a world of its own."""

    def land(self, world: deliver_kit.World, subject: str, *, merge: bool = False, rebased: bool = False) -> None:
        """Put one commit on the remote's main as GitHub would, committed by GitHub."""
        env = world.env(GIT_COMMITTER_NAME="GitHub", GIT_COMMITTER_EMAIL="noreply@github.com",
                        GIT_AUTHOR_DATE="2026-11-01T10:00:00Z",
                        GIT_COMMITTER_DATE="2026-11-02T10:00:00Z" if rebased else "2026-11-01T10:00:00Z")
        git = lambda *args: subprocess.run(["git", *args], cwd=world.work, env=env, check=True,  # noqa: E731
                                           capture_output=True)
        if merge:
            git("switch", "-q", "-c", "side")
            world.commit(world.work, "side.txt", "s\n", "feat: side")
            git("switch", "-q", "main")
            git("merge", "-q", "--no-ff", "side", "-m", subject)
        else:
            (world.work / "landed.txt").write_text(subject, encoding="utf-8")
            git("add", "landed.txt")
            git("commit", "-q", "-m", subject)
        git("push", "-q", "origin", "main")

    def merged_with(self, world: deliver_kit.World) -> list[str]:
        w = world
        w.git(w.work, "switch", "-q", "-c", "feat/method")
        head = w.commit(w.work, "m.txt", "m\n", "fix: method")
        w.git(w.work, "push", "-q", "-u", "origin", "feat/method")
        w.write_mark(branch="feat/method")
        w.add_record("feat/method", "start", branch_created=True)
        w.add_record("feat/method", "pr", number=12, url="https://github.com/owner/repo/pull/12")
        w.add_record("feat/method", "ready", commit=head, result="small edit", door="two-way")
        answer(w, head, checks=PASS)
        result = w.deliver("merge")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [c["args"] for c in w.gh_calls() if c["args"][:2] == ["pr", "merge"]][0]

    def test_history_of_merge_commits_merges(self):
        world = deliver_kit.World(self.addCleanup)
        self.land(world, "Merge pull request #3 from owner/side", merge=True)
        self.assertEqual(self.merged_with(world)[3], "--merge")

    def test_history_of_rebased_commits_rebases(self):
        world = deliver_kit.World(self.addCleanup)
        self.land(world, "fix: a rebased change", rebased=True)
        self.assertEqual(self.merged_with(world)[3], "--rebase")

    def test_history_of_squashed_commits_squashes(self):
        world = deliver_kit.World(self.addCleanup)
        self.land(world, "fix: a squashed change (#4)")
        self.assertEqual(self.merged_with(world)[3], "--squash")


if __name__ == "__main__":
    unittest.main()
