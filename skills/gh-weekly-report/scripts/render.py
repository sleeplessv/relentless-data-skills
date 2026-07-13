#!/usr/bin/env python3
"""Render week.json + the agent's bucket assignments into the report HTML.

Deterministic: merges the bucket mapping into the current period (unmapped
items land in `other`), merges the optional per-repo narratives, injects the
result into the fixed template at the __REPORT_DATA__ marker, and writes
report.html. All data is embedded in the page; the template pulls styling
(Tailwind) and charts (Chart.js) from CDNs and degrades to plain-but-complete
HTML when they are unreachable.
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
    so it stays untouched. A bucket outside the taxonomy is an agent typo;
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


def merge_narratives(week: dict, narratives: dict[str, str]) -> dict:
    """Attach the agent-authored per-repo narratives ({repo full name: text})
    verbatim under `narratives`. A key naming a repo with no activity in the
    current period is an authoring slip: warn, but keep the copy verbatim
    (repos without a narrative render fine without one)."""
    repos = {item.get("repo")
             for items in week.get("current", {}).values()
             for item in items}
    unknown = sorted(set(narratives) - repos)
    if unknown:
        print("warning: narrative for "
              f"{', '.join(unknown)} matches no repo in the data",
              file=sys.stderr)
    week["narratives"] = narratives
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
    parser.add_argument("--narratives",
                        help="path to narratives.json ({repo: narrative text})")
    parser.add_argument("--out", required=True, help="path for report.html")
    parser.add_argument("--template",
                        default=str(Path(__file__).resolve().parent.parent
                                    / "references" / "template.html"))
    opts = parser.parse_args(argv)

    week = json.loads(Path(opts.data).read_text())
    buckets = json.loads(Path(opts.buckets).read_text())
    narratives = (json.loads(Path(opts.narratives).read_text())
                  if opts.narratives else {})
    payload = merge_narratives(merge_buckets(week, buckets), narratives)
    html = inject(Path(opts.template).read_text(), payload)
    Path(opts.out).write_text(html)
    print(opts.out)


if __name__ == "__main__":
    main()
