"""deliver.py start: the routes, the entry check, the fresh branch, resume, and each refusal.

The entry check and the grant line are pure functions, tested in this process. Everything else
runs `deliver.py start` at its command line in a throwaway world of tests/deliver_kit.py, with
its bare remote and stand-in gh; one test puts a spy check into preflight's list first.

    python3 -m unittest tests.test_deliver_start
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

entry_check = deliver_kit.load("entry_check")
start = deliver_kit.load("start")
MISSING = "warning: no docs/agents/stack.toml: every stack setting has its default"
GRANT = ("Run grant: push this branch, open and update its PR, mark it ready and merge it through the scripts, "
         "file follow-up tickets.")
PROBE = "Next: run gh pr merge --deliver-guard-probe, which the guard refuses, then deliver.py preflight"
BODY = "## What to build\n\nAdd a --json flag.\n\n## Acceptance criteria\n\n- [ ] it parses\n- [ ] the help names it\n"
REPO_VIEW = ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]
TREE = "Source: working tree, requirements written from the diff\n"
SPY = """\
import sys
sys.path.insert(0, sys.argv[1])
import deliver, preflight
def spy(ctx):
    print("mark seen by preflight: " + (ctx.run.git_dir / "deliver-mark.json").read_text(encoding="utf-8"))
preflight.CHECKS.insert(0, spy)
sys.exit(deliver.main(sys.argv[2:]))
"""


class Start(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.work = self.world.work
        self.git_dir = self.work / ".git"
        self.world.gh_answer(["repo", "view"], "main\n")

    def issue(self, number: int, body: str = BODY, comments: tuple[str, ...] = ()) -> None:
        self.world.gh_answer(["issue", "view", str(number)], json.dumps(
            {"title": "A ticket", "body": body, "comments": [{"author": {"login": "a"}, "body": c} for c in comments]}))

    def merged(self, branch: str, prs: list[dict]) -> None:
        self.world.gh_answer(["pr", "list", "--head", branch, "--state", "merged"], json.dumps(prs))

    def advance_origin(self, name: str = "upstream.txt", content: str = "new\n") -> str:
        """Push a commit to origin's main from another clone; the work clone has not fetched it."""
        other = self.world.root / "other"
        if not other.exists():
            self.world.git(self.world.root, "clone", "-q", str(self.world.origin), str(other))
        tip = self.world.commit(other, name, content, "feat: upstream work")
        self.world.git(other, "push", "-q", "origin", "HEAD:refs/heads/main")
        return tip

    def mark(self) -> dict | None:
        path = self.git_dir / "deliver-mark.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def folder(self, branch: str) -> Path:
        return self.git_dir / "deliver" / "branches" / branch

    def branch(self) -> str:
        return self.world.git(self.work, "branch", "--show-current")

    def calls(self) -> list[list[str]]:
        return [call["args"] for call in self.world.gh_calls()]

    def excluded(self) -> list[str]:
        path = self.git_dir / "info" / "exclude"
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line == ".deliver/"] \
            if path.exists() else []

    def without_at(self, records: list[dict]) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "at"} for r in records]

    def assert_ends(self, result, code: int, stdout: str) -> None:
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, ""))

    def assert_nothing_written(self, branch: str = "main") -> None:
        self.assertIsNone(self.mark())
        self.assertEqual(self.branch(), branch)
        self.assertEqual(self.excluded(), [])
        self.assertFalse((self.git_dir / "deliver").exists())
        self.assertEqual(self.world.git(self.work, "branch", "--list", "deliver/*"), "")

    def started(self, result) -> tuple[str, str]:
        """The run id and branch of the first line, `Started run <id> on branch <branch>.`."""
        found = re.match(r"Started run ([0-9a-f]{8}) on branch (\S+)\.\n", result.stdout)
        self.assertIsNotNone(found, result.stdout + result.stderr)
        return found.group(1), found.group(2)

    def test_a_ticket_on_the_default_branch_gets_a_fresh_branch_from_the_fetched_remote(self):
        self.issue(7)
        local = self.world.git(self.work, "rev-parse", "HEAD")
        tip = self.advance_origin()
        result = self.world.deliver("start", "7")
        run, branch = self.started(result)
        self.assertEqual(branch, f"deliver/ticket-7-{run}")
        self.assert_ends(result, 0, "\n".join([
            f"Started run {run} on branch {branch}.", "R1: it parses", "R2: the help names it", MISSING, PROBE,
        ]) + "\n")
        self.assertEqual(self.branch(), branch)
        self.assertEqual(self.world.git(self.work, "rev-parse", "HEAD"), tip)
        self.assertEqual(self.world.git(self.work, "rev-parse", "main"), local)
        self.assertEqual(self.world.git(self.work, "for-each-ref", "--format=%(upstream)", f"refs/heads/{branch}"), "")
        self.assertEqual({k: v for k, v in self.mark().items() if k != "started"},
                         {"run": run, "branch": branch, "role": "session"})
        self.assertEqual((self.folder(branch) / "request.md").read_text(encoding="utf-8"),
                         "Source: ticket #7\n\n## What to build\n\nAdd a --json flag.\n")
        self.assertEqual(self.without_at(self.world.records(branch)),
                         [{"event": "save", "kind": "request", "file": "request.md", "commit": tip}])
        self.assertEqual(self.excluded(), [".deliver/"])
        self.assertEqual(self.calls(), [["issue", "view", "7", "--json", "title,body,comments"], REPO_VIEW])
        self.assertEqual(self.world.state_lines("preflight-stops.jsonl"), [])

    def test_after_start_the_probe_and_preflight_pass(self):
        self.issue(7)
        run, branch = self.started(self.world.deliver("start", "7"))
        self.assertIn('"permissionDecision": "deny"', self.world.probe().stdout)
        self.assert_ends(self.world.deliver("preflight"), 0, f"{MISSING}\nPreflight passed.\n")
        self.assertEqual([(r["event"], r.get("result")) for r in self.world.records(branch)],
                         [("save", None), ("preflight", "pass")])

    def test_the_fresh_branch_carries_uncommitted_and_untracked_changes(self):
        (self.work / "README.md").write_text("seed\nedited\n", encoding="utf-8")
        (self.work / "new.txt").write_text("new\n", encoding="utf-8")
        result = self.world.deliver("start")
        run, branch = self.started(result)
        self.assertEqual(branch, f"deliver/tree-{run}")
        self.assert_ends(result, 0, f"Started run {run} on branch {branch}.\n{MISSING}\n{PROBE}\n")
        self.assertEqual(self.branch(), branch)
        self.assertEqual(self.world.git(self.work, "status", "--porcelain"), "M README.md\n?? new.txt")
        self.assertEqual((self.folder(branch) / "request.md").read_text(encoding="utf-8"), TREE)
        self.assertEqual(self.without_at(self.world.records(branch)),
                         [{"event": "save", "kind": "request", "file": "request.md", "commit": None}])

    def test_a_request_is_read_from_the_drop_folder_and_moved_into_the_records(self):
        self.world.git(self.work, "switch", "-q", "-c", "feat/flag")
        self.merged("feat/flag", [])
        drop = self.work / ".deliver"
        drop.mkdir()
        (drop / "request.md").write_text("\nAdd a --json flag.\n\n  Keep `--quiet` as it is.\n\n", encoding="utf-8")
        (drop / "notes.md").write_text("scratch\n", encoding="utf-8")
        result = self.world.deliver("start", "request")
        run, branch = self.started(result)
        self.assert_ends(result, 0, f"Started run {run} on branch feat/flag.\n{MISSING}\n{PROBE}\n")
        self.assertEqual((self.folder("feat/flag") / "request.md").read_text(encoding="utf-8"),
                         "Source: conversation\n\nAdd a --json flag.\n\n  Keep `--quiet` as it is.\n")
        self.assertFalse((drop / "request.md").exists())
        self.assertEqual(self.world.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        head = self.world.git(self.work, "rev-parse", "HEAD")
        self.assertEqual(self.without_at(self.world.records("feat/flag")),
                         [{"event": "save", "kind": "request", "file": "request.md", "commit": head}])
        self.assertEqual(self.calls(), [REPO_VIEW, ["pr", "list", "--head", "feat/flag", "--state", "merged",
                                                    "--json", "number"]])

    def test_a_request_on_the_command_line_is_a_usage_error(self):
        result = self.world.deliver("start", "request", "Add a --json flag.")
        usage = deliver_kit.load("deliver").USAGE
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", (
            "deliver.py: start takes one ticket number, request, --resume or nothing, got: request Add a --json flag."
            f"\n\n{usage}\n")))
        self.assert_nothing_written()

    def test_a_branch_whose_pr_is_merged_gets_a_fresh_branch(self):
        self.world.git(self.work, "switch", "-q", "-c", "feat/done")
        self.merged("feat/done", [{"number": 3}])
        self.issue(7)
        run, branch = self.started(self.world.deliver("start", "7"))
        self.assertEqual((self.branch(), self.mark()["branch"]), (f"deliver/ticket-7-{run}",) * 2)

    def test_a_detached_head_gets_a_fresh_branch(self):
        self.world.git(self.work, "switch", "-q", "--detach")
        self.issue(7)
        run, branch = self.started(self.world.deliver("start", "7"))
        self.assertEqual(self.branch(), f"deliver/ticket-7-{run}")
        self.assertNotIn(["pr", "list"], [c[:2] for c in self.calls()])

    def test_the_exclude_line_is_added_once(self):
        exclude = self.git_dir / "info" / "exclude"
        exclude.write_text("# local\n*.log", encoding="utf-8")
        self.issue(7)
        self.issue(8)
        self.world.gh_answer(["pr", "list"], "[]")
        first = self.world.deliver("start", "7")
        (self.git_dir / "deliver-mark.json").unlink()
        second = self.world.deliver("start", "8")
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stdout + second.stdout)
        self.assertEqual(exclude.read_text(encoding="utf-8"), "# local\n*.log\n.deliver/\n")

    def test_the_grant_line_drops_follow_ups_and_names_a_withheld_merge(self):
        self.assertEqual(start.grant_line({"stop_at_ready": False, "follow_ups": True}), GRANT)
        self.assertEqual(start.grant_line({"stop_at_ready": False, "follow_ups": False}),
                         "Run grant: push this branch, open and update its PR, mark it ready and merge it through "
                         "the scripts.")
        self.assertEqual(start.grant_line({"stop_at_ready": True, "follow_ups": True}),
                         "Run grant: push this branch, open and update its PR, mark it ready through the scripts, "
                         "no merge: stop at ready, file follow-up tickets.")
        self.assertEqual(start.grant_line({"stop_at_ready": True, "follow_ups": False}),
                         "Run grant: push this branch, open and update its PR, mark it ready through the scripts, "
                         "no merge: stop at ready.")

    def test_start_prints_no_grant_and_resume_reads_it_from_the_stack_settings(self):
        (self.work / "docs" / "agents").mkdir(parents=True)
        (self.work / "docs" / "agents" / "stack.toml").write_text("stop_at_ready = true\nfollow_ups = false\n",
                                                                  encoding="utf-8")
        result = self.world.deliver("start")
        run, branch = self.started(result)
        self.assert_ends(result, 0, f"Started run {run} on branch {branch}.\n{PROBE}\n")
        self.world.probe()
        self.assertEqual(self.world.deliver("start", "--resume").stdout.splitlines()[-2:], [
            "Preflight passed.",
            "Run grant: push this branch, open and update its PR, mark it ready through the scripts, "
            "no merge: stop at ready."])

    def test_the_mark_is_written_before_preflight_runs(self):
        (self.work / "new.txt").write_text("new\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-c", SPY, str(deliver_kit.SCRIPTS), "start"], cwd=self.work, env=self.world.env(),
            capture_output=True, text=True)
        run, branch = self.started(result)
        mark = (self.git_dir / "deliver-mark.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(mark)["run"], run)
        self.assert_ends(result, 0, f"Started run {run} on branch {branch}.\n"
                                    f"mark seen by preflight: {mark}\n{MISSING}\n{PROBE}\n")

    def test_a_preflight_stop_at_start_is_saved_and_logged_after_the_requirements(self):
        (self.work / "docs" / "agents").mkdir(parents=True)
        (self.work / "docs" / "agents" / "stack.toml").write_text("check_slots = 'two'\n", encoding="utf-8")
        self.issue(7)
        result = self.world.deliver("start", "7")
        run, branch = self.started(result)
        self.assert_ends(result, 10, "\n".join([
            f"Started run {run} on branch {branch}.", "R1: it parses", "R2: the help names it",
            "REFUSED preflight.bad-settings: the stack settings cannot be read: "
            "docs/agents/stack.toml: check_slots must be int",
            "Next: fix docs/agents/stack.toml, then run deliver.py preflight"]) + "\n")
        self.assertEqual(self.mark()["run"], run)
        self.assertEqual(self.without_at(self.world.records(branch)), [
            {"event": "save", "kind": "request", "file": "request.md", "commit": self.world.git(self.work, "rev-parse", "HEAD")},
            {"event": "preflight", "run": run, "result": "stop", "stops": ["preflight.bad-settings"], "warnings": [],
             "guard_probe": "missing", "permission_mode": None, "harness": "claude-code"}])
        self.assertEqual(self.without_at(self.world.state_lines("preflight-stops.jsonl")),
                         [{"run": run, "code": "preflight.bad-settings", "harness": "claude-code"}])

    def test_a_ticket_with_a_gap_ends_in_exit_20_with_one_question(self):
        self.issue(7, body="## Acceptance criteria\n\n- [ ]\n")
        self.assert_ends(self.world.deliver("start", "7"), 20, "\n".join([
            "Ticket #7 does not pass the entry check:",
            f"- {entry_check.NO_TEXT}",
            f"- {entry_check.NO_CRITERION}",
            "Will you add what is missing to ticket #7? Then the session runs deliver.py start 7 again."]) + "\n")
        self.assert_nothing_written()
        self.assertEqual(self.calls(), [["issue", "view", "7", "--json", "title,body,comments"]])

    def test_the_newest_agent_brief_gives_the_requirements(self):
        self.issue(7, comments=("## Agent Brief\n\n**Acceptance criteria:**\n- from the brief\n",))
        result = self.world.deliver("start", "7")
        run, branch = self.started(result)
        self.assert_ends(result, 0, f"Started run {run} on branch {branch}.\nR1: from the brief\n{MISSING}\n{PROBE}\n")

    def test_placeholders_alone_end_in_exit_20_before_anything_is_written(self):
        cases = {
            "Build a flag.\n\n## Acceptance\n\n- [ ]\n- [x] <!-- a criterion -->\n1.\n": [entry_check.NO_CRITERION],
            "<!--\nSay what to build.\n-->\n\n## Acceptance\n- it parses\n": [entry_check.NO_TEXT],
        }
        for number, (body, gaps) in enumerate(cases.items(), 7):
            with self.subTest(body=body):
                self.issue(number, body=body)
                self.assert_ends(self.world.deliver("start", str(number)), 20, "\n".join([
                    f"Ticket #{number} does not pass the entry check:", *(f"- {gap}" for gap in gaps),
                    f"Will you add what is missing to ticket #{number}? Then the session runs deliver.py start "
                    f"{number} again."]) + "\n")
                self.assert_nothing_written()

    def test_every_list_of_every_criteria_section_is_numbered_in_order(self):
        self.issue(7, body="Add a JSON export.\n\n## Acceptance\n\nThe export command:\n\n- Red\n\nAnother case\n\n"
                           "  1. Green\n  2. Blue\n     still Blue\n\n### Done when\n- nested\n\n### Edge cases\n"
                           "- sibling\n\n## Notes\n- out\n")
        result = self.world.deliver("start", "7")
        run, branch = self.started(result)
        self.assert_ends(result, 0, "\n".join([
            f"Started run {run} on branch {branch}.", "R1: Red", "R2: Green", "R3: Blue still Blue", "R4: nested",
            "R5: sibling", MISSING, PROBE]) + "\n")

    def test_resume_keeps_the_mark_and_prints_where_the_run_stands(self):
        self.issue(7)
        run, branch = self.started(self.world.deliver("start", "7"))
        mark = (self.git_dir / "deliver-mark.json").read_text(encoding="utf-8")
        (self.folder(branch) / "plan.md").write_text("| R1 | it parses | `make test` |\n", encoding="utf-8")
        with (self.folder(branch) / "records.jsonl").open("a", encoding="utf-8") as f:
            for line in ({"event": "check", "at": "t", "command": "make lint", "exit": 0, "commit": None},
                         {"event": "check", "at": "t", "command": "make test", "exit": 1, "commit": "abcdef123456"},
                         {"event": "pr", "at": "t", "number": 12, "url": "https://github.com/o/r/pull/12"}):
                f.write(json.dumps(line) + "\n")
        self.world.probe()
        result = self.world.deliver("start", "--resume")
        started = json.loads(mark)["started"]
        self.assert_ends(result, 0, "\n".join([
            f"Resuming run {run} on branch {branch}, started {started}.",
            "Saved: request, plan.",
            "Checks: 2; the last, `make test`, exited 1 at abcdef1.",
            "PR: #12 https://github.com/o/r/pull/12",
            MISSING, "Preflight passed.", GRANT]) + "\n")
        self.assertEqual((self.git_dir / "deliver-mark.json").read_text(encoding="utf-8"), mark)
        self.assertEqual(self.world.records(branch)[-1]["result"], "pass")

    def test_resume_reruns_the_whole_preflight(self):
        self.issue(7)
        run, branch = self.started(self.world.deliver("start", "7"))
        self.assert_ends(self.world.deliver("start", "--resume"), 10, "\n".join([
            f"Resuming run {run} on branch {branch}, started {self.mark()['started']}.",
            "Saved: request.", "Checks: none.", MISSING,
            f"REFUSED preflight.guards-off: the guards are off: no refusal of the guard probe is logged for run {run} "
            "since its mark was written",
            "Next: turn the hooks on, run gh pr merge --deliver-guard-probe, then run deliver.py preflight"]) + "\n")
        self.assertEqual(self.mark()["run"], run)

    def test_start_run_in_progress(self):
        self.issue(7)
        run, branch = self.started(self.world.deliver("start", "7"))
        mark = (self.git_dir / "deliver-mark.json").read_text(encoding="utf-8")
        self.assert_ends(self.world.deliver("start", "7"), 10, (
            f"REFUSED start.run-in-progress: run {run} is in progress in this checkout "
            f"(run mark: {self.git_dir / 'deliver-mark.json'}); deliver.py start --resume resumes it\n"
            "Next: deliver.py finish, to end it\n"))
        self.assertEqual((self.git_dir / "deliver-mark.json").read_text(encoding="utf-8"), mark)
        self.assertEqual(len(self.world.records(branch)), 1)

    def test_start_no_run(self):
        self.assert_ends(self.world.deliver("start", "--resume"), 10, (
            "REFUSED start.no-run: no run mark in this checkout, so there is no run to resume\n"
            "Next: deliver.py start\n"))
        self.assert_nothing_written()

    def test_start_not_built(self):
        for args in (["7", "8"], ["spec", "200"], ["backlog"]):
            with self.subTest(args=args):
                self.assert_ends(self.world.deliver("start", *args), 10, (
                    f"REFUSED start.not-built: start {' '.join(args)} is a multi-ticket run, and multi-ticket runs "
                    "come with a later build stage\nNext: deliver.py start <one ticket>\n"))
        self.assert_nothing_written()
        self.assertEqual(self.calls(), [])

    def test_a_mark_wins_over_every_other_start_form(self):
        self.issue(7)
        run, branch = self.started(self.world.deliver("start", "7"))
        calls = self.calls()
        for args in (["7", "8"], ["spec", "200"], ["backlog"], ["request", "Add a flag."], ["request"], []):
            with self.subTest(args=args):
                self.assert_ends(self.world.deliver("start", *args), 10, (
                    f"REFUSED start.run-in-progress: run {run} is in progress in this checkout "
                    f"(run mark: {self.git_dir / 'deliver-mark.json'}); deliver.py start --resume resumes it\n"
                    "Next: deliver.py finish, to end it\n"))
        self.assertEqual((self.mark()["run"], len(self.world.records(branch)), self.calls()), (run, 1, calls))

    def test_start_nothing_to_start(self):
        (self.work / ".deliver").mkdir()
        (self.work / ".deliver" / "notes.md").write_text("scratch\n", encoding="utf-8")
        self.assert_ends(self.world.deliver("start"), 10, (
            "REFUSED start.nothing-to-start: the tree has no changes and no ticket or request was named. "
            "start accepts: start <ticket>; start request, after the request is written word for word into "
            ".deliver/request.md; start with changes in the tree; start --resume\n"))
        self.assert_nothing_written()
        self.assertEqual(self.calls(), [])

    def test_start_no_request(self):
        for text in (None, " \n\n"):
            with self.subTest(text=text):
                if text is not None:
                    (self.work / ".deliver").mkdir()
                    (self.work / ".deliver" / "request.md").write_text(text, encoding="utf-8")
                self.assert_ends(self.world.deliver("start", "request"), 10, (
                    "REFUSED start.no-request: .deliver/request.md is missing or empty, and a request is read from "
                    "there only\nNext: write the request word for word into .deliver/request.md, then run "
                    "deliver.py start request\n"))
        self.assert_nothing_written()

    def test_start_no_ticket(self):
        self.world.gh_answer(["issue", "view"], stderr="GraphQL: Could not resolve to an issue with the number of 9.\n",
                             exit=1)
        self.assert_ends(self.world.deliver("start", "9"), 10, (
            "REFUSED start.no-ticket: gh cannot read ticket #9: GraphQL: Could not resolve to an issue with the "
            "number of 9.\nNext: check the number and gh auth status, then run deliver.py start 9\n"))
        self.assert_nothing_written()

    def test_start_not_a_repo(self):
        outside = self.world.root / "outside"
        outside.mkdir()
        self.assert_ends(self.world.deliver("start", "7", cwd=outside), 10, (
            f"REFUSED start.not-a-repo: {outside} is not in a git working tree\n"
            "Next: run deliver.py start inside the repo\n"))
        self.assertEqual(self.calls(), [])

    def test_start_fetch_failed(self):
        self.issue(7)
        self.world.git(self.work, "remote", "set-url", "origin", str(self.world.root / "gone.git"))
        result = self.world.deliver("start", "7")
        self.assertEqual((result.returncode, result.stderr), (10, ""))
        self.assertRegex(result.stdout, re.compile(
            r"\AREFUSED start\.fetch-failed: git fetch origin main failed, so no fresh branch was cut: "
            r"fatal: .*gone\.git.*\nNext: fix the error, then run deliver\.py start 7\n\Z", re.S))
        self.assert_nothing_written()

    def test_start_cannot_carry(self):
        self.advance_origin("README.md", "seed\nupstream\n")
        (self.work / "README.md").write_text("seed\nlocal\n", encoding="utf-8")
        result = self.world.deliver("start")
        self.assertEqual((result.returncode, result.stderr), (10, ""))
        self.assertRegex(result.stdout, re.compile(
            r"\AREFUSED start\.cannot-carry: git cannot carry the changes in the tree onto a fresh branch from "
            r"origin/main, so nothing was changed: error: .*README\.md.*\n"
            r"Next: commit or stash the changes git names, then run deliver\.py start\n\Z", re.S))
        self.assert_nothing_written()
        self.assertEqual((self.work / "README.md").read_text(encoding="utf-8"), "seed\nlocal\n")


class EntryCheck(unittest.TestCase):
    def check(self, body: str, comments: tuple[str, ...] = ()):
        return entry_check.check(body, list(comments))

    def test_reads_the_items_under_acceptance_criteria_as_r1_on(self):
        entry = self.check("## What to build\n\nAdd a flag.\n\n## Acceptance criteria\n\n"
                           "- [ ] the flag parses\n- [x] the help names it\n* a bullet\n1. a number\n2) another\n")
        self.assertEqual(entry.requirements,
                         ["the flag parses", "the help names it", "a bullet", "a number", "another"])
        self.assertEqual(entry.gaps, [])
        self.assertEqual(entry.quote, "## What to build\n\nAdd a flag.")

    def test_reads_all_three_headings_at_any_level_and_case_in_the_order_they_appear(self):
        entry = self.check("Build it.\n\n### Done when\n- first\n\n# ACCEPTANCE\n- second\n\n"
                           "## Acceptance Criteria:\n- third\n")
        self.assertEqual(entry.requirements, ["first", "second", "third"])
        self.assertEqual(entry.quote, "Build it.")

    def test_a_section_ends_at_the_next_heading_of_the_same_or_a_higher_level(self):
        entry = self.check("Build it.\n\n## Acceptance criteria\n- in\n### Detail\n- still in\n"
                           "## Notes\n- out\n# Top\n- out too\n")
        self.assertEqual(entry.requirements, ["in", "still in"])

    def test_reads_a_bold_line_label_up_to_the_next_bold_line(self):
        entry = self.check("Build it.\n\n**Acceptance criteria:**\n- in\n\n**Out of scope:**\n- out\n")
        self.assertEqual(entry.requirements, ["in"])

    def test_continuation_lines_and_nested_items_join_their_parent(self):
        entry = self.check("Build it.\n\n## Acceptance criteria\n\n- [ ] parent\n  goes on\n  - child\n\n"
                           "    more of it\n- next\nnot a criterion\n  not joined\n")
        self.assertEqual(entry.requirements, ["parent goes on - child more of it", "next"])

    def test_lines_in_a_code_fence_are_not_items(self):
        entry = self.check("Build it.\n\n## Acceptance criteria\n- real\n```\n- fenced\n## Done when\n```\n")
        self.assertEqual(entry.requirements, ["real"])

    def test_a_longer_fence_holds_a_shorter_fence_line(self):
        entry = self.check("Build it.\n\n## Acceptance criteria\n- real\n````\n```\n- sample\n````\n- after\n")
        self.assertEqual(entry.requirements, ["real", "after"])

    def test_prose_above_a_criteria_list_is_text_saying_what_to_build(self):
        entry = self.check("## Acceptance\n\nAdd a JSON export command.\n\n- it exports\n")
        self.assertEqual((entry.requirements, entry.gaps, entry.quote), (["it exports"], [], ""))

    def test_html_comments_are_neither_text_nor_criteria(self):
        entry = self.check("<!-- Say what to build. -->\n## Acceptance\n- <!-- a criterion -->\n- [ ] <!--\nmore\n-->\n")
        self.assertEqual(entry.gaps, [entry_check.NO_TEXT, entry_check.NO_CRITERION])

    def test_the_newest_agent_brief_replaces_the_bodys_criteria(self):
        old = "## Agent Brief\n\n**Acceptance criteria:**\n- old one\n"
        new = "## agent brief\n\n**Summary:** do the thing\n\n**Acceptance criteria:**\n- new one\n- new two\n"
        entry = self.check("Build it.\n\n## Acceptance criteria\n- body one\n", ("A remark.", old, new, "Thanks."))
        self.assertEqual((entry.requirements, entry.gaps, entry.quote), (["new one", "new two"], [], "Build it."))

    def test_the_brief_can_hold_the_text_saying_what_to_build(self):
        entry = self.check("", ("## Agent Brief\n\nAdd a flag.\n\n## Acceptance criteria\n- it parses\n",))
        self.assertEqual((entry.requirements, entry.gaps, entry.quote), (["it parses"], [], ""))

    def test_a_ticket_with_no_criterion_has_that_gap(self):
        entry = self.check("Add a flag.\n\n## Acceptance criteria\n\nIt should work.\n")
        self.assertEqual(entry.gaps, [entry_check.NO_CRITERION])

    def test_a_brief_without_criteria_leaves_the_ticket_without_one(self):
        entry = self.check("Add a flag.\n\n## Acceptance criteria\n- body one\n", ("## Agent Brief\n\nNo list.\n",))
        self.assertEqual(entry.gaps, [entry_check.NO_CRITERION])

    def test_headings_and_criteria_alone_are_not_text_saying_what_to_build(self):
        entry = self.check("## Parent\n\n## Acceptance criteria\n- it parses\n")
        self.assertEqual(entry.gaps, [entry_check.NO_TEXT])

    def test_an_empty_ticket_has_both_gaps(self):
        self.assertEqual(self.check("").gaps, [entry_check.NO_TEXT, entry_check.NO_CRITERION])


if __name__ == "__main__":
    unittest.main()
