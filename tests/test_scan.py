"""Exercise scripts/scan.py at its command line on session logs the tests build.

Each log is written in the shape of a Claude Code session log: one JSON object per
line, helpers' transcripts under <session>/subagents/. No line comes from a real
session, and every run points the machine directory and the Claude config
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

    def scan(self, target: str, *, env: dict | None = None) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "DELIVER_STATE_DIR": str(self.state), "CLAUDE_CONFIG_DIR": str(self.config)}
        environment.update(env or {})
        return subprocess.run([sys.executable, str(SCAN), target], cwd=self.root, env=environment,
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


if __name__ == "__main__":
    unittest.main()
