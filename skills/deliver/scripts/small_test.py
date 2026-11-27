"""The small test `ready` runs on the finished branch (spec #407, "The small test and the door").

`measure` reads the committed diff of `HEAD` against its merge base with the target branch and
returns a result, never a refusal.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from core import path_matches

LIMIT = 50


def measure(checkout: Path, base: str, settings: dict, door: str | None, proofs: dict[str, str]) -> dict:
    small_edit = settings["small_edit"]
    diff = f"{base}...HEAD"
    changed = _paths(checkout, diff)
    added = set(_paths(checkout, "--diff-filter=A", diff))
    lines = 0
    for row in _git(checkout, "diff", "--numstat", "-z", "--no-renames", diff).split("\0"):
        if not row:
            continue
        plus, minus, path = row.split("\t", 2)
        if path_matches(path, small_edit["exclude_generated"]) or (
                path in added and path_matches(path, small_edit["exclude_tests"])):
            continue
        if plus != "-":  # a binary file
            lines += int(plus) + int(minus)
    critical = [p for p in changed if path_matches(p, small_edit["critical_paths"])]
    failed = []
    if lines > LIMIT:
        failed.append(f"{lines} lines, over the limit of {LIMIT}")
    if critical:
        failed.append("high blast radius, critical paths changed: " + ", ".join(critical))
    return {
        "passed": not failed,
        "reason": "needs review: " + "; ".join(failed) if failed
        else f"small edit: a two-way door, {lines} lines and a low blast radius",
        "small_test": {"lines": lines, "critical_paths": critical, "dependents": None},
        "door": door,
        "door_paths": [],
    }


def _paths(checkout: Path, *args: str) -> list[str]:
    return [p for p in _git(checkout, "diff", "--name-only", "-z", "--no-renames", *args).split("\0") if p]


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=checkout, capture_output=True, text=True, check=True).stdout
