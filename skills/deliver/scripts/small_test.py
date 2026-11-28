"""The small test, for `ready` to run on the finished branch (spec #407, "The small test and the door").

`ready` (#423) calls it. Of the program's modules it imports only `core`.

`measure` reads the committed diff of `HEAD` against its merge base with the target branch, the
stack settings as `settings.load` merges them, and the saved plan's door and proofs. It returns a
result, never a refusal:

    {"passed": bool, "reason": str,
     "small_test": {"lines": int, "critical_paths": [str], "dependents": None | dict},
     "door": "two-way" | "one-way", "door_paths": [str]}

`small_test`, `door` and `door_paths` are the `ready` record's fields of the same names.

- Lines are added plus removed, read with git's rename detection: a moved file counts only the
  lines its move changed. Files whose new name matches `exclude_generated`, and newly added
  files matching `exclude_tests`, are left out; a renamed file is not newly added. A binary file
  adds none. More than `LIMIT` lines fails.
- Every changed path, both names of a moved file and paths left out of the count included, meets
  the critical list, the one-way list and the dependents command.
- The dependents command runs through the shell in the checkout, with every changed path
  appended as a quoted argument. Its first output line is the count. Every further non-blank
  line names a report or exposure the change feeds. `dependents` is None with no command,
  `{"count", "feeds"}` when it ran, and `{"error"}` when it exited non-zero, printed no count or
  printed output that is not UTF-8.
  A count over `dependents_limit`, anything it feeds, or an error gives a high blast radius.
- The door is the plan's (`two-way` or `one-way`; anything else, or None, is one-way), raised to
  one-way by a changed path on `[one_way] paths` and never lowered. `door_paths` names every
  such path. A one-way door fails.
- A proof holding `no check exists` fails unless it is `no check exists, meaning unchanged`
  (#171 rule 11), compared without case or surrounding space.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from core import path_matches

LIMIT = 50
NO_CHECK = "no check exists"
UNCHANGED = "no check exists, meaning unchanged"


def measure(checkout: Path, base: str, settings: dict, door: str | None, proofs: dict[str, str]) -> dict:
    """Run the small test on `HEAD` against its merge base with `base`; `proofs` maps requirement to proof."""
    small_edit = settings["small_edit"]
    diff = f"{base}...HEAD"
    changed = [p for p in _git(checkout, "diff", "--name-only", "-z", "--no-renames", diff).split("\0") if p]
    added = set(_git(checkout, "diff", "--name-only", "-z", "--find-renames", "--diff-filter=A", diff).split("\0"))
    rows = iter(_git(checkout, "diff", "--numstat", "-z", "--find-renames", diff).split("\0"))
    lines = 0
    for row in rows:
        if not row:
            continue
        plus, minus, path = row.split("\t", 2)
        if not path:  # a rename: the old and the new name follow
            next(rows)
            path = next(rows)
        left_out = path_matches(path, small_edit["exclude_generated"]) or (
            path in added and path_matches(path, small_edit["exclude_tests"]))
        if not left_out and plus != "-":  # git prints - for a binary file's counts
            lines += int(plus) + int(minus)
    critical = [p for p in changed if path_matches(p, small_edit["critical_paths"])]
    door_paths = [p for p in changed if path_matches(p, settings["one_way"]["paths"])]
    dependents = _dependents(checkout, small_edit["dependents_command"], changed)

    failed = []
    if door == "one-way":
        failed.append("the plan's door is one-way")
    elif door != "two-way":
        failed.append("the plan names no two-way or one-way door, so the door is one-way")
    if door_paths:
        failed.append("one-way paths changed: " + ", ".join(door_paths))
    if lines > LIMIT:
        failed.append(f"{lines} lines, over the limit of {LIMIT}")
    if critical:
        failed.append("high blast radius, critical paths changed: " + ", ".join(critical))
    if dependents and "error" in dependents:
        failed.append(f"high blast radius, the dependents command failed: {dependents['error']}")
    elif dependents:
        limit = small_edit["dependents_limit"]
        if dependents["count"] > limit:
            failed.append(f"high blast radius, the change feeds {dependents['count']} dependents, "
                          f"over the limit of {limit}")
        if dependents["feeds"]:
            failed.append("high blast radius, the change feeds " + ", ".join(dependents["feeds"]))
    unchecked = [r for r, proof in proofs.items() if NO_CHECK in proof.lower() and proof.strip().lower() != UNCHANGED]
    if unchecked:
        failed.append(f'requirements with no check, not recorded "{UNCHANGED}": ' + ", ".join(unchecked))

    counted = f"{lines} line" + ("" if lines == 1 else "s")
    return {
        "passed": not failed,
        "reason": "needs review: " + "; ".join(failed) if failed
        else f"small edit: a two-way door, {counted} and a low blast radius",
        "small_test": {"lines": lines, "critical_paths": critical, "dependents": dependents},
        "door": "two-way" if door == "two-way" and not door_paths else "one-way",
        "door_paths": door_paths,
    }


def _dependents(checkout: Path, command: str, changed: list[str]) -> dict | None:
    if not command:
        return None
    proc = subprocess.run(f"{command} {shlex.join(changed)}", shell=True, cwd=checkout, capture_output=True)
    if proc.returncode != 0:
        return {"error": f"exit {proc.returncode}"}
    try:
        out = proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return {"error": "its output is not UTF-8"}
    first, *rest = out.splitlines() or [""]
    if not re.fullmatch(r"[0-9]+", first.strip()):
        return {"error": "it printed no count"}
    return {"count": int(first), "feeds": [line.strip() for line in rest if line.strip()]}


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=checkout, capture_output=True, text=True, check=True).stdout
