"""The core every deliver.py subcommand shares: endings, refusal codes, the run mark and records.

Endings (#256 rule 4). A subcommand returns for exit 0. It raises `Refused` for exit 10, which
prints `REFUSED <code>: <reason>` and, on the next line, `Next: <command>` when there is one. It
raises `Question` for exit 20, which prints the question for the owner. Anything else is a crash.
`UsageError` is exit 2 with the usage text.

Refusal codes are `<subcommand>.<reason>`, lower case with hyphens, and every one is in
`REFUSALS`. To add one, add its line here, raise `Refused("<code>", ...)`, and add a test named
`test_<code>` with dots and hyphens as underscores (for `ready.no-preflight`,
`test_ready_no_preflight`) in a `tests/test_deliver_*.py` file. The meta-test in
`tests/test_deliver_core.py` fails while a code has no such test.

Layout (spec #407, "Records and the run mark"):

- The run mark is `deliver-mark.json` in the checkout's own git directory (`git rev-parse
  --git-dir`): `{"run", "branch", "role", "started"}`.
- A branch's records are under `deliver/branches/<branch>/` in the shared git directory (`git
  rev-parse --git-common-dir`). Every event appends one JSON line, with `event` and `at` first,
  to its `records.jsonl`.
- The machine directory is `$DELIVER_STATE_DIR`, default `~/.local/state/deliver` (#256 rule 7).
  No line written there holds a session id.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MARK = "deliver-mark.json"
RECORDS = "records.jsonl"
NO_MARK = "no run mark in this checkout, so no run is in progress here"

# Every refusal code of the program, with its reason. A reason may hold str.format fields.
REFUSALS = {
    "preflight.no-mark": NO_MARK,
    "preflight.bad-settings": "the stack settings cannot be read: {error}",
    "check.no-mark": NO_MARK,
    "save.no-mark": NO_MARK,
    "pr.no-mark": NO_MARK,
    "ready.no-mark": NO_MARK,
    "merge.no-mark": NO_MARK,
    "finish.no-mark": NO_MARK,
}


class Refused(Exception):
    """Exit 10: the subcommand refused, with a fixed code and the next command."""

    def __init__(self, code: str, next_command: str | None = None, **fields: object):
        self.code = code
        self.reason = REFUSALS[code].format(**fields)
        self.next_command = next_command
        super().__init__(f"{code}: {self.reason}")

    def lines(self) -> list[str]:
        out = [f"REFUSED {self.code}: {self.reason}"]
        if self.next_command:
            out.append(f"Next: {self.next_command}")
        return out


class Question(Exception):
    """Exit 20: the run waits for the owner, who answers the question."""


class UsageError(Exception):
    """Exit 2: the arguments do not fit the subcommand."""


@dataclass
class Run:
    """Where a subcommand runs: the checkout, its git directories and its run mark, if any."""

    checkout: Path
    git_dir: Path
    common_dir: Path
    mark: dict | None

    def record(self, event: str, **fields: object) -> None:
        """Append one event to the records of the run's branch."""
        append_record(self.common_dir, self.mark["branch"], event, **fields)


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_run(cwd: Path) -> Run | None:
    """The checkout holding `cwd` with its run mark, or None outside a git working tree."""
    proc = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir", "--git-common-dir"],
        cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    checkout, git_dir, common_dir = (Path(line) for line in proc.stdout.splitlines())
    return Run(checkout, git_dir, common_dir, read_mark(git_dir))


def read_mark(git_dir: Path) -> dict | None:
    try:
        return json.loads((git_dir / MARK).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def write_mark(git_dir: Path, run: str, branch: str, role: str = "session") -> dict:
    mark = {"run": run, "branch": branch, "role": role, "started": now()}
    (git_dir / MARK).write_text(json.dumps(mark) + "\n", encoding="utf-8")
    return mark


def records_dir(common_dir: Path, branch: str) -> Path:
    return common_dir / "deliver" / "branches" / branch


def append_record(common_dir: Path, branch: str, event: str, **fields: object) -> None:
    _append(records_dir(common_dir, branch) / RECORDS, {"event": event, "at": now(), **fields})


def state_dir() -> Path:
    return Path(os.environ.get("DELIVER_STATE_DIR") or Path.home() / ".local" / "state" / "deliver").absolute()


def append_state(name: str, **fields: object) -> None:
    """Append one line to a log in the machine directory, which never holds a session id."""
    if any("session" in key for key in fields):
        raise ValueError(f"no session id goes into the machine directory: {sorted(fields)}")
    _append(state_dir() / name, {"at": now(), **fields})


def path_matches(path: str, patterns: list[str]) -> bool:
    """Whether a repo-relative path matches any glob of a lists.toml path list."""
    return any(re.match(glob.translate(p, recursive=True, include_hidden=True), path) for p in patterns)


def _append(path: Path, line: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
