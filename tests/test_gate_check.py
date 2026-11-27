"""Test scripts/gate_check.py, the rule gate's CI check, at its command line.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_gate_check -v

Each test writes a PR body and a changed-file list into a temporary folder and runs
the script there against a throwaway git repository made once for the class. The
repository has two commits: `bare` has no `skills/deliver/` and `held` has one.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gate_check.py"
GIT = shutil.which("git")


@unittest.skipUnless(GIT, "git is not on PATH")
class GateCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        git = ["git", "-C", str(cls.repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "init", "-q"], check=True)
        (cls.repo / "README.md").write_text("x\n")
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "bare"], check=True)
        subprocess.run([*git, "tag", "bare"], check=True)
        (cls.repo / "skills" / "deliver").mkdir(parents=True)
        (cls.repo / "skills" / "deliver" / "SKILL.md").write_text("x\n")
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "held"], check=True)
        subprocess.run([*git, "tag", "held"], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def gate(self, body: str | None, *, base: str = "main", base_rev: str = "held",
             changed: tuple[str, ...] = ("skills/deliver/SKILL.md",)) -> tuple[int, str, str]:
        """Run the script as CI does; return its exit code, stdout and stderr."""
        work = Path(tempfile.mkdtemp(dir=self.tmp.name))
        (work / "body.md").write_text(body or "", newline="")
        (work / "changed").write_bytes(b"".join(path.encode() + b"\0" for path in changed))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--body", str(work / "body.md"), "--base", base,
             "--default-branch", "main", "--base-rev", base_rev, "--changed", str(work / "changed")],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout, result.stderr

    def test_silent_when_base_is_not_the_default_branch(self) -> None:
        self.assertEqual(
            self.gate(None, base="feature/deliver-stage-3"),
            (0, "gate_check: not checked: the base feature/deliver-stage-3 is not the default branch main.\n", ""))

    def test_silent_when_no_changed_file_is_under_skills_deliver(self) -> None:
        self.assertEqual(
            self.gate(None, changed=("README.md", "skills/deliver-old/SKILL.md", "docs/skills/deliver/x.md")),
            (0, "gate_check: not checked: no changed file is under skills/deliver/.\n", ""))

    def test_silent_when_the_base_has_no_skills_deliver(self) -> None:
        self.assertEqual(
            self.gate(None, base_rev="bare"),
            (0, "gate_check: not checked: the base has no skills/deliver/.\n", ""))

    def test_refuses_a_body_with_no_block(self) -> None:
        self.assertEqual(
            self.gate("## Summary\n\nchange kind: repair\n"),
            (1, "", "gate_check: refused: the PR body has no ## Change kind heading.\n"))

    def with_block(self, *lines: str) -> tuple[int, str, str]:
        """Run the gate on a body whose block holds these lines; expect a refusal."""
        return self.gate("## Summary\n\nx\n\n## Change kind\n\n" + "\n".join(lines) + "\n\n## Evidence\n\ny\n")

    def test_refuses_a_block_with_no_kind(self) -> None:
        self.assertEqual(
            self.with_block("repair: tests.test_x fails at abc1234, passes at def5678"),
            (1, "", "gate_check: refused: the ## Change kind block has no kind: line.\n"))

    def test_refuses_two_kinds(self) -> None:
        self.assertEqual(
            self.with_block("kind: repair | code change"),
            (1, "", 'gate_check: refused: kind: "repair | code change" is not one of repair, code change, '
                    "text rule, step or figure change.\n"))

    def test_repair_passes_with_its_line(self) -> None:
        self.assertEqual(
            self.with_block("kind: repair", "repair: tests.test_x fails at abc1234, passes at def5678"),
            (0, "gate_check: passed: repair.\n", ""))

    def test_repair_refused_without_its_line(self) -> None:
        self.assertEqual(
            self.with_block("kind: repair"),
            (1, "", "gate_check: refused: a repair needs a repair: line.\n"))


    def test_repair_refused_when_its_line_cannot_be_read(self) -> None:
        self.assertEqual(
            self.with_block("kind: repair", "repair: tests.test_x failed before and passes now"),
            (1, "", 'gate_check: refused: cannot read "repair: tests.test_x failed before and passes now"; '
                    "write it as repair: <test> fails at <sha>, passes at <sha>.\n"))

    def test_repair_tie_fails_and_passes_at_one_commit(self) -> None:
        self.assertEqual(
            self.with_block("kind: repair", "repair: tests.test_x fails at abc1234, passes at abc1234def"),
            (1, "", "gate_check: refused: repair: the test fails and passes at the same commit.\n"))

    def test_code_change_passes_when_every_test_passes(self) -> None:
        self.assertEqual(
            self.with_block("kind: code change", "tests: 12 of 12 pass"),
            (0, "gate_check: passed: code change.\n", ""))

    def test_code_change_refused_when_a_test_fails(self) -> None:
        self.assertEqual(
            self.with_block("kind: code change", "tests: 11 of 12 pass"),
            (1, "", "gate_check: refused: tests: 1 of 12 fail.\n"))

    def test_code_change_refused_with_no_test(self) -> None:
        self.assertEqual(
            self.with_block("kind: code change", "tests: 0 of 0 pass"),
            (1, "", "gate_check: refused: tests: no test ran.\n"))

    def test_code_change_refused_without_its_line(self) -> None:
        self.assertEqual(
            self.with_block("kind: code change", "repair: tests.test_x fails at abc1234, passes at def5678"),
            (1, "", "gate_check: refused: a code change needs a tests: line.\n"))


    TEXT_RULE = ("kind: text rule", "lesson: #12, 3 sightings",
                 "cases: 3 replayed; failed without the rule 2; failed with it 0",
                 "harm test: 3 of 3 right, was 3; median tokens +10%")

    def text_rule(self, **lines: str) -> tuple[int, str, str]:
        """The gate on a passing text rule block with the named lines replaced."""
        given = {line.split(":")[0].replace(" ", "_"): line for line in self.TEXT_RULE}
        given.update({key: f"{key.replace('_', ' ')}: {value}" for key, value in lines.items()})
        return self.with_block(*given.values())

    def test_text_rule_passes_with_its_lines(self) -> None:
        self.assertEqual(self.text_rule(), (0, "gate_check: passed: text rule.\n", ""))

    def test_text_rule_refused_without_its_harm_test(self) -> None:
        self.assertEqual(
            self.with_block(*self.TEXT_RULE[:3]),
            (1, "", "gate_check: refused: a text rule needs a harm test: line.\n"))

    def test_harm_test_refused_with_one_fewer_right(self) -> None:
        self.assertEqual(
            self.text_rule(harm_test="2 of 3 right, was 3; median tokens -5%"),
            (1, "", "gate_check: refused: harm test: 2 right, fewer than the 3 the current version got.\n"))

    def test_harm_test_refused_when_median_tokens_rise_over_ten_percent(self) -> None:
        self.assertEqual(
            self.text_rule(harm_test="3 of 3 right, was 2; median tokens +10.5%"),
            (1, "", "gate_check: refused: harm test: median tokens +10.5%, more than +10%.\n"))

    def test_harm_test_refused_on_other_than_the_buckets_three_tickets(self) -> None:
        self.assertEqual(
            self.text_rule(harm_test="10 of 10 right, was 10; median tokens +4%"),
            (1, "", "gate_check: refused: harm test: 10 tickets replayed; the line is the bucket's 3.\n"))

    def test_harm_test_refused_when_its_counts_cannot_be_read(self) -> None:
        self.assertEqual(
            self.text_rule(harm_test="3 of 3 right, was 3; median tokens about the same"),
            (1, "", 'gate_check: refused: cannot read "harm test: 3 of 3 right, was 3; median tokens about the same"; '
                    "write it as harm test: <n> of <n> right, was <n>; median tokens <+n or -n>%.\n"))

    def test_harm_test_refused_when_right_exceeds_the_tickets(self) -> None:
        self.assertEqual(
            self.text_rule(harm_test="4 of 3 right, was 3; median tokens +1%"),
            (1, "", "gate_check: refused: harm test: 4 right of 3 tickets.\n"))

    def test_cases_tie_fails_when_the_failure_never_reproduced_without_the_rule(self) -> None:
        self.assertEqual(
            self.text_rule(cases="3 replayed; failed without the rule 0; failed with it 0"),
            (1, "", "gate_check: refused: cases: the failure never reproduced without the rule.\n"))

    def test_cases_refused_when_the_failure_comes_back_with_the_rule(self) -> None:
        self.assertEqual(
            self.text_rule(cases="3 replayed; failed without the rule 3; failed with it 1"),
            (1, "", "gate_check: refused: cases: the failure came back with the rule in 1 of 3.\n"))

    def test_lesson_refused_with_no_sighting(self) -> None:
        self.assertEqual(
            self.text_rule(lesson="#12, 0 sightings"),
            (1, "", "gate_check: refused: lesson: no sighting.\n"))

    def test_step_change_passes_with_more_right(self) -> None:
        self.assertEqual(
            self.with_block("kind: step or figure change", "replay: 12 of 12 right, was 11; tokens +5%"),
            (0, "gate_check: passed: step or figure change.\n", ""))

    def test_step_change_passes_with_as_many_right_and_fewer_tokens(self) -> None:
        self.assertEqual(
            self.with_block("kind: step or figure change", "replay: 11 of 12 right, was 11; tokens -3%"),
            (0, "gate_check: passed: step or figure change.\n", ""))

    def test_step_change_refused_with_one_fewer_right(self) -> None:
        self.assertEqual(
            self.with_block("kind: step or figure change", "replay: 10 of 12 right, was 11; tokens -20%"),
            (1, "", "gate_check: refused: replay: 10 right, fewer than the 11 the current version got.\n"))

    def test_step_change_tie_fails(self) -> None:
        self.assertEqual(
            self.with_block("kind: step or figure change", "replay: 11 of 12 right, was 11; tokens 0%"),
            (1, "", "gate_check: refused: replay: a tie, 11 right as before and tokens 0%, not fewer.\n"))

    def test_step_change_refused_on_other_than_the_sets_twelve_tickets(self) -> None:
        self.assertEqual(
            self.with_block("kind: step or figure change", "replay: 27 of 30 right, was 26; tokens -12%"),
            (1, "", "gate_check: refused: replay: 30 tickets replayed; the line is the set's 12.\n"))

    def test_step_change_refused_without_its_line(self) -> None:
        self.assertEqual(
            self.with_block("kind: step or figure change", "tests: 3 of 3 pass"),
            (1, "", "gate_check: refused: a step or figure change needs a replay: line.\n"))


    def test_no_line_waives_the_check(self) -> None:
        self.assertEqual(
            self.with_block("kind: text rule", "waiver: the owner accepts it", "waive: yes"),
            (1, "", "gate_check: refused: a text rule needs a lesson: line.\n"))

    def test_refuses_a_line_given_twice(self) -> None:
        self.assertEqual(
            self.with_block("kind: code change", "tests: 0 of 1 pass", "tests: 1 of 1 pass"),
            (1, "", "gate_check: refused: the ## Change kind block has tests: twice.\n"))

    def test_reads_a_fenced_block_with_crlf_line_ends(self) -> None:
        body = "## Change kind\r\n\r\n```\r\nkind: code change\r\ntests: 4 of 4 pass\r\n```\r\n"
        self.assertEqual(self.gate(body), (0, "gate_check: passed: code change.\n", ""))


if __name__ == "__main__":
    unittest.main()
