"""deliver.py ready: the small test, the description with its measurement block, and each refusal.

Each test runs deliver.py ready at its command line in its own worktree of one shared throwaway
world, against the bare remote and the stand-in gh of tests/deliver_kit.py, with the records
written by hand. The world runs a copy of the plugin whose scan.py is a stand-in: its
`start_background` appends one line to `scan-starts.txt` in the world, so no real scan starts.

    python3 -m unittest tests.test_deliver_ready
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402
from test_deliver_render import SUMMARY, TICKET_REQUEST  # noqa: E402

render = deliver_kit.load("render")
deps = deliver_kit.load("deps")
URL = "https://github.com/owner/repo/pull/12"
VERSION = json.loads((deliver_kit.SCRIPTS.parent / "plugin.json").read_text(encoding="utf-8"))["version"]
AT = "2026-11-27T19:00:00Z"
PLAN = """\
| # | Requirement | Proof |
|---|---|---|
| R1 | The flag prints JSON | `echo ok` |
| R2 | The README is unchanged | no check exists, meaning unchanged |

door: two-way, a new flag; nothing deploys on merge
"""
QUERY_PLAN = PLAN.replace("| R2 |", "| R2 | Rows drop by two | query `echo rows`: 120 before, 118 after |\n| R3 |")
WARNING = "no docs/agents/stack.toml: every stack setting has its default"
SCAN_STUB = """\
import os
from pathlib import Path


def start_background(harness=None, run=None):
    with (Path(os.environ["DELIVER_KIT_WORLD"]) / "scan-starts.txt").open("a") as f:
        f.write("start\\n")
    return True
"""


class Ready(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        folders = cls.world.install_upstream()
        (cls.world.root / "plugin" / "scripts" / "scan.py").write_text(SCAN_STUB, encoding="utf-8")
        cls.hashes = {name: deps.folder_hash(folders[name]) for name in ("code-review", "ponytail-review")}
        cls.common = Path(cls.world.git(cls.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))

    def setUp(self):
        deliver_kit.reset_gh(self.world)
        (self.world.root / "scan-starts.txt").unlink(missing_ok=True)
        self.world.gh_answer(["repo", "view"], "main\n")
        self.world.gh_answer(["pr", "edit"])
        self.world.gh_answer(["pr", "ready"])

    def branch(self, name: str, plan: str = PLAN, preflight: bool = True, pr: bool = True,
               files: dict[str, str] | None = None) -> tuple[Path, str]:
        """A worktree on a new branch with one commit, a run mark and its saved texts; returns it and HEAD."""
        checkout = self.world.worktree(name.replace("/", "-"), name)
        for path, text in (files or {"flag.txt": "x\n"}).items():
            head = self.world.commit(checkout, path, text, f"feat: {path}")
        self.world.write_mark(checkout, branch=name)
        folder = self.folder(name)
        folder.mkdir(parents=True)
        for kind, text in {"request": TICKET_REQUEST, "summary": SUMMARY, "plan": plan}.items():
            (folder / f"{kind}.md").write_text(text, encoding="utf-8")
        if preflight:
            self.add(name, "preflight", run="run-1", result="pass", stops=[], warnings=[WARNING],
                     guard_probe="seen", permission_mode="default", harness="claude-code")
        if pr:
            self.add(name, "pr", number=12, url=URL)
        return checkout, head

    def folder(self, branch: str) -> Path:
        return self.common / "deliver" / "branches" / branch

    def add(self, branch: str, event: str, at: str = AT, **fields: object) -> None:
        with (self.folder(branch) / "records.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, "at": at, **fields}) + "\n")

    def check(self, branch: str, command: str, commit: str | None, exit: int = 0, selected_nothing: bool = False,
              output: str = "ok 1\n", slot_wait_s: float = 0.0, at: str = AT) -> None:
        checks = self.folder(branch) / "checks"
        checks.mkdir(exist_ok=True)
        name = f"checks/{len(list(checks.iterdir())) + 1}.txt"
        (self.folder(branch) / name).write_text(output, encoding="utf-8")
        self.add(branch, "check", at=at, command=command, exit=exit, output=name, commit=commit,
                 selected_nothing=selected_nothing, slot_wait_s=slot_wait_s)

    def on_github(self, head: str) -> None:
        """The stand-in gh answers `gh pr view` with `head` as the PR's head commit."""
        self.world.gh_answer(["pr", "view"], head + "\n")

    def ready(self, checkout: Path):
        tmp = self.world.root / "tmp"
        tmp.mkdir(exist_ok=True)
        return self.world.deliver("ready", cwd=checkout, TMPDIR=str(tmp))

    def assert_ends(self, result, code: int, stdout: str):
        self.assertEqual((result.returncode, result.stdout), (code, stdout), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def calls(self) -> list[list[str]]:
        return [call["args"] for call in self.world.gh_calls()]

    def scan_starts(self) -> int:
        path = self.world.root / "scan-starts.txt"
        return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0

    def ready_records(self, branch: str) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "at"} for r in self.world.records(branch) if r["event"] == "ready"]

    def assert_refused(self, checkout: Path, branch: str, stdout: str, calls: list[list[str]] | None = None):
        self.assert_ends(self.ready(checkout), 10, stdout)
        self.assertEqual(self.calls(), calls or [])
        self.assertEqual((self.ready_records(branch), self.scan_starts()), ([], 0))

    def test_marks_the_pr_ready_after_rendering_the_description(self):
        checkout, head = self.branch("feat/pass")
        self.check("feat/pass", "echo ok", head, slot_wait_s=1.5)
        self.check("feat/pass", "echo ok", head, slot_wait_s=2.0)
        self.check("feat/pass", "echo old", None, slot_wait_s=9.0, at="2026-11-27T17:00:00Z")  # before the mark
        self.on_github(head)
        self.assert_ends(self.ready(checkout), 0, (
            "small edit: a two-way door, 1 line and a low blast radius.\n"
            f"Marked PR #12 ready: {URL}\n"))
        calls = self.world.gh_calls()
        body_file = calls[2]["args"][-1]
        self.assertEqual([c["args"] for c in calls], [
            ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
            ["pr", "view", "12", "--json", "headRefOid", "--jq", ".headRefOid"],
            ["pr", "edit", "12", "--body-file", body_file],
            ["pr", "ready", "12"],
        ])
        self.assertFalse(Path(body_file).exists())
        block = (
            "<details><summary>Measurement</summary>\n\n```text\n"
            f"version: {VERSION}\n"
            "path: small edit\n"
            "harness: claude-code\n"
            "small test: pass, 1 line, no critical path, no dependents command\n"
            "door: two-way\n"
            "roles: author\n"
            "findings: 0\n"
            "fix rounds: 0\n"
            "follow-ups: 0\n"
            "slot wait: 3.5s\n"
            f"review skills: code-review {self.hashes['code-review']}, ponytail-review {self.hashes['ponytail-review']}\n"
            f"preflight warnings: {WARNING}\n"
            "waiver: none\n"
            "merge: pending\n"
            "```\n\n</details>\n")
        body = calls[2]["body"]
        self.assertTrue(body.endswith("\n## Findings\n\nNo review: small edit.\n\n" + block), body)
        self.assertEqual(body.count("<details"), 1)
        self.assertIn("**Blast Radius:** low. 1 line, no critical path changed, and no dependents command is set\n",
                      body)
        self.assertIn("**Door:** two-way. A new flag; nothing deploys on merge\n", body)
        self.assertIn(f"- R1: pass at {head[:7]}\n", body)
        self.assertNotRegex(body, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        self.assertNotIn("session", body.lower())
        # merge.py in a process of its own: in a full run another skill's `render` is already imported.
        merged = subprocess.run(
            [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import merge; "
             "sys.stdout.write(merge.with_line(sys.stdin.read(), sys.argv[2]))",
             str(deliver_kit.SCRIPTS), "merge: squash at abc1234"],
            input=body, capture_output=True, text=True, check=True).stdout
        self.assertEqual(merged, body.replace("merge: pending\n", "merge: squash at abc1234\n"))
        self.assertEqual(self.ready_records("feat/pass"), [{
            "event": "ready", "commit": head, "result": "small edit",
            "small_test": {"lines": 1, "critical_paths": [], "dependents": None}, "door": "two-way", "door_paths": [],
        }])
        self.assertEqual(self.scan_starts(), 1)

    def test_ready_no_preflight(self):
        checkout, head = self.branch("feat/no-preflight", preflight=False)
        self.check("feat/no-preflight", "echo ok", head)
        self.add("feat/no-preflight", "preflight", run="run-0", result="pass")  # another run's pass
        refused = ("REFUSED ready.no-preflight: no passing preflight is saved for run run-1\n"
                   "Next: deliver.py preflight\n")
        self.assert_refused(checkout, "feat/no-preflight", refused)
        with self.subTest("a newer stop after the pass"):
            self.add("feat/no-preflight", "preflight", run="run-1", result="pass")
            self.add("feat/no-preflight", "preflight", run="run-1", result="stop", stops=["preflight.no-gh"])
            self.assert_refused(checkout, "feat/no-preflight", refused)

    def test_ready_drop_folder(self):
        checkout, head = self.branch("feat/drop")
        self.check("feat/drop", "echo ok", head)
        (checkout / ".deliver").mkdir()
        (checkout / ".deliver" / "summary.md").write_text("late\n", encoding="utf-8")
        (checkout / ".deliver" / "notes.txt").write_text("x\n", encoding="utf-8")
        self.assert_refused(checkout, "feat/drop", (
            "REFUSED ready.drop-folder: the drop folder .deliver/ still holds notes.txt, summary.md\n"
            "Next: move .deliver/notes.txt out of .deliver/, then deliver.py ready\n"))
        (checkout / ".deliver" / "notes.txt").unlink()
        self.assert_refused(checkout, "feat/drop", (
            "REFUSED ready.drop-folder: the drop folder .deliver/ still holds summary.md\n"
            "Next: deliver.py save summary\n"))

    def test_ready_no_pr(self):
        checkout, head = self.branch("feat/no-pr", pr=False)
        self.check("feat/no-pr", "echo ok", head)
        self.assert_refused(checkout, "feat/no-pr", (
            "REFUSED ready.no-pr: the records of feat/no-pr hold no PR\nNext: deliver.py pr\n"))

    def test_ready_unreadable(self):
        checkout, head = self.branch("feat/bad-plan", plan="| R1 | no table header | `echo ok` |\n")
        self.assert_refused(checkout, "feat/bad-plan", (
            "REFUSED ready.unreadable: the saved plan.md cannot be read: the plan needs one table headed "
            "| # | Requirement | Proof |, and it has 0\n"
            "Next: rewrite .deliver/plan.md, then deliver.py save plan\n"))

    def test_ready_bad_settings(self):
        checkout, head = self.branch("feat/bad-settings")
        self.check("feat/bad-settings", "echo ok", head)
        (checkout / "docs" / "agents").mkdir(parents=True)
        (checkout / "docs" / "agents" / "stack.toml").write_text("check_command = [\n", encoding="utf-8")
        result = self.ready(checkout)
        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertTrue(result.stdout.startswith(
            "REFUSED ready.bad-settings: the stack settings cannot be read: docs/agents/stack.toml is not TOML: "))
        self.assertTrue(result.stdout.endswith("\nNext: fix docs/agents/stack.toml, then deliver.py ready\n"))
        self.assertEqual((self.calls(), self.ready_records("feat/bad-settings")), ([], []))

    def test_ready_no_pass(self):
        """Only a check of the exact text, exit 0, selecting something, tied to the full HEAD counts (D2)."""
        checkout, head = self.branch("feat/match", files={"one.txt": "1\n"})
        parent = head
        head = self.world.commit(checkout, "flag.txt", "x\n", "feat: flag")
        refused = (f"REFUSED ready.no-pass: `echo ok` has no counted pass on the head commit {head[:7]}\n"
                   "Next: deliver.py check -- 'echo ok'\n")
        for case, fields in [
            ("extra whitespace", {"command": "echo  ok", "commit": head}),
            ("a trailing space", {"command": "echo ok ", "commit": head}),
            ("a prefix", {"command": "echo", "commit": head}),
            ("a longer command", {"command": "echo ok && true", "commit": head}),
            ("a pass at the parent commit", {"command": "echo ok", "commit": parent}),
            ("a short sha", {"command": "echo ok", "commit": head[:7]}),
            ("commit null", {"command": "echo ok", "commit": None}),
            ("exit non-zero", {"command": "echo ok", "commit": head, "exit": 1}),
            ("selected nothing", {"command": "echo ok", "commit": head, "selected_nothing": True}),
        ]:
            with self.subTest(case):
                self.check("feat/match", **fields)
                self.assert_refused(checkout, "feat/match", refused)
        with self.subTest("check_command is set and has no pass"):
            (checkout / "docs" / "agents").mkdir(parents=True)
            (checkout / "docs" / "agents" / "stack.toml").write_text('check_command = "make test"\n', encoding="utf-8")
            self.check("feat/match", "echo ok", head)
            self.check("feat/match", "make  test", head)
            self.assert_refused(checkout, "feat/match", (
                f"REFUSED ready.no-pass: `make test` has no counted pass on the head commit {head[:7]}\n"
                "Next: deliver.py check -- 'make test'\n"))
        with self.subTest("records of the exact commands count, one written by hand and one by deliver.py check"):
            self.check("feat/match", "make test", head)
            saved = self.world.deliver("check", "--", "echo ok", cwd=checkout)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.on_github(head)
            self.assertEqual(self.ready(checkout).returncode, 0)
            self.assertEqual(self.calls()[-1], ["pr", "ready", "12"])
            self.assertEqual(self.scan_starts(), 1)

    def test_ready_no_query_numbers(self):
        """A query proof needs a check ending in a number before the change and a counted one on HEAD."""
        view = ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]
        missing = "REFUSED ready.no-query-numbers: the query of R2, `echo rows`, has no saved {} numbers\n"
        after_only = "Next: deliver.py check -- 'echo rows'\n"
        for n, (case, before, after, refused) in enumerate([
            ("no numbers", None, None, "before and after"),
            ("a before run with no number in its output", "no rows\n", "118\n", "before"),
            ("before numbers only", "120\n", None, "after"),
            ("an after run with no number in its output", "120\n", "none\n", "after"),
            ("a digit in a message is no number", "client-v2: no result\n", "client-v2: no result\n",
             "before and after"),
            ("a number followed by more text", "120\nrows dropped\n", "118 rows\n", "before and after"),
            ("before and after numbers", "120\n", "118\n", None),
        ]):
            with self.subTest(case):
                self.setUp()
                branch = f"feat/query-{n}"
                checkout, head = self.branch(branch, plan=QUERY_PLAN)
                base = self.world.git(checkout, "merge-base", "origin/main", "HEAD")
                self.check(branch, "echo ok", head)
                if before is not None:
                    self.check(branch, "echo rows", base, output=before)
                if after is not None:
                    self.check(branch, "echo rows", head, output=after)
                if refused is None:
                    self.on_github(head)
                    self.assertEqual(self.ready(checkout).returncode, 0)
                    self.assertEqual(self.scan_starts(), 1)
                    continue
                fix = after_only if refused == "after" else (
                    f"Next: git switch --detach {base[:7]}, deliver.py check -- 'echo rows', git switch {branch}\n")
                self.assert_refused(checkout, branch, missing.format(refused) + fix, [view])

    def test_ready_bad_query(self):
        """A proof that names a query outside its code spans and is not one query proof is refused, never skipped."""
        view = ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]
        for n, proof in enumerate(["query `echo rows` against `orders`", "run the query `echo rows`: 120 then 118",
                                   "a query shows the rows drop"]):
            with self.subTest(proof):
                self.setUp()
                branch = f"feat/bad-query-{n}"
                checkout, head = self.branch(branch, plan=PLAN.replace("no check exists, meaning unchanged", proof))
                self.check(branch, "echo ok", head)
                self.assert_refused(checkout, branch, (
                    "REFUSED ready.bad-query: the proof of R2 names a query, and its query command cannot be read\n"
                    "Next: give R2 one query proof in .deliver/plan.md, then deliver.py save plan\n"), [view])

    def test_ready_stale_pr(self):
        """The PR's head on GitHub must be the HEAD ready tested, or nothing is written to the PR."""
        checkout, head = self.branch("feat/stale")
        pushed = self.world.git(checkout, "rev-parse", "HEAD~1")
        self.check("feat/stale", "echo ok", head)
        self.on_github(pushed)
        self.assert_refused(checkout, "feat/stale", (
            f"REFUSED ready.stale-pr: PR #12's head on GitHub is {pushed[:7]}, not the tested HEAD {head[:7]}\n"
            "Next: deliver.py pr\n"), [
            ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
            ["pr", "view", "12", "--json", "headRefOid", "--jq", ".headRefOid"]])

    def test_ready_needs_review(self):
        checkout, head = self.branch("feat/one-way", plan=PLAN.replace("door: two-way", "door: one-way"))
        self.check("feat/one-way", "echo ok", head)
        self.assert_ends(self.ready(checkout), 10,
                         "REFUSED ready.needs-review: this change needs a review: the plan's door is one-way\n")
        self.assertEqual(self.calls(), [["repo", "view", "--json", "defaultBranchRef", "--jq",
                                         ".defaultBranchRef.name"]])
        self.assertEqual(self.ready_records("feat/one-way"), [{
            "event": "ready", "commit": head, "result": "needs review",
            "small_test": {"lines": 1, "critical_paths": [], "dependents": None}, "door": "one-way", "door_paths": [],
        }])
        self.assertEqual(self.scan_starts(), 0)

    def test_ready_needs_review_when_the_dependents_command_prints_non_utf8(self):
        """D4: output that is not UTF-8 is a failed count, so a high blast radius, never a crash."""
        checkout, head = self.branch("feat/bytes")
        self.check("feat/bytes", "echo ok", head)
        (checkout / "docs" / "agents").mkdir(parents=True)
        (checkout / "docs" / "agents" / "stack.toml").write_text(
            "[small_edit]\ndependents_command = 'printf \"1\\n\\377\\n\"'\n", encoding="utf-8")
        self.assert_ends(self.ready(checkout), 10, (
            "REFUSED ready.needs-review: this change needs a review: high blast radius, the dependents command "
            "failed: its output is not UTF-8\n"))
        self.assertEqual(self.ready_records("feat/bytes")[0]["small_test"]["dependents"],
                         {"error": "its output is not UTF-8"})
        self.assertEqual(self.scan_starts(), 0)
        self.assertNotIn(["pr", "ready", "12"], self.calls())


if __name__ == "__main__":
    unittest.main()
