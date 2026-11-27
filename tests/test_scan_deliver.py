"""Exercise the second half of `deliver.py scan`: the record of a `deliver` PR.

Each test builds Claude Code session logs in a throwaway config folder, answers `gh` with the
shared stand-in, and runs `deliver.py scan` at its command line with a scratch machine directory.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deliver_kit import World  # noqa: E402

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
            "pr": URL, "ready_at": stamp(READY_AT + timedelta(hours=1)),
            "note": "the record of this PR is the row of session s1, which called ready first"})

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


if __name__ == "__main__":
    unittest.main()
