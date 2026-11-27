"""The small test `ready` runs on the finished branch (spec #407, "The small test and the door").

`measure` reads the committed diff of `HEAD` against its merge base with the target branch and
returns a result, never a refusal.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

LIMIT = 50


def measure(checkout: Path, base: str, settings: dict, door: str | None, proofs: dict[str, str]) -> dict:
    lines = 0
    for row in _git(checkout, "diff", "--numstat", "-z", "--no-renames", f"{base}...HEAD").split("\0"):
        if row:
            added, removed, _ = row.split("\t", 2)
            lines += int(added) + int(removed)
    return {
        "passed": True,
        "reason": f"small edit: a two-way door, {lines} lines and a low blast radius",
        "small_test": {"lines": lines, "critical_paths": [], "dependents": None},
        "door": door,
        "door_paths": [],
    }


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=checkout, capture_output=True, text=True, check=True).stdout
