#!/usr/bin/env python3
"""Render week.json + the agent's bucket assignments into the report HTML.

Deterministic: merges the bucket mapping into the current period (unmapped
items land in `other`), injects the result into the fixed template at the
__REPORT_DATA__ marker, and writes a fully self-contained report.html.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BUCKETS = ["feature", "fix", "refactor", "docs", "chore/infra",
           "triage/review", "other"]

MARKER = "__REPORT_DATA__"


def merge_buckets(week: dict, buckets: dict[str, str]) -> dict:
    """Stamp a bucket on every current-period item; previous is deltas-only
    so it stays untouched. A bucket outside the taxonomy is an agent typo —
    fail loudly rather than render a category that doesn't exist."""
    for value in buckets.values():
        if value not in BUCKETS:
            sys.exit(f"error: unknown bucket {value!r}; taxonomy: {BUCKETS}")
    unmapped = set()
    for items in week["current"].values():
        for item in items:
            item["bucket"] = buckets.get(item["key"], "other")
            if item["key"] not in buckets:
                unmapped.add(item["key"])
    if unmapped:
        print("warning: no bucket assigned for "
              f"{', '.join(sorted(unmapped))}; defaulted to 'other'",
              file=sys.stderr)
    return week


def inject(template: str, payload: dict) -> str:
    data = json.dumps(payload)
    # A literal </script> inside the data would end the tag early.
    return template.replace(MARKER, data.replace("</", "<\\/"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="path to week.json")
    parser.add_argument("--buckets", required=True,
                        help="path to buckets.json ({item key: bucket})")
    parser.add_argument("--out", required=True, help="path for report.html")
    parser.add_argument("--template",
                        default=str(Path(__file__).resolve().parent.parent
                                    / "references" / "template.html"))
    opts = parser.parse_args(argv)

    week = json.loads(Path(opts.data).read_text())
    buckets = json.loads(Path(opts.buckets).read_text())
    html = inject(Path(opts.template).read_text(), merge_buckets(week, buckets))
    Path(opts.out).write_text(html)
    print(opts.out)


if __name__ == "__main__":
    main()
