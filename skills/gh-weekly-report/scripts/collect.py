#!/usr/bin/env python3
"""Collect one actor's week of GitHub activity across one owner's repos.

Shells out to the gh CLI (inheriting its auth) and emits a single
week.json — the complete drill-down-ready dataset for the report week and
the week before it. Deterministic: all judgment (bucketing, narrative)
belongs to the agent, not this script.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SEARCH_LIMIT = 1000


def run_gh(args: list[str]) -> str:
    """Single seam to the gh CLI; tests replace this function.

    Retries once on a nonzero exit (search endpoints flake) before raising.
    """
    res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode != 0:
        res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def owner_flag(owner: str | None) -> list[str]:
    """Owner is an optional narrowing filter; absent means no scoping."""
    return ["--owner", owner] if owner else []


def gh_json(args: list[str]):
    out = run_gh(args)
    return json.loads(out) if out.strip() else []


def previous_window(start: date, end: date) -> tuple[date, date]:
    return start - timedelta(days=7), end - timedelta(days=7)


def iso_week_slug(start: date) -> str:
    iso_year, iso_week, _ = start.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def parse_range(from_arg: str | None, to_arg: str | None) -> tuple[date, date]:
    """Validate an explicit --from/--to override: both given, from <= to."""
    if (from_arg is None) != (to_arg is None):
        sys.exit("error: --from and --to must be given together")
    start, end = date.fromisoformat(from_arg), date.fromisoformat(to_arg)
    if start > end:
        sys.exit("error: --from must not be after --to")
    return start, end


def split_closed_issues(candidates: list[dict], actor: str) -> tuple[list[dict], list[dict]]:
    """Resolved = closed by the actor with reason `completed` (or none, as
    API closes carry no reason); the actor's `not_planned` closes are kept
    as a separate line; closes by anyone else are not the actor's work."""
    resolved, not_planned = [], []
    for item in candidates:
        if item.get("closed_by") != actor:
            continue
        if item.get("state_reason") == "not_planned":
            not_planned.append(item)
        else:
            resolved.append(item)
    return resolved, not_planned


def abandoned_prs(closed: list[dict], merged_keys: set[str]) -> list[dict]:
    """Closed-unmerged in window; merging closes a PR, so the merged set
    is exactly what to subtract."""
    return [p for p in closed if p["key"] not in merged_keys]


def reviews_in_window(reviews: list[dict], actor: str, start: date, end: date) -> list[dict]:
    """Reviews the actor submitted inside the window (edges inclusive, UTC)."""
    kept = []
    for r in reviews:
        if (r.get("user") or {}).get("login") != actor:
            continue
        submitted = r.get("submitted_at")
        if submitted and start <= date.fromisoformat(submitted[:10]) <= end:
            kept.append(r)
    return kept


def attribute_commits(commits: list[dict], pr_by_sha: dict[str, str]) -> list[dict]:
    """Mark each commit as carried by a PR or as a direct push, so weeks of
    push-to-main solo work stay visible."""
    for c in commits:
        c["pr"] = pr_by_sha.get(c["key"])
        c["direct_push"] = c["pr"] is None
    return commits


SIGNAL_BUCKETS = {
    "feat": "feature",
    "fix": "fix",
    "refactor": "refactor",
    "docs": "docs",
    "chore": "chore/infra",
    "ci": "chore/infra",
    "build": "chore/infra",
    "test": "chore/infra",
}

_SIGNAL_RE = re.compile(r"^(\w+)(?:\([^)]*\))?!?:")


def classify_signal(title: str) -> str | None:
    """Conventional-commit prefix → bucket hint; None when the title gives
    no signal (the agent decides those)."""
    m = _SIGNAL_RE.match(title.strip())
    return SIGNAL_BUCKETS.get(m.group(1).lower()) if m else None


def compute_window(today: date) -> tuple[date, date]:
    """Last complete Mon-Sun week (UTC) strictly before `today`'s week."""
    monday_of_current_week = today - timedelta(days=today.weekday())
    start = monday_of_current_week - timedelta(days=7)
    return start, start + timedelta(days=6)


# --- fetch layer: every function below talks to gh through run_gh ---------

SEARCH_FIELDS = "number,title,url,repository,labels,createdAt,closedAt,state,author"


def norm_item(raw: dict) -> dict:
    repo = raw["repository"]["nameWithOwner"]
    return {
        "key": f"{repo}#{raw['number']}",
        "repo": repo,
        "number": raw["number"],
        "title": raw["title"],
        "url": raw["url"],
        "labels": [lb["name"] for lb in raw.get("labels") or []],
        "author": (raw.get("author") or {}).get("login"),
        "created_at": raw.get("createdAt"),
        "closed_at": raw.get("closedAt"),
        "signal": classify_signal(raw["title"]),
    }


def search(kind: str, extra: list[str], owner: str | None) -> list[dict]:
    args = ["search", kind, *owner_flag(owner), "--json", SEARCH_FIELDS,
            "--limit", str(SEARCH_LIMIT), *extra]
    results = gh_json(args)
    if len(results) >= SEARCH_LIMIT:
        print(f"warning: gh search {kind} hit the {SEARCH_LIMIT}-result cap; "
              "the report may be missing items", file=sys.stderr)
    return [norm_item(r) for r in results]


def fetch_closed_issue_detail(item: dict) -> dict:
    """Search can't filter on closed-by, so each candidate needs one API
    call to learn who closed it and why."""
    repo, number = item["repo"], item["number"]
    detail = gh_json(["api", f"repos/{repo}/issues/{number}"]) or {}
    item["closed_by"] = ((detail.get("closed_by") or {}).get("login"))
    item["state_reason"] = detail.get("state_reason")
    return item


def fetch_reviews_given(owner: str, actor: str, start: date, end: date) -> list[dict]:
    candidates = search("prs", ["--reviewed-by", actor,
                                "--updated", f">={start}"], owner)
    given = []
    for pr in candidates:
        if pr["author"] == actor:
            continue
        reviews = gh_json(["api", f"repos/{pr['repo']}/pulls/{pr['number']}/reviews"])
        mine = reviews_in_window(reviews, actor, start, end)
        if mine:
            pr["review_states"] = sorted({r["state"] for r in mine})
            pr["reviewed_at"] = min(r["submitted_at"] for r in mine)
            given.append(pr)
    return given


COMMIT_SEARCH_FIELDS = "sha,commit,repository,url"


def fetch_commits(owner: str | None, actor: str, start: date, end: date,
                  attribute: bool) -> list[dict]:
    """Commits the actor authored, windowed on committer date: a squash
    merge carries the merge moment as committer date, so merged work lands
    in the week it merged. Accepted limits of the search index: default
    branch only, GitHub-linked commit email matching, eventual consistency.
    """
    raw = gh_json(["search", "commits", *owner_flag(owner),
                   "--author", actor,
                   "--committer-date", f"{start}..{end}",
                   "--json", COMMIT_SEARCH_FIELDS,
                   "--limit", str(SEARCH_LIMIT)])
    if len(raw) >= SEARCH_LIMIT:
        print(f"warning: gh search commits hit the {SEARCH_LIMIT}-result cap; "
              "the report may be missing commits", file=sys.stderr)
    commits = []
    for c in raw:
        headline = c["commit"]["message"].splitlines()[0]
        commits.append({
            "key": c["sha"],
            "repo": c["repository"]["fullName"],
            "title": headline,
            "url": c["url"],
            "committed_at": c["commit"]["committer"]["date"],
            "signal": classify_signal(headline),
        })
    if attribute:
        pr_by_sha = {}
        for c in commits:
            pulls = gh_json(["api", f"repos/{c['repo']}/commits/{c['key']}/pulls"])
            if pulls:
                pr_by_sha[c["key"]] = (f"{pulls[0]['base']['repo']['full_name']}"
                                       f"#{pulls[0]['number']}")
        commits = attribute_commits(commits, pr_by_sha)
    return commits


def collect_period(owner: str, actor: str, start: date, end: date,
                   attribute: bool) -> dict:
    rng = f"{start}..{end}"
    created = search("issues", ["--author", actor, "--created", rng], owner)
    closed_candidates = search("issues", ["--state", "closed", "--closed", rng], owner)
    resolved, not_planned = split_closed_issues(
        [fetch_closed_issue_detail(i) for i in closed_candidates], actor)

    prs_created = search("prs", ["--author", actor, "--created", rng], owner)
    prs_merged = search("prs", ["--author", actor, "--merged",
                                "--merged-at", rng], owner)
    prs_closed = search("prs", ["--author", actor, "--state", "closed",
                                "--closed", rng], owner)

    return {
        "issues_created": created,
        "issues_resolved": resolved,
        "issues_not_planned": not_planned,
        "prs_created": prs_created,
        "prs_merged": prs_merged,
        "prs_abandoned": abandoned_prs(prs_closed, {p["key"] for p in prs_merged}),
        "reviews_given": fetch_reviews_given(owner, actor, start, end),
        "commits": fetch_commits(owner, actor, start, end, attribute),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", help="account whose repos bound the report"
                        " (default: owner of the current repo)")
    parser.add_argument("--actor", help="user whose activity is reported"
                        " (default: the authenticated gh user)")
    parser.add_argument("--from", dest="from_", metavar="YYYY-MM-DD")
    parser.add_argument("--to", metavar="YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="directory for week.json")
    opts = parser.parse_args(argv)

    actor = opts.actor or run_gh(["api", "user", "--jq", ".login"]).strip()
    owner = opts.owner or run_gh(
        ["repo", "view", "--json", "owner", "--jq", ".owner.login"]).strip()

    if opts.from_ or opts.to:
        start, end = parse_range(opts.from_, opts.to)
    else:
        start, end = compute_window(datetime.now(timezone.utc).date())
    prev_start, prev_end = previous_window(start, end)

    payload = {
        "actor": actor,
        "owner": owner,
        "window": {"from": str(start), "to": str(end),
                   "iso_week": iso_week_slug(start)},
        "previous_window": {"from": str(prev_start), "to": str(prev_end)},
        "current": collect_period(owner, actor, start, end, attribute=True),
        "previous": collect_period(owner, actor, prev_start, prev_end,
                                   attribute=False),
    }

    out = Path(opts.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "week.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
