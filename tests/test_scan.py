"""Exercise scripts/scan.py at its command line on session logs the tests build.

Each log is written in the shape of a Claude Code session log: one JSON object per
line, helpers' transcripts under <session>/subagents/. No line comes from a real
session. Every run points HOME, the machine directory and the Claude config
directory at temporary folders.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCAN = Path(__file__).resolve().parent.parent / "scripts" / "scan.py"
MODEL = "claude-test-model-1"


def stamp(minute: float) -> str:
    """A log timestamp `minute` minutes after a fixed start, in the log's format."""
    moment = datetime(2026, 1, 5, 10, tzinfo=timezone.utc) + timedelta(minutes=minute)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Log:
    """Builds one transcript file line by line."""

    def __init__(self, session: str, agent: str | None = None) -> None:
        self.session = session
        self.agent = agent
        self.lines: list[dict] = []

    def _base(self, kind: str, minute: float) -> dict:
        line = {
            "parentUuid": None, "isSidechain": self.agent is not None, "userType": "external",
            "cwd": "/work/example", "sessionId": self.session, "version": "2.1.0",
            "gitBranch": "main", "type": kind, "uuid": str(uuid.uuid4()), "timestamp": stamp(minute),
        }
        if self.agent:
            line["agentId"] = self.agent
        return line

    def user(self, minute: float, text: str, **extra: object) -> "Log":
        line = self._base("user", minute)
        line["message"] = {"role": "user", "content": text}
        line.update(extra)
        self.lines.append(line)
        return self

    def skill(self, minute: float, path: str) -> "Log":
        """The meta line Claude Code writes when a skill loads."""
        return self.user(minute, [{"type": "text", "text": f"Base directory for this skill: {path}\n\n# Body"}],
                         isMeta=True)

    def assistant(self, minute: float, usage: tuple[int, int, int, int] | None, *, message_id: str | None = None,
                  model: str = MODEL, content: list | None = None, blocks: int = 1) -> str:
        """One response; `blocks` lines repeat its usage, as Claude Code does per content block."""
        message_id = message_id or "msg_" + uuid.uuid4().hex[:20]
        for _ in range(blocks):
            line = self._base("assistant", minute)
            line["requestId"] = "req_" + uuid.uuid4().hex[:20]
            message = {"model": model, "id": message_id, "type": "message", "role": "assistant",
                       "content": content or [{"type": "text", "text": "Done."}], "stop_reason": "end_turn"}
            if usage is not None:
                given, output, write, read = usage
                message["usage"] = {"input_tokens": given, "cache_creation_input_tokens": write,
                                    "cache_read_input_tokens": read, "output_tokens": output,
                                    "service_tier": "standard"}
            line["message"] = message
            self.lines.append(line)
        return message_id

    def agent_call(self, minute: float, usage: tuple[int, int, int, int], tool_use_id: str, prompt: str) -> str:
        return self.assistant(minute, usage, content=[{
            "type": "tool_use", "id": tool_use_id, "name": "Agent",
            "input": {"description": "helper", "prompt": prompt, "subagent_type": "general-purpose"}}])

    def compaction(self, minute: float, trigger: str) -> "Log":
        line = self._base("system", minute)
        line.update({"subtype": "compact_boundary", "content": "Conversation compacted", "level": "info",
                     "isMeta": False, "compactMetadata": {"trigger": trigger, "preTokens": 150000}})
        self.lines.append(line)
        return self

    def raw(self, line: dict) -> "Log":
        self.lines.append(line)
        return self

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in self.lines))
        return path


class TestScan(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "state"
        self.config = self.root / "claude"
        self.project = self.config / "projects" / "-work-example"
        self.session = str(uuid.uuid4())

    def log_path(self, session: str | None = None) -> Path:
        return self.project / f"{session or self.session}.jsonl"

    def helper(self, agent: str, description: str, log: Log, tool_use_id: str, **meta: object) -> None:
        folder = self.project / self.session / "subagents"
        log.write(folder / f"agent-{agent}.jsonl")
        (folder / f"agent-{agent}.meta.json").write_text(json.dumps(
            {"agentType": "general-purpose", "description": description, "toolUseId": tool_use_id, **meta}))

    def environment(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(self.state),
                "CLAUDE_CONFIG_DIR": str(self.config)}

    def scan(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCAN), *args], cwd=self.root, env=self.environment(),
                              text=True, capture_output=True)

    def rows(self, state: Path | None = None) -> list[dict]:
        path = (state or self.state) / "scan-rows.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def only_row(self) -> dict:
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_row_holds_tokens_by_kind_model_and_skills(self) -> None:
        log = Log(self.session).user(0, "Fix the bug.")
        log.skill(0.5, "/home/someone/.claude/skills/tdd")
        log.assistant(1, (10, 200, 3000, 40000), blocks=3)
        log.assistant(2, (5, 100, 1000, 50000))
        log.assistant(3, (0, 0, 0, 0), model="<synthetic>")
        log.write(self.log_path())

        result = self.scan(str(self.log_path()))

        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.only_row()
        self.assertEqual(row["session"], self.session)
        self.assertEqual(
            (row["input_tokens"], row["output_tokens"], row["cache_write_tokens"], row["cache_read_tokens"]),
            (15, 300, 4000, 90000))
        self.assertEqual(row["total_tokens"], 94315)
        self.assertEqual(row["model"], MODEL)
        self.assertEqual(row["skills"], ["tdd"])

    def test_session_named_by_id_is_found_under_the_config_directory(self) -> None:
        log = Log(self.session).user(0, "Hello.")
        log.assistant(1, (1, 2, 3, 4))
        log.write(self.log_path())

        result = self.scan(self.session)

        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.only_row()
        self.assertEqual((row["session"], row["total_tokens"]), (self.session, 10))

    def test_a_line_holding_a_unicode_line_separator_is_read_whole(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 2, 3, 4), content=[{"type": "text", "text": "one\u2028two\x85three"}])
        path = log.write(self.log_path())
        # Claude Code writes such characters raw, not as \\u escapes.
        path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in log.lines))

        self.scan(str(path))

        self.assertEqual(self.only_row()["total_tokens"], 10)

    def test_an_id_is_matched_literally_not_as_a_pattern(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 2, 3, 4))
        log.write(self.log_path())

        self.scan("*")

        self.assertIsNone(self.only_row()["total_tokens"])

    def test_helpers_tokens_are_in_the_total_and_each_helper_is_listed(self) -> None:
        main = Log(self.session).user(0, "Build it.")
        shared = main.assistant(1, (1, 10, 100, 1000))
        main.agent_call(2, (1, 10, 100, 1000), "toolu_one", "Review the diff.\nRead the files first.")
        main.agent_call(3, (1, 10, 100, 1000), "toolu_fork", "Write the tests.")
        main.write(self.log_path())
        reviewer = Log(self.session, "aone").user(2.5, "Review the diff.\nRead the files first.")
        reviewer.skill(2.6, "/home/someone/.claude/skills/code-review")
        reviewer.assistant(3, (2, 20, 200, 2000), blocks=2)
        self.helper("aone", "Review the change", reviewer, "toolu_one")
        # A forked helper's log starts with a copy of its parent's context: that line was paid for once.
        fork = Log(self.session, "afork").raw({"type": "fork-context-ref", "agentId": "afork"})
        fork.assistant(1, (1, 10, 100, 1000), message_id=shared)
        fork.assistant(4, (3, 30, 300, 3000))
        self.helper("afork", "Write the tests", fork, "toolu_fork", agentType="fork")
        silent = Log(self.session, "asilent").user(5, "Look around.")
        self.helper("asilent", "Never answered", silent, "toolu_missing")

        result = self.scan(str(self.log_path()))

        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.only_row()
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["cache_write_tokens"],
                          row["cache_read_tokens"], row["total_tokens"]), (8, 80, 800, 8000, 8888))
        self.assertEqual(row["skills"], ["code-review"])
        self.assertEqual(row["helpers"], [
            {"id": "afork", "description": "Write the tests", "brief_head": "Write the tests.",
             "input_tokens": 3, "output_tokens": 30, "cache_write_tokens": 300, "cache_read_tokens": 3000,
             "total_tokens": 3333},
            {"id": "aone", "description": "Review the change",
             "brief_head": "Review the diff.\nRead the files first.", "input_tokens": 2, "output_tokens": 20,
             "cache_write_tokens": 200, "cache_read_tokens": 2000, "total_tokens": 2222},
            {"id": "asilent", "description": "Never answered", "brief_head": "Look around.",
             "input_tokens": None, "output_tokens": None, "cache_write_tokens": None,
             "cache_read_tokens": None, "total_tokens": None},
        ])

    def test_a_response_copied_into_a_nested_fork_belongs_to_the_helper_that_made_it(self) -> None:
        main = Log(self.session).user(0, "Build it.")
        main.agent_call(1, (1, 1, 1, 1), "toolu_parent", "Plan the work.")
        main.write(self.log_path())
        parent = Log(self.session, "aplan").user(1.5, "Plan the work.")
        planned = parent.assistant(2, (1, 10, 100, 1000))
        parent.agent_call(3, (1, 10, 100, 1000), "toolu_child", "Fork: draft part one.")
        self.helper("aplan", "Plan", parent, "toolu_parent", spawnDepth=1)
        # Forks of a helper copy its context. File names sort the grandchild first and the parent last.
        child = Log(self.session, "adraft").user(1.5, "Plan the work.")
        child.assistant(2, (1, 10, 100, 1000), message_id=planned)
        drafted = child.agent_call(4, (2, 20, 200, 2000), "toolu_grandchild", "Fork: check part one.")
        self.helper("adraft", "Draft", child, "toolu_child", isFork=True, spawnDepth=2, parentAgentId="aplan")
        grandchild = Log(self.session, "acheck").user(1.5, "Plan the work.")
        grandchild.assistant(2, (1, 10, 100, 1000), message_id=planned)
        grandchild.assistant(4, (2, 20, 200, 2000), message_id=drafted)
        grandchild.assistant(5, (3, 30, 300, 3000))
        self.helper("acheck", "Check", grandchild, "toolu_grandchild",
                    isFork=True, spawnDepth=3, parentAgentId="adraft")

        self.scan(str(self.log_path()))

        row = self.only_row()
        self.assertEqual(row["total_tokens"], 4 + 2222 + 2222 + 3333)
        self.assertEqual([(helper["id"], helper["total_tokens"]) for helper in row["helpers"]],
                         [("acheck", 3333), ("adraft", 2222), ("aplan", 2222)])

    def test_brief_head_is_cut_to_its_first_200_characters(self) -> None:
        main = Log(self.session).user(0, "Go.")
        main.agent_call(1, (1, 1, 1, 1), "toolu_long", "x" * 500)
        main.write(self.log_path())
        self.helper("along", "Long brief", Log(self.session, "along").user(1.5, "x" * 500), "toolu_long")

        self.scan(str(self.log_path()))

        self.assertEqual(self.only_row()["helpers"][0]["brief_head"], "x" * 200)


    def test_active_minutes_sum_gaps_under_30_minutes_helpers_included(self) -> None:
        main = Log(self.session).user(0, "Start.")
        main.assistant(10, (1, 1, 1, 1))
        main.user(50, "Back after a break.")  # 40 minutes after the last main line
        main.assistant(55, (1, 1, 1, 1))
        main.user(85, "Exactly 30 minutes later.")
        main.write(self.log_path())
        # The helper's lines split the 40-minute gap into 20 and 20, both counted.
        self.helper("aone", "Busy", Log(self.session, "aone").user(30, "Work.").raw({"type": "mode"}), "toolu_x")

        self.scan(str(self.log_path()))

        self.assertEqual(self.only_row()["active_minutes"], 55.0)

    def test_automatic_and_typed_compactions_are_counted_apart(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.compaction(2, "auto").compaction(3, "manual").compaction(4, "auto")
        log.write(self.log_path())

        self.scan(str(self.log_path()))

        row = self.only_row()
        self.assertEqual((row["auto_compactions"], row["typed_compactions"]), (2, 1))

    def test_a_session_with_no_compaction_records_zero_not_blank(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())

        self.scan(str(self.log_path()))

        row = self.only_row()
        self.assertEqual((row["auto_compactions"], row["typed_compactions"], row["skills"], row["helpers"]),
                         (0, 0, [], []))

    def assert_blank_row(self, session: str) -> None:
        text = (self.state / "scan-rows.jsonl").read_text()
        row = self.only_row()
        self.assertEqual(row["session"], session)
        self.assertEqual({key for key, value in row.items() if value is not None}, {"session"})
        self.assertNotIn(": 0", text)

    def test_a_session_whose_log_is_gone_gets_a_row_of_blanks(self) -> None:
        missing = str(uuid.uuid4())

        result = self.scan(missing)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_blank_row(missing)

    def test_a_missing_log_named_by_path_gets_a_row_of_blanks(self) -> None:
        result = self.scan(str(self.log_path()))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_blank_row(self.session)

    def test_a_log_with_no_token_counts_gets_a_row_of_blanks(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, None)
        log.assistant(2, (0, 0, 0, 0), model="<synthetic>")
        log.compaction(3, "manual")
        log.write(self.log_path())

        self.scan(str(self.log_path()))

        self.assert_blank_row(self.session)

    def test_scanning_the_same_session_twice_leaves_one_row(self) -> None:
        other = Log("other").user(0, "Other.")
        other.assistant(1, (1, 1, 1, 1))
        other.write(self.log_path("other"))
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        self.scan(str(self.log_path("other")))
        self.scan(str(self.log_path()))
        log.assistant(2, (1, 1, 1, 1))
        log.write(self.log_path())

        self.scan(self.session)

        rows = {row["session"]: row for row in self.rows()}
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual((rows["other"]["total_tokens"], rows[self.session]["total_tokens"]), (4, 8))

    def test_rows_go_to_the_machine_directory_and_nowhere_else(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        def outside_state() -> list[Path]:
            return sorted(path for path in self.root.rglob("*") if path != self.state and self.state not in path.parents)
        before = outside_state()

        self.scan(str(self.log_path()))

        self.assertEqual(outside_state(), before)
        self.assertEqual(sorted(path.name for path in self.state.iterdir()), ["scan-rows.jsonl", "scan-rows.lock"])

    def test_the_machine_directory_defaults_to_local_state_deliver(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        environment = self.environment()
        del environment["DELIVER_STATE_DIR"]

        result = subprocess.run([sys.executable, str(SCAN), str(self.log_path())], cwd=self.root,
                                env=environment, text=True, capture_output=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.rows(self.root / "home" / ".local" / "state" / "deliver")), 1)

    def test_without_one_session_named_it_prints_usage_and_exits_2(self) -> None:
        result = self.scan()

        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertFalse(self.state.exists())

    def test_a_relative_log_path_may_start_with_a_dash(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 2, 3, 4))
        log.write(self.root / "-work-example" / f"{self.session}.jsonl")

        result = self.scan(f"-work-example/{self.session}.jsonl")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.only_row()["total_tokens"], 10)

    def test_an_unknown_option_prints_usage_and_exits_2(self) -> None:
        result = self.scan("--verbose")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.state.exists())

    def test_scans_run_at_once_keep_every_row(self) -> None:
        scans = [subprocess.Popen([sys.executable, str(SCAN), str(self.log_path(f"gone-{number}"))],
                                  cwd=self.root, env=self.environment(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 for number in range(40)]
        self.assertEqual([process.wait() for process in scans], [0] * 40)

        self.assertEqual(len(self.rows()), 40)

    def test_help_prints_usage_and_writes_no_row(self) -> None:
        result = self.scan("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
