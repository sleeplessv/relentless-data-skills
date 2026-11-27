"""deliver.py pr: the push, the draft PR or the edited description, and each refusal.

Each test runs deliver.py pr in its own worktree of one shared throwaway world, against the bare
remote and the stand-in gh of tests/deliver_kit.py, with the records written by hand.

    python3 -m unittest tests.test_deliver_pr
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402
from test_deliver_render import PLAN, SUMMARY, TICKET_REQUEST, write_records  # noqa: E402

render = deliver_kit.load("render")
URL = "https://github.com/owner/repo/pull/{}"
CONVERSATION = "Source: conversation\n\nAdd a --json flag.\n"


class Pr(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        cls.common = Path(cls.world.git(cls.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))

    def setUp(self):
        (self.world.root / "gh-calls.jsonl").unlink(missing_ok=True)
        self.answer(open_prs=[])

    def answer(self, open_prs: list[dict]) -> None:
        (self.world.root / "gh-answers.json").write_text("[]", encoding="utf-8")
        self.world.gh_answer(["repo", "view"], "main\n")
        self.world.gh_answer(["pr", "list"], json.dumps(open_prs))
        self.world.gh_answer(["pr", "create"], URL.format(12) + "\n")
        self.world.gh_answer(["pr", "edit"])

    def branch(self, name: str, request: str | None = TICKET_REQUEST, subject: str | None = None,
               **more: str) -> Path:
        """A worktree on a new branch with one commit and a run mark, and its records when given."""
        checkout = self.world.worktree(name.replace("/", "-"), name)
        self.world.commit(checkout, f"{name}.txt", "x\n", subject or f"feat: {name} work")
        self.world.write_mark(checkout, branch=name)
        if request is not None:
            write_records(self.common / "deliver" / "branches" / name, request, records=[], **more)
        return checkout

    def pr(self, checkout: Path):
        tmp = self.world.root / "tmp"
        tmp.mkdir(exist_ok=True)
        return self.world.deliver("pr", cwd=checkout, TMPDIR=str(tmp))

    def assert_ends(self, result, code: int, stdout: str):
        self.assertEqual((result.returncode, result.stdout), (code, stdout), result.stderr)

    def remote_tip(self, branch: str) -> str:
        return self.world.git(self.world.origin, "for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}")

    def calls(self) -> list[list[str]]:
        return [call["args"] for call in self.world.gh_calls()]

    def test_opens_a_draft_pr_with_the_rendered_description(self):
        checkout = self.branch("feat/open")
        self.assert_ends(self.pr(checkout), 0, f"Opened draft PR #12: {URL.format(12)}\n")
        calls = self.world.gh_calls()
        body_file = calls[2]["args"][-1]
        self.assertEqual([c["args"] for c in calls], [
            ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
            ["pr", "list", "--head", "feat/open", "--state", "open", "--json", "number,url"],
            ["pr", "create", "--draft", "--base", "main", "--head", "feat/open", "--title", "feat: feat/open work",
             "--body-file", body_file],
        ])
        self.assertEqual(calls[2]["body"], render.description(self.common / "deliver" / "branches" / "feat/open"))
        self.assertTrue(calls[2]["body"].startswith("## Summary\n"))
        self.assertEqual(Path(body_file).parent, self.world.root / "tmp")
        self.assertFalse(Path(body_file).exists())
        self.assertEqual(self.world.git(checkout, "status", "--porcelain"), "")
        self.assertEqual(self.remote_tip("feat/open"), self.world.git(checkout, "rev-parse", "HEAD"))
        self.assertEqual({k: v for k, v in self.world.records("feat/open")[-1].items() if k != "at"},
                         {"event": "pr", "number": 12, "url": URL.format(12)})

    def test_edits_the_body_of_the_open_pr(self):
        checkout = self.branch("feat/edit")
        self.answer(open_prs=[{"number": 7, "url": URL.format(7)}])
        self.assert_ends(self.pr(checkout), 0, f"Updated the description of PR #7: {URL.format(7)}\n")
        calls = self.world.gh_calls()
        self.assertEqual(calls[2]["args"], ["pr", "edit", "7", "--body-file", calls[2]["args"][-1]])
        self.assertEqual(len(calls), 3)
        self.assertIn("Closes #415\n", calls[2]["body"])
        self.assertEqual(self.remote_tip("feat/edit"), self.world.git(checkout, "rev-parse", "HEAD"))
        self.assertEqual(self.world.records("feat/edit")[-1]["number"], 7)

    def test_pr_not_saved(self):
        checkout = self.branch("feat/nothing", request=None)
        self.assert_ends(self.pr(checkout), 10, (
            "REFUSED pr.not-saved: the author's files are not saved: request, summary, plan, requirements\n"
            "Next: deliver.py save request\n"))
        self.assertEqual((self.calls(), self.remote_tip("feat/nothing")), ([], ""))

    def test_pr_not_saved_without_requirements_when_the_source_is_not_a_ticket(self):
        checkout = self.branch("feat/no-requirements", request=CONVERSATION)
        self.assert_ends(self.pr(checkout), 10, (
            "REFUSED pr.not-saved: the author's files are not saved: requirements\n"
            "Next: deliver.py save requirements\n"))

    def test_pr_not_saved_while_the_drop_folder_holds_a_file(self):
        checkout = self.branch("feat/drop")
        (checkout / ".deliver").mkdir()
        (checkout / ".deliver" / "plan.md").write_text(PLAN, encoding="utf-8")
        self.assert_ends(self.pr(checkout), 10, (
            "REFUSED pr.not-saved: the author's files are not saved: plan\nNext: deliver.py save plan\n"))
        self.assertEqual(self.calls(), [])

    def test_only_a_saveable_kind_in_the_drop_folder_counts_as_unsaved(self):
        checkout = self.branch("feat/ds-store")
        (checkout / ".deliver").mkdir()
        for name in (".DS_Store", "plan.md~", "notes.md"):
            (checkout / ".deliver" / name).write_text("x\n", encoding="utf-8")
        self.assert_ends(self.pr(checkout), 0, f"Opened draft PR #12: {URL.format(12)}\n")

    def test_pr_wrong_branch(self):
        checkout = self.branch("feat/two", request=None)
        self.world.write_mark(checkout, branch="feat/one")
        write_records(self.common / "deliver" / "branches" / "feat/one", TICKET_REQUEST, records=[])
        self.assert_ends(self.pr(checkout), 10, (
            "REFUSED pr.wrong-branch: the checked-out branch is feat/two, and the run mark's branch is feat/one\n"
            "Next: git switch feat/one\n"))
        self.assertEqual((self.calls(), self.remote_tip("feat/two"), self.remote_tip("feat/one")), ([], "", ""))
        self.assertEqual(self.world.records("feat/one"), [])

    def test_a_secret_in_the_title_ends_in_exit_20_before_the_push(self):
        checkout = self.branch("feat/title-secret", subject="fix: use ghp_" + "a" * 36)
        self.assert_ends(self.pr(checkout), 20, (
            "The PR title, the branch's first commit subject, looks like it holds a secret (a GitHub token) on "
            "line 1, so nothing was pushed or sent to gh. Is it a real secret that should be taken out of the "
            "commit subject before the run goes on?\n"))
        self.assertEqual(self.calls(), [["repo", "view", "--json", "defaultBranchRef", "--jq",
                                         ".defaultBranchRef.name"]])
        self.assertEqual(self.remote_tip("feat/title-secret"), "")

    def test_masks_the_title(self):
        checkout = self.branch("feat/title-mask", subject="fix: ask @octocat about /Users/jane/work")
        self.assert_ends(self.pr(checkout), 0, f"Opened draft PR #12: {URL.format(12)}\n")
        create = self.calls()[2]
        self.assertEqual(create[create.index("--title") + 1], "fix: ask [mention] about [private path]")

    def test_pr_unreadable(self):
        checkout = self.branch("feat/unreadable", plan="Just prose.\n")
        self.assert_ends(self.pr(checkout), 10, (
            "REFUSED pr.unreadable: the saved plan.md cannot be read: it has no requirement row such as "
            "| R1 | <requirement> | <proof> |\nNext: rewrite .deliver/plan.md, then deliver.py save plan\n"))
        self.assertEqual(self.calls(), [])

    def test_pr_default_branch(self):
        self.world.write_mark(self.world.work, branch="main")
        self.addCleanup((self.world.work / ".git" / "deliver-mark.json").unlink)
        write_records(self.common / "deliver" / "branches" / "main", TICKET_REQUEST, records=[])
        self.assert_ends(self.world.deliver("pr"), 10, (
            "REFUSED pr.default-branch: main is the default branch, and a PR needs a branch of its own\n"
            "Next: git switch -c <type>/<name>\n"))
        self.assertEqual(self.calls(), [["repo", "view", "--json", "defaultBranchRef", "--jq",
                                         ".defaultBranchRef.name"]])

    def test_pr_push_rejected(self):
        tree = self.world.git(self.world.work, "rev-parse", "main^{tree}")
        other = self.world.git(self.world.work, "commit-tree", tree, "-p", "main", "-m", "someone else's commit")
        self.world.git(self.world.work, "push", "-q", "origin", f"{other}:refs/heads/feat/rejected")
        checkout = self.branch("feat/rejected")
        result = self.pr(checkout)
        self.assert_ends(result, 10, (
            "REFUSED pr.push-rejected: the push of feat/rejected to origin failed, and nothing was forced\n"
            "Next: git pull --no-rebase origin feat/rejected\n"))
        self.assertIn("[rejected]", result.stderr)
        self.assertEqual(self.remote_tip("feat/rejected"), other)
        self.assertEqual(len(self.calls()), 1)

    def test_pr_push_rejected_without_advising_a_pull_when_a_hook_declines(self):
        hook = self.world.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho '[rejected] unsigned commit'\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        self.addCleanup(hook.unlink)
        checkout = self.branch("feat/hooked")
        result = self.pr(checkout)
        self.assert_ends(result, 10, (
            "REFUSED pr.push-rejected: the push of feat/hooked to origin failed, and nothing was forced\n"
            "Next: fix the error above, then deliver.py pr\n"))
        self.assertIn("[remote rejected]", result.stderr)
        self.assertEqual(self.remote_tip("feat/hooked"), "")

    def without_origin_main(self) -> None:
        """Take the local origin/main ref away for one test, as a single-branch checkout lacks it."""
        tip = self.world.git(self.world.work, "rev-parse", "refs/remotes/origin/main")
        self.world.git(self.world.work, "update-ref", "-d", "refs/remotes/origin/main")
        self.addCleanup(self.world.git, self.world.work, "update-ref", "refs/remotes/origin/main", tip)

    def test_edits_the_open_pr_without_a_local_origin_default_ref(self):
        checkout = self.branch("feat/no-base-edit")
        self.without_origin_main()
        self.answer(open_prs=[{"number": 7, "url": URL.format(7)}])
        self.assert_ends(self.pr(checkout), 0, f"Updated the description of PR #7: {URL.format(7)}\n")
        self.assertEqual(self.calls()[2][:3], ["pr", "edit", "7"])

    def test_the_title_falls_back_to_the_branch_name_without_a_local_origin_default_ref(self):
        checkout = self.branch("feat/no-base-open")
        self.without_origin_main()
        self.assert_ends(self.pr(checkout), 0, f"Opened draft PR #12: {URL.format(12)}\n")
        create = self.calls()[2]
        self.assertEqual(create[create.index("--title") + 1], "feat/no-base-open")

    def test_pr_push_rejected_without_advising_a_pull_when_origin_cannot_be_reached(self):
        checkout = self.branch("feat/unreachable")
        tmp = self.world.root / "tmp"
        tmp.mkdir(exist_ok=True)
        result = self.world.deliver("pr", cwd=checkout, TMPDIR=str(tmp), GIT_CONFIG_COUNT="1",
                                    GIT_CONFIG_KEY_0="remote.origin.pushurl",
                                    GIT_CONFIG_VALUE_0=str(self.world.root / "no-such-remote.git"))
        self.assert_ends(result, 10, (
            "REFUSED pr.push-rejected: the push of feat/unreachable to origin failed, and nothing was forced\n"
            "Next: fix the error above, then deliver.py pr\n"))
        self.assertNotIn("[rejected]", result.stderr)
        self.assertEqual((len(self.calls()), self.remote_tip("feat/unreachable")), (1, ""))

    def test_a_secret_ends_in_exit_20_before_any_push_or_gh_call(self):
        checkout = self.branch("feat/secret", request="Source: conversation\n\nUse AKIAABCDEFGHIJ234567 here.\n",
                               requirements="R1: x\n")
        self.assert_ends(self.pr(checkout), 20, (
            "The saved request.md looks like it holds a secret (an AWS key id) on line 3, so nothing was "
            "pushed or sent to gh. Is it a real secret that should be taken out of the request before the "
            "run goes on?\n"))
        self.assertEqual((self.calls(), self.remote_tip("feat/secret")), ([], ""))
        self.assertEqual(self.world.records("feat/secret"), [])

    def test_masks_the_quote_in_the_body_it_sends(self):
        checkout = self.branch("feat/masked", request=CONVERSATION + "Ask @octocat about ~/work/repo.\n",
                               requirements="R1: x\n", summary=SUMMARY)
        self.assert_ends(self.pr(checkout), 0, f"Opened draft PR #12: {URL.format(12)}\n")
        body = self.world.gh_calls()[2]["body"]
        self.assertIn("Source: conversation (masked: @ mentions and private paths)\n\n"
                      "> Add a --json flag.\n> Ask [mention] about [private path]\n", body)
        self.assertNotIn("@octocat", body)


if __name__ == "__main__":
    unittest.main()
