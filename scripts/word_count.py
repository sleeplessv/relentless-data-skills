#!/usr/bin/env python3
"""Word-count lint for the rule gate.

Reads the path map (default ``docs/path-map.toml``, or the file given as the one
argument) and counts the words of each row's files. A word is a run of
characters between whitespace. Listed paths resolve from the repo root; an
absolute path stays as written.

Each row prints one line:

- ``<name>: <words> words, limit <limit>`` on stdout, at or under its limit;
- ``<name>: <words> words, no limit`` on stdout, for a row without ``limit``;
- ``<name>: <words> words, over its limit of <limit>`` on stderr, over it.

A row that lists a missing file prints ``<name>: missing file <path>`` and a
row that lists a script prints ``<name>: lists script <path>, scripts are not
counted``, both on stderr, one line per file, and the row gets no count. A
script is a file under a ``scripts`` folder or with a suffix in
``SCRIPT_SUFFIXES``.

Standard library only.

Exit code 0 = every row passed, 1 = at least one row was refused.

Usage: python3 scripts/word_count.py [path-map.toml]
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_SUFFIXES = {".py", ".sh", ".js", ".mjs", ".ts"}


def refusals(name: str, files: list[str]) -> list[str]:
    """Return one line for each listed file the row may not count."""
    lines = []
    for listed in files:
        path = Path(listed)
        if "scripts" in path.parts[:-1] or path.suffix in SCRIPT_SUFFIXES:
            lines.append(f"{name}: lists script {listed}, scripts are not counted")
        elif not (REPO_ROOT / path).is_file():
            lines.append(f"{name}: missing file {listed}")
    return lines


def main(argv: list[str]) -> int:
    path_map = Path(argv[0]) if argv else REPO_ROOT / "docs" / "path-map.toml"
    status = 0
    for row in tomllib.loads(path_map.read_text(encoding="utf-8"))["path"]:
        name, files, limit = row["name"], row["files"], row.get("limit")
        refused = refusals(name, files)
        if refused:
            print("\n".join(refused), file=sys.stderr)
            status = 1
            continue
        words = sum(len((REPO_ROOT / f).read_text(encoding="utf-8").split()) for f in files)
        if limit is None:
            print(f"{name}: {words} words, no limit")
        elif words <= limit:
            print(f"{name}: {words} words, limit {limit}")
        else:
            print(f"{name}: {words} words, over its limit of {limit}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
