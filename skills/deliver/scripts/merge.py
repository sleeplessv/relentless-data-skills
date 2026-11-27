"""deliver.py merge: merge the run's PR, or say why it waits (#176 rules 15 to 19; #256 merge row).

In order, `merge`:

1. refuses `merge.no-pr` when the branch's records hold no `pr` record, and `merge.not-open`
   unless GitHub shows that PR open;
2. refuses `merge.not-ready` unless a `ready` record with the result `small edit` is tied to the
   PR's head commit;
3. refuses `merge.one-way` when that record's door is not `two-way`, and `merge.withheld` when
   the stack setting `stop_at_ready` is set, when a `start` record of the branch carries
   `"stop_at_ready": true` (the owner said `stop at ready` at start), or when GitHub's review
   decision is `REVIEW_REQUIRED` (the branch rules need an approval the agent cannot give; no
   admin bypass is ever tried). Both refusals first write the merge line and the `merge` record;
4. refuses `merge.behind` or `merge.conflicting` as GitHub reports them, which sends the PR back
   to its author;
5. reads CI with `gh pr checks`: a failed or cancelled check refuses `merge.ci-red`, and pending
   checks wait through `gh pr checks --watch`, then CI is read again. "No checks reported" is
   trusted only after a second look: a workflow run listed for the head commit, or a workflow
   under `.github/workflows` that runs on `pull_request`, refuses `merge.ci-unknown`, since CI may
   not have started. With neither, the merge line records `checks: none reported`;
6. merges with `gh pr merge <PR> --<method> --match-head-commit <head>`, the method being squash
   unless the base branch's newest PR commit shows a merge or a rebase, then confirms with
   `gh pr view`, routing by the state it shows and not by the exit code: a PR that is not merged
   refuses `merge.not-merged`;
7. writes the merge line, appends the `merge` record and calls cleanup.

The merge line is `merge: <value>` in the PR description's measurement block. It replaces a
`merge:` line there or is added at the end of the block, and a block holding only the line is
added when the description has none. Every value it can take is in `LINE` below. The line never
claims a merge that did not happen.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

import cleanup
import core
import render
import settings

KEY = "merge"
# Every value of the merge line.
LINE = {
    "merged": "by the session, {method}",
    "no-checks": ", checks: none reported",
    "one-way": "left to the owner, one-way door",
    "setting": f"withheld, stop_at_ready is set in {settings.PATH}",
    "start": "withheld, stop at ready was given at start",
    "approval": "withheld, the branch rules need an approval the agent cannot give",
}
VIEW = "state,headRefOid,baseRefName,mergeStateStatus,mergeable,reviewDecision,body"
RED = ("fail", "cancel")
PULL_REQUEST = re.compile(r"^[^#\n]*\bpull_request(?:_target)?\b", re.MULTILINE)
PR_NUMBER = re.compile(r"\(#\d+\)$")
FINISH = "deliver.py finish"
BACK = "git pull --no-rebase origin {base}, then deliver.py check, deliver.py pr and deliver.py ready again"


def main(args: list[str], run: core.Run) -> None:
    if args:
        raise core.UsageError(f"merge takes no arguments, got: {' '.join(args)}")
    branch = run.mark["branch"]
    recs = cleanup.records(run, branch)
    pr_record = cleanup.latest(recs, "pr")
    if pr_record is None:
        raise core.Refused("merge.no-pr", "deliver.py pr", branch=branch)
    number = pr_record["number"]
    pr = json.loads(cleanup.gh(run, "pr", "view", str(number), "--json", VIEW))
    head, base = pr["headRefOid"], pr["baseRefName"]
    if pr["state"] != "OPEN":
        raise core.Refused("merge.not-open", FINISH, number=number, state=pr["state"].lower())
    ready = cleanup.latest(recs, "ready", commit=head)
    if ready is None or ready.get("result") != "small edit":
        raise core.Refused("merge.not-ready", "deliver.py ready", commit=head[:7])
    if ready.get("door") != "two-way":
        _write(run, branch, number, pr["body"], head, None, LINE["one-way"])
        raise core.Refused("merge.one-way", FINISH, number=number)
    if why := _withheld(run, recs, pr["reviewDecision"]):
        _write(run, branch, number, pr["body"], head, None, LINE[why])
        raise core.Refused("merge.withheld", FINISH, why=LINE[why].removeprefix("withheld, "))
    if pr["mergeable"] == "CONFLICTING" or pr["mergeStateStatus"] == "DIRTY":
        raise core.Refused("merge.conflicting", BACK.format(base=base), number=number, base=base)
    if pr["mergeStateStatus"] == "BEHIND":
        raise core.Refused("merge.behind", BACK.format(base=base), number=number, base=base)
    no_checks = _ci(run, number, head, base)
    method = _method(run, base)
    merged = subprocess.run(
        ["gh", "pr", "merge", str(number), f"--{method}", "--match-head-commit", head],
        cwd=run.checkout, capture_output=True, text=True)
    after = cleanup.view(run, number)
    if after.state != "MERGED":
        sys.stderr.write(merged.stderr)
        raise core.Refused("merge.not-merged", f"gh pr view {number}", number=number, state=after.state.lower())
    print(f"Merged PR #{number} with {method} at {head[:7]}.")
    line = LINE["merged"].format(method=method) + (LINE["no-checks"] if no_checks else "")
    _write(run, branch, number, pr["body"], head, method, line)
    default = cleanup.default_branch(run)
    for out in cleanup.clean(run, branch, default, after, recs, remove_records=False):
        print(out)


def _withheld(run: core.Run, recs: list[dict], review_decision: str | None) -> str | None:
    """The key in `LINE` of the first reason the merge is withheld, or None."""
    try:
        stack, _ = settings.load(run.checkout)
    except settings.SettingsError as e:
        raise core.Refused("merge.bad-settings", f"fix {settings.PATH}, then deliver.py merge", error=str(e)) from None
    if stack["stop_at_ready"]:
        return "setting"
    if cleanup.latest(recs, "start", stop_at_ready=True):
        return "start"
    if review_decision == "REVIEW_REQUIRED":
        return "approval"
    return None


def _ci(run: core.Run, number: int, head: str, base: str) -> bool:
    """Wait out pending checks; return True when there is no CI at all. Refuse on red or unknown CI."""
    while True:
        look = subprocess.run(["gh", "pr", "checks", str(number), "--json", "name,bucket"],
                                      cwd=run.checkout, capture_output=True, text=True)
        if look.stdout.strip():
            checks = json.loads(look.stdout)
        elif "no checks reported" in look.stderr:
            checks = []
        else:
            raise RuntimeError(f"gh pr checks {number} failed ({look.returncode}): {look.stderr.strip()}")
        red = [c["name"] for c in checks if c["bucket"] in RED]
        if red:
            raise core.Refused("merge.ci-red", BACK.format(base=base), commit=head[:7], checks=", ".join(red))
        pending = [c["name"] for c in checks if c["bucket"] == "pending"]
        if not pending:
            break
        print(f"Waiting for pending checks on PR #{number}: {', '.join(pending)}.", flush=True)
        subprocess.run(["gh", "pr", "checks", str(number), "--watch"], cwd=run.checkout,
                               capture_output=True, text=True)
    if checks:
        return False
    runs = json.loads(cleanup.gh(run, "run", "list", "--commit", head, "--json", "databaseId"))
    if runs:
        raise core.Refused("merge.ci-unknown", "deliver.py merge", commit=head[:7], why="a workflow run is listed for it")
    folder = run.checkout / ".github" / "workflows"
    for path in sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")]):
        if PULL_REQUEST.search(path.read_text(encoding="utf-8")):
            raise core.Refused("merge.ci-unknown", "deliver.py merge", commit=head[:7],
                               why=f".github/workflows/{path.name} runs on pull_request")
    return True


def _method(run: core.Run, base: str) -> str:
    """Squash, unless the base branch's newest commit a PR landed shows a merge or a rebase."""
    cleanup.git(run, "fetch", "--quiet", "origin", base, check=False)
    log = cleanup.git(run, "log", "--first-parent", "-n", "50", "--format=%P%x1f%cn%x1f%at%x1f%ct%x1f%s",
                      f"refs/remotes/origin/{base}", "--", check=False)
    for line in log.stdout.splitlines():
        parents, committer, authored, committed, subject = line.split("\x1f", 4)
        if len(parents.split()) > 1 and subject.startswith("Merge pull request #"):
            return "merge"
        if committer == "GitHub" and PR_NUMBER.search(subject):
            return "squash"
        if committer == "GitHub" and authored != committed:
            return "rebase"
    return "squash"


def _write(run: core.Run, branch: str, number: int, body: str, head: str, method: str | None, value: str) -> None:
    """Put the merge line into the PR description and append the `merge` record."""
    line = f"{KEY}: {value}"
    fd, body_file = tempfile.mkstemp(prefix="deliver-merge-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(with_line(body, line))
        cleanup.gh(run, "pr", "edit", str(number), "--body-file", body_file)
    finally:
        os.unlink(body_file)
    core.append_record(run.common_dir, branch, "merge", commit=head, method=method, merge_line=line)


def with_line(body: str, line: str) -> str:
    """The description with the merge line in its measurement block, which is added if missing."""
    lines = body.replace("\r\n", "\n").rstrip("\n").split("\n")
    opening, closing = list(render.MEASUREMENT_OPEN), render.MEASUREMENT_CLOSE[0]
    starts = [i for i in range(len(lines)) if lines[i:i + len(opening)] == opening]
    if not starts:
        return "\n".join([*lines, "", *opening, line, *render.MEASUREMENT_CLOSE]) + "\n"
    first = starts[-1] + len(opening)
    end = lines.index(closing, first)
    old = [i for i in range(first, end) if lines[i].startswith(f"{KEY}:")]
    if old:
        lines[old[0]] = line
    else:
        lines.insert(end, line)
    return "\n".join(lines) + "\n"
