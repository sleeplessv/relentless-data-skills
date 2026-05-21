#!/usr/bin/env python3
"""Doc-URL liveness check.

Verifies the durable Prefect doc entry point plus every URL listed in
``references/docs-map.md`` still resolves (HTTP 200). This is the skill's guard
against Prefect moving or renaming documentation pages. Standard library only.

Exit code 0 = all live, 1 = at least one URL failed.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

DURABLE = ["https://docs.prefect.io/llms.txt"]
DOCS_MAP = Path(__file__).resolve().parent.parent / "skills" / "prefect-skill" / "references" / "docs-map.md"
URL_RE = re.compile(r"=>\s*(https://\S+)")
TIMEOUT = 30


def collect_urls() -> list[str]:
    urls = list(DURABLE)
    urls += URL_RE.findall(DOCS_MAP.read_text(encoding="utf-8"))
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
    urls = collect_urls()
    failures: list[tuple[str, str]] = []
    for url in urls:
        ok, info = check(url)
        print(f"[{'OK ' if ok else 'FAIL'}] {info:>5}  {url}")
        if not ok:
            failures.append((url, info))
    print(f"\n{len(urls) - len(failures)}/{len(urls)} URLs live")
    if failures:
        print("\nFAILURES — re-fetch llms.txt and fix references/docs-map.md:")
        for url, info in failures:
            print(f"  {url}  ({info})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
