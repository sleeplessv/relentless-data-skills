"""Exercise scripts/scan.py at its command line on session logs the tests build.

Each log is written in the shape of a Claude Code session log: one JSON object per
line, helpers' transcripts under <session>/subagents/. No line comes from a real
session. Every run points HOME, the machine directory and the Claude config
directory at temporary folders.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
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


def figures(given: int, output: int, write: int, read: int) -> dict[str, int]:
    """A row's token columns."""
    return {"input_tokens": given, "output_tokens": output, "cache_write_tokens": write, "cache_read_tokens": read,
            "total_tokens": given + output + write + read}


def whole_row(session: str, tokens: tuple[int, int, int, int], minutes: float, *, copied: int = 0,
              skills: tuple[str, ...] = (), helpers: tuple[dict, ...] = ()) -> dict:
    """A row of a log with no compaction whose responses name MODEL."""
    return {"session": session, **figures(*tokens), "copied_tokens": copied, "active_minutes": minutes,
            "auto_compactions": 0, "typed_compactions": 0, "model": MODEL, "skills": list(skills),
            "helpers": list(helpers)}


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

    def skill(self, minute: float, path: str, **extra: object) -> "Log":
        """The meta line Claude Code writes when a skill loads; a Skill call's id goes in sourceToolUseID."""
        return self.user(minute, [{"type": "text", "text": f"Base directory for this skill: {path}\n\n# Body"}],
                         isMeta=True, **extra)

    def skill_call(self, minute: float, tool_use_id: str, skill: object, *, folder: str | None = None,
                   failed: bool = False, answered: bool = True, tool_input: object = None) -> "Log":
        """A Skill call, its result unless not `answered`, and the folder line that names the call, if any.

        `tool_input` replaces the call's {"skill": skill}."""
        self.assistant(minute, None, content=[{"type": "tool_use", "id": tool_use_id, "name": "Skill",
                                               "input": {"skill": skill} if tool_input is None else tool_input}])
        if answered:
            self.user(minute, [{"type": "tool_result", "tool_use_id": tool_use_id, "content": "Launching skill",
                                **({"is_error": True} if failed else {})}])
        if folder is not None:
            self.skill(minute, folder, sourceToolUseID=tool_use_id)
        return self

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

    def agent_call(self, minute: float, usage: tuple[int, int, int, int] | None, tool_use_id: str,
                   prompt: str) -> str:
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

    def helper(self, agent: str, description: str | None, log: Log, tool_use_id: str, **meta: object) -> None:
        folder = self.project / self.session / "subagents"
        log.write(folder / f"agent-{agent}.jsonl")
        (folder / f"agent-{agent}.meta.json").write_text(json.dumps(
            {"agentType": "general-purpose", "description": description, "toolUseId": tool_use_id, **meta}))

    def environment(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(self.state),
                "CLAUDE_CONFIG_DIR": str(self.config)}

    def scan(self, *args: str, umask: int = -1) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCAN), *args], cwd=self.root, env=self.environment(),
                              text=True, capture_output=True, umask=umask)

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
        grandchild = Log(self.session, "acheck").user(1.5, "Plan the work.")
        grandchild.assistant(2, (1, 10, 100, 1000), message_id=planned)
        grandchild.assistant(4, (2, 20, 200, 2000), message_id=drafted)
        grandchild.assistant(5, (3, 30, 300, 3000))
        self.helper("acheck", "Check", grandchild, "toolu_grandchild",
                    isFork=True, spawnDepth=3, parentAgentId="adraft")
        for depth in ({"spawnDepth": 2}, {}):
            with self.subTest(child=depth):
                self.state = self.root / f"state-{len(depth)}"
                self.helper("adraft", "Draft", child, "toolu_child", isFork=True, parentAgentId="aplan", **depth)

                result = self.scan(str(self.log_path()))

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.rows(), [whole_row(self.session, (8, 71, 701, 7001), 5.0, helpers=(
                    {"id": "acheck", "description": "Check", "brief_head": "Fork: check part one.",
                     **figures(3, 30, 300, 3000)},
                    {"id": "adraft", "description": "Draft", "brief_head": "Fork: draft part one.",
                     **figures(2, 20, 200, 2000)},
                    {"id": "aplan", "description": "Plan", "brief_head": "Plan the work.",
                     **figures(2, 20, 200, 2000)}))])

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
        self.assertEqual(self.rows(), [{"session": session, **dict.fromkeys([
            "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens", "total_tokens", "copied_tokens",
            "active_minutes", "auto_compactions", "typed_compactions", "model", "skills", "helpers"])}])

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

    def test_a_workflow_helper_in_a_subfolder_is_read(self) -> None:
        main = Log(self.session).user(0, "Run the workflow.")
        main.assistant(1, (1, 2, 3, 4))
        main.write(self.log_path())
        worker = Log(self.session, "aworker").user(2, "Step one.")
        worker.assistant(11, (2, 4, 6, 8))
        worker.write(self.project / self.session / "subagents" / "workflows" / "wf_example1" / "agent-aworker.jsonl")

        self.scan(str(self.log_path()))

        row = self.only_row()
        self.assertEqual((row["total_tokens"], row["active_minutes"]), (30, 11.0))
        self.assertEqual([(helper["id"], helper["total_tokens"]) for helper in row["helpers"]], [("aworker", 20)])

    def test_a_response_counts_at_its_final_usage(self) -> None:
        main = Log(self.session).user(0, "Go.")
        main.agent_call(1, (1, 1, 1, 1), "toolu_one", "Write it.")
        main.write(self.log_path())
        helper = Log(self.session, "aone").user(1.5, "Write it.")
        response = helper.assistant(2, (10, 1, 0, 0))
        helper.assistant(2.5, (10, 90, 0, 0), message_id=response)
        self.helper("aone", "Write", helper, "toolu_one")

        self.scan(str(self.log_path()))

        row = self.only_row()
        self.assertEqual((row["total_tokens"], row["helpers"][0]["total_tokens"]), (104, 100))

    def test_a_forks_early_copy_of_a_response_does_not_replace_its_final_count(self) -> None:
        main = Log(self.session).user(0, "Go.")
        response = main.assistant(1, (5, 1, 0, 0))
        main.assistant(1.5, (5, 50, 0, 0), message_id=response)
        main.write(self.log_path())
        fork = Log(self.session, "afork").raw({"type": "fork-context-ref", "agentId": "afork"})
        fork.assistant(1, (5, 1, 0, 0), message_id=response)
        fork.assistant(3, (2, 3, 0, 0))
        self.helper("afork", "Fork", fork, "toolu_fork", agentType="fork", spawnDepth=1)

        self.scan(str(self.log_path()))

        row = self.only_row()
        self.assertEqual((row["total_tokens"], row["output_tokens"], row["helpers"][0]["total_tokens"]), (60, 53, 5))

    def test_usage_with_no_token_counts_gives_a_row_of_blanks(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (0, 0, 0, 0))
        log.lines[-1]["message"]["usage"] = {"service_tier": "standard"}
        log.write(self.log_path())

        self.scan(str(self.log_path()))

        self.assert_blank_row(self.session)

    def test_a_skill_loaded_by_a_skill_call_is_listed_and_a_failed_call_is_not(self) -> None:
        log = Log(self.session).user(0, "Go.")
        for minute, tool_use_id, name, failed in ((1, "toolu_ok", "example-plugin:bundled", False),
                                                  (2, "toolu_failed", "missing", True)):
            log.assistant(minute, (1, 1, 1, 1), content=[
                {"type": "tool_use", "id": tool_use_id, "name": "Skill", "input": {"skill": name}}])
            log.user(minute + 0.5, [{"type": "tool_result", "tool_use_id": tool_use_id, "is_error": failed,
                                     "content": "Launching skill"}])
        log.write(self.log_path())

        self.scan(str(self.log_path()))

        self.assertEqual(self.only_row()["skills"], ["bundled"])

    def assert_skills(self, log: Log, skills: list[str]) -> None:
        """Scan `log`, ended by one response at minute 10, and check its whole row."""
        log.assistant(10, (1, 1, 1, 1))
        result = self.scan(str(log.write(self.log_path())))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows(), [whole_row(self.session, (1, 1, 1, 1), 10.0, skills=tuple(skills))])

    def test_a_skill_a_call_loaded_takes_the_calls_name_and_its_folder_adds_none(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.skill_call(1, "toolu_alpha", "plug:alpha", folder="/home/someone/.claude/plugins/plug/alpha-folder")

        self.assert_skills(log, ["alpha"])

    def test_a_typed_skill_takes_its_folders_name(self) -> None:
        log = Log(self.session).user(0, "/alpha-folder")
        log.skill(1, "/home/someone/.claude/skills/alpha-folder")

        self.assert_skills(log, ["alpha-folder"])

    def test_a_bundled_skill_takes_the_calls_name_without_its_prefix(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.skill_call(1, "toolu_bundled", "plug:bundled")

        self.assert_skills(log, ["bundled"])

    def test_a_folder_loaded_by_a_call_and_typed_is_one_entry_named_by_the_call(self) -> None:
        folder = "/home/someone/.claude/plugins/plug/alpha-folder"
        for typed_first in (True, False):
            with self.subTest(typed_first=typed_first):
                self.state = self.root / f"state-{typed_first}"
                log = Log(self.session).user(0, "Go.")
                if typed_first:
                    log.skill(1, folder)
                log.skill_call(2, "toolu_beta", "plug:beta", folder="/home/someone/.claude/plugins/plug/beta")
                log.skill_call(3, "toolu_alpha", "plug:alpha", folder=folder)
                if not typed_first:
                    log.skill(4, folder)

                self.assert_skills(log, ["alpha", "beta"] if typed_first else ["beta", "alpha"])

    def test_two_plugins_skills_of_one_name_are_one_entry(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.skill_call(1, "toolu_one", "one:alpha", folder="/home/someone/.claude/plugins/one/alpha")
        log.skill_call(2, "toolu_two", "two:alpha", folder="/home/someone/.claude/plugins/two/alpha")

        self.assert_skills(log, ["alpha"])

    def test_each_shape_of_a_skill_load_gives_one_name(self) -> None:
        alpha, beta = "/home/someone/.claude/skills/alpha-folder", "/home/someone/.claude/skills/beta-folder"

        def bash(log: Log) -> None:
            log.assistant(1, None, content=[{"type": "tool_use", "id": "toolu_bash", "name": "Bash", "input": {}}])
            log.skill(1, alpha, sourceToolUseID="toolu_bash")

        def two_texts(log: Log) -> None:
            log.user(1, [{"type": "text", "text": f"Base directory for this skill: {folder}\n\n# Body"}
                         for folder in (alpha, beta)], isMeta=True)
        # The rule is in the scan's docstring. Each shape: what the log holds after its first line, and the skills.
        shapes = {
            "a folder line naming a call not in the lines": (
                lambda log: log.skill(1, alpha, sourceToolUseID="toolu_gone"), ["alpha-folder"]),
            "a folder line naming a call that is no Skill call": (bash, ["alpha-folder"]),
            "a folder line naming a failed Skill call": (
                lambda log: log.skill_call(1, "toolu_a", "plug:alpha", folder=alpha, failed=True), ["alpha-folder"]),
            "a folder line naming a Skill call with no result": (
                lambda log: log.skill_call(1, "toolu_a", "plug:alpha", folder=alpha, answered=False),
                ["alpha-folder"]),
            "a sourceToolUseID that is not text": (
                lambda log: log.skill(1, alpha, sourceToolUseID=["toolu_a"]), ["alpha-folder"]),
            "a call with no skill input": (
                lambda log: log.skill_call(1, "toolu_a", None, folder=alpha, tool_input={}), ["alpha-folder"]),
            "a call whose skill input is not text": (
                lambda log: log.skill_call(1, "toolu_a", 7, folder=alpha), ["alpha-folder"]),
            "a call whose skill input is empty": (
                lambda log: log.skill_call(1, "toolu_a", "", folder=alpha), ["alpha-folder"]),
            "a call for a plugin and no skill": (
                lambda log: log.skill_call(1, "toolu_a", "plug:", folder=alpha), ["alpha-folder"]),
            "a call for a plugin and no skill, with no folder line": (
                lambda log: log.skill_call(1, "toolu_a", "plug:"), []),
            "a call whose skill input holds two colons": (
                lambda log: log.skill_call(1, "toolu_a", "one:two:alpha", folder=alpha), ["alpha"]),
            "a call whose input is not an object": (
                lambda log: log.skill_call(1, "toolu_a", None, folder=alpha, tool_input="plug:alpha"),
                ["alpha-folder"]),
            "two folders with the same last name": (
                lambda log: log.skill(1, "/one/alpha").skill(2, "/two/alpha"), ["alpha"]),
            "a folder whose name is another skill's call name": (
                lambda log: log.skill(1, "/one/alpha").skill_call(2, "toolu_a", "plug:alpha", folder=beta),
                ["alpha"]),
            "one line with two folder texts": (two_texts, ["alpha-folder", "beta-folder"]),
            "a folder path that ends in a slash": (
                lambda log: log.skill_call(1, "toolu_a", "plug:alpha", folder=alpha).skill(2, alpha + "/")
                .skill(3, beta + "/"), ["alpha", "beta-folder"]),
            "one skill loaded by two calls": (
                lambda log: log.skill_call(1, "toolu_a", "plug:alpha", folder=alpha)
                .skill_call(2, "toolu_b", "plug:alpha", folder=alpha), ["alpha"]),
            "a later call of another name for an earlier call's folder": (
                lambda log: log.skill_call(1, "toolu_old", "plug:old", folder=alpha)
                .skill_call(2, "toolu_middle", "plug:middle", folder=beta)
                .skill_call(3, "toolu_new", "plug:new", folder=alpha), ["old", "middle", "new"]),
            "a typed load of a folder two calls of other names loaded": (
                lambda log: log.skill(1, alpha).skill_call(2, "toolu_new", "plug:new", folder=alpha)
                .skill_call(3, "toolu_old", "plug:old", folder=alpha), ["new", "old"]),
        }
        for number, (shape, (build, skills)) in enumerate(shapes.items()):
            with self.subTest(shape=shape):
                self.state = self.root / f"state-{number}"
                log = Log(self.session).user(0, "Go.")
                build(log)

                self.assert_skills(log, skills)

    def test_a_call_and_its_folder_line_pair_across_the_main_log_and_a_helpers(self) -> None:
        plugins = "/home/someone/.claude/plugins/plug"
        main = Log(self.session).user(0, "Go.")
        main.skill_call(1, "toolu_alpha", "plug:alpha")
        main.agent_call(2, (1, 1, 1, 1), "toolu_one", "Look.")
        main.skill(3, f"{plugins}/beta-folder", sourceToolUseID="toolu_beta")
        main.skill_call(4, "toolu_gamma", "plug:gamma", folder=f"{plugins}/gamma-folder")
        main.agent_call(5, (1, 1, 1, 1), "toolu_fork", "Fork: go on.")
        main.write(self.log_path())
        helper = Log(self.session, "aone").user(2, "Look.")
        helper.skill(2, f"{plugins}/alpha-folder", sourceToolUseID="toolu_alpha")
        helper.skill_call(2, "toolu_beta", "plug:beta")
        helper.assistant(3, (2, 2, 2, 2))
        self.helper("aone", "Look", helper, "toolu_one")
        # A forked helper's log starts with a copy of its parent's lines, the Skill call's among them.
        fork = Log(self.session, "afork").raw({"type": "fork-context-ref", "agentId": "afork"})
        for line in main.lines:
            fork.raw(line)
        fork.assistant(6, (3, 3, 3, 3))
        self.helper("afork", "Fork", fork, "toolu_fork", agentType="fork")

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows(), [whole_row(
            self.session, (7, 7, 7, 7), 6.0, skills=("alpha", "beta", "gamma"), helpers=(
                {"id": "afork", "description": "Fork", "brief_head": "Fork: go on.", **figures(3, 3, 3, 3)},
                {"id": "aone", "description": "Look", "brief_head": "Look.", **figures(2, 2, 2, 2)}))])

    def test_skills_are_in_the_order_of_first_load_by_time_across_the_logs(self) -> None:
        main = Log(self.session).user(0, "Go.")
        main.agent_call(0, (1, 1, 1, 1), "toolu_one", "Look.")
        main.agent_call(0, (1, 1, 1, 1), "toolu_two", "Look again.")
        main.skill(1, "/skills/first").skill(5, "/skills/last")
        main.write(self.log_path())
        for agent, prompt, minute, folder in (("aone", "Look.", 3, "/skills/third"),
                                              ("atwo", "Look again.", 2, "/skills/second")):
            helper = Log(self.session, agent).user(2, prompt).skill(minute, folder)
            helper.assistant(minute, (1, 1, 1, 1))
            self.helper(agent, prompt.rstrip("."), helper, "toolu_one" if agent == "aone" else "toolu_two")

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows(), [whole_row(
            self.session, (4, 4, 4, 4), 5.0, skills=("first", "second", "third", "last"), helpers=(
                {"id": "aone", "description": "Look", "brief_head": "Look.", **figures(1, 1, 1, 1)},
                {"id": "atwo", "description": "Look again", "brief_head": "Look again.", **figures(1, 1, 1, 1)}))])

    def test_a_load_with_no_time_takes_the_time_of_the_line_before_it(self) -> None:
        main = Log(self.session).user(0, "Go.")
        main.agent_call(0, (1, 1, 1, 1), "toolu_one", "Look.")
        main.skill(4, "/skills/main-four").skill(4.5, "/skills/main-untimed").skill(6, "/skills/main-six")
        del main.lines[-2]["timestamp"]
        main.write(self.log_path())
        helper = Log(self.session, "aone").user(1, "Look.").skill(2, "/skills/helper-untimed")
        helper.lines[-1]["timestamp"] = None
        helper.skill(5, "/skills/helper-five").assistant(5, (1, 1, 1, 1))
        self.helper("aone", "Look", helper, "toolu_one")

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows(), [whole_row(
            self.session, (2, 2, 2, 2), 6.0,
            skills=("helper-untimed", "main-four", "main-untimed", "helper-five", "main-six"),
            helpers=({"id": "aone", "description": "Look", "brief_head": "Look.", **figures(1, 1, 1, 1)},))])

    def test_skills_read_lines_whose_times_the_scan_would_refuse_without_stopping(self) -> None:
        # The draw passes skills() lines whose times nothing has checked, so this calls it in the scan's module.
        spec = importlib.util.spec_from_file_location("scan_under_test", SCAN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        log = Log(self.session)
        for stamp_given, folder in ((7, "/skills/not-text"), ("soon", "/skills/unreadable"),
                                    ("2026-01-05T10:03:00", "/skills/no-zone"), ("2026-01-05T10:02:00Z", "/skills/utc"),
                                    ("2026-01-05T10:01:00+01:00", "/skills/an-hour-east")):
            log.skill(0, folder)
            log.lines[-1]["timestamp"] = stamp_given

        self.assertEqual(module.skills(log.lines), ["not-text", "unreadable", "an-hour-east", "utc", "no-zone"])

    def test_copied_tokens_hold_the_responses_only_copied_lines_carry(self) -> None:
        earlier = str(uuid.uuid4())

        def resumed(copied: list[tuple[str | None, tuple | None]], own: list[tuple[str | None, tuple | None]]) -> Log:
            """A log whose lines carry the earlier session's id, then its own; each response is (id, usage)."""
            log, later = Log(earlier).user(0, "Go."), Log(self.session).user(2, "Go on.")
            for message_id, usage in copied:
                log.assistant(1, usage, message_id=message_id)
            for message_id, usage in own:
                later.assistant(3, usage, message_id=message_id)
            log.lines += later.lines
            return log

        def no_session_id(value: object) -> Log:
            log = resumed([(None, (0, 100, 0, 0))], [(None, (0, 10, 0, 0))])
            log.lines[-1]["sessionId"] = value
            if value == "missing":
                del log.lines[-1]["sessionId"]
            return log
        cases = {  # the log, its row's output_tokens, copied_tokens and active_minutes
            "100 copied output tokens and 10 of its own": (
                resumed([(None, (0, 100, 0, 0))], [(None, (0, 10, 0, 0))]), 110, 100, 3.0),
            "no copied line": (Log(self.session).raw(resumed([], [(None, (0, 10, 0, 0))]).lines[-1]), 10, 0, 0.0),
            "a response on a copied line and on the session's own": (
                resumed([("msg_both", (0, 100, 0, 0))], [("msg_both", (0, 100, 0, 0)), (None, (0, 10, 0, 0))]),
                110, 0, 3.0),
            "a response on a copied line and on an own line with no token counts": (
                resumed([("msg_both", (0, 100, 0, 0))], [("msg_both", None), (None, (0, 10, 0, 0))]), 110, 0, 3.0),
            "a larger final count on the copied line": (
                resumed([("msg_both", (0, 100, 0, 0))], [("msg_both", (0, 40, 0, 0))]), 100, 0, 3.0),
            "a larger final count on the session's own line": (
                resumed([("msg_both", (0, 40, 0, 0))], [("msg_both", (0, 100, 0, 0))]), 100, 0, 3.0),
            "a line with no session id": (no_session_id("missing"), 110, 100, 3.0),
            "a line with a null session id": (no_session_id(None), 110, 100, 3.0),
            "a line whose session id is not text": (no_session_id(7), 110, 100, 3.0),
            "copied lines with no token counts": (resumed([(None, None)], [(None, (0, 10, 0, 0))]), 10, 0, 3.0),
            "token counts on copied lines alone": (resumed([(None, (0, 100, 0, 0))], [(None, None)]), 100, 100, 3.0),
        }
        for number, (case, (log, output, copied, minutes)) in enumerate(cases.items()):
            with self.subTest(case=case):
                self.state = self.root / f"state-{number}"

                result = self.scan(str(log.write(self.log_path())))

                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertEqual(self.rows(), [whole_row(self.session, (0, output, 0, 0), minutes, copied=copied)])

    def test_copied_lines_in_a_helpers_log_count_and_a_response_a_helper_repeats_does_not(self) -> None:
        earlier = str(uuid.uuid4())
        main = Log(earlier).user(0, "Go.")
        shared = main.assistant(0, (0, 0, 0, 100))
        later = Log(self.session).user(0.5, "Go on.")
        later.agent_call(1, (1, 0, 0, 0), "toolu_one", "Look.")
        main.lines += later.lines
        main.write(self.log_path())
        helper = Log(self.session, "aone").user(1.5, "Look.")
        helper.assistant(2, (0, 0, 0, 100), message_id=shared)
        copied = Log(earlier, "aone")
        copied.assistant(2.5, (0, 0, 100, 0))
        helper.lines += copied.lines
        helper.assistant(3, (0, 1, 0, 0))
        self.helper("aone", "Look", helper, "toolu_one")

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows(), [whole_row(self.session, (1, 1, 100, 100), 3.0, copied=100, helpers=(
            {"id": "aone", "description": "Look", "brief_head": "Look.", **figures(0, 1, 100, 0)},))])

    def test_a_log_is_keyed_by_the_session_id_inside_it(self) -> None:
        sessions = [str(uuid.uuid4()), str(uuid.uuid4())]
        for number, session in enumerate(sessions):
            log = Log(session).user(0, "Go.")
            log.assistant(1, (1, 1, 1, 1))
            log.write(self.root / f"saved-{number}" / "saved.jsonl")
            self.scan(str(self.root / f"saved-{number}" / "saved.jsonl"))

        self.assertEqual(sorted(row["session"] for row in self.rows()), sorted(sessions))

    def test_a_log_that_starts_with_another_sessions_lines_is_keyed_by_its_own_name(self) -> None:
        other = str(uuid.uuid4())
        source = Log(other).user(0, "Go.")
        source.assistant(1, (1, 1, 1, 1))
        source.write(self.log_path(other))
        log = Log(self.session).user(2, "Go on.")
        log.assistant(3, (2, 2, 2, 2))
        log.lines[:0] = source.lines
        log.write(self.log_path())

        for path in (self.log_path(other), self.log_path()):
            self.scan(str(path))

        self.assertEqual(sorted(row["session"] for row in self.rows()), sorted([other, self.session]))

    def test_the_machine_directory_its_rows_and_its_lock_are_owner_only_under_any_umask(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        for umask in (0o022, 0o077):
            for existing in (False, True):
                with self.subTest(umask=oct(umask), existing=existing):
                    self.state = self.root / f"state-{umask:o}-{existing}"
                    if existing:  # made by an earlier version, with looser modes
                        self.state.mkdir()
                        self.state.chmod(0o755)
                        (self.state / "scan-rows.lock").touch()
                        (self.state / "scan-rows.lock").chmod(0o644)

                    result = self.scan(str(self.log_path()), umask=umask)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual({path.name: oct(stat.S_IMODE(path.stat().st_mode))
                                      for path in (self.state, *self.state.iterdir())},
                                     {self.state.name: "0o700", "scan-rows.jsonl": "0o600", "scan-rows.lock": "0o600"})

    def test_a_helper_without_a_description_takes_its_dispatch_description(self) -> None:
        main = Log(self.session).user(0, "Go.")
        main.agent_call(1, (1, 1, 1, 1), "toolu_one", "Look.")
        main.write(self.log_path())
        self.helper("aone", None, Log(self.session, "aone").user(1.5, "Look."), "toolu_one")

        self.scan(str(self.log_path()))

        self.assertEqual(self.only_row()["helpers"][0]["description"], "helper")

    def test_a_damaged_line_before_the_last_stops_the_scan_and_keeps_the_row(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.assistant(2, (2, 2, 2, 2))
        log.write(self.log_path())
        self.scan(str(self.log_path()))
        text = self.log_path().read_text().split("\n")
        text[1] = text[1][:40]
        self.log_path().write_text("\n".join(text))

        result = self.scan(str(self.log_path()))

        self.assertEqual(result.returncode, 1)
        self.assertIn(":2:", result.stderr)
        self.assertEqual(self.only_row()["total_tokens"], 12)

    def test_a_line_nested_too_deep_is_skipped_while_cut_off_at_the_end_and_refused_once_ended(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        with self.log_path().open("a") as file:
            file.write("[" * 12000)
        cut_off = self.scan(str(self.log_path()))
        self.assertEqual((cut_off.returncode, cut_off.stderr), (0, ""))
        self.assertEqual(self.only_row()["total_tokens"], 4)
        with self.log_path().open("a") as file:
            file.write("\n")
        self.state = self.root / "state-ended"

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, "", f"{self.log_path()}:3: not a JSON line\n"))
        self.assertFalse(self.state.exists())

    def test_a_last_line_cut_off_mid_write_is_skipped(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        with self.log_path().open("a") as file:
            file.write('{"type": "assistant", "message": {"usa')

        result = self.scan(str(self.log_path()))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.only_row()["total_tokens"], 4)

    def test_help_prints_usage_and_writes_no_row(self) -> None:
        result = self.scan("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertFalse(self.state.exists())


    def test_a_parent_chain_that_loops_names_itself_or_names_no_helper_still_gives_every_response_once(self) -> None:
        main = Log(self.session).user(0, "Build it.")
        main.assistant(1, (1, 1, 1, 1))
        main.write(self.log_path())
        for agent, parent_id, usage in (("aloop", "bloop", (1, 0, 0, 0)), ("bloop", "aloop", (0, 1, 0, 0)),
                                        ("aself", "aself", (0, 0, 1, 0)), ("aorphan", "agone", (0, 0, 0, 1))):
            log = Log(self.session, agent).user(2, "Work.")
            log.assistant(3, usage)
            self.helper(agent, agent, log, "toolu_" + agent, parentAgentId=parent_id, spawnDepth="not read")

        result = self.scan(str(self.log_path()))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows(), [whole_row(self.session, (2, 2, 2, 2), 3.0, helpers=(
            {"id": "aloop", "description": "aloop", "brief_head": "Work.", **figures(1, 0, 0, 0)},
            {"id": "aorphan", "description": "aorphan", "brief_head": "Work.", **figures(0, 0, 0, 1)},
            {"id": "aself", "description": "aself", "brief_head": "Work.", **figures(0, 0, 1, 0)},
            {"id": "bloop", "description": "bloop", "brief_head": "Work.", **figures(0, 1, 0, 0)}))])

    def test_a_timestamp_that_is_not_an_iso_time_stops_the_scan_naming_the_log(self) -> None:
        for number, (stamp, usage) in enumerate((("yesterday", (1, 1, 1, 1)), (1767607200, (1, 1, 1, 1)),
                                                 ("yesterday", None))):
            with self.subTest(timestamp=stamp, usage=usage):
                self.state = self.root / f"state-{number}"
                log = Log(self.session).user(0, "Go.")
                log.assistant(1, usage)
                log.lines[0]["timestamp"] = stamp
                log.write(self.log_path())

                result = self.scan(str(self.log_path()))

                self.assertEqual((result.returncode, result.stdout, result.stderr), (
                    1, "", f"{self.log_path()}: a timestamp that is not an ISO time\n"))
                self.assertFalse(self.state.exists())

    def test_a_line_with_no_timestamp_or_a_null_one_is_left_out(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.assistant(50, (1, 1, 1, 1))
        log.lines[1]["timestamp"] = None
        del log.lines[2]["timestamp"]

        result = self.scan(str(log.write(self.log_path())))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows(), [whole_row(self.session, (2, 2, 2, 2), 0.0)])

    def test_times_with_no_time_zone_anywhere_are_read(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(5, (1, 1, 1, 1))
        for line in log.lines:
            line["timestamp"] = line["timestamp"].removesuffix("Z")

        result = self.scan(str(log.write(self.log_path())))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.rows(), [whole_row(self.session, (1, 1, 1, 1), 5.0)])

    def test_times_with_and_without_a_time_zone_stop_the_scan_naming_the_log_that_breaks_the_pattern(self) -> None:
        main = Log(self.session).user(0, "Go.")
        main.agent_call(1, (1, 1, 1, 1), "toolu_one", "Look.")
        main.write(self.log_path())
        helper = Log(self.session, "aone").user(1.5, "Look.")
        helper.assistant(2, (1, 1, 1, 1))
        helper.lines[1]["timestamp"] = "2026-01-05T10:02:00.000"
        self.helper("aone", "Look", helper, "toolu_one")

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, "", f"{self.project / self.session / 'subagents' / 'agent-aone.jsonl'}: "
                   "times with and without a time zone in one session\n"))
        self.assertFalse(self.state.exists())

    def test_a_helpers_meta_json_it_cannot_read_stops_the_scan_naming_the_file(self) -> None:
        meta = self.project / self.session / "subagents" / "agent-aone.meta.json"
        # A session with no token counts is read the same way.
        for usage in ((1, 1, 1, 1), None):
            main = Log(self.session).user(0, "Go.")
            main.agent_call(1, usage, "toolu_one", "Look.")
            main.write(self.log_path())
            helper = Log(self.session, "aone").user(1.5, "Look.")
            helper.assistant(2, usage)
            self.helper("aone", "Look", helper, "toolu_one")
            whole = meta.read_bytes()
            for number, (content, error) in enumerate((
                    (whole[:20], "not a JSON object"), (b"[]", "not a JSON object"),
                    (b'{"description": "Look \xff"}', "not a JSON object"),
                    ('{"description": "Look"}'.encode("utf-16"), "not a JSON object"),
                    (b"[" * 12000, "not a JSON object"),
                    (b'{"parentAgentId": 7}', "parentAgentId is neither text nor null"),
                    (b'{"toolUseId": ["toolu_one"]}', "toolUseId is neither text nor null"),
                    (b'{"description": {}}', "description is neither text nor null"))):
                with self.subTest(usage=usage, content=content[:30]):
                    self.state = self.root / f"state-{usage is None}-{number}"
                    meta.write_bytes(content)

                    result = self.scan(str(self.log_path()))

                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (1, "", f"{meta}: {error}\n"))
                    self.assertFalse(self.state.exists())

    def test_an_argument_that_starts_with_a_dash_and_is_no_jsonl_path_prints_usage_and_exits_2(self) -> None:
        usage = self.scan("--help").stdout
        # A log at the path the first argument names, relative to the folder the scan runs in.
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.root / "--state-dir=out" / "x")
        for number, args in enumerate((["--state-dir=out/x"], ["-"], ["-x"], ["--help", "x"], ["x", "--help"])):
            with self.subTest(args=args):
                self.state = self.root / f"state-{number}"
                result = self.scan(*args)

                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", usage))
                self.assertFalse(self.state.exists())

    def test_a_jsonl_path_that_starts_with_a_dash_is_scanned(self) -> None:
        result = self.scan("-x.jsonl")

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assert_blank_row("-x")

    def test_a_rows_file_line_that_is_not_a_json_object_is_kept_and_named(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        self.state.mkdir()
        rows = self.state / "scan-rows.jsonl"
        session = self.session.encode()
        # Line number, bytes, and whether the scan names it. Its last line has no newline, as a write cut off
        # would leave it.
        lines = [
            (1, b'{"session": "other", "total_tokens": 4}\r', False), (2, b"[]", True), (3, b"not json", True),
            (4, b"", True), (5, b" \t", True), (6, b'{"note": "no session"}', False), (7, b"\xff\xfe cut", True),
            (8, b"torn\rinside\r", True), (9, b'{"session": "' + session + b'", "note": "\xff"}', True),
            (10, b"[" * 12000, True), (12, b'{"session": "x", "tot', True)]
        replaced = b'{"session": "' + session + b'", "total_tokens": 1}\r'
        rows.write_bytes(b"\n".join(data for _, data, _ in lines[:10]) + b"\n" + replaced + b"\n" + lines[10][1])

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stderr), (0, "".join(
            f"{rows}:{number}: not a JSON object, kept as it is\n" for number, _, named in lines if named)))
        row = whole_row(self.session, (1, 1, 1, 1), 1.0)
        self.assertEqual(rows.read_bytes(), b"".join(data + b"\n" for _, data, _ in lines)
                         + json.dumps(row).encode() + b"\n")

    def test_a_renamed_copy_of_a_log_is_keyed_by_the_last_session_id_in_it(self) -> None:
        later = str(uuid.uuid4())
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        copy = Log(later).user(2, "Go on.")
        copy.assistant(3, (2, 2, 2, 2))
        copy.lines[:0] = log.lines
        copy.write(self.root / "saved" / "copy.jsonl")

        for path in (self.log_path(), self.root / "saved" / "copy.jsonl"):
            self.scan(str(path))

        self.assertEqual(self.rows(), [whole_row(self.session, (1, 1, 1, 1), 1.0),
                                       whole_row(later, (3, 3, 3, 3), 3.0, copied=4)])

    def test_a_log_with_no_session_id_is_keyed_by_the_files_name(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        for line in log.lines:
            del line["sessionId"]

        self.scan(str(log.write(self.root / "saved.jsonl")))

        self.assertEqual(self.rows(), [whole_row("saved", (1, 1, 1, 1), 1.0)])

    def test_a_machine_directory_and_lock_reached_through_symlinks_are_made_owner_only(self) -> None:
        log = Log(self.session).user(0, "Go.")
        log.assistant(1, (1, 1, 1, 1))
        log.write(self.log_path())
        real = self.root / "real-state"
        real.mkdir()
        real.chmod(0o755)
        lock = self.root / "real-lock"
        lock.write_text("")
        lock.chmod(0o644)
        self.state.symlink_to(real)
        (real / "scan-rows.lock").symlink_to(lock)

        result = self.scan(str(self.log_path()))

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual((oct(stat.S_IMODE(real.stat().st_mode)), oct(stat.S_IMODE(lock.stat().st_mode))),
                         ("0o700", "0o600"))
        self.assertTrue(self.state.is_symlink() and (real / "scan-rows.lock").is_symlink())

    def test_help_gives_the_three_steps_of_the_rows_key_and_what_the_scan_refuses(self) -> None:
        help_text = " ".join(self.scan("--help").stdout.split())

        for sentence in (
                "A log whose lines carry the file's name as a session id is keyed by the file's name.",
                "Otherwise it is keyed by the session id of the last line that carries one, since a log's own "
                "lines come after the lines it copied.",
                "A log with no session id at all is keyed by the file's name.",
                "A line of scan-rows.jsonl that is not a JSON object is kept as it is, and the scan names it on "
                "standard error.",
                "The scan stops with exit 1, one line on standard error and no row written when it cannot read an "
                "input: a log line that is not JSON, unless it is the last line, cut off mid-write; a timestamp "
                "that is not an ISO time, or one session's times with and without a time zone; or a helper's "
                "meta.json that is not a JSON object, or whose parentAgentId, toolUseId or description is neither "
                "text nor null."):
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, help_text)

    def test_help_gives_the_naming_rule_and_the_copied_lines(self) -> None:
        help_text = " ".join(self.scan("--help").stdout.split())

        for sentence in (
                "The row's skills list each skill the logs show loaded once, never with a plugin prefix.",
                "A skill that a successful Skill call loaded takes the name the call gives, less everything up to "
                "its last colon.",
                "The line that gives that load's folder names the call in sourceToolUseID, takes the call's name and "
                "adds no second entry.",
                "Any other load of that folder, as a typed one, takes the name of the first call that loaded it.",
                "A skill that no such call loaded takes its folder's last name.",
                "A call that failed, has no result or gives no name adds no entry.",
                "So two skills of one name from two plugins are one entry: a typed skill leaves no prefix to recover.",
                "A line whose sessionId is text other than the row's session is a copied line, as the lines a "
                "resumed session copied from an earlier one are.",
                "Copied lines, in the session's log or a helper's, count in every column like the session's own.",
                "copied_tokens is the part of total_tokens from the responses that only copied lines carry: 0 when "
                "there are none, blank when total_tokens is blank.",
                "A line carries a response when it holds part of it, with or without token counts.",
                "The skills are in the order of first load by time, across the session's log and its helpers' logs.",
                "A time with no zone is read as UTC.",
                "A line with no time that reads takes the time of the line before it, or comes first when there is "
                "none, and loads at one time keep the order of the lines."):
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, help_text)


if __name__ == "__main__":
    unittest.main()
