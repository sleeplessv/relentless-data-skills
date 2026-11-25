#!/usr/bin/env python3
"""Read one Claude Code session from its log and write one row about it.

Usage: python3 scripts/scan.py SESSION

SESSION is a session id or the path of its .jsonl log. An id is looked up as
$CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl (default ~/.claude). Helpers' logs
are read from <log without .jsonl>/subagents/ and every folder below it; a
folder there that cannot be listed stops the scan with an error. The
row is keyed by the file's name when the log's lines carry it, else by the
first session id inside the log.

The row replaces any earlier row for the same session in scan-rows.jsonl in the
machine directory: $DELIVER_STATE_DIR, default ~/.local/state/deliver. A
session whose log is gone, or holds no token counts, gets a row of nulls; a
null is a blank, never a zero. A line that is not JSON stops the scan with
exit 1 and no row written, unless it is the last line, cut off mid-write.
"""
from __future__ import annotations

import fcntl
import fnmatch
import glob
import json
import os
import sys
from collections.abc import Iterable
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
    raw = path.read_text(errors="replace").split("\n")  # splitlines() would also split on U+2028
    for number, text in enumerate(raw, 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except ValueError:
            if number == len(raw):
                continue  # the last line, cut off while the session was still writing
            sys.exit(f"{path}:{number}: not a JSON line")
        if isinstance(line, dict):
            lines.append(line)
    return lines


def texts(line: dict) -> list[str]:
    content = (line.get("message") or {}).get("content")
    if isinstance(content, str):
        return [content]
    return [part.get("text", "") for part in content or [] if isinstance(part, dict) and part.get("type") == "text"]


def usages(lines: list[dict]) -> dict[str, dict]:
    """Each response's final usage by API message id, from lines that hold a token count.

    Claude Code writes a response's usage on each of its content blocks' lines, and a later line can
    hold a larger, final count. A forked helper's log can hold an early copy. So each field keeps its
    largest value, whatever the order of the lines and files.
    """
    found: dict[str, dict] = {}
    for line in lines:
        message = line.get("message") or {}
        usage = message.get("usage")
        if (line.get("type") == "assistant" and isinstance(usage, dict) and message.get("model") != "<synthetic>"
                and any(isinstance(usage.get(field), (int, float)) for field in KINDS.values())):
            counts = found.setdefault(message.get("id") or line.get("uuid"), {})
            for field in KINDS.values():
                if isinstance(usage.get(field), (int, float)):
                    counts[field] = max(counts.get(field, 0), usage[field])
    return found


def tokens(keys: Iterable[str], final: dict[str, dict]) -> dict | None:
    """Sum the final usage of the responses in `keys`; None when there are none."""
    keys = list(keys)
    if not keys:
        return None
    total = {column: sum(final[key].get(field) or 0 for key in keys) for column, field in KINDS.items()}
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


def tool_calls(lines: list[dict]) -> dict[str, dict]:
    """Each tool call in the lines, by its id."""
    return {part.get("id"): part for line in lines if line.get("type") == "assistant"
            for part in (line.get("message") or {}).get("content") or []
            if isinstance(part, dict) and part.get("type") == "tool_use"}


def skills(lines: list[dict]) -> list[str]:
    """The skills the lines show loaded, in the order they were first loaded."""
    calls = tool_calls(lines)
    found: list[str] = []
    for line in lines:
        if line.get("type") != "user":
            continue
        names = [Path(text[len(SKILL_LINE):].splitlines()[0].strip()).name
                 for text in (texts(line) if line.get("isMeta") else []) if text.startswith(SKILL_LINE)]
        # A bundled skill has no folder, so no such line: its successful Skill call names it.
        content = (line.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            call = calls.get(part.get("tool_use_id")) if isinstance(part, dict) else None
            if call and call.get("name") == "Skill" and part.get("type") == "tool_result" and not part.get("is_error"):
                names.append(str((call.get("input") or {}).get("skill", "")).split(":")[-1])
        found.extend(name for name in dict.fromkeys(names) if name and name not in found)
    return found


def helper_logs(log: Path) -> list[Path]:
    """The helpers' logs; a folder below subagents/ that cannot be listed raises OSError, not leaves one out."""
    # A workflow's helpers sit in folders below subagents/, such as subagents/workflows/<run>/.
    folder = log.parent / log.stem / "subagents"
    if not folder.is_dir():
        return []

    def fail(error: OSError) -> None:
        raise error
    return sorted(Path(root) / name for root, _, names in os.walk(folder, onerror=fail)
                  for name in fnmatch.filter(names, "agent-*.jsonl"))


def scan(session: str, log: Path) -> dict:
    row: dict = {"session": session}
    blank = {**blank_tokens(), "active_minutes": None, "auto_compactions": None,
             "typed_compactions": None, "model": None, "skills": None, "helpers": None}
    if not log.is_file():
        return {**row, **blank}
    main = read_lines(log)
    # A copy of a log keeps its session's id inside, whatever the file is called. A log can also start
    # with lines that carry another session's id, so the file's name wins when its lines carry it.
    ids = [line["sessionId"] for line in main if isinstance(line.get("sessionId"), str)]
    row["session"] = session if session in ids or not ids else ids[0]
    helpers = [(path, read_lines(path)) for path in helper_logs(log)]
    every = main + [line for _, lines in helpers for line in lines]
    final = usages(every)
    total = tokens(final, final)
    if total is None:
        return {**row, **blank}

    seen = set(usages(main))  # a forked helper's log repeats its parent's responses; those are the parent's spend
    calls = tool_calls(every)
    metas = {}
    for path, _ in helpers:
        meta_path = path.with_name(path.stem + ".meta.json")
        metas[path] = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    # A helper's fork copies its context too, so a parent, one level shallower, takes its responses first.
    owns = {}
    for path, lines in sorted(helpers, key=lambda helper: (metas[helper[0]].get("spawnDepth") or 1, helper[0])):
        own = usages(lines).keys() - seen
        seen |= own
        owns[path] = tokens(own, final)
    listed = []
    for path, lines in helpers:
        own, meta = owns[path], metas[path]
        call = (calls.get(meta.get("toolUseId")) or {}).get("input") or {}
        brief = call.get("prompt") or next(
            (line["message"]["content"] for line in lines
             if line.get("type") == "user" and isinstance((line.get("message") or {}).get("content"), str)), None)
        listed.append({"id": path.stem.removeprefix("agent-"), "description": meta.get("description") or call.get("description"),
                       "brief_head": brief[:BRIEF_HEAD] if brief else None, **(own or blank_tokens())})

    compactions = {line.get("uuid"): (line.get("compactMetadata") or {}).get("trigger")
                   for line in every if line.get("subtype") == "compact_boundary"}
    return {**row, **total, "active_minutes": active_minutes(every),
            "auto_compactions": sum(t == "auto" for t in compactions.values()),
            "typed_compactions": sum(t == "manual" for t in compactions.values()),
            "model": model(main), "skills": skills(every), "helpers": listed}


def is_path(target: str) -> bool:
    return target.endswith(".jsonl") or os.sep in target


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def state_dir() -> Path:
    """The machine directory, made private on first use: rows hold the head of each helper's brief."""
    # Absolute, so the paths the draw builds from it hold in the commands it runs from other folders.
    state = Path(os.environ.get("DELIVER_STATE_DIR") or Path.home() / ".local" / "state" / "deliver").absolute()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    return state


def resolve(target: str) -> tuple[str, Path]:
    if is_path(target):
        path = Path(target).expanduser()
        return path.stem, path
    config = config_dir()
    found = sorted((config / "projects").glob(f"*/{glob.escape(target)}.jsonl"))
    return target, found[0] if found else config / "projects" / f"{target}.jsonl"


def write_row(row: dict) -> Path:
    state = state_dir()
    rows = state / "scan-rows.jsonl"
    with open(state / "scan-rows.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = [text for text in (rows.read_text().splitlines() if rows.is_file() else [])
                if text.strip() and json.loads(text).get("session") != row["session"]]
        write_private(rows, "".join(text + "\n" for text in [*kept, json.dumps(row)]))
    return rows


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read, whole or not at all."""
    partial = path.with_name(path.name + ".partial")
    with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
        os.fchmod(file.fileno(), 0o600)  # a partial file left by an earlier run keeps its own mode
        file.write(text)
    partial.replace(path)


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
