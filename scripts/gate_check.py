#!/usr/bin/env python3
"""The rule gate's CI check: a PR that changes skills/deliver/ carries its evidence.

Usage: gate_check.py --body FILE --base BRANCH --default-branch BRANCH --base-rev REV --changed FILE
"""
from __future__ import annotations

import argparse
import subprocess
import sys

DELIVER = "skills/deliver/"
HEADING = "## Change kind"


def base_holds_deliver(rev: str) -> bool:
    """Whether the base commit's tree has a skills/deliver/ folder; a bad revision stops the script."""
    listed = subprocess.run(["git", "ls-tree", "-d", rev, DELIVER.rstrip("/")],
                            capture_output=True, text=True, check=True)
    return bool(listed.stdout.strip())


def block(body: str) -> list[str] | str:
    """The lines under the one ## Change kind heading, or the reason they cannot be read."""
    lines = [line.strip() for line in body.splitlines()]
    starts = [n for n, line in enumerate(lines) if line == HEADING]
    if not starts:
        return f"the PR body has no {HEADING} heading"
    if len(starts) > 1:
        return f"the PR body has {len(starts)} {HEADING} headings"
    taken = []
    for line in lines[starts[0] + 1:]:
        if line.startswith("## "):
            break
        taken.append(line)
    return taken


def check(body: str) -> str | None:
    """None when the body's block carries the evidence its kind needs, else what is missing."""
    lines = block(body)
    if isinstance(lines, str):
        return lines
    return "not built"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--body", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--default-branch", required=True)
    parser.add_argument("--base-rev", required=True)
    parser.add_argument("--changed", required=True)
    args = parser.parse_args(argv)
    with open(args.changed, "rb") as f:
        changed = f.read().decode().split("\0")
    if args.base != args.default_branch:
        reason = f"the base {args.base} is not the default branch {args.default_branch}"
    elif not any(path.startswith(DELIVER) for path in changed):
        reason = f"no changed file is under {DELIVER}"
    elif not base_holds_deliver(args.base_rev):
        reason = f"the base has no {DELIVER}"
    else:
        with open(args.body, encoding="utf-8") as f:
            problem = check(f.read())
        if problem:
            print(f"gate_check: refused: {problem}.", file=sys.stderr)
            return 1
        return 0
    print(f"gate_check: not checked: {reason}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
