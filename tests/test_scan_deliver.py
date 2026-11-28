"""Exercise the second half of `deliver.py scan`, the record of a `deliver` PR, and its readers for the other harnesses.

Each test builds Claude Code session logs in a throwaway config folder, or another harness's files
from tests/scan_inputs/ in the world's own home, answers `gh` with the shared stand-in, and runs
`deliver.py scan` at its command line with a scratch machine directory. No test reads a real home folder.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402
from deliver_kit import World  # noqa: E402

INPUTS = Path(__file__).resolve().parent / "scan_inputs"

URL = "https://github.com/o/r/pull/7"
BRANCH = "feat/ticket-7"
READY = "python3 skills/deliver/scripts/deliver.py ready"
BLOCK = ("<details><summary>Measurement</summary>\n\n```text\nversion: 0.1.0\npath: single ticket\n"
         "harness: claude-code\nroles: author; reader\nfix rounds: 1\n```\n\n</details>\n")


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
READY_AT = NOW - timedelta(days=3)


class Logs:
    """Session logs under one config folder, written line by line."""

    def __init__(self, world: World):
        self.world = world
        self.config = world.home / ".claude"
        self.project = self.config / "projects" / "-work"
        self.project.mkdir(parents=True)
        self.count = 0

    def path(self, session: str, helper: str | None = None) -> Path:
        if helper is None:
            return self.project / f"{session}.jsonl"
        return self.project / session / "subagents" / f"agent-{helper}.jsonl"

    def add(self, session: str, *lines: dict, helper: str | None = None, description: str | None = None) -> None:
        path = self.path(session, helper)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.writelines(json.dumps(line) + "\n" for line in lines)
        if helper is not None and description is not None:
            path.with_name(path.stem + ".meta.json").write_text(json.dumps({"description": description}))

    def response(self, session: str, at: datetime, *, model: str = "opus", effort: str | None = "high",
                 tokens: int = 10, command: str | None = None, branch: str = BRANCH,
                 cwd: Path | None = None) -> tuple[dict, str]:
        """One assistant line holding one response; with `command`, a shell call to run it."""
        self.count += 1
        content = []
        call = f"call-{self.count}"
        if command is not None:
            content.append({"type": "tool_use", "id": call, "name": "Bash", "input": {"command": command}})
        line = {"type": "assistant", "sessionId": session, "timestamp": stamp(at), "uuid": f"u{self.count}",
                "cwd": str(cwd or self.world.work), "gitBranch": branch,
                "message": {"id": f"msg-{self.count}", "model": model, "content": content,
                            "usage": {"input_tokens": tokens, "output_tokens": 0}}}
        if effort is not None:
            line["effort"] = effort
        return line, call

    def result(self, session: str, at: datetime, call: str, error: bool = False) -> dict:
        return {"type": "user", "sessionId": session, "timestamp": stamp(at),
                "message": {"content": [{"type": "tool_result", "tool_use_id": call, "is_error": error}]}}

    def ready_session(self, session: str = "s1", at: datetime = READY_AT) -> None:
        """A session that works, calls ready once with success, and stops."""
        work, _ = self.response(session, at - timedelta(minutes=5))
        ready, call = self.response(session, at, command=READY)
        self.add(session, work, ready, self.result(session, at + timedelta(seconds=5), call))


def pr(**changes) -> dict:
    view = {"number": 7, "url": URL, "state": "OPEN", "isDraft": False, "mergedAt": None, "closedAt": None,
            "body": "## Summary\n\nWork.\n\n" + BLOCK, "labels": [], "reviews": [], "baseRefName": "main",
            "headRefName": BRANCH}
    return {**view, **changes}


def commit(sha: str, at: datetime, parents: tuple[str, ...] = ("p",)) -> dict:
    return {"sha": sha, "commit": {"committer": {"date": stamp(at)}}, "parents": [{"sha": p} for p in parents]}


class ScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World(self.addCleanup)
        self.logs = Logs(self.world)
        self.answer_pr(pr())
        self.answer_commits([commit("ready-sha", READY_AT - timedelta(minutes=1))])
        self.answer_checks("ready-sha", [{"conclusion": "success"}])

    def answer(self, args: list[str], stdout: str, stderr: str = "", exit: int = 0) -> None:
        """Answer `gh args` from now on, in place of any earlier answer to the same arguments."""
        path = self.world.root / "gh-answers.json"
        kept = [answer for answer in json.loads(path.read_text()) if answer["args"] != args]
        path.write_text(json.dumps([{"args": args, "stdout": stdout, "stderr": stderr, "exit": exit}, *kept]))

    def answer_pr(self, view: dict) -> None:
        self.answer(["pr", "view"], json.dumps(view))

    def answer_commits(self, commits: list[dict]) -> None:
        self.answer(["api", "repos/o/r/pulls/7/commits?per_page=100"], json.dumps(commits))

    def answer_checks(self, sha: str, runs: list[dict]) -> None:
        self.answer(["api", f"repos/o/r/commits/{sha}/check-runs?per_page=100"], json.dumps({"check_runs": runs}))

    def ready_before(self, merged_at: datetime) -> None:
        """A ready session a day before the merge, its ready commit just before it."""
        at = merged_at - timedelta(days=1)
        self.answer_commits([commit("ready-sha", at - timedelta(minutes=1))])
        self.logs.ready_session(at=at)

    def scan(self, *args: str, **env: str):
        return self.world.deliver("scan", *args, CLAUDE_CONFIG_DIR=str(self.logs.config), **env)

    def rows(self) -> dict[str, dict]:
        return {row["session"]: row for row in self.world.state_lines("scan-rows.jsonl")}

    def record(self, session: str = "s1") -> dict:
        result = self.scan(session)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.rows()[session]["deliver"]


class TestTheRecord(ScanTest):
    def test_the_ready_call_finds_the_session_and_its_pr(self) -> None:
        self.logs.ready_session()
        record = self.record()
        self.assertEqual((record["pr"], record["branch"], record["ready_at"]), (URL, BRANCH, stamp(READY_AT)))
        first = self.world.gh_calls()[0]
        self.assertEqual((first["args"][:3], first["cwd"]), (["pr", "view", BRANCH], str(self.world.work)))

    def test_the_row_holds_the_measurement_blocks_fields(self) -> None:
        self.logs.ready_session()
        record = self.record()
        self.assertEqual(record["measurement"], {"version": "0.1.0", "path": "single ticket",
                                                 "harness": "claude-code", "roles": "author; reader",
                                                 "fix rounds": "1"})
        self.assertIsNone(record["measurement_note"])

    def test_a_pr_without_the_block_leaves_the_fields_blank_and_says_so(self) -> None:
        self.answer_pr(pr(body="## Summary\n\nNo block.\n"))
        self.logs.ready_session()
        record = self.record()
        self.assertIsNone(record["measurement"])
        self.assertEqual(record["measurement_note"], "no measurement block in the PR description")

    def test_a_block_with_a_line_that_is_not_key_value_is_left_blank_and_says_which(self) -> None:
        self.answer_pr(pr(body=BLOCK.replace("harness: claude-code", "harness claude-code")))
        self.logs.ready_session()
        record = self.record()
        self.assertIsNone(record["measurement"])
        self.assertEqual(record["measurement_note"],
                         "measurement block line 'harness claude-code' is not a key: value line")

    def test_a_block_that_names_a_key_twice_is_left_blank(self) -> None:
        self.answer_pr(pr(body=BLOCK.replace("fix rounds: 1", "fix rounds: 1\npath: small edit")))
        self.logs.ready_session()
        record = self.record()
        self.assertIsNone(record["measurement"])
        self.assertEqual(record["measurement_note"], "measurement block names 'path' twice")

    def test_each_agent_has_the_model_and_effort_of_its_own_responses(self) -> None:
        early = READY_AT - timedelta(minutes=30)
        copied, _ = self.logs.response("s0", early, model="older", effort="low")
        self.logs.add("s1", copied)  # a resumed session's copy of an earlier session's response
        self.logs.ready_session()
        helper, _ = self.logs.response("s1", early, model="sonnet", effort="medium")
        quiet, _ = self.logs.response("s1", early, model="haiku", effort=None)
        forked = json.loads(self.logs.path("s1").read_text().splitlines()[1])  # the session's own first response
        self.logs.add("s1", forked, helper, helper="h1", description="read the files")
        self.logs.add("s1", quiet, helper="h2", description="look up a name")
        agents = {agent["agent"]: agent for agent in self.record()["agents"]}
        self.assertEqual(agents["session"]["models"], {"opus": 2})
        self.assertEqual(agents["session"]["efforts"], {"high": 2})
        self.assertEqual((agents["h1"]["description"], agents["h1"]["models"], agents["h1"]["efforts"]),
                         ("read the files", {"sonnet": 1}, {"medium": 1}))
        self.assertEqual((agents["h2"]["models"], agents["h2"]["efforts"]), ({"haiku": 1}, {}))

    def test_a_session_without_a_ready_call_has_no_record_and_asks_gh_nothing(self) -> None:
        line, _ = self.logs.response("s1", READY_AT, command="python3 skills/deliver/scripts/deliver.py pr")
        self.logs.add("s1", line)
        result = self.scan("s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("deliver", self.rows()["s1"])
        self.assertEqual(self.world.gh_calls(), [])

    def test_a_ready_call_that_failed_is_not_the_ready_moment(self) -> None:
        self.logs.ready_session()
        later = READY_AT + timedelta(hours=1)
        refused, call = self.logs.response("s1", later, command=READY)
        self.logs.add("s1", refused, self.logs.result("s1", later, call, error=True))
        self.assertEqual(self.record()["ready_at"], stamp(READY_AT))

    def test_a_pr_gh_cannot_find_keeps_the_rows_first_half_and_says_why(self) -> None:
        self.answer(["pr", "view"], "", "no pull requests found\n", 1)
        self.logs.ready_session()
        result = self.scan("s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()["s1"]
        self.assertEqual(row["total_tokens"], 20)
        self.assertEqual(row["deliver"]["note"], "gh pr view failed: no pull requests found")
        self.assertIn("no pull requests found", result.stderr)


    def test_a_pr_has_one_record_the_session_that_called_ready_first(self) -> None:
        self.logs.ready_session()
        self.logs.ready_session("s2", at=READY_AT + timedelta(hours=1))
        result = self.scan("--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows()
        self.assertEqual(rows["s1"]["deliver"]["miss"], False)
        self.assertEqual(rows["s2"]["deliver"], {
            "pr": URL, "ready_at": stamp(READY_AT + timedelta(hours=1)), "record_of": "s1", "final": True,
            "note": "the record of this PR is the row of session s1, which called ready first"})

    def test_a_later_sessions_note_names_the_record_row_never_another_note(self) -> None:
        self.logs.ready_session()
        for number in (2, 3):
            self.logs.ready_session(f"s{number}", at=READY_AT + timedelta(hours=number))
        # s3 first: it takes the record, and s2 and s1, scanned after it, each find an earlier ready.
        for session in ("s3", "s2", "s1"):
            self.assertEqual(self.scan(session).returncode, 0)
        self.assertEqual(self.scan("--refresh").returncode, 0)
        self.assertEqual(self.scan("s3").returncode, 0)
        rows = self.rows()
        self.assertEqual((rows["s2"]["deliver"].get("record_of"), rows["s3"]["deliver"].get("record_of")),
                         ("s1", "s1"))

class TestTheReadyCall(ScanTest):
    """A ready call is a shell call that runs `deliver.py ready`; a command that only names it is not one."""

    def session(self, *commands: str, session: str = "s1", at: datetime = READY_AT) -> None:
        for step, command in enumerate(commands):
            line, call = self.logs.response(session, at + timedelta(minutes=step), command=command)
            self.logs.add(session, line, self.logs.result(session, at + timedelta(minutes=step, seconds=5), call))

    def found(self, *commands: str) -> str | None:
        """The ready moment the scan takes from a session with these shell calls; None when it finds no ready call."""
        self.session(*commands)
        result = self.scan("s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.rows()["s1"].get("deliver") or {}).get("ready_at")

    def test_the_plain_command_is_a_ready_call(self) -> None:
        self.assertEqual(self.found("deliver.py ready"), stamp(READY_AT))

    def test_uv_run_of_the_script_is_a_ready_call(self) -> None:
        self.assertEqual(self.found("uv run --python 3.13 --no-project /x/skills/deliver/scripts/deliver.py ready"),
                         stamp(READY_AT))

    def test_python3_of_the_script_is_a_ready_call(self) -> None:
        self.assertEqual(self.found("python3 /x/skills/deliver/scripts/deliver.py ready"), stamp(READY_AT))

    def test_a_call_after_cd_is_a_ready_call(self) -> None:
        self.assertEqual(self.found("cd /x/worktree && python3 skills/deliver/scripts/deliver.py ready"),
                         stamp(READY_AT))

    def test_a_grep_for_the_words_is_not_a_ready_call(self) -> None:
        self.assertIsNone(self.found('grep -rn "deliver.py ready" skills/'))

    def test_an_rg_for_the_words_is_not_a_ready_call(self) -> None:
        self.assertIsNone(self.found("rg -n 'deliver.py ready' skills/"))

    def test_a_cat_of_the_words_is_not_a_ready_call(self) -> None:
        self.assertIsNone(self.found("cat skills/deliver/scripts/deliver.py ready"))

    def test_an_echo_of_the_words_is_not_a_ready_call(self) -> None:
        self.assertIsNone(self.found("echo deliver.py ready"))

    def test_the_words_inside_quotes_are_not_a_ready_call(self) -> None:
        self.assertIsNone(self.found('git commit -m "wire deliver.py ready"'))

    def test_the_help_of_ready_is_not_a_ready_call(self) -> None:
        self.assertIsNone(self.found("python3 skills/deliver/scripts/deliver.py ready --help"))

    def test_a_mention_after_the_ready_call_leaves_the_ready_moment(self) -> None:
        self.assertEqual(self.found(READY, 'grep -rn "deliver.py ready" skills/'), stamp(READY_AT))


class TestTheMiss(ScanTest):
    def miss(self) -> tuple[bool | None, list[str]]:
        self.logs.ready_session()
        record = self.record()
        return record["miss"], record["miss_signals"]

    def test_no_signal_is_no_miss(self) -> None:
        self.assertEqual(self.miss(), (False, []))

    def test_a_draft_pr_has_no_miss_result_yet(self) -> None:
        self.answer_pr(pr(isDraft=True))
        self.assertEqual(self.miss(), (None, []))

    def test_a_commit_after_ready_is_a_miss(self) -> None:
        self.answer_commits([commit("ready-sha", READY_AT - timedelta(minutes=1)),
                             commit("fix-sha", READY_AT + timedelta(hours=1))])
        self.answer(["api", "repos/o/r/commits/fix-sha"],
                             json.dumps({"files": [{"filename": "a.py", "patch": "@@ -1 +1 @@\n-a = 1\n+a = 2"}]}))
        self.assertEqual(self.miss(), (True, ["commit after ready"]))

    def test_ci_failing_on_the_ready_commit_is_a_miss(self) -> None:
        self.answer_checks("ready-sha", [{"conclusion": "success"}, {"conclusion": "failure"}])
        self.assertEqual(self.miss(), (True, ["CI failed on the ready commit"]))

    def test_a_change_request_is_a_miss(self) -> None:
        self.answer_pr(pr(reviews=[{"state": "COMMENTED"}, {"state": "CHANGES_REQUESTED"}]))
        self.assertEqual(self.miss(), (True, ["change request"]))

    def test_a_pr_closed_unmerged_is_a_miss(self) -> None:
        self.answer_pr(pr(state="CLOSED", closedAt=stamp(NOW - timedelta(days=1))))
        self.assertEqual(self.miss(), (True, ["closed unmerged"]))

    def test_a_hand_over_to_the_owner_after_two_fix_rounds_is_a_miss(self) -> None:
        self.answer_pr(pr(body=BLOCK.replace("fix rounds: 1", "fix rounds: 2, handed to the owner")))
        self.assertEqual(self.miss(), (True, ["hand-over to the owner"]))

    def merged(self, later: list[dict]) -> None:
        merged_at = NOW - timedelta(days=2)
        self.answer_pr(pr(state="MERGED", mergedAt=stamp(merged_at), closedAt=stamp(merged_at)))
        self.answer(["pr", "list"], json.dumps(later))

    def test_a_later_pr_that_reverts_it_within_14_days_is_a_miss(self) -> None:
        self.merged([{"number": 9, "title": 'Revert "feat: the thing"', "body": "Reverts o/r#7",
                      "mergedAt": stamp(NOW - timedelta(days=1))}])
        self.assertEqual(self.miss(), (True, ["reverted or fixed by #9"]))
        listed = [call["args"] for call in self.world.gh_calls() if call["args"][:2] == ["pr", "list"]]
        self.assertEqual(listed[0][:4], ["pr", "list", "--repo", "o/r"])

    def test_a_later_pr_that_fixes_it_within_14_days_is_a_miss(self) -> None:
        self.merged([{"number": 10, "title": "fix(scan): the miss of #7", "body": "",
                      "mergedAt": stamp(NOW - timedelta(days=1))},
                     {"number": 11, "title": "fix: another thing", "body": "Unrelated to #70.",
                      "mergedAt": stamp(NOW - timedelta(days=1))}])
        self.assertEqual(self.miss(), (True, ["reverted or fixed by #10"]))

    def test_the_owners_miss_label_is_a_miss(self) -> None:
        self.answer_pr(pr(labels=[{"name": "deliver"}, {"name": "miss"}]))
        self.assertEqual(self.miss(), (True, ["miss label"]))

    def test_a_commit_that_only_brings_in_the_target_branch_is_not_a_miss(self) -> None:
        self.answer_commits([commit("ready-sha", READY_AT - timedelta(minutes=1)),
                             commit("merge-sha", READY_AT + timedelta(hours=1), ("ready-sha", "main-sha"))])
        self.answer(["api", "repos/o/r/compare/main...main-sha"], json.dumps({"status": "behind"}))
        self.assertEqual(self.miss(), (False, []))

    def test_a_merge_of_a_branch_that_is_not_the_target_is_a_miss(self) -> None:
        self.answer_commits([commit("ready-sha", READY_AT - timedelta(minutes=1)),
                             commit("merge-sha", READY_AT + timedelta(hours=1), ("ready-sha", "side-sha"))])
        self.answer(["api", "repos/o/r/compare/main...side-sha"], json.dumps({"status": "ahead"}))
        self.answer(["api", "repos/o/r/commits/merge-sha"], json.dumps({"files": []}))
        self.assertEqual(self.miss(), (True, ["commit after ready"]))

    def test_a_commit_of_version_lines_a_tool_wrote_is_not_a_miss(self) -> None:
        self.answer_commits([commit("ready-sha", READY_AT - timedelta(minutes=1)),
                             commit("bump-sha", READY_AT + timedelta(hours=1))])
        bump = '@@ -2,3 +2,3 @@\n   "name": "deliver",\n-  "version": "0.1.0",\n+  "version": "0.1.1",'
        self.answer(["api", "repos/o/r/commits/bump-sha"],
                             json.dumps({"files": [{"filename": "skills/deliver/plugin.json", "patch": bump}]}))
        self.assertEqual(self.miss(), (False, []))


class TestTokensAfterReady(ScanTest):
    def test_tokens_after_ready_on_the_branch_are_added_to_the_same_record(self) -> None:
        self.logs.ready_session()
        after = READY_AT + timedelta(hours=2)
        fix, _ = self.logs.response("s2", after, tokens=100)
        other, _ = self.logs.response("s2", after, tokens=1000, branch="main")
        elsewhere = self.world.root / "elsewhere"
        elsewhere.mkdir()
        outside, _ = self.logs.response("s2", after, tokens=5000, cwd=elsewhere)
        before, _ = self.logs.response("s3", READY_AT - timedelta(hours=1), tokens=10000)
        self.logs.add("s2", fix, other, outside)
        self.logs.add("s3", before)
        record = self.record()
        # The fix in a later session (100); not the ready call itself, the other branch, a
        # folder outside the repo, or work before ready.
        self.assertEqual(record["after_ready_tokens"]["total_tokens"], 100)
        self.assertEqual(self.rows()["s1"]["total_tokens"], 20)


class TestRefresh(ScanTest):
    def test_a_refresh_finds_a_new_ready_session(self) -> None:
        self.logs.ready_session()
        result = self.scan("--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()["s1"]["deliver"]["pr"], URL)

    def test_a_record_is_final_14_days_after_merge_and_is_not_refreshed_after(self) -> None:
        merged_at = NOW - timedelta(days=15)
        self.answer_pr(pr(state="MERGED", mergedAt=stamp(merged_at), closedAt=stamp(merged_at)))
        self.answer(["pr", "list"], "[]")
        self.ready_before(merged_at)
        self.assertTrue(self.record()["final"])
        rows = (self.world.state / "scan-rows.jsonl").read_bytes()
        calls = len(self.world.gh_calls())
        self.logs.add("s1", self.logs.response("s1", NOW, tokens=7)[0])
        for args in (["--refresh"], ["s1"]):
            result = self.scan(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.world.state / "scan-rows.jsonl").read_bytes(), rows)
        self.assertEqual(len(self.world.gh_calls()), calls)

    def test_a_record_merged_less_than_14_days_ago_is_refreshed(self) -> None:
        merged_at = NOW - timedelta(days=13)
        self.answer_pr(pr(state="MERGED", mergedAt=stamp(merged_at), closedAt=stamp(merged_at)))
        self.answer(["pr", "list"], "[]")
        self.ready_before(merged_at)
        self.assertFalse(self.record()["final"])
        self.answer_pr(pr(state="MERGED", mergedAt=stamp(merged_at), closedAt=stamp(merged_at),
                          labels=[{"name": "miss"}]))
        result = self.scan("--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()["s1"]["deliver"]["miss_signals"], ["miss label"])
        # A refresh asks for the PR by the address the first scan kept, not by the branch.
        views = [call["args"][2] for call in self.world.gh_calls() if call["args"][:2] == ["pr", "view"]]
        self.assertEqual(views, [BRANCH, URL])

    def views(self) -> int:
        return len([call for call in self.world.gh_calls() if call["args"][:2] == ["pr", "view"]])

    def test_a_later_sessions_note_is_not_asked_about_again(self) -> None:
        self.logs.ready_session()
        self.logs.ready_session("s2", at=READY_AT + timedelta(hours=1))
        counts = []
        for _ in range(3):
            self.assertEqual(self.scan("--refresh").returncode, 0)
            counts.append(self.views())
        # The first refresh asks once for each session; s1's record is not final, so each later refresh asks once.
        self.assertEqual(counts, [2, 3, 4])

    def test_a_pr_gh_cannot_find_14_days_after_ready_is_not_asked_about_again(self) -> None:
        self.answer(["pr", "view"], "", "no pull requests found\n", 1)
        self.logs.ready_session(at=NOW - timedelta(days=15))
        counts = []
        for _ in range(3):
            self.assertEqual(self.scan("--refresh").returncode, 0)
            counts.append(self.views())
        self.assertEqual(counts, [1, 1, 1])
        self.assertTrue(self.rows()["s1"]["deliver"]["final"])

    def test_a_pr_gh_cannot_find_less_than_14_days_after_ready_is_asked_about_again(self) -> None:
        self.answer(["pr", "view"], "", "no pull requests found\n", 1)
        self.logs.ready_session(at=NOW - timedelta(days=13))
        for _ in range(2):
            self.assertEqual(self.scan("--refresh").returncode, 0)
        self.assertEqual(self.views(), 2)
        self.assertNotIn("final", self.rows()["s1"]["deliver"])

    def test_a_refresh_keeps_a_record_whose_log_is_gone(self) -> None:
        self.logs.ready_session()
        self.record()
        self.logs.path("s1").unlink()
        self.answer_pr(pr(labels=[{"name": "miss"}]))
        result = self.scan("--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()["s1"]
        self.assertEqual((row["total_tokens"], row["deliver"]["miss"]), (20, True))


class TestBackgroundStart(ScanTest):
    def blocking_gh(self) -> Path:
        """Put a gh first on PATH whose first call waits on a pipe, then answers as the shared stand-in does."""
        gate = self.world.root / "gate"
        os.mkfifo(gate)
        shared = self.world.bin / "gh-shared"
        (self.world.bin / "gh").rename(shared)
        gh = self.world.bin / "gh"
        # Only the first call waits: it takes the pipe away once it is let through.
        gh.write_text(f"#!/bin/sh\nif [ -p {gate} ]; then cat {gate} >/dev/null; rm -f {gate}; fi\n"
                      f"exec {shared} \"$@\"\n")
        gh.chmod(0o755)
        return gate

    def test_the_start_returns_at_once_and_a_second_start_does_nothing(self) -> None:
        self.logs.ready_session()
        gate = self.blocking_gh()
        first = self.scan("--background")
        # The start came back while the refresh it started waits on gh.
        self.assertEqual((first.returncode, first.stdout, first.stderr), (0, "", ""))
        second = self.scan("--background")
        self.assertEqual((second.returncode, second.stderr), (0, ""))
        self.assertEqual(second.stdout, "a scan is already running; nothing started\n")
        with gate.open("w") as release:
            release.write("go\n")
        # The refresh holds the lock until it ends: taking it waits for that.
        with (self.world.state / "scan-refresh.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
        self.assertEqual(self.rows()["s1"]["deliver"]["pr"], URL)
        self.assertEqual(len([c for c in self.world.gh_calls() if c["args"][:2] == ["pr", "view"]]), 1)

    def test_a_start_while_a_refresh_holds_the_lock_starts_nothing(self) -> None:
        self.logs.ready_session()
        self.world.state.mkdir(mode=0o700, exist_ok=True)
        with (self.world.state / "scan-refresh.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.scan("--background")
            refresh = self.scan("--refresh")
        self.assertEqual(result.stdout, "a scan is already running; nothing started\n")
        self.assertEqual((refresh.returncode, refresh.stdout), (0, "a scan is already running; nothing done\n"))
        self.assertEqual(self.world.gh_calls(), [])
        self.assertFalse((self.world.state / "scan-rows.jsonl").exists())


THREAD = "019a0000-0000-7000-8000-000000000001"  # a made-up Codex thread id
NOT_READ = ("copied_tokens", "active_minutes", "auto_compactions", "typed_compactions", "skills")


def other_row(session: str, harness: str, tokens: tuple | None, model: str | None = None, effort: str | None = None,
              helpers: list | None = None) -> dict:
    """A row of another harness: the four token columns and their total, blank when `tokens` is None."""
    counts = dict.fromkeys(("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
                            "total_tokens"))
    if tokens is not None:
        counts.update(zip(counts, tokens))
        counts["total_tokens"] = sum(value for value in tokens if value is not None)
    return {"session": session, "harness": harness, **counts, **dict.fromkeys(NOT_READ[:4]), "model": model,
            "effort": effort, "skills": None, "helpers": helpers}


def helper_of(agent: str, tokens: tuple | None) -> dict:
    row = other_row(agent, "", tokens)
    return {"id": agent, "description": None, "brief_head": None,
            **{key: row[key] for key in ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
                                         "total_tokens")}}


class OtherHarnessTest(ScanTest):
    def codex_log(self, name: str = "codex_rollout_not_yet_seen.jsonl") -> None:
        folder = self.world.home / ".codex" / "sessions" / "2026" / "11" / "28"
        folder.mkdir(parents=True)
        shutil.copy(INPUTS / name, folder / f"rollout-2026-11-28T10-00-00-{THREAD}.jsonl")

    def cortex_stats(self) -> None:
        folder = self.world.home / ".snowflake" / "cortex" / "stats"
        folder.mkdir(parents=True)
        shutil.copy(INPUTS / "cortex_usage_not_yet_seen.json", folder / "usage.json")

    def antigravity_brain(self) -> Path:
        brain = self.world.home / ".gemini" / "antigravity-cli" / "brain"
        shutil.copytree(INPUTS / "antigravity_brain_not_yet_seen", brain)
        return brain

    def row_of(self, harness: str, session: str) -> dict:
        result = self.scan("--harness", harness, session)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return self.rows()[session]


class TestOtherHarnesses(OtherHarnessTest):
    def test_a_codex_session_log_gives_the_rows_tokens_model_and_effort(self) -> None:
        self.codex_log()
        # The last token_count holds the thread's totals: 3000 input, 2000 of it cached, and 400 output.
        self.assertEqual(self.row_of("codex", THREAD),
                         other_row(THREAD, "codex", (1000, 400, None, 2000), "gpt-test-model", "high"))

    def test_a_codex_log_with_no_usage_gives_blank_tokens(self) -> None:
        self.codex_log("codex_rollout_no_usage_not_yet_seen.jsonl")
        self.assertEqual(self.row_of("codex", THREAD), other_row(THREAD, "codex", None, "gpt-test-model", "low"))

    def test_a_codex_thread_with_no_log_gives_a_blank_row(self) -> None:
        self.assertEqual(self.row_of("codex", THREAD), other_row(THREAD, "codex", None))

    def test_the_codex_log_is_found_under_codex_home(self) -> None:
        self.codex_log()
        (self.world.home / ".codex").rename(self.world.root / "codex-home")
        result = self.scan("--harness", "codex", THREAD, CODEX_HOME=str(self.world.root / "codex-home"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()[THREAD]["total_tokens"], 3400)

    def test_the_cortex_code_stats_file_gives_the_rows_tokens_and_its_agents(self) -> None:
        self.cortex_stats()
        self.assertEqual(self.row_of("cortex-code", "cortex-session-1"), other_row(
            "cortex-session-1", "cortex-code", (590, 138, 300, 4100), "claude-sonnet-test",
            helpers=[helper_of("cortex-helper-1", (40, 8, 0, 100))]))

    def test_a_cortex_code_session_with_no_counts_or_no_entry_gives_blank_tokens(self) -> None:
        self.cortex_stats()
        for session in ("cortex-session-no-models", "cortex-session-absent"):
            with self.subTest(session=session):
                self.assertEqual(self.row_of("cortex-code", session), other_row(session, "cortex-code", None))

    def test_a_cursor_runs_row_is_blank_never_zero(self) -> None:
        self.assertEqual(self.row_of("cursor", "run-1"), other_row("run-1", "cursor", None))

    def test_an_antigravity_session_and_its_agents_transcripts_give_session_and_agent_tokens(self) -> None:
        self.antigravity_brain()
        # The session's own 2000 input, 450 output, 1000 cache read, and its agents' in their own transcripts.
        self.assertEqual(self.row_of("antigravity", "ag-session-1"), other_row(
            "ag-session-1", "antigravity", (2460, 550, None, 1010), "gemini-test-model",
            helpers=[helper_of("ag-agent-1", (400, 80, None, 0)), helper_of("ag-agent-2", (60, 20, None, 10))]))

    def test_a_missing_agent_transcript_gives_that_agent_blank_and_the_row_blank(self) -> None:
        brain = self.antigravity_brain()
        shutil.rmtree(brain / "ag-agent-2" / ".system_generated" / "logs")
        self.assertEqual(self.row_of("antigravity", "ag-session-1"), other_row(
            "ag-session-1", "antigravity", None, "gemini-test-model",
            helpers=[helper_of("ag-agent-1", (400, 80, None, 0)), helper_of("ag-agent-2", None)]))

    def test_the_antigravity_brain_is_found_under_its_app_data_dir(self) -> None:
        brain = self.antigravity_brain()
        brain.parent.rename(self.world.root / "app-data")
        result = self.scan("--harness", "antigravity", "ag-session-1",
                           ANTIGRAVITY_APP_DATA_DIR=str(self.world.root / "app-data"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()["ag-session-1"]["total_tokens"], 4020)

    def test_a_claude_code_row_names_its_harness(self) -> None:
        self.logs.ready_session()
        for args in (("s1",), ("--harness", "claude-code", "s1")):
            with self.subTest(args=args):
                self.assertEqual(self.scan(*args).returncode, 0)
                self.assertEqual((self.rows()["s1"]["harness"], self.rows()["s1"]["total_tokens"]),
                                 ("claude-code", 20))

    def test_a_harness_the_scan_does_not_know_is_bad_usage(self) -> None:
        result = self.scan("--harness", "other", "s1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage: deliver.py scan [--harness HARNESS] SESSION", result.stderr)

    def test_no_reader_starts_a_process_or_opens_a_connection(self) -> None:
        self.codex_log()
        self.cortex_stats()
        self.antigravity_brain()
        readers = deliver_kit.load("scan").scan_harness
        refused = AssertionError("a reader started a process or opened a connection")
        with mock.patch.dict(os.environ, {"HOME": str(self.world.home)}), \
                mock.patch.object(Path, "home", return_value=self.world.home), \
                mock.patch.object(subprocess, "Popen", side_effect=refused), \
                mock.patch.object(socket, "socket", side_effect=refused), \
                mock.patch.object(socket, "create_connection", side_effect=refused):
            totals = {harness: readers.read(harness, session)["total_tokens"] for harness, session in (
                ("codex", THREAD), ("cortex-code", "cortex-session-1"), ("cursor", "run-1"),
                ("antigravity", "ag-session-1"))}
        self.assertEqual(totals, {"codex": 3400, "cortex-code": 5128, "cursor": None, "antigravity": 4020})

    def test_the_help_says_where_each_harness_is_read_from(self) -> None:
        help_text = self.scan("--help").stdout
        for sentence in (
                "HARNESS is claude-code (the default), codex, cortex-code, cursor or\nantigravity, and every row "
                "names it in its harness column.",
                "The figures come\n  from the local stats file, ~/.snowflake/cortex/stats/usage.json, never from\n"
                "  Snowflake's usage view",
                "Cursor keeps no token count on disk, so every figure is blank.",
                "The scan only reads local files: it starts no process and opens no connection.",
                "a blank is never\na zero, and the report leaves the row out of its token figures and counts it."):
            self.assertIn(" ".join(sentence.split()), " ".join(help_text.split()))


class TestOtherHarnessRecords(OtherHarnessTest):
    def handed(self, harness: str, session: str) -> str:
        return json.dumps({"session": session, "harness": harness, "ready_at": stamp(READY_AT), "branch": BRANCH,
                           "cwd": str(self.world.work)})

    def test_a_ready_call_on_codex_handed_to_the_refresh_gets_its_record_and_later_refreshes(self) -> None:
        self.codex_log()
        result = self.scan("--refresh", DELIVER_SCAN_RUN=self.handed("codex", THREAD))
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[THREAD]
        self.assertEqual((row["harness"], row["total_tokens"], row["deliver"]["pr"], row["deliver"]["ready_at"]),
                         ("codex", 3400, URL, stamp(READY_AT)))
        self.assertNotIn("agents", row["deliver"])
        self.answer_pr(pr(labels=[{"name": "miss"}]))
        self.assertEqual(self.scan("--refresh").returncode, 0)  # nothing handed: the row's harness says how
        row = self.rows()[THREAD]
        self.assertEqual((row["total_tokens"], row["deliver"]["miss"]), (3400, True))

    def test_a_cursor_run_handed_to_the_refresh_keeps_its_time_and_miss_with_blank_tokens(self) -> None:
        self.answer_pr(pr(labels=[{"name": "miss"}]))
        self.assertEqual(self.scan("--refresh", DELIVER_SCAN_RUN=self.handed("cursor", "run-1")).returncode, 0)
        row = self.rows()["run-1"]
        self.assertEqual((row["total_tokens"], row["deliver"]["ready_at"], row["deliver"]["miss"]),
                         (None, stamp(READY_AT), True))

    def test_a_background_start_hands_the_run_on_another_harness_to_the_refresh(self) -> None:
        scan = deliver_kit.load("scan")
        run = SimpleNamespace(mark={"run": "run-1", "branch": BRANCH}, checkout=self.world.work)
        handed = {}
        for harness, variables in (("codex", {"CODEX_THREAD_ID": THREAD}), ("cursor", {}), ("claude-code", {}),
                                   (None, {})):
            with self.subTest(harness=harness), \
                    mock.patch.dict(os.environ, {"DELIVER_STATE_DIR": str(self.world.state), **variables}), \
                    mock.patch.object(scan.subprocess, "Popen") as popen:
                self.assertTrue(scan.start_background(harness, run))
                handed[harness] = json.loads(popen.call_args.kwargs["env"].get("DELIVER_SCAN_RUN", "null"))
        self.assertEqual({harness: found and (found["session"], found["harness"], found["branch"], found["cwd"])
                          for harness, found in handed.items()},
                         {"codex": (THREAD, "codex", BRANCH, str(self.world.work)),
                          "cursor": ("run-1", "cursor", BRANCH, str(self.world.work)), "claude-code": None, None: None})


if __name__ == "__main__":
    unittest.main()
