#!/usr/bin/env python3
"""Read one Claude Code session from its log and write one row about it.

Usage: python3 scripts/scan.py SESSION

SESSION is a session id or the path of its .jsonl log. An id is looked up as
$CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl (default ~/.claude). Helpers' logs
are read from <log without .jsonl>/subagents/.

The row replaces any earlier row for the same session in scan-rows.jsonl in the
machine directory: $DELIVER_STATE_DIR, default ~/.local/state/deliver. A
session whose log is gone, or holds no token counts, gets a row of nulls; a
null is a blank, never a zero.
"""
from __future__ import annotations

import fcntl
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

KINDS = {  # row column: usage field in the log
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_write_tokens": "cache_creation_input_tokens",
    "cache_read_tokens": "cache_read_input_tokens",
}
GAP_MINUTES = 30
BRIEF_HEAD = 200
SKILL_LINE = "Base directory for this skill: "


def read_lines(path: Path) -> list[dict]:
    lines = []
    for text in path.read_text(errors="replace").split("\n"):  # splitlines() would also split on U+2028
        try:
            line = json.loads(text)
        except ValueError:
            continue  # a line cut off while the session was still writing
        if isinstance(line, dict):
            lines.append(line)
    return lines


def texts(line: dict) -> list[str]:
    content = (line.get("message") or {}).get("content")
    if isinstance(content, str):
        return [content]
    return [part.get("text", "") for part in content or [] if isinstance(part, dict) and part.get("type") == "text"]


def tokens(lines: list[dict], seen: set[str]) -> dict | None:
    """Sum usage once per API message id not already in `seen`; None when no line has usage."""
    total = dict.fromkeys(KINDS, 0)
    counted = False
    for line in lines:
        message = line.get("message") or {}
        usage = message.get("usage")
        if line.get("type") != "assistant" or not usage or message.get("model") == "<synthetic>":
            continue
        key = message.get("id") or line.get("uuid")
        if key in seen:
            continue  # Claude Code repeats one response's usage on each of its content blocks
        seen.add(key)
        counted = True
        for column, field in KINDS.items():
            total[column] += usage.get(field) or 0
    if not counted:
        return None
    total["total_tokens"] = sum(total.values())
    return total


def blank_tokens() -> dict:
    return dict.fromkeys([*KINDS, "total_tokens"], None)


def active_minutes(lines: list[dict]) -> float:
    moments = sorted(datetime.fromisoformat(line["timestamp"].replace("Z", "+00:00"))
                     for line in lines if isinstance(line.get("timestamp"), str))
    gaps = ((later - earlier).total_seconds() / 60 for earlier, later in zip(moments, moments[1:]))
    return round(sum(gap for gap in gaps if gap < GAP_MINUTES), 2)


def model(lines: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    for line in lines:
        name = (line.get("message") or {}).get("model") if line.get("type") == "assistant" else None
        if name and name != "<synthetic>":
            counts[name] = counts.get(name, 0) + 1
    return max(counts, key=counts.get) if counts else None


def scan(session: str, log: Path) -> dict:
    row: dict = {"session": session}
    blank = {**blank_tokens(), "active_minutes": None, "auto_compactions": None,
             "typed_compactions": None, "model": None, "skills": None, "helpers": None}
    if not log.is_file():
        return {**row, **blank}
    main = read_lines(log)
    helper_logs = sorted((log.parent / log.stem / "subagents").glob("*.jsonl"))
    helpers = [(path, read_lines(path)) for path in helper_logs]
    every = main + [line for _, lines in helpers for line in lines]
    total = tokens(every, set())
    if total is None:
        return {**row, **blank}

    seen: set[str] = set()
    tokens(main, seen)  # a forked helper's log repeats its parent's responses; those are the parent's spend
    briefs = {part.get("id"): (part.get("input") or {}).get("prompt")
              for line in every if line.get("type") == "assistant"
              for part in (line.get("message") or {}).get("content") or []
              if isinstance(part, dict) and part.get("type") == "tool_use"}
    metas = {}
    for path, _ in helpers:
        meta_path = path.with_name(path.stem + ".meta.json")
        metas[path] = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    # A helper's fork copies its context too, so a parent, one level shallower, takes its responses first.
    owns = {path: tokens(lines, seen)
            for path, lines in sorted(helpers, key=lambda helper: (metas[helper[0]].get("spawnDepth") or 1, helper[0]))}
    listed = []
    for path, lines in helpers:
        own, meta = owns[path], metas[path]
        brief = briefs.get(meta.get("toolUseId")) or next(
            (line["message"]["content"] for line in lines
             if line.get("type") == "user" and isinstance((line.get("message") or {}).get("content"), str)), None)
        listed.append({"id": path.stem.removeprefix("agent-"), "description": meta.get("description"),
                       "brief_head": brief[:BRIEF_HEAD] if brief else None, **(own or blank_tokens())})

    compactions = {line.get("uuid"): (line.get("compactMetadata") or {}).get("trigger")
                   for line in every if line.get("subtype") == "compact_boundary"}
    skills: list[str] = []
    for line in every:
        if line.get("type") == "user" and line.get("isMeta"):
            for text in texts(line):
                if text.startswith(SKILL_LINE):
                    name = Path(text[len(SKILL_LINE):].splitlines()[0].strip()).name
                    if name not in skills:
                        skills.append(name)
    return {**row, **total, "active_minutes": active_minutes(every),
            "auto_compactions": sum(t == "auto" for t in compactions.values()),
            "typed_compactions": sum(t == "manual" for t in compactions.values()),
            "model": model(main), "skills": skills, "helpers": listed}


def is_path(target: str) -> bool:
    return target.endswith(".jsonl") or os.sep in target


def resolve(target: str) -> tuple[str, Path]:
    if is_path(target):
        path = Path(target).expanduser()
        return path.stem, path
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    found = sorted((config / "projects").glob(f"*/{glob.escape(target)}.jsonl"))
    return target, found[0] if found else config / "projects" / f"{target}.jsonl"


def write_row(row: dict) -> Path:
    state = Path(os.environ.get("DELIVER_STATE_DIR") or Path.home() / ".local" / "state" / "deliver")
    state.mkdir(parents=True, exist_ok=True)
    rows = state / "scan-rows.jsonl"
    with open(state / "scan-rows.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = [text for text in (rows.read_text().splitlines() if rows.is_file() else [])
                if text.strip() and json.loads(text).get("session") != row["session"]]
        partial = rows.with_name(rows.name + ".partial")
        partial.write_text("".join(text + "\n" for text in [*kept, json.dumps(row)]))
        partial.replace(rows)
    return rows


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    # A path may start with "-": Claude Code names each project folder "-<path>".
    if len(argv) != 1 or (argv[0].startswith("-") and not is_path(argv[0])):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    session, log = resolve(argv[0])
    print(write_row(scan(session, log)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
