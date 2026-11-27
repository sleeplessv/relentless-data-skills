#!/usr/bin/env python3
"""Read one Claude Code session from its log and write one row about it.

Usage: deliver.py scan SESSION
       deliver.py scan --refresh
       deliver.py scan --background

SESSION is a session id or the path of its .jsonl log. An id is looked up as
$CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl (default ~/.claude). An argument that
starts with "-" and does not end in .jsonl is bad usage, except -h or --help as
the only argument, which prints this help. Helpers' logs are read
from <log without .jsonl>/subagents/ and every folder below it; a folder there
that cannot be listed stops the scan with an error.

The row's key comes from the log in three steps. A log whose lines carry the
file's name as a session id is keyed by the file's name. Otherwise it is keyed
by the session id of the last line that carries one, since a log's own lines
come after the lines it copied. A log with no session id at all is keyed by the
file's name.

The row's skills list each skill the logs show loaded once, never with a
plugin prefix. A skill that a successful Skill call loaded takes the name the
call gives, less everything up to its last colon. The line that gives that
load's folder names the call in sourceToolUseID, takes the call's name and adds
no second entry. Any other load of that folder, as a typed one, takes the name
of the call the first such line names. A skill that no such call loaded takes
its folder's last name. A call that failed, has no result or gives no name adds
no entry. So two skills of one name from two plugins are one entry: a typed
skill leaves no prefix to recover.

The skills are in the order of first load by time, across the session's log
and its helpers' logs. A time with no zone is read as UTC. A line with no
timestamp, or a null one, takes the time of the line before it, or comes first
when there is none, and loads at one time keep the order of the lines.

A line whose sessionId is text other than the row's session is a copied line,
as the lines a resumed session copied from an earlier one are. Copied lines, in
the session's log or a helper's, count in every other column like the session's
own. copied_tokens is the part of total_tokens from the responses that only
copied lines carry: 0 when there are none, blank when total_tokens is blank. A
line carries a response when it holds part of it, with or without token counts.

The row replaces any earlier row for the same session in scan-rows.jsonl in the
machine directory: $DELIVER_STATE_DIR, default ~/.local/state/deliver. The scan
makes that directory 0700, and scan-rows.jsonl and scan-rows.lock 0600. A line
of scan-rows.jsonl that is not a JSON object is kept as it is, and the scan
names it on standard error. A session whose log is gone gets a row of nulls,
and so does one whose inputs the scan can read but whose logs hold no token
counts; a null is a blank, never a zero.

The scan stops with exit 1, one line on standard error and no row written when
it cannot read an input: a log line that is not JSON, unless it is the last
line, cut off mid-write; a timestamp that is not an ISO time, or one session's
times with and without a time zone; or a helper's meta.json that is not a JSON
object, or whose parentAgentId, toolUseId or description is neither text nor
null.

The record of a deliver PR. A session whose own lines hold a shell call of
`deliver.py ready` is a deliver session. Its ready moment is the last such call
whose result is not an error. Its row gains a "deliver" record:

- pr, state, merged_at, closed_at: the PR, which the first scan finds with
  gh pr view <branch> in the call's folder. Later scans ask gh by the PR's URL.
- measurement: the key: value lines of the Measurement block in the PR
  description. A missing block, a line that is not key: value, or a key named
  twice leaves it null, and measurement_note says why.
- agents: for the session and each helper, the models (.message.model) and
  efforts (.effort) of its own responses, each with the number of responses
  that carried it. A value the log does not hold is not filled in.
- miss and miss_signals: the miss result of #175 rule 1, null while the PR is
  a draft. The signals are: a commit after ready; a failed check run on the
  ready commit; a change request; the PR closed unmerged; a hand-over to the
  owner, read from the block's fix rounds line; a later PR that names it and
  reverts or fixes it within 14 days of its merge; and the miss label. A commit
  that only merges in the target branch, or holds only version lines, is not
  a commit after ready (#176 rule 20).
- after_ready_tokens: the tokens of every response after the ready moment on
  the PR's branch in the PR's repo, from every session's and helper's log,
  each response counted once.
- final: true 14 days after the PR merged, or closed unmerged. A final record
  is not read or asked about again, and its row stays as it is.
- note: why gh gave no answer; the rest of the record stays as the last scan
  found it.

A PR has one record. A later session that also called ready for it gets a
note that names the session holding the record.

--refresh refreshes every record that is not final, and makes a record for
each session log with a ready call. A log whose session is gone keeps its
row's figures. --background starts --refresh as a detached process and
returns at once; it writes to scan-refresh.log in the machine directory. Both
hold scan-refresh.lock there while the refresh runs, so a start or a refresh
while one runs does nothing and says so.
"""
from __future__ import annotations

import fcntl
import fnmatch
import glob
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

KINDS = {  # row column: usage field in the log
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_write_tokens": "cache_creation_input_tokens",
    "cache_read_tokens": "cache_read_input_tokens",
}
GAP_MINUTES = 30
NOT_JSON = (ValueError, RecursionError)  # json.loads can raise RecursionError on JSON nested too deep (3.13 does)
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
        except NOT_JSON:
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


def moments(logs: list[tuple[Path, list[dict]]]) -> list[datetime]:
    """The lines' times, in order; a line with no timestamp, or a null one, has none."""
    found: list[datetime] = []
    for path, lines in logs:
        for line in lines:
            stamp = line.get("timestamp")
            if stamp is None:
                continue
            try:
                moment = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if isinstance(stamp, str) else None
            except ValueError:
                moment = None
            if moment is None:
                sys.exit(f"{path}: a timestamp that is not an ISO time")
            if found and (moment.tzinfo is None) != (found[0].tzinfo is None):  # they cannot be compared
                sys.exit(f"{path}: times with and without a time zone in one session")
            found.append(moment)
    return sorted(found)


def active_minutes(times: list[datetime]) -> float:
    gaps = ((later - earlier).total_seconds() / 60 for earlier, later in zip(times, times[1:]))
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


def when(line: dict, before: float) -> float:
    """The line's time in seconds, to order loads by; `before` when it has no time that reads."""
    try:
        moment = datetime.fromisoformat(line.get("timestamp").replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return before
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def skills(lines: list[dict]) -> list[str]:
    """The skills the lines show loaded, named and ordered as the module's docstring says."""
    calls = tool_calls(lines)
    loads: list[tuple[float, Path | None, str | None]] = []  # (time, None, call id), or (time, folder, its call's id)
    moment = float("-inf")
    for line in lines:
        moment = when(line, moment)
        if line.get("type") != "user":
            continue
        content = (line.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            call = calls.get(part.get("tool_use_id")) if isinstance(part, dict) else None
            if call and call.get("name") == "Skill" and part.get("type") == "tool_result" and not part.get("is_error"):
                loads.append((moment, None, part["tool_use_id"]))
        source = line.get("sourceToolUseID") if isinstance(line.get("sourceToolUseID"), str) else None
        loads += [(moment, Path(text[len(SKILL_LINE):].splitlines()[0].strip()), source)
                  for text in (texts(line) if line.get("isMeta") else []) if text.startswith(SKILL_LINE)]

    def call_name(call_id: str | None) -> str:
        given = (calls.get(call_id) or {}).get("input")
        skill = given.get("skill") if isinstance(given, dict) else None
        return skill.split(":")[-1] if isinstance(skill, str) else ""
    loads.sort(key=lambda load: load[0])  # stable; the module's docstring gives the order
    call_names = {call_id: call_name(call_id) for _, folder, call_id in loads if folder is None}
    first_call_names: dict[Path, str] = {}
    for _, folder, call_id in loads:
        if folder is not None and call_names.get(call_id):
            first_call_names.setdefault(folder, call_names[call_id])
    names = [call_names.get(call_id) or ("" if folder is None else first_call_names.get(folder, folder.name))
             for _, folder, call_id in loads]
    return list(dict.fromkeys(name for name in names if name))


def helper_logs(log: Path) -> list[Path]:
    """The helpers' logs. A session without a subagents/ folder has none. A folder on the way to subagents/
    that cannot be searched raises OSError; one that can be searched need not be listed. subagents/, or a
    folder below it, that cannot be listed raises, and so does one that cannot be searched and holds a
    folder; one that can be listed but not searched yields its transcripts' paths, which cannot be read."""
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


def json_object(data: bytes) -> dict | None:
    """The JSON object `data` holds as UTF-8, or None when it holds none."""
    try:
        value = json.loads(data.decode())
    except NOT_JSON:  # UnicodeDecodeError is a ValueError
        return None
    return value if isinstance(value, dict) else None


def read_meta(log: Path) -> dict:
    """A helper's meta.json, or {} when it has none."""
    path = log.with_name(log.stem + ".meta.json")
    if not path.is_file():
        return {}
    meta = json_object(path.read_bytes())
    if meta is None:
        sys.exit(f"{path}: not a JSON object")
    for field in ("parentAgentId", "toolUseId", "description"):
        if not isinstance(meta.get(field), (str, type(None))):
            sys.exit(f"{path}: {field} is neither text nor null")
    return meta


def owners(main: list[dict], helpers: list[tuple[Path, list[dict]]], metas: dict[Path, dict]) -> dict[Path, set]:
    """The ids of the responses each helper's log holds that are its own, by the helper's log."""
    seen = set(usages(main))  # a forked helper's log repeats its parent's responses; those are the parent's spend
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
        owns[path] = usages(lines).keys() - seen
        seen |= owns[path]
    return owns


def scan(session: str, log: Path) -> dict:
    row: dict = {"session": session}
    blank = {**blank_tokens(), "copied_tokens": None, "active_minutes": None, "auto_compactions": None,
             "typed_compactions": None, "model": None, "skills": None, "helpers": None}
    if not log.is_file():
        return {**row, **blank}
    main = read_lines(log)
    ids = [line["sessionId"] for line in main if isinstance(line.get("sessionId"), str)]
    row["session"] = session if session in ids or not ids else ids[-1]  # the rule is in the module's docstring
    helpers = [(path, read_lines(path)) for path in helper_logs(log)]
    every = main + [line for _, lines in helpers for line in lines]
    times = moments([(log, main), *helpers])
    metas = {path: read_meta(path) for path, _ in helpers}
    final = usages(every)
    total = tokens(final, final)
    if total is None:
        return {**row, **blank}

    calls = tool_calls(every)
    owns = {path: tokens(own, final) for path, own in owners(main, helpers, metas).items()}
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
    copied = [isinstance(line.get("sessionId"), str) and line["sessionId"] != row["session"] for line in every]
    # The module's docstring says which lines carry a response. A key that is a list or an object names none.
    carried = {key for line, mark in zip(every, copied) if not mark and line.get("type") == "assistant"
               for key in [(line.get("message") or {}).get("id") or line.get("uuid")]
               if not isinstance(key, (list, dict))}
    only_copied = usages([line for line, mark in zip(every, copied) if mark]).keys() - carried
    return {**row, **total, "copied_tokens": sum(sum(final[key].values()) for key in only_copied),
            "active_minutes": active_minutes(times),
            "auto_compactions": sum(t == "auto" for t in compactions.values()),
            "typed_compactions": sum(t == "manual" for t in compactions.values()),
            "model": model(main), "skills": skills(every), "helpers": listed}


def is_path(target: str) -> bool:
    return target.endswith(".jsonl") or os.sep in target


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def state_path() -> Path:
    # Absolute, so the paths the draw builds from it hold in the commands it runs from other folders.
    return Path(os.environ.get("DELIVER_STATE_DIR") or Path.home() / ".local" / "state" / "deliver").absolute()


def state_dir() -> Path:
    """The machine directory, made private on first use: rows hold the head of each helper's brief."""
    state = state_path()
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
        # Read as bytes and split on b"\n" only, so a kept line comes back byte for byte.
        written = rows.read_bytes().split(b"\n") if rows.is_file() else []
        if written[-1:] == [b""]:
            written.pop()  # what follows the final newline is no line
        kept = []
        for number, data in enumerate(written, 1):
            line = json_object(data)
            if line is None:
                print(f"{rows}:{number}: not a JSON object, kept as it is", file=sys.stderr)
            elif line.get("session") == row["session"]:
                continue
            kept.append(data.decode(errors="surrogateescape"))  # write_private encodes it back to these bytes
        write_private(rows, "".join(text + "\n" for text in [*kept, json.dumps(row)]))
    return rows


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read, whole or not at all."""
    partial = path.with_name(path.name + ".partial")
    with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8",
                   errors="surrogateescape") as file:  # a kept rows-file line may hold bytes that are not UTF-8
        os.fchmod(file.fileno(), 0o600)  # a partial file left by an earlier run keeps its own mode
        file.write(text)
    partial.replace(path)


# The record of a deliver PR: the scan's second half.

READY_CALL = re.compile(r"\bdeliver\.py\s+ready(?![\w.-])")
FINAL_AFTER = timedelta(days=14)  # a record is final this long after its PR merged, or closed unmerged
BLOCK = re.compile(r"<details>\s*<summary>\s*Measurement\s*</summary>(.*?)</details>", re.S)
VERSION_LINE = re.compile(r'^[+-]\s*"?version"?\s*[:=]')
FIX_TITLE = re.compile(r"^(?:revert\b|(?:fix|revert)(?:\([^)]*\))?!?:)", re.I)
CI_FAILED = {"failure", "timed_out", "startup_failure"}
MISS_LABEL = "miss"  # the stack settings' default name for the owner's miss label
PR_FIELDS = "number,url,state,isDraft,mergedAt,closedAt,body,labels,reviews,baseRefName,headRefName"
REFRESH_LOCK = "scan-refresh.lock"
LOCK_FD = "DELIVER_SCAN_LOCK_FD"  # the lock a background start hands to the refresh it starts


class GhFailed(Exception):
    pass


def gh(*args: str, cwd: str | None = None):
    """What `gh args` prints, read as JSON; GhFailed with gh's last line of standard error when it fails."""
    name = " ".join(args[:2])
    try:
        done = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    except OSError as error:
        raise GhFailed(f"gh {name} failed: {error.strerror}") from None
    if done.returncode:
        raise GhFailed(f"gh {name} failed: " + (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1])
    try:
        return json.loads(done.stdout)
    except NOT_JSON:
        raise GhFailed(f"gh {name} printed no JSON") from None


def moment(stamp: object) -> datetime | None:
    """An ISO time as UTC when it has no zone; None when it is not one."""
    try:
        found = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def parts(line: dict) -> list[dict]:
    content = (line.get("message") or {}).get("content")
    return [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []


def own(line: dict, session: str) -> bool:
    """Whether the line is the session's own, not copied from an earlier session."""
    return not isinstance(line.get("sessionId"), str) or line["sessionId"] == session


def ready_call(lines: list[dict], session: str) -> dict | None:
    """The session's last own `deliver.py ready` call whose result is not an error: its time, folder and branch."""
    failed = {part.get("tool_use_id") for line in lines if line.get("type") == "user" for part in parts(line)
              if part.get("type") == "tool_result" and part.get("is_error")}
    found = None
    for line in lines:
        if line.get("type") != "assistant" or not own(line, session):
            continue
        for part in parts(line):
            given = part.get("input") if part.get("type") == "tool_use" else None
            command = given.get("command") if isinstance(given, dict) else None
            if isinstance(command, str) and READY_CALL.search(command) and part.get("id") not in failed:
                found = {"ready_at": line.get("timestamp"), "cwd": line.get("cwd"), "branch": line.get("gitBranch")}
    return found


def measurement(body: object) -> tuple[dict | None, str | None]:
    """The measurement block's fields in order, or None and why there are none."""
    block = BLOCK.search(body) if isinstance(body, str) else None
    if block is None:
        return None, "no measurement block in the PR description"
    fields: dict[str, str] = {}
    for text in block.group(1).splitlines():
        text = text.strip()
        if not text or text.startswith("```"):  # the block's text sits in a code fence
            continue
        key, colon, value = text.partition(":")
        if not colon or not key.strip():
            return None, f"measurement block line {text!r} is not a key: value line"
        if key.strip() in fields:
            return None, f"measurement block names {key.strip()!r} twice"
        fields[key.strip()] = value.strip()
    return fields, None


def agents(session: str, main: list[dict], helpers: list[tuple[Path, list[dict]]], metas: dict) -> list[dict]:
    """Each agent's models and efforts, counted over its own responses only, as X5 found them in the logs."""
    def tally(lines: list[dict], ids: set) -> dict:
        counts: dict[str, dict[str, int]] = {"models": {}, "efforts": {}}
        seen = set()
        for line in lines:
            message = line.get("message") or {}
            key = message.get("id") or line.get("uuid")
            if line.get("type") != "assistant" or key not in ids or key in seen:
                continue
            seen.add(key)
            for field, value in (("models", message.get("model")), ("efforts", line.get("effort"))):
                if isinstance(value, str) and value:
                    counts[field][value] = counts[field].get(value, 0) + 1
        return counts
    mine = set(usages([line for line in main if own(line, session)]))
    owns = owners(main, helpers, metas)
    return [{"agent": "session", "description": None, **tally(main, mine)},
            *({"agent": path.stem.removeprefix("agent-"), "description": metas[path].get("description"),
               **tally(lines, owns[path])} for path, lines in helpers)]


def common_dir(folder: object, cache: dict) -> str | None:
    """The shared git directory of the repo `folder` is in; None when it is gone or in no repo."""
    if not isinstance(folder, str):
        return None
    if folder not in cache:
        try:
            done = subprocess.run(["git", "-C", folder, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                  capture_output=True, text=True)
            cache[folder] = done.stdout.strip() if done.returncode == 0 else None
        except OSError:
            cache[folder] = None
    return cache[folder]


def tolerant_lines(data: bytes) -> list[dict]:
    """The JSON objects among a log's lines; a line that is not one is passed over, as this log is not the row's."""
    found = []
    for text in data.decode(errors="replace").split("\n"):
        try:
            line = json.loads(text) if text.strip() else None
        except NOT_JSON:
            continue
        if isinstance(line, dict):
            found.append(line)
    return found


def after_ready(ready_at: datetime, branch: str, git_dir: str) -> dict:
    """The tokens of every response after ready on the PR's branch in its repo, from every log, each counted once."""
    needle = json.dumps(branch).encode()
    cache: dict = {}
    lines = []
    for path in sorted((config_dir() / "projects").glob("**/*.jsonl")):
        try:
            if path.stat().st_mtime < ready_at.timestamp():
                continue  # a log last written before ready holds nothing after it
            data = path.read_bytes()
        except OSError:
            continue
        if needle not in data:
            continue
        lines += [line for line in tolerant_lines(data)
                  if line.get("type") == "assistant" and line.get("gitBranch") == branch
                  and (at := moment(line.get("timestamp"))) is not None and at > ready_at
                  and common_dir(line.get("cwd"), cache) == git_dir]
    final = usages(lines)
    return tokens(final, final) or dict.fromkeys([*KINDS, "total_tokens"], 0)


def tool_only(commit: dict, repo: str, base: str) -> bool:
    """Whether a commit only brings in the target branch, or holds only version lines a tool wrote (#176 rule 20)."""
    parents = commit.get("parents") or []
    if len(parents) == 2 and gh("api", f"repos/{repo}/compare/{base}...{parents[1]['sha']}").get("status") in (
            "behind", "identical"):
        return True
    files = gh("api", f"repos/{repo}/commits/{commit['sha']}").get("files") or []
    changed = [line for changes in files for line in (changes.get("patch") or "").splitlines() if line[:1] in "+-"]
    return bool(files) and all(changes.get("patch") for changes in files) and bool(changed) and all(
        VERSION_LINE.match(line) for line in changed)


def miss(view: dict, ready_at: datetime, fields: dict | None) -> tuple[bool | None, list[str]]:
    """The miss result of #175 rule 1 and the signals that make it; no result while the PR is a draft."""
    if view.get("isDraft"):
        return None, []
    number, repo = view["number"], "/".join(view["url"].split("/")[3:5])
    commits = gh("api", f"repos/{repo}/pulls/{number}/commits?per_page=100")
    after = [commit for commit in commits if (moment(commit["commit"]["committer"]["date"]) or ready_at) > ready_at]
    before = [commit for commit in commits if commit not in after]
    signals = []
    if any(not tool_only(commit, repo, view["baseRefName"]) for commit in after):
        signals.append("commit after ready")
    if before and any(run.get("conclusion") in CI_FAILED for run in gh(
            "api", f"repos/{repo}/commits/{before[-1]['sha']}/check-runs?per_page=100").get("check_runs", [])):
        signals.append("CI failed on the ready commit")
    if any(review.get("state") == "CHANGES_REQUESTED" for review in view.get("reviews") or []):
        signals.append("change request")
    if view.get("state") == "CLOSED":
        signals.append("closed unmerged")
    if re.search(r"\bhand", (fields or {}).get("fix rounds", ""), re.I):
        signals.append("hand-over to the owner")
    if merged_at := moment(view.get("mergedAt")):
        mention = re.compile(rf"#{number}(?!\d)|{re.escape(view['url'])}(?!\d)")
        later = gh("pr", "list", "--repo", repo, "--state", "merged", "--search", str(number),
                   "--json", "number,title,body,mergedAt", "--limit", "100")
        signals += [f"reverted or fixed by #{other['number']}" for other in later
                    if other["number"] != number and merged_at < (moment(other.get("mergedAt")) or merged_at)
                    <= merged_at + FINAL_AFTER and mention.search(f"{other.get('title')}\n{other.get('body')}")
                    and FIX_TITLE.match(other.get("title") or "")]
    if any(label.get("name") == MISS_LABEL for label in view.get("labels") or []):
        signals.append("miss label")
    return bool(signals), signals


def is_final(view: dict, now: datetime) -> bool:
    ended = moment(view.get("mergedAt")) or (moment(view.get("closedAt")) if view.get("state") == "CLOSED" else None)
    return ended is not None and ended + FINAL_AFTER <= now


def read_rows() -> dict[str, dict]:
    path = state_path() / "scan-rows.jsonl"  # reading makes no directory: a scan that stops writes nothing
    found = [json_object(data) for data in path.read_bytes().split(b"\n")] if path.is_file() else []
    return {row["session"]: row for row in found if row and isinstance(row.get("session"), str)}


def deliver_row(session: str, log: Path, rows: dict[str, dict]) -> dict | None:
    """The session's row, with the record of its PR when it called ready; None when its record is final."""
    old = (rows.get(session) or {}).get("deliver")
    if isinstance(old, dict) and old.get("final"):
        return None
    if not isinstance(old, dict):
        old = None
    row = scan(session, log)
    if not log.is_file():
        if old is None:
            return row
        row = {**rows[session]}  # the log is gone: its figures stay as the last scan found them
        call = {"ready_at": old.get("ready_at"), "branch": old.get("branch"), "cwd": None}
    else:
        main = read_lines(log)
        call = ready_call(main, row["session"])
        if call is None:
            return {**row, "deliver": old} if old else row
        helpers = [(path, read_lines(path)) for path in helper_logs(log)]
        row["deliver"] = {**(old or {}), "agents": agents(row["session"], main, helpers,
                                                         {path: read_meta(path) for path, _ in helpers})}
    part = row["deliver"] = {**(old or {}), **row.get("deliver", {}), "ready_at": call["ready_at"],
                             "branch": call["branch"], "note": None}
    if "git_dir" not in part:
        part["git_dir"] = common_dir(call["cwd"], {})
    ready_at = moment(call["ready_at"])
    try:
        if ready_at is None or not (part.get("pr") or call["branch"]):
            raise GhFailed("the ready call's line has no time or no branch")
        view = gh("pr", "view", part.get("pr") or call["branch"], "--json", PR_FIELDS,
                  cwd=None if part.get("pr") else call["cwd"])
        first = next((other for other, kept in rows.items() if other != row["session"]
                      and (kept.get("deliver") or {}).get("pr") == view["url"]
                      and (kept["deliver"].get("ready_at") or "") < call["ready_at"]), None)
        if first is not None:
            row["deliver"] = {"pr": view["url"], "ready_at": call["ready_at"],
                              "note": f"the record of this PR is the row of session {first}, which called ready first"}
            return row
        fields, why = measurement(view.get("body"))
        result, signals = miss(view, ready_at, fields)
        part.update(pr=view["url"], state=view.get("state"), merged_at=view.get("mergedAt"),
                    closed_at=view.get("closedAt"), measurement=fields, measurement_note=why, miss=result,
                    miss_signals=signals, final=is_final(view, datetime.now(timezone.utc)),
                    after_ready_tokens=after_ready(ready_at, view["headRefName"], part["git_dir"])
                    if part["git_dir"] else None)
    except (GhFailed, KeyError, TypeError, AttributeError) as error:  # gh gave an answer of another shape
        part["note"] = str(error) if isinstance(error, GhFailed) else f"gh gave an answer the scan cannot read ({error!r})"
        print(f"scan: {row['session']}: {part['note']}", file=sys.stderr)
    return row


def take_refresh_lock():
    """The refresh lock, held; None when another refresh holds it. A background start hands its lock down."""
    handed = os.environ.pop(LOCK_FD, None)
    descriptor = int(handed) if handed else os.open(state_dir() / REFRESH_LOCK, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the handed-down lock is this one: taking it again holds
    except BlockingIOError:
        os.close(descriptor)
        return None
    return descriptor


def refresh() -> int:
    """Refresh every record not yet final, and make one for each session log with a ready call and none yet."""
    lock = take_refresh_lock()
    if lock is None:
        print("a scan is already running; nothing done")
        return 0
    try:
        rows = read_rows()
        targets: dict[str, Path] = {}
        for log in sorted((config_dir() / "projects").glob("*/*.jsonl")):
            try:
                text = log.read_bytes().decode(errors="replace")
            except OSError:
                continue
            if READY_CALL.search(text):
                targets.setdefault(log.stem, log)
        for session, row in rows.items():
            if isinstance(row.get("deliver"), dict) and not row["deliver"].get("final"):
                targets.setdefault(session, resolve(session)[1])
        for session, log in targets.items():
            try:
                row = deliver_row(session, log, rows)
            except SystemExit as error:  # a log the first half cannot read: the other records go on
                print(f"scan: {session}: {error.code}", file=sys.stderr)
                continue
            if row is not None and "deliver" in row:
                write_row(row)
                rows[row["session"]] = row
        return 0
    finally:
        os.close(lock)


def start_background() -> bool:
    """Start a refresh in the background and return at once; False, starting nothing, while one runs."""
    state = state_dir()
    descriptor = os.open(state / REFRESH_LOCK, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        with open(state / "scan-refresh.log", "a") as log:
            os.chmod(log.name, 0o600)
            # The refresh shares this lock, so it is held from now until the refresh ends.
            subprocess.Popen([sys.executable, str(Path(__file__).with_name("deliver.py")), "scan", "--refresh"],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=state, start_new_session=True,
                             pass_fds=(descriptor,), env={**os.environ, LOCK_FD: str(descriptor)})
        return True
    finally:
        os.close(descriptor)


def cli(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv == ["--refresh"]:
        return refresh()
    if argv == ["--background"]:
        if not start_background():
            print("a scan is already running; nothing started")
        return 0
    # A path may start with "-": Claude Code names each project folder "-<path>".
    if len(argv) != 1 or (argv[0].startswith("-") and not argv[0].endswith(".jsonl")):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    session, log = resolve(argv[0])
    row = deliver_row(session, log, read_rows())
    print(write_row(row) if row is not None else state_dir() / "scan-rows.jsonl")
    return 0


def main(args: list[str], run: object = None) -> None:
    """deliver.py's entry: `run` is unused, since the scan reads the machine directory, not a checkout."""
    code = cli(args)
    if code:
        raise SystemExit(code)
