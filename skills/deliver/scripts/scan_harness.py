"""The scan's readers for Codex, Cortex Code, Cursor and Antigravity: one run's tokens from that harness's own files.

`read(harness, session)` is the one entry. It returns the row's columns after session and harness, with every
figure blank (None) that the files do not hold: a blank is never a zero (#175 rule 15). It only reads local
files: it starts no process and opens no connection, and it never reads Snowflake's usage view (#175 rule 13).
deliver.py scan --help says where each harness's files are and how they are read.
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

COLUMNS = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")
# The variable that holds the session's id in a command the session runs; Cursor sets none (#189 table).
SESSION_VARIABLES = {"cortex-code": "CORTEX_SESSION_ID", "codex": "CODEX_THREAD_ID", "cursor": None,
                     "antigravity": "ANTIGRAVITY_CONVERSATION_ID"}
CORTEX_COUNTS = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
                 "cache_write_tokens": "cacheWriteTokens", "cache_read_tokens": "cacheReadTokens"}


def blank() -> dict:
    return {**dict.fromkeys([*COLUMNS, "total_tokens"]), "copied_tokens": None, "active_minutes": None,
            "auto_compactions": None, "typed_compactions": None, "model": None, "effort": None, "skills": None,
            "helpers": None}


def count(value: object) -> bool:
    return type(value) is int and value >= 0


def figures(counts: dict | None) -> dict:
    """The token columns of `counts`, a column it lacks blank, and their total; all blank when `counts` is None."""
    if counts is None:
        return dict.fromkeys([*COLUMNS, "total_tokens"])
    found = {column: counts.get(column) for column in COLUMNS}
    return {**found, "total_tokens": sum(value for value in found.values() if value is not None)}


def json_lines(path: Path) -> list[dict]:
    """The JSON objects among a file's lines; a line that is not one, such as a last line cut off mid-write, is passed over."""
    found = []
    for text in path.read_text(errors="replace").split("\n"):
        try:
            line = json.loads(text) if text.strip() else None
        except (ValueError, RecursionError):
            continue
        if isinstance(line, dict):
            found.append(line)
    return found


def most(values: list) -> str | None:
    named = [value for value in values if isinstance(value, str) and value]
    return max(dict.fromkeys(named), key=named.count) if named else None  # a tie goes to the first seen


def row(session: dict | None, agents: list[tuple[str, dict | None]] | None, **named: object) -> dict:
    """A row from the session's own counts and each agent's, by id. Each total is the sum over all of them, and
    blank when any of them is blank, as an agent's tokens are not in its session's (#189 rule 23)."""
    found = {**blank(), **named}
    if session is None:
        return found  # as a Claude Code row with no token counts lists no helpers
    if agents is not None:
        found["helpers"] = [listed(agent, counts) for agent, counts in agents]
    every = [session, *(counts for _, counts in agents or [])]
    if any(counts is None for counts in every):
        return found
    held = {column: [counts[column] for counts in every if counts.get(column) is not None] for column in COLUMNS}
    return {**found, **figures({column: sum(values) for column, values in held.items() if values})}


def listed(agent: str, counts: dict | None) -> dict:
    return {"id": agent, "description": None, "brief_head": None, **figures(counts)}


def codex(thread: str) -> dict:
    """The thread's session log: $CODEX_HOME/sessions/**/rollout-*<thread id>.jsonl (default ~/.codex)."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    logs = sorted((home / "sessions").glob(f"**/rollout-*{glob.escape(thread)}.jsonl"))
    if not logs:
        return blank()
    lines = json_lines(logs[-1])
    payloads = [(line.get("type"), line.get("payload")) for line in lines if isinstance(line.get("payload"), dict)]
    contexts = [payload for kind, payload in payloads if kind == "turn_context"]
    named = {"model": most([payload.get("model") for payload in contexts]),
             "effort": most([payload.get("effort") for payload in contexts])}
    usage = None
    for kind, payload in payloads:
        info = payload.get("info") if kind == "event_msg" and payload.get("type") == "token_count" else None
        total = info.get("total_token_usage") if isinstance(info, dict) else None
        if isinstance(total, dict) and all(count(total.get(field)) for field in (
                "input_tokens", "cached_input_tokens", "output_tokens")):
            usage = total  # each count is the thread's running total, so the last one holds
    if usage is None or usage["cached_input_tokens"] > usage["input_tokens"]:
        return row(None, None, **named)
    # Codex counts cached input inside input_tokens; the row's input_tokens is the part not read from the cache.
    counts = {"input_tokens": usage["input_tokens"] - usage["cached_input_tokens"],
              "output_tokens": usage["output_tokens"], "cache_read_tokens": usage["cached_input_tokens"]}
    if count(usage.get("cache_write_input_tokens")):
        counts["cache_write_tokens"] = usage["cache_write_input_tokens"]
    return row(counts, None, **named)


def cortex_counts(entry: object) -> dict | None:
    """An entry's four counts summed over its models; None when no model holds a count."""
    models = entry.get("models") if isinstance(entry, dict) else None
    counts = [counts for counts in (models.values() if isinstance(models, dict) else []) if isinstance(counts, dict)]
    held = {column: [one[field] for one in counts if count(one.get(field))] for column, field in CORTEX_COUNTS.items()}
    found = {column: sum(values) for column, values in held.items() if values}
    return found or None


def cortex(session: str) -> dict:
    """The local stats file, ~/.snowflake/cortex/stats/usage.json: the session's entry under "sessions", and each
    entry whose rootSessionId names it, which is one of its agents."""
    path = Path.home() / ".snowflake" / "cortex" / "stats" / "usage.json"
    try:
        data = json.loads(path.read_bytes().decode())
    except (OSError, ValueError, RecursionError):
        return blank()
    sessions = data.get("sessions") if isinstance(data, dict) else None
    entry = sessions.get(session) if isinstance(sessions, dict) else None
    if not isinstance(entry, dict):
        return blank()
    models = entry.get("models") if isinstance(entry.get("models"), dict) else {}
    weights = {name: sum(value for value in counts.values() if count(value))
               for name, counts in models.items() if isinstance(counts, dict)}
    agents = [(other, cortex_counts(found)) for other, found in sessions.items()
              if other != session and isinstance(found, dict) and found.get("rootSessionId") == session]
    return row(cortex_counts(entry), agents, model=max(weights, key=weights.get) if weights else None)


def antigravity_counts(brain: Path, conversation: str) -> tuple[dict | None, list]:
    """A conversation's counts and models from its transcript; None for the counts when it has none or no transcript."""
    path = brain / conversation / ".system_generated" / "logs" / "transcript.jsonl"
    if not path.is_file():
        return None, []
    steps = [line for line in json_lines(path) if line.get("type") == "PLANNER_RESPONSE"]
    found = {column: [line[column] for line in steps if count(line.get(column))]
             for column in ("input_tokens", "output_tokens", "cache_read_tokens")}
    counts = {column: sum(values) for column, values in found.items() if values}
    return counts or None, [line.get("model") for line in steps]


def antigravity(conversation: str) -> dict:
    """<app data dir>/brain/<conversation id>/.system_generated/logs/transcript.jsonl for the session and for each
    agent, whose ids are the names of the files in .system_generated/subagents/ beside it, at any depth. The app data
    dir is $ANTIGRAVITY_APP_DATA_DIR (default ~/.gemini/antigravity-cli)."""
    brain = Path(os.environ.get("ANTIGRAVITY_APP_DATA_DIR") or Path.home() / ".gemini" / "antigravity-cli") / "brain"
    session, models = antigravity_counts(brain, conversation)
    if session is None:
        return blank()
    agents, waiting, seen = [], [conversation], {conversation}
    while waiting:
        folder = brain / waiting.pop(0) / ".system_generated" / "subagents"
        for agent in sorted(path.stem for path in folder.glob("*.json")) if folder.is_dir() else []:
            if agent not in seen:
                seen.add(agent)
                waiting.append(agent)
                agents.append((agent, antigravity_counts(brain, agent)[0]))
    return row(session, agents, model=most(models))


READERS = {"codex": codex, "cortex-code": cortex, "cursor": lambda session: blank(), "antigravity": antigravity}


def read(harness: str, session: str) -> dict:
    """The row's columns for one session on a harness other than Claude Code."""
    return READERS[harness](session)
