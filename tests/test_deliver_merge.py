"""deliver.py merge: each refusal, the CI reading, the merge method, the merge line and the cleanup after it.

Each test runs deliver.py merge in the clone of a throwaway world from tests/deliver_kit.py, on a
branch of its own pushed to the bare remote, with the records written by hand and GitHub played
by the stand-in gh. `StartedRun` begins its run with deliver.py start, which writes the run's
`start` record.

    python3 -m unittest tests.test_deliver_merge
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

VIEW = ["pr", "view", "12", "--json", "state,headRefOid,baseRefName,mergeStateStatus,mergeable,reviewDecision,body"]
CHECKS = ["pr", "checks", "12", "--json", "name,bucket"]
AFTER = ["pr", "view", "12", "--json", "state,headRefOid"]
BODY_NOW = ["pr", "view", "12", "--json", "body"]
EDIT = ["pr", "edit", "12", "--body-file", "<file>"]
DEFAULT = ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]
BLOCK = "<details><summary>Measurement</summary>\n\n```text\nversion: 0.1.0\npath: small edit\n{merge}```\n\n</details>\n"
BODY = "## Summary\n\nFix the typo.\n\n" + BLOCK.format(merge="")
PASS = [{"name": "tests", "bucket": "pass"}]
NEXT_BACK = "Next: git pull --no-rebase origin main, then deliver.py check, deliver.py pr and deliver.py ready again\n"


def view(head: str, *, state: str = "OPEN", merge_state: str = "CLEAN", mergeable: str = "MERGEABLE",
         review: str = "", body: str = BODY, base: str = "main") -> str:
    """GitHub's answer to merge's `gh pr view`."""
    return json.dumps({"state": state, "headRefOid": head, "baseRefName": base, "mergeStateStatus": merge_state,
                       "mergeable": mergeable, "reviewDecision": review, "body": body})


def answer(w: deliver_kit.World, head: str, *, checks: list | None = None, after: str = "MERGED",
           body_now: str | None = None, **pr: str) -> None:
    """Save GitHub's answers for one merge of PR #12 at the head commit; `pr` goes to `view`."""
    w.gh_answer(VIEW, view(head, **pr))
    if checks is not None:
        w.gh_answer(CHECKS, json.dumps(checks))
    w.gh_answer(["pr", "merge"])
    w.gh_answer(AFTER, json.dumps({"state": after, "headRefOid": head}))
    w.gh_answer(BODY_NOW, json.dumps({"body": pr.get("body", BODY) if body_now is None else body_now}))
    w.gh_answer(["pr", "edit"])
    w.gh_answer(DEFAULT, "main\n")


def wrapped(w: deliver_kit.World, program: str, before: str) -> str:
    """A PATH whose `program` runs the Python `before` (with `args`, the arguments) and then the real one.

    `before` may end the call itself with `sys.exit`, which makes the call fail without the real one.
    """
    real = shutil.which(program, path=w.base_env["PATH"])
    folder = w.root / f"wrap-{program}-{len(list(w.root.glob(f'wrap-{program}-*')))}"
    folder.mkdir()
    script = folder / program
    script.write_text(f"#!{sys.executable} -I\nimport json, os, sys\nargs = sys.argv[1:]\n{before}\n"
                      f"os.execv({real!r}, [{real!r}, *args])\n", encoding="utf-8")
    script.chmod(0o755)
    return f"{folder}{os.pathsep}{w.base_env['PATH']}"


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
        w.add_record(name, "start", run="run-1", branch_created=created, **start)
        w.add_record(name, "pr", number=12, url="https://github.com/owner/repo/pull/12")
        if ready:
            w.add_record(name, "ready", commit=head, result=ready, door=door)
        self.saved = self.world.records(name)
        return head

    def answer(self, head: str, **kwargs) -> None:
        answer(self.world, head, **kwargs)

    def merge(self, **env: str):
        return self.world.deliver("merge", TMPDIR=str(self.tmp), **env)

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
        self.assertEqual(self.world.records(branch), self.saved)
        self.assertEqual([c[:2] for c in self.calls() if c[:2] in (["pr", "merge"], ["pr", "edit"])], [])


class Merge(MergeWorld):
    def test_merges_with_squash_writes_the_line_and_cleans_up(self):
        head = self.branch("feat/merge")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 0, (
            f"Merged PR #12 with squash at {head[:7]}.\n"
            "Switched this checkout to main.\n"
            "Removed the remote branch origin/feat/merge and the local branch feat/merge.\n"))
        self.assertEqual(self.calls(), [
            VIEW, CHECKS, VIEW, ["pr", "merge", "12", "--squash", "--match-head-commit", head], AFTER,
            BODY_NOW, EDIT, DEFAULT,
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
            "Removed the remote branch origin/feat/pending and the local branch feat/pending.\n"))
        self.assertEqual(self.calls()[:6], [VIEW, CHECKS, ["pr", "checks", "12", "--watch"], CHECKS, VIEW,
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
        head = w.git(w.work, "rev-parse", "HEAD")
        self.assert_ends(self.merge(), 10, "REFUSED merge.no-pr: the records of feat/no-pr hold no PR\n"
                                           "Next: deliver.py pr\n")
        self.assertEqual(self.calls(), [])
        self.assertEqual((w.records("feat/no-pr"), w.git(w.work, "branch", "--show-current")), ([], "feat/no-pr"))
        self.assertEqual(self.tips("feat/no-pr"), (head, ""))

    def test_merge_not_open(self):
        head = self.branch("feat/closed")
        self.answer(head, state="MERGED")
        self.assert_ends(self.merge(), 10, "REFUSED merge.not-open: PR #12 is merged, not open\n"
                                           "Next: deliver.py finish\n")
        self.assertEqual(self.calls(), [VIEW])
        self.assert_untouched("feat/closed", head)

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
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.not-ready: `ready` has not passed on the PR's head commit {head[:7]}\n"
            "Next: deliver.py ready\n"))
        self.assertEqual(self.calls(), [VIEW])
        self.assert_untouched("feat/no-ready", head)

    def test_merge_not_ready_when_the_head_moved_during_the_ci_wait(self):
        head = self.branch("feat/moved-late")
        self.world.gh_answer(VIEW, view(head), once=True)
        self.answer("f" * 40, checks=PASS)
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.not-ready: `ready` has not passed on the PR's head commit fffffff\n"
            "Next: deliver.py ready\n"))
        self.assertEqual(self.calls(), [VIEW, CHECKS, VIEW])
        self.assert_untouched("feat/moved-late", head)

    def test_merge_one_way_from_the_record_the_small_test_writes(self):
        # The small test fails every one-way door, so the ready record says "needs review".
        head = self.branch("feat/door", ready=None)
        self.world.add_record("feat/door", "ready", commit=head, result="needs review", door="one-way",
                              door_paths=[], reason="the plan's door is one-way",
                              small_test={"lines": 1, "critical_paths": [], "dependents": None})
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, "REFUSED merge.one-way: the door is one-way, so the owner merges PR #12\n"
                                           "Next: deliver.py finish\n")
        self.assert_left_with_line("feat/door", head, "merge: left to the owner, one-way door")

    def assert_left_with_line(self, branch: str, head: str, line: str, calls: list | None = None):
        self.assertEqual(self.calls(), calls or [VIEW, BODY_NOW, EDIT])
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

    def test_merge_ci_unknown_when_a_workflow_runs_on_push(self):
        head = self.branch("feat/push-ci", files={".github/workflows/ci.yml": "# pull_request is off\non: push\n"})
        self.no_checks()
        self.answer(head)
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.ci-unknown: GitHub reports no checks on {head[:7]}, but "
            ".github/workflows/ci.yml runs on push, so CI may not have started yet\nNext: deliver.py merge\n"))
        self.assert_untouched("feat/push-ci", head)

    def no_checks(self) -> None:
        self.world.gh_answer(CHECKS, stderr="no checks reported\n", exit=1)
        self.world.gh_answer(["run", "list"], "[]\n")

    def test_workflows_that_would_not_run_on_this_pr_are_not_ci(self):
        head = self.branch("feat/not-ci", files={
            ".github/workflows/manual.yml": "on: workflow_dispatch\njobs:\n  a:\n    steps:\n      - run: echo pull_request\n",
            ".github/workflows/release.yml": "on:\n  push:\n    branches:\n      - 'release/*'\n    tags: [v*]\n",
            ".github/workflows/nightly.yml": "on:\n  pull_request:\n    branches: [nightly]\n  schedule:\n    - cron: '0 0 * * *'\n",
        })
        self.no_checks()
        self.answer(head)
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.merge_records("feat/not-ci")[0]["merge_line"],
                         "merge: by the session, squash, checks: none reported")

    def test_a_workflow_only_in_the_working_tree_is_not_read(self):
        head = self.branch("feat/tree")
        folder = self.world.work / ".github" / "workflows"
        folder.mkdir(parents=True)
        (folder / "ci.yml").write_text("on: pull_request\n", encoding="utf-8")
        self.addCleanup(lambda: (folder / "ci.yml").unlink() or folder.rmdir() or folder.parent.rmdir())
        self.no_checks()
        self.answer(head)
        self.assert_ends(self.merge(), 0, (
            f"Merged PR #12 with squash at {head[:7]}.\n"
            f"Kept feat/tree: {self.world.work} has changed or untracked files.\n"))
        self.assertEqual(self.tips("feat/tree"), (head, head))

    def test_merge_ci_unknown_when_a_workflow_cannot_be_read(self):
        head = self.branch("feat/odd-ci", files={".github/workflows/ci.yml": "on: {push: {}}\n"})
        self.no_checks()
        self.answer(head)
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.ci-unknown: GitHub reports no checks on {head[:7]}, but "
            ".github/workflows/ci.yml has triggers this script cannot read, so CI may not have started yet\n"
            "Next: deliver.py merge\n"))
        self.assert_untouched("feat/odd-ci", head)

    def assert_ci_unknown(self, branch: str, files: dict[str, str], why: str):
        head = self.branch(branch, files=files)
        self.no_checks()
        self.answer(head)
        self.assert_ends(self.merge(), 10, (
            f"REFUSED merge.ci-unknown: GitHub reports no checks on {head[:7]}, but {why}, "
            "so CI may not have started yet\nNext: deliver.py merge\n"))
        self.assert_untouched(branch, head)

    def test_branch_filters_this_script_does_not_fully_read_count_as_ci(self):
        for n, pattern in enumerate(["feat/glob-[0-9]", "feat/**", "feat/glob-?", "feat/glob+"]):
            with self.subTest(pattern=pattern):
                self.setUp()
                self.assert_ci_unknown(f"feat/glob-{n}", {".github/workflows/ci.yml": (
                    f"on:\n  push:\n    branches: ['{pattern}']\n")}, ".github/workflows/ci.yml runs on push")

    def test_workflow_files_with_spaces_or_accents_in_their_names_are_read(self):
        for n, name in enumerate(["my ci.yml", "vérify.yml"]):
            with self.subTest(name=name):
                self.setUp()
                self.assert_ci_unknown(f"feat/named-{n}", {f".github/workflows/{name}": "on: push\n"},
                                       f".github/workflows/{name} runs on push")

    def test_an_indented_workflow_is_read(self):
        self.assert_ci_unknown("feat/indented", {".github/workflows/ci.yml": (
            "  name: ci\n  on:\n    push:\n  jobs:\n    a:\n      runs-on: x\n")}, ".github/workflows/ci.yml runs on push")

    def test_a_workflow_with_no_top_level_on_cannot_be_read(self):
        self.assert_ci_unknown("feat/no-on", {".github/workflows/ci.yml": "name: ci\njobs:\n  a:\n    on: push\n"},
                               ".github/workflows/ci.yml has triggers this script cannot read")

    def test_merge_not_merged(self):
        head = self.branch("feat/queued")
        self.world.gh_answer(["pr", "merge"], stderr="Head branch was modified.\n", exit=1)
        self.answer(head, checks=PASS, after="OPEN")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.not-merged: gh pr merge did not merge PR #12: GitHub shows it open\n"
            "Next: gh pr view 12\n"), "Head branch was modified.\n")
        self.assertEqual(self.calls(), [VIEW, CHECKS, VIEW,
                                        ["pr", "merge", "12", "--squash", "--match-head-commit", head], AFTER])
        self.assertEqual(self.merge_records("feat/queued"), [])
        self.assertEqual(self.tips("feat/queued"), (head, head))

    def test_merge_behind_after_the_ci_wait(self):
        head = self.branch("feat/late-behind")
        self.world.gh_answer(VIEW, view(head), once=True)
        self.answer(head, checks=PASS, merge_state="BEHIND")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.behind: PR #12 is behind main, so it goes back to its author\n" + NEXT_BACK))
        self.assertEqual(self.calls(), [VIEW, CHECKS, VIEW])
        self.assert_untouched("feat/late-behind", head)

    def test_merge_conflicting_after_the_ci_wait(self):
        head = self.branch("feat/late-conflict")
        self.world.gh_answer(VIEW, view(head), once=True)
        self.answer(head, checks=PASS, mergeable="CONFLICTING", merge_state="DIRTY")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.conflicting: PR #12 conflicts with main, so it goes back to its author\n" + NEXT_BACK))
        self.assert_untouched("feat/late-conflict", head)

    def test_merge_mergeable_unknown(self):
        head = self.branch("feat/unknown")
        self.answer(head, checks=PASS, mergeable="UNKNOWN", merge_state="UNKNOWN")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.mergeable-unknown: GitHub has not worked out yet whether PR #12 can merge\n"
            "Next: deliver.py merge\n"))
        self.assertEqual(self.calls(), [VIEW, VIEW, CHECKS, VIEW, VIEW])
        self.assert_untouched("feat/unknown", head)

    def test_unknown_mergeability_is_read_again_before_merging(self):
        head = self.branch("feat/known")
        self.world.gh_answer(VIEW, view(head), once=True)
        self.world.gh_answer(VIEW, view(head, mergeable="UNKNOWN", merge_state="UNKNOWN"), once=True)
        self.answer(head, checks=PASS)
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.calls()[:5], [VIEW, CHECKS, VIEW, VIEW,
                                            ["pr", "merge", "12", "--squash", "--match-head-commit", head]])

    def test_merge_withheld_when_changes_are_requested(self):
        head = self.branch("feat/changes")
        self.answer(head, checks=PASS, review="CHANGES_REQUESTED", merge_state="BLOCKED")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.withheld: the merge is withheld: a reviewer requested changes\n"
            "Next: deliver.py finish\n"))
        self.assert_left_with_line("feat/changes", head, "merge: withheld, a reviewer requested changes")

    def test_merge_withheld_when_the_branch_rules_block_it_after_ci(self):
        head = self.branch("feat/blocked")
        self.answer(head, checks=PASS, merge_state="BLOCKED")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.withheld: the merge is withheld: "
            "the branch rules block the merge and the agent does not bypass them\nNext: deliver.py finish\n"))
        self.assert_left_with_line(
            "feat/blocked", head, "merge: withheld, the branch rules block the merge and the agent does not bypass them",
            [VIEW, CHECKS, VIEW, BODY_NOW, EDIT])
        self.assertNotIn("--admin", [a for c in self.calls() for a in c])

    def test_merge_bad_body(self):
        head = self.branch("feat/bad-body")
        self.answer(head, checks=PASS, body="## Summary\n\n<details><summary>Measurement</summary>\n\n```text\npath: x\n")
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.bad-body: the measurement block in PR #12's description has no closing line\n"
            "Next: close the measurement block in PR #12's description, then deliver.py merge\n"))
        self.assertEqual(self.calls(), [VIEW])
        self.assert_untouched("feat/bad-body", head)

    def test_merge_bad_body_with_a_fence_only_after_the_measurement_section(self):
        head = self.branch("feat/late-fence")
        body = ("## Summary\n\n<details><summary>Measurement</summary>\n\n```text\npath: x\n\n</details>\n\n"
                "## Try it\n\n```sh\nmake check\n```\n")
        self.answer(head, checks=PASS, body=body)
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.bad-body: the measurement block in PR #12's description has no closing line\n"
            "Next: close the measurement block in PR #12's description, then deliver.py merge\n"))
        self.assertEqual(self.calls(), [VIEW])
        self.assert_untouched("feat/late-fence", head)

    def test_the_line_goes_into_the_description_as_it_is_after_the_merge(self):
        head = self.branch("feat/edited")
        self.answer(head, checks=PASS, body_now=BODY.replace("Fix the typo.", "Fix the typo, edited by the owner."))
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.body_sent(), "## Summary\n\nFix the typo, edited by the owner.\n\n" + BLOCK.format(
            merge="merge: by the session, squash\n"))

    def test_merge_no_history(self):
        head = self.branch("feat/no-base")
        self.answer(head, checks=PASS, base="gone")
        result = self.merge()
        self.assertEqual((result.returncode, result.stderr), (10, ""))
        self.assertEqual(result.stdout, (
            "REFUSED merge.no-history: the history of origin/gone cannot be read: "
            "fatal: couldn't find remote ref gone\nNext: git fetch origin gone, then deliver.py merge\n"))
        self.assert_untouched("feat/no-base", head)

    def test_an_earlier_run_on_the_branch_decides_nothing(self):
        head = self.branch("feat/second-run", created=False, stop_at_ready=True)
        self.world.add_record("feat/second-run", "start", run="run-2", branch_created=True)
        self.world.add_record("feat/second-run", "pr", number=12, url="https://github.com/owner/repo/pull/12")
        self.world.add_record("feat/second-run", "ready", commit=head, result="small edit", door="two-way")
        self.world.write_mark(run="run-2", branch="feat/second-run")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 0, (
            f"Merged PR #12 with squash at {head[:7]}.\n"
            "Switched this checkout to main.\n"
            "Removed the remote branch origin/feat/second-run and the local branch feat/second-run.\n"))

    def test_a_pr_of_an_earlier_run_is_not_this_runs(self):
        head = self.branch("feat/new-run")
        self.world.add_record("feat/new-run", "start", run="run-2", branch_created=True)
        self.world.write_mark(run="run-2", branch="feat/new-run")
        self.answer(head, checks=PASS)
        self.saved = self.world.records("feat/new-run")
        self.assert_ends(self.merge(), 10, "REFUSED merge.no-pr: the records of feat/new-run hold no PR\n"
                                           "Next: deliver.py pr\n")
        self.assertEqual(self.calls(), [])
        self.assert_untouched("feat/new-run", head)

    def test_a_mark_whose_run_has_no_start_of_its_own_decides_nothing(self):
        head = self.branch("feat/other-run")
        self.world.write_mark(run="run-2", branch="feat/other-run")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, "REFUSED merge.no-pr: the records of feat/other-run hold no PR\n"
                                           "Next: deliver.py pr\n")
        self.assertEqual(self.calls(), [])
        self.assert_untouched("feat/other-run", head)

    def test_records_written_before_the_mark_belong_to_another_run(self):
        # A run begun before start wrote a start record: the mark's start time bounds the run.
        w = self.world
        w.git(w.work, "switch", "-q", "-c", "deliver/ticket-9-run3")
        head = w.commit(w.work, "nine.txt", "x\n", "fix: nine")
        w.git(w.work, "push", "-q", "-u", "origin", "deliver/ticket-9-run3")
        w.add_record("deliver/ticket-9-run3", "pr", number=12, url="https://github.com/owner/repo/pull/12")
        w.add_record("deliver/ticket-9-run3", "ready", commit=head, result="small edit", door="two-way")
        w.write_mark(run="run3", branch="deliver/ticket-9-run3", started="2999-01-01T00:00:00Z")
        self.saved = w.records("deliver/ticket-9-run3")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, "REFUSED merge.no-pr: the records of deliver/ticket-9-run3 hold no PR\n"
                                           "Next: deliver.py pr\n")
        self.assert_untouched("deliver/ticket-9-run3", head)

    def start_shaped(self, name: str, run: str) -> str:
        """A branch with the records of a run begun before start wrote a start record."""
        w = self.world
        w.git(w.work, "switch", "-q", "-c", name)
        head = w.commit(w.work, f"{run}.txt", "x\n", f"fix: {run}")
        w.git(w.work, "push", "-q", "-u", "origin", name)
        w.write_mark(run=run, branch=name, started="2000-01-01T00:00:00Z")
        w.save_text(name, "request", "Source: ticket #9\n\nFix it.\n")
        w.add_record(name, "save", kind="request", file="request.md", commit=None)
        w.add_record(name, "pr", number=12, url="https://github.com/owner/repo/pull/12")
        w.add_record(name, "ready", commit=head, result="small edit", door="two-way")
        return head

    def test_a_branch_start_cut_for_the_run_is_removed(self):
        head = self.start_shaped("deliver/ticket-9-ab12cd34", "ab12cd34")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 0, (
            f"Merged PR #12 with squash at {head[:7]}.\nSwitched this checkout to main.\n"
            "Removed the remote branch origin/deliver/ticket-9-ab12cd34 and the local branch deliver/ticket-9-ab12cd34.\n"))

    def test_a_branch_start_found_checked_out_is_kept(self):
        head = self.start_shaped("feat/owners", "cd34ab12")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 0, (
            f"Merged PR #12 with squash at {head[:7]}.\nSwitched this checkout to main.\n"
            "Kept feat/owners: this run did not create it.\n"))
        self.assertEqual(self.tips("feat/owners"), (head, head))

    def test_merge_behind_when_the_base_moved_past_the_head(self):
        w = self.world
        head = self.branch("feat/stale")
        w.git(w.work, "switch", "-q", "main")
        w.commit(w.work, "base-moved.txt", "b\n", "chore: the base moves")
        w.git(w.work, "push", "-q", "origin", "main")
        w.git(w.work, "switch", "-q", "feat/stale")
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(), 10, (
            "REFUSED merge.behind: PR #12 is behind main, so it goes back to its author\n" + NEXT_BACK))
        self.assertEqual(self.calls(), [VIEW, CHECKS, VIEW])
        self.assert_untouched("feat/stale", head)

    def test_a_ready_record_written_during_the_ci_wait_decides(self):
        head = self.branch("feat/late-door")
        log = self.world.work / ".git" / "deliver" / "branches" / "feat" / "late-door" / "records.jsonl"
        line = json.dumps({"event": "ready", "at": "2026-11-27T20:00:00Z", "commit": head,
                           "result": "needs review", "door": "one-way"})
        path = wrapped(self.world, "gh", f"if args[:2] == ['pr', 'checks'] and '--watch' in args:\n"
                                         f"    open({str(log)!r}, 'a').write({line!r} + '\\n')")
        self.world.gh_answer(CHECKS, json.dumps([{"name": "tests", "bucket": "pending"}]), once=True)
        self.world.gh_answer(["pr", "checks", "12", "--watch"])
        self.answer(head, checks=PASS)
        self.assert_ends(self.merge(PATH=path), 10, (
            "Waiting for pending checks on PR #12: tests.\n"
            "REFUSED merge.one-way: the door is one-way, so the owner merges PR #12\nNext: deliver.py finish\n"))
        self.assert_left_with_line("feat/late-door", head, "merge: left to the owner, one-way door",
                                   [VIEW, CHECKS, ["pr", "checks", "12", "--watch"], CHECKS, VIEW, BODY_NOW, EDIT])


class StartedRun(unittest.TestCase):
    """A run begun by deliver.py start, whose records then gain a PR and a passing ready."""

    def test_merge_withheld_when_stop_at_ready_was_given_at_start(self):
        w = deliver_kit.World(self.addCleanup)
        w.install_upstream()
        w.gh_answer(DEFAULT, "main\n")
        deliver_kit.github_ok(w)
        (w.work / "fix.txt").write_text("x\n", encoding="utf-8")
        started = w.deliver("start", "--stop-at-ready")
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        branch = w.git(w.work, "branch", "--show-current")
        w.git(w.work, "add", "fix.txt")
        w.git(w.work, "commit", "-q", "-m", "fix: started run")
        head = w.git(w.work, "rev-parse", "HEAD")
        w.git(w.work, "push", "-q", "-u", "origin", branch)
        w.add_record(branch, "pr", number=12, url="https://github.com/owner/repo/pull/12")
        w.add_record(branch, "ready", commit=head, result="small edit", door="two-way")
        w.gh_reset()
        answer(w, head, checks=PASS)
        result = w.deliver("merge", TMPDIR=str(w.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (10, (
            "REFUSED merge.withheld: the merge is withheld: stop at ready was given at start\n"
            "Next: deliver.py finish\n"), ""))
        self.assertEqual([{k: v for k, v in r.items() if k != "at"} for r in w.records(branch) if r["event"] == "merge"],
                         [{"event": "merge", "commit": head, "method": None,
                           "merge_line": "merge: withheld, stop at ready was given at start"}])
        self.assertEqual([c["args"][:2] for c in w.gh_calls()], [["pr", "view"], ["pr", "view"], ["pr", "edit"]])


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
        w.add_record("feat/method", "start", run="run-1", branch_created=True)
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

    def test_a_merge_commit_with_any_title_merges(self):
        world = deliver_kit.World(self.addCleanup)
        self.land(world, "Add checkout support (#33)", merge=True)
        for n in range(60):
            world.commit(world.work, "direct.txt", f"{n}\n", f"chore: direct push {n}")
        world.git(world.work, "push", "-q", "origin", "main")
        self.assertEqual(self.merged_with(world)[3], "--merge")

    def test_a_direct_commit_github_made_after_a_merge_is_skipped(self):
        world = deliver_kit.World(self.addCleanup)
        self.land(world, "Merge pull request #3 from owner/side", merge=True)
        self.land(world, "docs: fix a spelling")  # an edit on GitHub: committed by GitHub, dates equal
        self.assertEqual(self.merged_with(world)[3], "--merge")

    def test_history_of_squashed_commits_squashes(self):
        world = deliver_kit.World(self.addCleanup)
        self.land(world, "fix: a squashed change (#4)")
        self.assertEqual(self.merged_with(world)[3], "--squash")


if __name__ == "__main__":
    unittest.main()
