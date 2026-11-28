"""deliver.py settle and follow-up, and a review run end to end from the briefs to the Findings table.

Each test runs deliver.py at its command line in a throwaway world from tests/deliver_kit.py,
against its bare remote and the stand-in gh. The Settle and FollowUp tests share one world, each
in its own worktree, with a saved review written into the records by hand; the end-to-end test
saves made-up reports written into `.deliver/`.

    python3 -m unittest tests.test_deliver_settle
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

URL = "https://github.com/owner/repo/pull/12"
ISSUE = "https://github.com/owner/repo/issues/31"
FINDINGS = (
    ("F1", "calc.py:1", "add ignores b", "`echo ok` fails", "in", True),
    ("F2", "calc.py:2", "add may be slow", "none", "in", False),
    ("F3", "README.md:1", "the seed is stale", "breaks the house style", "out", True),
    ("F4", "README.md:1", "the seed is short", "none", "out", False),
)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        cls.count = 0

    def setUp(self):
        deliver_kit.reset_gh(self.world)
        type(self).count += 1
        self.name = f"feat/settle-{self.count}"
        self.checkout = self.world.worktree(self.name.replace("/", "-"), self.name)
        self.head = self.world.commit(self.checkout, "calc.py", "def add(a, b):\n    return a\n", "feat: add")
        self.world.write_mark(self.checkout, branch=self.name)
        self.world.add_record(self.name, "pr", number=12, url=URL)
        self.world.add_record(self.name, "review", role="defect", round=0, commit=self.head,
                              file="reviews/defect-0.md", answers={}, findings=[
                                  {"number": n, "reviewer": "defect", "where": where, "text": text,
                                   "evidence": evidence, "scope": scope, "proven": proven}
                                  for n, where, text, evidence, scope, proven in FINDINGS])

    def run_(self, *args: str):
        return self.world.deliver(*args, cwd=self.checkout, TMPDIR=str(self.world.root))

    def added(self, event: str) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "at"} for r in self.world.records(self.name) if r["event"] == event]

    def check(self, command: str, commit: str, exit: int = 0) -> None:
        self.world.add_record(self.name, "check", command=command, exit=exit, output="checks/1.txt", commit=commit,
                              selected_nothing=False)

    def assert_ends(self, result, code: int, stdout: str):
        self.assertEqual((result.returncode, result.stdout), (code, stdout), result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class Settle(Base):
    def assert_refused(self, args: tuple[str, ...], stdout: str):
        self.assert_ends(self.run_("settle", *args), 10, stdout)
        self.assertEqual(self.added("settle"), [])

    def test_a_counted_pass_of_the_exact_text_on_head_disproves_a_finding_proven_or_not(self):
        self.check("echo ok", self.head)
        for number in ("F2", "F1"):
            with self.subTest(number):
                self.assert_ends(self.run_("settle", number, "--check", "echo ok"), 0,
                                 f"{number} is disproven: `echo ok` passes on {self.head[:7]}.\n")
        self.assertEqual(self.added("settle"), [
            {"event": "settle", "finding": n, "state": "disproven", "command": "echo ok", "commit": self.head}
            for n in ("F2", "F1")])

    def test_settle_no_pass(self):
        older = self.world.git(self.checkout, "rev-parse", "HEAD~1")
        self.check("echo ok", older)
        self.check("echo ok", self.head, exit=1)
        self.check("echo  ok", self.head)
        self.world.add_record(self.name, "check", command="echo ok", exit=0, output="checks/1.txt", commit=self.head,
                              selected_nothing=True)
        self.assert_refused(("F2", "--check", "echo ok"), (
            f"REFUSED settle.no-pass: `echo ok` has no counted pass on the head commit {self.head[:7]}\n"
            "Next: deliver.py check -- 'echo ok', then deliver.py settle F2 --check 'echo ok'\n"))

    def test_unsettled_leaves_an_unproven_finding_to_the_owner(self):
        self.assert_ends(self.run_("settle", "F2", "--unsettled"), 0, "F2 is unsettled; the owner decides it.\n")
        self.assertEqual(self.added("settle"), [{"event": "settle", "finding": "F2", "state": "unsettled"}])

    def test_settle_proven(self):
        self.assert_refused(("F1", "--unsettled"), (
            "REFUSED settle.proven: F1 is proven, so it is fixed in a commit or disproven by a check that passes\n"
            "Next: fix it in a commit, or deliver.py settle F1 --check <command>\n"))

    def test_settle_out_of_scope(self):
        self.check("echo ok", self.head)
        self.assert_refused(("F3", "--check", "echo ok"), (
            "REFUSED settle.out-of-scope: F3 is out of scope, and settle takes a finding in scope\n"
            "Next: deliver.py follow-up F3\n"))
        self.assert_refused(("F4", "--unsettled"),
                            "REFUSED settle.out-of-scope: F4 is out of scope, and settle takes a finding in scope\n")

    def test_settle_unknown_finding(self):
        self.assert_refused(("F9", "--unsettled"), "REFUSED settle.unknown-finding: no saved finding is numbered F9\n")

    def test_other_arguments_are_a_usage_error(self):
        for args in ((), ("F1",), ("F1", "--check"), ("F1", "--check", ""), ("F1", "--check", "a", "b"),
                     ("F1", "--unsettled", "x"), ("F1", "--settled")):
            with self.subTest(args):
                result = self.run_("settle", *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("settle takes a finding, F<n>, and --check <command> or --unsettled", result.stderr)


class FollowUp(Base):
    def assert_refused(self, number: str, stdout: str):
        self.assert_ends(self.run_("follow-up", number), 10, stdout)
        self.assertEqual(self.added("follow-up"), [])
        self.assertEqual(self.world.gh_calls(), [])

    def stack(self, text: str) -> None:
        path = self.checkout / "docs" / "agents" / "stack.toml"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")

    def test_files_a_ticket_with_the_line_the_pr_and_the_label(self):
        self.stack('[labels]\nfollow_up = "found-in-review"\n')
        self.world.gh_answer(["issue", "create"], f"{ISSUE}\n")
        self.assert_ends(self.run_("follow-up", "F3"), 0, f"Filed follow-up #31 for F3: {ISSUE}\n")
        self.assertEqual(self.world.gh_calls(), [{
            "args": ["issue", "create", "--title", "README.md:1: the seed is stale", "--body-file",
                     self.world.gh_calls()[0]["args"][5], "--label", "found-in-review"],
            "cwd": str(self.checkout),
            "body": ("F3: README.md:1: the seed is stale. Evidence: breaks the house style\n\n"
                     f"Found out of scope by the defect review of {URL}.\n")}])
        self.assertFalse(Path(self.world.gh_calls()[0]["args"][5]).exists())
        self.assertEqual(self.added("follow-up"), [{"event": "follow-up", "finding": "F3", "state": "filed", "issue": 31}])

    def test_follow_ups_off_records_not_filed_and_calls_no_gh(self):
        self.stack("follow_ups = false\n")
        self.assert_ends(self.run_("follow-up", "F3"), 0, "Follow-up not filed for F3: follow_ups = false in "
                                                          "docs/agents/stack.toml.\n")
        self.assertEqual(self.world.gh_calls(), [])
        self.assertEqual(self.added("follow-up"), [{"event": "follow-up", "finding": "F3", "state": "not filed",
                                                    "reason": "follow_ups = false in docs/agents/stack.toml"}])

    def test_gh_failing_records_not_filed_and_exits_0(self):
        self.world.gh_answer(["issue", "create"], stderr="could not add label: 'needs-triage' not found\n", exit=1)
        self.assert_ends(self.run_("follow-up", "F3"), 0, "Follow-up not filed for F3: gh issue create failed: could "
                                                          "not add label: 'needs-triage' not found.\n")
        self.assertEqual([c["args"][-2:] for c in self.world.gh_calls()], [["--label", "needs-triage"]])
        self.assertEqual(self.added("follow-up"), [{"event": "follow-up", "finding": "F3", "state": "not filed",
                                                    "reason": "gh issue create failed: could not add label: "
                                                              "'needs-triage' not found"}])

    def test_follow_up_in_scope(self):
        self.assert_refused("F1", "REFUSED follow-up.in-scope: F1 is in scope, so it is fixed or settled in this PR\n"
                                  "Next: fix it in a commit\n")

    def test_follow_up_not_proven(self):
        self.assert_refused("F4", "REFUSED follow-up.not-proven: F4 is not proven, so it is listed and needs no "
                                  "follow-up\n")

    def test_follow_up_unknown_finding(self):
        self.assert_refused("F9", "REFUSED follow-up.unknown-finding: no saved finding is numbered F9\n")

    def test_follow_up_bad_settings(self):
        self.stack("follow_ups = [\n")
        result = self.run_("follow-up", "F3")
        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertTrue(result.stdout.startswith("REFUSED follow-up.bad-settings: the stack settings cannot be read: "
                                                 "docs/agents/stack.toml is not TOML: "))
        self.assertTrue(result.stdout.endswith("\nNext: fix docs/agents/stack.toml, then deliver.py follow-up F3\n"))
        self.assertEqual(self.added("follow-up"), [])

    def test_a_usage_error_names_the_finding(self):
        result = self.run_("follow-up")
        self.assertEqual(result.returncode, 2)
        self.assertIn("follow-up takes a finding, F<n>", result.stderr)


CALC = "".join(f"line {n}\n" for n in range(1, 11))
PLAN = """\
| # | Requirement | Proof |
|---|---|---|
| R1 | calc.py keeps ten lines | `echo ok` |

door: two-way, one file; nothing deploys on merge
"""
GREP = "grep -q 'line 3' calc.py"


class EndToEnd(unittest.TestCase):
    """Briefs, two saved reviews, a fix, a call-back, a settle, an unsettled finding and a follow-up, to the table."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.install_upstream()
        self.work = self.world.work
        self.world.commit(self.work, "calc.py", CALC, "feat: calc")
        self.world.git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.world.git(self.work, "switch", "-q", "-c", "feat/e2e")
        self.world.write_mark(branch="feat/e2e")
        self.world.add_record("feat/e2e", "preflight", run="run-1", result="pass", stops=[], warnings=[],
                              harness="claude-code")
        for kind, text in (("request", "Source: conversation\n\nMend calc.py.\n"), ("requirements", "- R1: ten lines\n"),
                           ("summary", "Mends calc.py.\n"), ("plan", PLAN)):
            self.world.save_text("feat/e2e", kind, text)

    def deliver(self, *args: str, code: int = 0) -> str:
        result = self.world.deliver(*args, TMPDIR=str(self.world.root))
        self.assertEqual(result.returncode, code, f"{args}: {result.stdout}{result.stderr}")
        return result.stdout

    def report(self, kind: str, text: str) -> None:
        (self.work / ".deliver").mkdir(exist_ok=True)
        (self.work / ".deliver" / f"{kind}.md").write_text(text, encoding="utf-8")

    def push(self, head: str, opened: bool) -> None:
        """`deliver.py pr` opens the PR or edits it, then GitHub shows `head` as its head."""
        deliver_kit.reset_gh(self.world)
        self.world.gh_answer(["repo", "view"], "main\n")
        self.world.gh_answer(["pr", "list"], json.dumps([{"number": 12, "url": URL}] if opened else []))
        self.world.gh_answer(["pr", "create"], f"{URL}\n")
        self.world.gh_answer(["pr", "edit"], "")
        self.deliver("pr")
        self.world.gh_answer(["pr", "view"], json.dumps({"headRefOid": head, "baseRefName": "main"}))

    def test_review_fix_callback_settle_and_follow_up_reach_the_findings_table(self):
        read = self.world.commit(self.work, "calc.py", CALC.replace("line 3", "line three").replace("line 5", "line V"),
                                 "feat: words")
        self.deliver("check", "--", "echo ok")
        self.deliver("check", "--", GREP)
        self.push(read, opened=False)
        self.deliver("brief", "requirements", "--model", "sonnet")
        self.deliver("brief", "defect", "--model", "opus")
        self.report("review", f"R1: met\nF1: calc.py:3: line 3 lost its digit. Evidence: `{GREP}` fails\n"
                              "F2: calc.py:5: line V may confuse. Evidence: none\n")
        self.deliver("save", "review", "requirements")
        self.report("review", "F1: calc.py:5: a roman numeral. Evidence: none\n"
                              "F2: README.md:1: the seed is stale. Evidence: breaks the house style\n"
                              "F3: calc.py:9: line 9 is odd. Evidence: none\n")
        self.deliver("save", "review", "defect")

        fix = self.world.commit(self.work, "calc.py", CALC.replace("line 5", "line V"), "fix: line 3 keeps its digit")
        self.deliver("check", "--", "echo ok")
        self.deliver("check", "--", GREP)
        self.push(fix, opened=True)
        self.assertEqual(self.deliver("brief", "callback", "requirements"),
                         f"Read {self.work}/.git/deliver/branches/feat/e2e/briefs/requirements-1.md and follow it.\n")
        self.report("callback", "F1: resolved\nF2: not resolved\n")
        self.assertIn(f"F1 (in scope, proven) calc.py:3: line 3 lost its digit. Next: nothing; it is fixed in "
                      f"{fix[:7]}: `{GREP}` fails before, passes after.\n",
                      self.deliver("save", "callback", "requirements"))
        self.deliver("settle", "F2", "--check", "echo ok")
        self.deliver("settle", "F3", "--unsettled")
        self.world.gh_answer(["issue", "create"], f"{ISSUE}\n")
        self.deliver("follow-up", "F4")

        self.push(fix, opened=True)
        body = next(c["body"] for c in self.world.gh_calls() if c["args"][:2] == ["pr", "edit"])
        self.assertIn(f"""
## Findings

| # | From | Finding | Scope | State |
|---|---|---|---|---|
| F1 | requirements review | `calc.py:3`: line 3 lost its digit; `{GREP}` fails | in | fixed in {fix[:7]}: `{GREP}` fails before, passes after |
| F2 | requirements review | `calc.py:5`: line V may confuse | in | disproven: `echo ok` passes |
| F3 | defect review | `calc.py:5`: a roman numeral | in | unsettled |
| F4 | defect review | `README.md:1`: the seed is stale; breaks the house style | out | follow-up #31 |
| F5 | defect review | `calc.py:9`: line 9 is odd | out | listed, not proven |
""", body)
        self.assertEqual([(r["role"], r["round"], r["model"]) for r in self.world.records("feat/e2e")
                          if r["event"] == "brief"],
                         [("requirements", 0, "sonnet"), ("defect", 0, "opus"), ("requirements", 1, "sonnet")])
        self.assertEqual(self.world.git(self.work, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
