"""deliver.py brief: the reviewer's brief, its record, and each refusal.

Each test runs deliver.py brief at its command line in its own worktree of one shared throwaway
world from tests/deliver_kit.py, against the bare remote and the stand-in gh, with the records
written by hand. The world's upstream skills are the kit's stand-ins.

    python3 -m unittest tests.test_deliver_brief
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

URL = "https://github.com/owner/repo/pull/12"
AT = "2026-11-28T10:00:00Z"
REQUEST = "Source: conversation\n\nMake add() add.\n"
REQUIREMENTS = "- R1: add(2, 2) is 4\n"
SUMMARY = "Secret author's account: add now adds.\n"
PLAN = """\
| # | Requirement | Proof |
|---|---|---|
| R1 | add(2, 2) is 4 | `echo ok` |
| R2 | The README is unchanged | review: README |

door: two-way, one function; nothing deploys on merge
"""


class Brief(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        cls.skills = cls.world.install_upstream()
        cls.plugin = cls.world.root / "plugin"
        cls.common = Path(cls.world.git(cls.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        cls.base = cls.world.git(cls.world.work, "rev-parse", "HEAD")

    def branch(self, name: str, harness: str = "claude-code", pr: bool = True, passed: bool = True,
               requirements: bool = True) -> tuple[Path, str]:
        """A worktree on a new branch with one commit, a run mark, its saved texts, a pass and a PR."""
        checkout = self.world.worktree(name.replace("/", "-"), name)
        head = self.world.commit(checkout, "calc.py", "def add(a, b):\n    return a + b\n", "feat: add adds")
        self.world.write_mark(checkout, branch=name)
        folder = self.folder(name)
        folder.mkdir(parents=True)
        texts = {"request": REQUEST, "summary": SUMMARY, "plan": PLAN}
        if requirements:
            texts["requirements"] = REQUIREMENTS
        for kind, text in texts.items():
            (folder / f"{kind}.md").write_text(text, encoding="utf-8")
        self.add(name, "preflight", run="run-1", result="pass", stops=[], warnings=[], harness=harness)
        if passed:
            self.check(name, "echo ok", head)
        self.check(name, "echo other", head, exit=1)
        if pr:
            self.add(name, "pr", number=12, url=URL)
        self.on_github(head)
        return checkout, head

    def folder(self, branch: str) -> Path:
        return self.common / "deliver" / "branches" / branch

    def add(self, branch: str, event: str, **fields: object) -> None:
        with (self.folder(branch) / "records.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, "at": AT, **fields}) + "\n")

    def check(self, branch: str, command: str, commit: str, exit: int = 0) -> None:
        checks = self.folder(branch) / "checks"
        checks.mkdir(exist_ok=True)
        name = f"checks/{len(list(checks.iterdir())) + 1}.txt"
        (self.folder(branch) / name).write_text("ok\n", encoding="utf-8")
        self.add(branch, "check", command=command, exit=exit, output=name, commit=commit, selected_nothing=False,
                 slot_wait_s=0.0)

    def on_github(self, head: str) -> None:
        """The stand-in gh answers `gh pr view` with `head` as the PR's head, and nothing else."""
        deliver_kit.reset_gh(self.world)
        self.world.gh_answer(["pr", "view"], json.dumps({"headRefOid": head, "baseRefName": "main"}))

    def brief(self, checkout: Path, *args: str):
        return self.world.deliver("brief", *args, cwd=checkout)

    def assert_ends(self, result, code: int, stdout: str):
        self.assertEqual((result.returncode, result.stdout), (code, stdout), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def briefs(self, branch: str) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "at"} for r in self.world.records(branch) if r["event"] == "brief"]

    def assert_refused(self, checkout: Path, branch: str, stdout: str, role: str = "requirements",
                       args: tuple[str, ...] = ()):
        self.assert_ends(self.brief(checkout, *(args or (role, "--model", "sonnet"))), 10, stdout)
        self.assertEqual(self.briefs(branch), [])
        self.assertFalse((self.folder(branch) / "briefs").exists())

    def test_writes_the_requirements_brief_and_prints_only_its_line(self):
        checkout, head = self.branch("feat/requirements")
        result = self.brief(checkout, "requirements", "--model", "sonnet")
        path = self.folder("feat/requirements") / "briefs" / "requirements-0.md"
        self.assert_ends(result, 0, f"Read {path} and follow it.\n")
        deliver = self.plugin / "scripts" / "deliver.py"
        self.assertEqual(path.read_text(encoding="utf-8"), f"""\
role: deliver-requirements-reviewer, defined in {self.plugin}/agents/deliver-requirements-reviewer.md
review skill: {self.skills["code-review"]}/SKILL.md
deliver folder: {self.plugin}
fixed point: {self.base}
review target: {head}, pushed
saved check output: {self.folder("feat/requirements")}/checks/1.txt
requirements source: the text below and nothing else

## Request

{REQUEST.rstrip()}

## Requirements

{REQUIREMENTS.rstrip()}

## Check plan

{PLAN.rstrip()}

## Report

Your final message is the report: one line per requirement of the check plan, then one line per finding, and nothing else. Blank lines are allowed.

R1: met | not met | cannot tell: <check or file:line>
F1: <file:line or R<n>>: <what is wrong>. Evidence: <failing command and output | rule or requirement broken | none>

Run any command that proves a finding as `uv run --python 3.13 --no-project {deliver} check -- <command>`, or with python3 when uv is missing, so that its output is saved.
Write no file.
Start no agent.
Never run `deliver.py merge`.
Do both of the skill's readings yourself, and start no helper for them.
""")
        self.assertEqual(self.briefs("feat/requirements"), [{
            "event": "brief", "role": "requirements", "round": 0, "model": "sonnet", "effort": "high", "commit": head,
            "path": "briefs/requirements-0.md", "fixed_point": self.base}])
        self.assertEqual(self.world.git(checkout, "status", "--porcelain"), "")
        self.assertEqual([c["args"] for c in self.world.gh_calls()],
                         [["pr", "view", "12", "--json", "headRefOid,baseRefName"]])

    def test_the_defect_brief_names_ponytail_review_and_asks_for_finding_lines_only(self):
        checkout, head = self.branch("feat/defect", requirements=False)
        result = self.brief(checkout, "defect", "--model", "opus")
        path = self.folder("feat/defect") / "briefs" / "defect-0.md"
        self.assert_ends(result, 0, f"Read {path} and follow it.\n")
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(
            f"role: deliver-defect-reviewer, defined in {self.plugin}/agents/deliver-defect-reviewer.md\n"
            f"review skill: {self.skills['ponytail-review']}/SKILL.md\n"))
        self.assertIn("\n## Report\n\nYour final message is the report: one line per finding, and nothing else. "
                      "Blank lines are allowed.\n\nF1: <file:line or R<n>>:", text)
        self.assertTrue(text.endswith("Never run `deliver.py merge`.\n"
                                      "Follow ponytail-review as written, and write finding lines only.\n"))
        for absent in ("R1: met |", "readings", "## Requirements\n", SUMMARY.strip(), "## Summary"):
            self.assertNotIn(absent, text)
        self.assertEqual(self.briefs("feat/defect")[0]["role"], "defect")

    def test_the_effort_follows_the_preflight_harness_and_session_is_a_model(self):
        for harness, effort in (("codex", "high"), ("cortex-code", "high, not applied"),
                                ("cursor", "high, not applied"), ("antigravity", "high, not applied")):
            with self.subTest(harness):
                branch = f"feat/effort-{harness}"
                checkout, _ = self.branch(branch, harness=harness)
                self.assertEqual(self.brief(checkout, "requirements", "--model", "session").returncode, 0)
                record = self.briefs(branch)[0]
                self.assertEqual((record["model"], record["effort"]), ("session", effort))

    def test_a_usage_error_names_the_roles(self):
        checkout, _ = self.branch("feat/usage")
        for args in ((), ("requirements",), ("callback", "--model", "x"), ("defect", "--modle", "x"),
                     ("defect", "--model", ""), ("callback",), ("callback", "author"), ("callback", "defect", "x")):
            with self.subTest(args):
                result = self.brief(checkout, *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("brief takes a role, one of requirements, defect, and --model <id>, or callback and a "
                              "role", result.stderr)

    def test_brief_no_mark(self):
        result = self.world.deliver("brief", "requirements", "--model", "sonnet")
        self.assert_ends(result, 10, "REFUSED brief.no-mark: no run mark in this checkout, so no run is in "
                                     "progress here\nNext: deliver.py start\n")

    def test_brief_no_pr(self):
        checkout, _ = self.branch("feat/no-pr", pr=False)
        self.assert_refused(checkout, "feat/no-pr", "REFUSED brief.no-pr: the records of feat/no-pr hold no PR\n"
                                                    "Next: deliver.py pr\n")
        self.assertEqual(self.world.gh_calls(), [])

    def test_brief_not_pushed(self):
        checkout, head = self.branch("feat/not-pushed")
        self.on_github("a" * 40)
        self.assert_refused(checkout, "feat/not-pushed",
                            f"REFUSED brief.not-pushed: PR #12's head on GitHub is aaaaaaa, not the local HEAD "
                            f"{head[:7]}\nNext: deliver.py pr\n")

    def test_brief_no_pass(self):
        checkout, head = self.branch("feat/no-pass", passed=False)
        self.assert_refused(checkout, "feat/no-pass",
                            f"REFUSED brief.no-pass: `echo ok` has no counted pass on the head commit {head[:7]}\n"
                            "Next: deliver.py check -- 'echo ok'\n")

    def test_brief_unreadable(self):
        for case, text in (("no table", "door: two-way, one function\n"), ("not saved", None)):
            with self.subTest(case):
                branch = f"feat/unreadable-{case.replace(' ', '-')}"
                checkout, _ = self.branch(branch)
                plan = self.folder(branch) / "plan.md"
                if text is None:
                    plan.unlink()
                else:
                    plan.write_text(text, encoding="utf-8")
                result = self.brief(checkout, "requirements", "--model", "sonnet")
                self.assertEqual(result.returncode, 10, result.stderr)
                self.assertTrue(result.stdout.startswith("REFUSED brief.unreadable: the saved plan.md cannot be read: "))
                self.assertTrue(result.stdout.endswith("\nNext: rewrite .deliver/plan.md, then deliver.py save plan\n"))
                self.assertEqual(self.briefs(branch), [])
                self.assertFalse((self.folder(branch) / "briefs").exists())

    def test_brief_bad_settings(self):
        checkout, _ = self.branch("feat/bad-settings")
        (checkout / "docs" / "agents").mkdir(parents=True)
        (checkout / "docs" / "agents" / "stack.toml").write_text("check_command = [\n", encoding="utf-8")
        result = self.brief(checkout, "defect", "--model", "opus")
        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertTrue(result.stdout.startswith(
            "REFUSED brief.bad-settings: the stack settings cannot be read: docs/agents/stack.toml is not TOML: "))
        self.assertTrue(result.stdout.endswith(
            "\nNext: fix docs/agents/stack.toml, then deliver.py brief defect --model opus\n"))
        self.assertEqual(self.briefs("feat/bad-settings"), [])

    def test_brief_no_review_skill(self):
        checkout, _ = self.branch("feat/no-skill")
        folder = self.skills["ponytail-review"]
        moved = folder.with_name("ponytail-review-away")
        folder.rename(moved)
        self.addCleanup(moved.rename, folder)
        self.assert_refused(checkout, "feat/no-skill",
                            "REFUSED brief.no-review-skill: the review skill ponytail-review is not installed, so "
                            "the brief cannot name its path\n"
                            "Next: install ponytail-review, then deliver.py brief defect --model sonnet\n", role="defect")


    def reviewed(self, name: str) -> tuple[Path, str, str]:
        """A branch whose defect review of its first commit is saved, then a fix commit with a pass, pushed."""
        checkout, read = self.branch(name)
        for role, model, finding in (
                ("defect", "opus", {"where": "calc.py:2", "text": "add ignores b", "evidence": "`echo ok` fails"}),
                ("requirements", "sonnet", {"where": "R1", "text": "not met", "evidence": "R1 not met"})):
            self.add(name, "brief", role=role, round=0, model=model, effort="high", commit=read,
                     path=f"briefs/{role}-0.md", fixed_point=self.base)
            number = f"F{len([r for r in self.world.records(name) if r['event'] == 'review']) + 1}"
            self.add(name, "review", role=role, round=0, commit=read, file=f"reviews/{role}-0.md", answers={},
                     findings=[{"number": number, "reviewer": role, **finding, "scope": "in", "proven": True}])
        fix = self.world.commit(checkout, "calc.py", "def add(a, b):\n    return b + a\n", "fix: add uses b")
        self.check(name, "echo ok", fix)
        self.on_github(fix)
        return checkout, read, fix

    def test_writes_the_callback_brief_with_the_fix_and_the_findings_on_the_review_model(self):
        checkout, read, fix = self.reviewed("feat/callback")
        folder = self.folder("feat/callback")
        result = self.brief(checkout, "callback", "defect")
        path = folder / "briefs" / "defect-1.md"
        self.assert_ends(result, 0, f"Read {path} and follow it.\n")
        deliver = self.plugin / "scripts" / "deliver.py"
        self.assertEqual(path.read_text(encoding="utf-8"), f"""\
role: deliver-defect-reviewer, defined in {self.plugin}/agents/deliver-defect-reviewer.md
review skill: {self.skills["ponytail-review"]}/SKILL.md
deliver folder: {self.plugin}
fixed point: {self.base}
review target: {fix}, pushed
saved check output: {folder}/checks/3.txt
requirements source: the text below and nothing else

## Request

{REQUEST.rstrip()}

## Requirements

{REQUIREMENTS.rstrip()}

## Check plan

{PLAN.rstrip()}

## Commits since your last read

{fix} fix: add uses b

## Your findings

F1: calc.py:2: add ignores b. Evidence: `echo ok` fails

## Report

Your final message is the report: one line for each of your findings above, then one line per new finding on a line the commits above changed, and nothing else. Blank lines are allowed.

F1: resolved | not resolved
F1: <file:line or R<n>>: <what is wrong>. Evidence: <failing command and output | rule or requirement broken | none>

Run any command that proves a finding as `uv run --python 3.13 --no-project {deliver} check -- <command>`, or with python3 when uv is missing, so that its output is saved.
Write no file.
Start no agent.
Never run `deliver.py merge`.
Judge whether the commits above fix each of your findings, and read only the lines they changed.
""")
        self.assertEqual(self.briefs("feat/callback")[-1], {
            "event": "brief", "role": "defect", "round": 1, "model": "opus", "effort": "high", "commit": fix,
            "path": "briefs/defect-1.md", "fixed_point": self.base})
        self.assertEqual(self.world.git(checkout, "status", "--porcelain"), "")

    def test_a_callback_of_another_role_on_the_same_fix_joins_its_round(self):
        checkout, _, fix = self.reviewed("feat/join")
        self.assertEqual(self.brief(checkout, "callback", "defect").returncode, 0)
        result = self.brief(checkout, "callback", "requirements")
        self.assert_ends(result, 0, f"Read {self.folder('feat/join')}/briefs/requirements-1.md and follow it.\n")
        self.assertEqual([(r["role"], r["round"], r["model"]) for r in self.briefs("feat/join")[2:]],
                         [("defect", 1, "opus"), ("requirements", 1, "sonnet")])
        text = (self.folder("feat/join") / "briefs" / "requirements-1.md").read_text(encoding="utf-8")
        self.assertIn("\n## Your findings\n\nF2: R1: not met. Evidence: R1 not met\n\n## Report\n", text)

    def test_a_callback_for_a_third_fix_round_is_handed_to_the_owner_and_writes_nothing(self):
        checkout, _, fix = self.reviewed("feat/third")
        self.add("feat/third", "brief", role="defect", round=1, model="opus", effort="high", commit=fix,
                 path="briefs/defect-1.md", fixed_point=self.base)
        self.add("feat/third", "review", role="defect", round=1, commit=fix, file="reviews/defect-1.md",
                 resolutions={"F1": "not resolved"}, findings=[])
        second = self.world.commit(checkout, "calc.py", "def add(a, b):\n    return a + b + 0\n", "fix: again")
        self.add("feat/third", "brief", role="requirements", round=2, model="sonnet", effort="high", commit=second,
                 path="briefs/requirements-2.md", fixed_point=self.base)
        self.add("feat/third", "review", role="requirements", round=2, commit=second, file="reviews/requirements-2.md",
                 resolutions={"F2": "not resolved"}, findings=[])
        self.world.commit(checkout, "calc.py", "def add(a, b):\n    return sum((a, b))\n", "fix: once more")
        before = self.world.records("feat/third")
        deliver_kit.reset_gh(self.world)
        self.assert_ends(self.brief(checkout, "callback", "defect"), 20, (
            "This call-back would start a third fix round, and a run takes two at most. The PR stays draft and goes "
            "to the owner with its open findings: run deliver.py ready, then deliver.py finish.\n"))
        self.assertEqual(self.world.records("feat/third"), before)
        self.assertFalse((self.folder("feat/third") / "briefs").exists())
        self.assertEqual(self.world.gh_calls(), [])

    def test_a_callback_brief_whose_report_was_never_saved_uses_up_no_round(self):
        checkout, _, fix = self.reviewed("feat/unsaved")
        self.assertEqual(self.brief(checkout, "callback", "defect").returncode, 0)
        again = self.world.commit(checkout, "calc.py", "def add(a, b):\n    return a + b + 0\n", "fix: again")
        self.check("feat/unsaved", "echo ok", again)
        self.on_github(again)
        self.assert_ends(self.brief(checkout, "callback", "defect"), 0,
                         f"Read {self.folder('feat/unsaved')}/briefs/defect-1.md and follow it.\n")
        self.assertEqual([(r["round"], r["commit"]) for r in self.briefs("feat/unsaved")[2:]], [(1, fix), (1, again)])

    def test_brief_no_review(self):
        checkout, _ = self.branch("feat/no-review")
        self.assert_refused(checkout, "feat/no-review", (
            "REFUSED brief.no-review: no defect review is saved, so there is nothing to call back\n"
            "Next: deliver.py brief defect --model <id>\n"), args=("callback", "defect"))

    def test_brief_no_fix(self):
        checkout, read, _ = self.reviewed("feat/no-fix")
        self.world.git(checkout, "reset", "-q", "--hard", read)
        before = self.briefs("feat/no-fix")
        self.assert_ends(self.brief(checkout, "callback", "defect"), 10, (
            f"REFUSED brief.no-fix: HEAD {read[:7]} is the commit the defect reviewer last read, so there is no fix "
            "to call back\n"
            "Next: commit the fix, run its checks and deliver.py pr, then deliver.py brief callback defect\n"))
        self.assertEqual(self.briefs("feat/no-fix"), before)


if __name__ == "__main__":
    unittest.main()
