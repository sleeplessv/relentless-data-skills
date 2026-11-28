"""findings.py and `deliver.py save review`: reading a reviewer's report, and each finding's number, scope and proof.

The parsing, scope and proof rules are tested on tables of made-up report lines with
`findings.py` loaded in this process. `save review` and the Findings table are tested through
deliver.py at its command line in a throwaway world from tests/deliver_kit.py, with made-up
reports written into `.deliver/`.

    python3 -m unittest tests.test_deliver_findings
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

findings = deliver_kit.load("findings")


class Parse(unittest.TestCase):
    def test_a_requirements_report_gives_its_answers_and_findings(self):
        answers, found = findings.parse(
            "R1: met: `python3 -m unittest tests.test_x`\n"
            "\n"
            "R2: not met: calc.py:4 still divides by zero\n"
            "R3: cannot tell\n"
            "F1: calc.py:7: the guard returns None. Evidence: `python3 -m unittest tests.test_calc` fails\n"
            "F2: R1: the test asserts nothing. Evidence: none\n",
            "requirements")
        self.assertEqual(answers, {"R1": "met", "R2": "not met", "R3": "cannot tell"})
        self.assertEqual(found, [
            {"where": "R2", "text": "not met: calc.py:4 still divides by zero", "evidence": "R2 not met"},
            {"where": "R3", "text": "cannot tell", "evidence": "R3 cannot tell"},
            {"where": "calc.py:7", "text": "the guard returns None",
             "evidence": "`python3 -m unittest tests.test_calc` fails"},
            {"where": "R1", "text": "the test asserts nothing", "evidence": "none"},
        ])

    def test_a_line_outside_the_form_names_its_number(self):
        table = (
            ("requirements", "R1: met\nLooks good to me.\n", 2),
            ("requirements", "R1: mostly met\n", 1),
            ("requirements", "F1: calc.py:7: no evidence given\n", 1),
            ("requirements", "F1: calc.py: no line. Evidence: none\n", 1),
            ("requirements", "## Report\nR1: met\n", 1),
            ("defect", "R1: met\n", 1),
            ("defect", "\n\nF1: calc.py:7: wrong. Evidence: none\nSummary: one finding\n", 4),
        )
        for role, text, number in table:
            with self.subTest(text):
                with self.assertRaises(findings.BadLine) as caught:
                    findings.parse(text, role)
                self.assertEqual(caught.exception.number, number)

    def test_a_location_in_a_code_span_and_a_line_range_are_read(self):
        _, found = findings.parse("F1: `src/a.py:3`: x. Evidence: none\nF2: lib/x.py:3-5: y. Evidence: none\n",
                                  "defect")
        self.assertEqual([f["where"] for f in found], ["src/a.py:3", "lib/x.py:3-5"])


DIFF = """\
diff --git a/calc.py b/calc.py
index 1111111..2222222 100644
--- a/calc.py
+++ b/calc.py
@@ -3 +3,2 @@ def add(a, b):
-    return a - b
+    return a + b
+
@@ -10,0 +12 @@ def div(a, b):
+    assert b
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
"""


class ScopeAndProof(unittest.TestCase):
    def test_changed_lines_are_the_added_and_changed_lines_of_the_new_side(self):
        self.assertEqual(findings.changed_lines(DIFF), {"calc.py": {3, 4, 12}, "new.txt": {1}})

    def test_a_finding_is_in_scope_on_a_changed_line_or_naming_a_requirement(self):
        changed = findings.changed_lines(DIFF)
        for where, scope in (("calc.py:3", "in"), ("calc.py:12", "in"), ("new.txt:1", "in"), ("R2", "in"),
                             ("calc.py:5", "out"), ("calc.py:1-2", "out"), ("calc.py:1-3", "in"),
                             ("other.py:3", "out"), ("old.py:1", "out"), ("./calc.py:4", "in")):
            with self.subTest(where):
                self.assertEqual(findings.scope(where, changed), scope)

    def test_a_finding_is_proven_when_its_evidence_is_not_none(self):
        for evidence, proven in (("none", False), ("None.", False), (" none ", False),
                                 ("`make test` fails: 1 error", True), ("breaks R2", True), ("R2 not met", True)):
            with self.subTest(evidence):
                self.assertEqual(findings.proven(evidence), proven)


CALC = "".join(f"line {n}\n" for n in range(1, 11))
REQUIREMENTS_REPORT = """\
R1: met: `echo ok`

R2: not met: calc.py:3 still says line 3.
F1: calc.py:3: the new line is wrong. Evidence: `echo ok` prints the wrong line
F2: calc.py:3: the new line may be slow. Evidence: none
F3: calc.py:8: an old line is odd. Evidence: none
F4: README.md:1: the seed is stale. Evidence: breaks the house style
"""
SAVED_REQUIREMENTS = """\
Saved the requirements review of {head}.
F1 (in scope, proven) R2: not met: calc.py:3 still says line 3. Next: fix it in a commit.
F2 (in scope, proven) calc.py:3: the new line is wrong. Next: fix it in a commit.
F3 (in scope, not proven) calc.py:3: the new line may be slow. Next: settle it: deliver.py settle F3 --check <command>, or deliver.py settle F3 --unsettled.
F4 (out of scope, not proven) calc.py:8: an old line is odd. Next: nothing; it is listed, not proven.
F5 (out of scope, proven) README.md:1: the seed is stale. Next: file a follow-up: deliver.py follow-up F5.
"""
URL = "https://github.com/owner/repo/pull/12"


class SaveReview(unittest.TestCase):
    """Each test has its own worktree on a branch that changes line 3 of calc.py, and a brief record per role."""

    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        cls.world.commit(cls.world.work, "calc.py", CALC, "feat: calc")
        cls.world.git(cls.world.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        cls.base = cls.world.git(cls.world.work, "rev-parse", "HEAD")
        cls.common = Path(cls.world.git(cls.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        cls.count = 0

    def setUp(self):
        deliver_kit.reset_gh(self.world)
        type(self).count += 1
        self.name = f"feat/review-{self.count}"
        self.checkout = self.world.worktree(self.name.replace("/", "-"), self.name)
        self.head = self.world.commit(self.checkout, "calc.py", CALC.replace("line 3\n", "line three\n"), "fix: line 3")
        self.world.write_mark(self.checkout, branch=self.name)
        self.folder = self.common / "deliver" / "branches" / self.name
        for role in ("requirements", "defect"):
            self.world.add_record(self.name, "brief", role=role, round=0, model="sonnet", effort="high",
                                  commit=self.head, path=f"briefs/{role}-0.md", fixed_point=self.base)

    def drop(self, text: str) -> Path:
        path = self.checkout / ".deliver" / "review.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def save(self, role: str, text: str | None = None):
        if text is not None:
            self.drop(text)
        return self.world.deliver("save", "review", role, cwd=self.checkout)

    def reviews(self) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "at"} for r in self.world.records(self.name)
                if r["event"] == "review"]

    def assert_ends(self, result, code: int, stdout: str):
        self.assertEqual((result.returncode, result.stdout), (code, stdout), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def assert_refused(self, result, stdout: str):
        self.assert_ends(result, 10, stdout)
        self.assertEqual(self.reviews(), [])
        self.assertTrue((self.checkout / ".deliver" / "review.md").exists())

    def test_scope_reads_the_diff_whatever_the_diff_config(self):
        """diff.noprefix drops the b/ prefix, and git quotes a non-ASCII path unless core.quotePath is off."""
        self.world.git(self.checkout, "config", "diff.noprefix", "true")
        self.addCleanup(self.world.git, self.checkout, "config", "--unset", "diff.noprefix")
        head = self.world.commit(self.checkout, "café.py", "x = 1\n", "feat: café")
        self.world.add_record(self.name, "brief", role="defect", round=0, model="sonnet", effort="high", commit=head,
                              path="briefs/defect-0.md", fixed_point=self.base)
        settle = "settle it: deliver.py settle {n} --check <command>, or deliver.py settle {n} --unsettled"
        self.assert_ends(self.save("defect", "F1: calc.py:3: off by one. Evidence: none\n"
                                             "F2: café.py:1: x is unused. Evidence: none\n"), 0,
                         f"Saved the defect review of {head[:7]}.\n"
                         f"F1 (in scope, not proven) calc.py:3: off by one. Next: {settle.format(n='F1')}.\n"
                         f"F2 (in scope, not proven) café.py:1: x is unused. Next: {settle.format(n='F2')}.\n")

    def test_a_requirements_report_is_saved_numbered_scoped_and_proven(self):
        self.assert_ends(self.save("requirements", REQUIREMENTS_REPORT), 0,
                         SAVED_REQUIREMENTS.format(head=self.head[:7]))
        self.assertFalse((self.checkout / ".deliver" / "review.md").exists())
        self.assertEqual((self.folder / "reviews" / "requirements-0.md").read_text(encoding="utf-8"),
                         REQUIREMENTS_REPORT)

        def finding(number, where, text, evidence, scope, proven):
            return {"number": number, "reviewer": "requirements", "where": where, "text": text, "evidence": evidence,
                    "scope": scope, "proven": proven}

        self.assertEqual(self.reviews(), [{
            "event": "review", "role": "requirements", "round": 0, "commit": self.head,
            "file": "reviews/requirements-0.md", "answers": {"R1": "met", "R2": "not met"}, "findings": [
                finding("F1", "R2", "not met: calc.py:3 still says line 3.", "R2 not met", "in", True),
                finding("F2", "calc.py:3", "the new line is wrong", "`echo ok` prints the wrong line", "in", True),
                finding("F3", "calc.py:3", "the new line may be slow", "none", "in", False),
                finding("F4", "calc.py:8", "an old line is odd", "none", "out", False),
                finding("F5", "README.md:1", "the seed is stale", "breaks the house style", "out", True),
            ]}])

    def test_numbers_continue_across_the_two_reviewers_in_save_order(self):
        self.save("defect", "F1: calc.py:3: off by one. Evidence: none\n")
        self.assert_ends(self.save("requirements", "R1: met\nR2: cannot tell\n"), 0, (
            f"Saved the requirements review of {self.head[:7]}.\n"
            "F2 (in scope, proven) R2: cannot tell. Next: fix it in a commit.\n"))
        self.assertEqual([[f["number"] for f in r["findings"]] for r in self.reviews()], [["F1"], ["F2"]])

    def test_a_report_with_no_finding_says_so(self):
        self.assert_ends(self.save("defect", "\n"), 0, f"Saved the defect review of {self.head[:7]}.\nNo findings.\n")
        self.assertEqual(self.reviews()[0]["findings"], [])

    def test_save_bad_review(self):
        result = self.save("defect", "\nF1: calc.py:3: off by one. Evidence: none\nR1: met\nNot a line\n")
        self.assert_refused(result, (
            "REFUSED save.bad-review: line 3 of .deliver/review.md is outside the report's form: R1: met\n"
            f"Next: start the reviewer again with `Read {self.folder}/briefs/defect-0.md and follow it.`, write its "
            "final message into .deliver/review.md, then deliver.py save review defect\n"))

    def test_save_no_brief(self):
        self.world.git(self.checkout, "checkout", "-q", "-b", "feat/unbriefed")
        self.world.write_mark(self.checkout, branch="feat/unbriefed")
        self.drop("F1: calc.py:3: off by one. Evidence: none\n")
        result = self.world.deliver("save", "review", "defect", cwd=self.checkout)
        self.assert_ends(result, 10, (
            "REFUSED save.no-brief: no defect brief is saved, so the report is tied to no reviewed commit\n"
            "Next: deliver.py brief defect --model <id>\n"))
        self.assertTrue((self.checkout / ".deliver" / "review.md").exists())

    def test_save_tree_changed(self):
        self.drop("F1: calc.py:3: off by one. Evidence: none\n")
        (self.checkout / "calc.py").write_text("changed\n", encoding="utf-8")
        self.assert_refused(self.save("defect"), (
            "REFUSED save.tree-changed: a tracked file is changed, so the report did not read this tree\n"
            "Next: commit or restore the changed files, then deliver.py save review defect\n"))
        moved = self.world.commit(self.checkout, "calc.py", "changed\n", "fix: more")
        self.assert_refused(self.save("defect"), (
            f"REFUSED save.tree-changed: HEAD is {moved[:7]}, not the reviewed commit {self.head[:7]}, so the "
            "report did not read this tree\n"
            "Next: deliver.py brief defect --model sonnet, then start the reviewer again with its line\n"))

    def test_save_missing_file_for_a_review(self):
        self.assert_ends(self.save("defect"), 10, (
            "REFUSED save.missing-file: there is no .deliver/review.md to save\n"
            "Next: write .deliver/review.md, then run deliver.py save review defect\n"))

    def test_pr_renders_the_findings_table(self):
        self.save("requirements", REQUIREMENTS_REPORT)
        self.save("defect", "F1: calc.py:3: `x | y` is wrong. Evidence: none\n")
        body = self.pr()
        self.assertIn("""
## Findings

| # | From | Finding | Scope | State |
|---|---|---|---|---|
| F1 | requirements review | `R2`: not met: calc.py:3 still says line 3; R2 not met | in | open |
| F2 | requirements review | `calc.py:3`: the new line is wrong; `echo ok` prints the wrong line | in | open |
| F3 | requirements review | `calc.py:3`: the new line may be slow | in | open |
| F4 | requirements review | `calc.py:8`: an old line is odd | out | listed, not proven |
| F5 | requirements review | `README.md:1`: the seed is stale; breaks the house style | out | open |
| F6 | defect review | `calc.py:3`: `x \\| y` is wrong | in | open |
""", body)
        self.assertNotIn("No review: small edit.", body)

    def test_a_finding_holding_a_secret_is_refused_as_the_description_is(self):
        self.save("defect", "F1: calc.py:3: the key ghp_" + "a1B2" * 9 + " is in the code. Evidence: none\n")
        self.save_texts()
        result = self.world.deliver("pr", cwd=self.checkout)
        self.assertEqual(result.returncode, 20, result.stderr)
        self.assertIn("Finding F1 looks like it holds a secret", result.stdout)
        self.assertNotIn("ghp_", result.stdout)
        self.assertEqual([c["args"][:2] for c in self.world.gh_calls()], [])

    def save_texts(self) -> None:
        for kind, text in (("request", "Source: ticket #7\n\nFix line 3.\n"), ("summary", "Fixes line 3.\n"),
                           ("plan", "| # | Requirement | Proof |\n|---|---|---|\n| R1 | line 3 | `echo ok` |\n"
                                    "| R2 | no more | review |\n\ndoor: two-way, one line\n")):
            self.world.save_text(self.name, kind, text)

    def pr(self) -> str:
        """Run deliver.py pr with the texts saved, and return the body it sent to gh."""
        self.save_texts()
        deliver_kit.reset_gh(self.world)
        self.world.gh_answer(["repo", "view"], "main\n")
        self.world.gh_answer(["pr", "list"], "[]")
        self.world.gh_answer(["pr", "create"], f"{URL}\n")
        tmp = self.world.root / "tmp"
        tmp.mkdir(exist_ok=True)
        result = self.world.deliver("pr", cwd=self.checkout, TMPDIR=str(tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return next(c["body"] for c in self.world.gh_calls() if c["args"][:2] == ["pr", "create"])


if __name__ == "__main__":
    unittest.main()
