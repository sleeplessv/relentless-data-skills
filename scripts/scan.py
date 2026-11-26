#!/usr/bin/env python3
"""Read one Claude Code session from its log and write one row about it.

Usage: python3 scripts/scan.py SESSION

SESSION is a session id or the path of its .jsonl log. An id is looked up as
$CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl (default ~/.claude). An argument that
starts with "-" and does not end in .jsonl is bad usage. Helpers' logs are read
from <log without .jsonl>/subagents/ and every folder below it; a folder there
that cannot be listed stops the scan with an error.

The row's key comes from the log in three steps. A log whose lines carry the
file's name as a session id is keyed by the file's name. Otherwise it is keyed
by the session id of the last line that carries one, since a log's own lines
come after the lines it copied. A log with no session id at all is keyed by the
file's name.

The row replaces any earlier row for the same session in scan-rows.jsonl in the
machine directory: $DELIVER_STATE_DIR, default ~/.local/state/deliver. The scan
makes that directory 0700 and its files 0600. A line of scan-rows.jsonl that is
not a JSON object is kept as it is, and the scan names it on standard error. A
session whose log is gone, or holds no token counts, gets a row of nulls; a
null is a blank, never a zero.

The scan stops with exit 1, one line on standard error and no row written when
it cannot read an input: a log line that is not JSON, unless it is the last
line, cut off mid-write; a timestamp that is not an ISO time with a time zone;
or a helper's meta.json that is not a JSON object, or whose parentAgentId,
toolUseId or description is neither text nor null.
"""
from __future__ import annotations

import fcntl
import fnmatch
import glob
import json
import os
import stat
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
    return parse_lines(path.read_text(errors="replace"), path)


def parse_lines(text: str, path: Path) -> list[dict]:
    """A log's lines, from its text as read from `path`."""
    lines = []
    raw = text.split("\n")  # splitlines() would also split on U+2028
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


def active_minutes(logs: list[tuple[Path, list[dict]]]) -> float:
    moments = []
    for path, lines in logs:
        for line in lines:
            if isinstance(line.get("timestamp"), str):
                try:
                    moment = datetime.fromisoformat(line["timestamp"].replace("Z", "+00:00"))
                except ValueError:
                    moment = None
                if moment is None or moment.tzinfo is None:  # times with and without a zone cannot be compared
                    sys.exit(f"{path}: a timestamp that is not an ISO time with a time zone")
                moments.append(moment)
    moments.sort()
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
    """The helpers' logs. A session without a subagents/ folder has none; a folder on the way to one, or
    below it, that cannot be searched or listed raises OSError, not leaves one out."""
    # A workflow's helpers sit in folders below subagents/, such as subagents/workflows/<run>/.
    folder = log.parent / log.stem / "subagents"
    try:
        if not stat.S_ISDIR(folder.stat().st_mode):
            return []
    except (FileNotFoundError, NotADirectoryError):
        return []

    def fail(error: OSError) -> None:
        raise error
    return sorted(Path(root) / name for root, _, names in os.walk(folder, onerror=fail)
                  for name in fnmatch.filter(names, "agent-*.jsonl"))


def read_meta(log: Path) -> dict:
    """A helper's meta.json, or {} when it has none."""
    path = log.with_name(log.stem + ".meta.json")
    if not path.is_file():
        return {}
    try:
        meta = json.loads(path.read_bytes())
    except ValueError:  # not JSON, or not text
        meta = None
    if not isinstance(meta, dict):
        sys.exit(f"{path}: not a JSON object")
    for field in ("parentAgentId", "toolUseId", "description"):
        if not isinstance(meta.get(field), (str, type(None))):
            sys.exit(f"{path}: {field} is neither text nor null")
    return meta


def scan(session: str, log: Path) -> dict:
    row: dict = {"session": session}
    blank = {**blank_tokens(), "active_minutes": None, "auto_compactions": None,
             "typed_compactions": None, "model": None, "skills": None, "helpers": None}
    if not log.is_file():
        return {**row, **blank}
    main = read_lines(log)
    # A copy of a log keeps its session's id inside, whatever the file is called. A log can also start
    # with lines that carry another session's id, so the file's name wins when its lines carry it, and
    # otherwise the last id does: a log's own lines come after the lines it copied.
    ids = [line["sessionId"] for line in main if isinstance(line.get("sessionId"), str)]
    row["session"] = session if session in ids or not ids else ids[-1]
    helpers = [(path, read_lines(path)) for path in helper_logs(log)]
    every = main + [line for _, lines in helpers for line in lines]
    final = usages(every)
    total = tokens(final, final)
    if total is None:
        return {**row, **blank}

    seen = set(usages(main))  # a forked helper's log repeats its parent's responses; those are the parent's spend
    calls = tool_calls(every)
    metas = {path: read_meta(path) for path, _ in helpers}
    by_id = {path.stem.removeprefix("agent-"): path for path, _ in helpers}

    def depth(path: Path) -> int:
        """How many helpers the chain of parentAgentId holds from this one up; it ends at a helper seen twice."""
        chain = [path]
        while (parent := by_id.get(metas[chain[-1]].get("parentAgentId"))) and parent not in chain:
            chain.append(parent)
        return len(chain)
    # A helper's fork copies its context too, so a parent, one level shallower, takes its responses first.
    owns = {}
    for path, lines in sorted(helpers, key=lambda helper: (depth(helper[0]), helper[0])):
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
    return {**row, **total, "active_minutes": active_minutes([(log, main), *helpers]),
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
    state.chmod(0o700)  # one an earlier version made keeps its mode otherwise
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
    with os.fdopen(os.open(state / "scan-rows.lock", os.O_WRONLY | os.O_CREAT, 0o600), "w") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Bytes that are not UTF-8 pass through as they are; split("\n"), as splitlines() splits on more.
        written = rows.read_text(errors="surrogateescape").split("\n") if rows.is_file() else []
        kept = []
        for number, text in enumerate(written, 1):
            if not text.strip():
                continue
            try:
                line = json.loads(text)
            except ValueError:
                line = None
            if not isinstance(line, dict):
                print(f"{rows}:{number}: not a JSON object, kept as it is", file=sys.stderr)
            elif line.get("session") == row["session"]:
                continue
            kept.append(text)
        write_private(rows, "".join(text + "\n" for text in [*kept, json.dumps(row)]))
    return rows


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read, whole or not at all."""
    partial = path.with_name(path.name + ".partial")
    with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                   errors="surrogateescape") as file:  # a kept rows-file line may hold bytes that are not UTF-8
        os.fchmod(file.fileno(), 0o600)  # a partial file left by an earlier run keeps its own mode
        file.write(text)
    partial.replace(path)


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    # A path may start with "-": Claude Code names each project folder "-<path>".
    if len(argv) != 1 or (argv[0].startswith("-") and not argv[0].endswith(".jsonl")):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    session, log = resolve(argv[0])
    print(write_row(scan(session, log)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
