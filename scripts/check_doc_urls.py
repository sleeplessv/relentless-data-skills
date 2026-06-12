#!/usr/bin/env python3
"""Doc-URL liveness check.

For every skill that ships a ``references/docs-map.md``, verifies that each doc
URL it lists still resolves (HTTP 200). This is a skill's guard against upstream
documentation moving or renaming pages. Skills without a docs-map are skipped,
so the check imposes nothing on skills that don't lean on live docs.

Standard library only. Exit code 0 = all live (or nothing to check), 1 = at
least one URL failed.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
URL_RE = re.compile(r"=>\s*(https://\S+)")
TIMEOUT = 30

# Durable entry points a skill should always check, keyed by skill name. These
# are roots the docs-map itself is derived from (e.g. an llms.txt index).
DURABLE: dict[str, list[str]] = {}


def collect_urls(docs_map: Path, skill_name: str) -> list[str]:
    urls = list(DURABLE.get(skill_name, []))
    urls += URL_RE.findall(docs_map.read_text(encoding="utf-8"))
    seen: set[str] = set()
    ordered: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def check(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "doc-liveness-check"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.getcode()
            return code == 200, str(code)
    except Exception as exc:  # noqa: BLE001 - report any failure mode
        return False, repr(exc)


def main() -> int:
    docs_maps = sorted(SKILLS_DIR.glob("*/references/docs-map.md"))
    if not docs_maps:
        print("no skills ship a references/docs-map.md — nothing to check.")
        return 0

    total = 0
    failures: list[tuple[str, str, str]] = []
    for docs_map in docs_maps:
        skill_name = docs_map.relative_to(SKILLS_DIR).parts[0]
        urls = collect_urls(docs_map, skill_name)
        print(f"\n{skill_name} ({len(urls)} URLs):")
        for url in urls:
            ok, info = check(url)
            total += 1
            print(f"  [{'OK ' if ok else 'FAIL'}] {info:>5}  {url}")
            if not ok:
                failures.append((skill_name, url, info))

    print(f"\n{total - len(failures)}/{total} URLs live")
    if failures:
        print("\nFAILURES — re-fetch the source index and fix the skill's docs-map:")
        for skill_name, url, info in failures:
            print(f"  [{skill_name}] {url}  ({info})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
