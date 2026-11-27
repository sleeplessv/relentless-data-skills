"""Cleanup after a merge: the branch, its remote branch and its records (#256 rules 9, 44 to 46).

`clean` is the one cleanup, called by `merge` after a merge and by `finish`. It removes the local
branch, the branch on `origin` and, when `finish` asks, the branch's records, only when all of
these hold:

- this run created the branch: a `start` record of the branch carries `"branch_created": true`;
- GitHub shows the PR merged;
- the PR's head commit equals the local tip and the remote tip, each where it still exists. The
  test is equality and never ancestry, because a squash merge leaves the branch's commits out of
  the target's history;
- the checkout that has the branch checked out has no changed or untracked file;
- no other worktree has the branch checked out.

When one fails, nothing is removed and one `Kept <branch>: <reasons>.` line names each failed
guard. The default branch is never touched. Nothing passes `--force`: the local branch is deleted
with `git update-ref -d` against the PR's head commit, so git refuses if the tip has moved, and
the remote branch with `git push origin --delete`. After a merge, the run's own checkout is
switched to the default branch first when its tree is clean; a switch git refuses is kept as a
failed guard. Stage 3 starts no author worktree, so cleanup removes none.

The helpers `git`, `gh`, `records` and `view` are shared with `merge` and `finish`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import core


@dataclass
class Pr:
    """A PR as GitHub shows it: its number, state (`OPEN`, `MERGED` or `CLOSED`) and head commit."""

    number: int
    state: str
    head: str


def clean(run: core.Run, branch: str, default: str, pr: Pr | None, recs: list[dict], *,
          remove_records: bool) -> list[str]:
    """Remove what every guard allows and return the lines that say what was removed or kept."""
    if branch == default:
        return []
    if pr is None:
        return [f"Kept {branch}: no PR was opened."]
    reasons = []
    if not any(r["event"] == "start" and r.get("branch_created") is True for r in recs):
        reasons.append("this run did not create it")
    if pr.state != "MERGED":
        reasons.append(f"PR #{pr.number} is {pr.state.lower()}, not merged")
    local = git(run, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).stdout.strip() or None
    remote = git(run, "ls-remote", "origin", f"refs/heads/{branch}").stdout.split("\t")[0].strip() or None
    for where, tip in (("local", local), ("remote", remote)):
        if tip and tip != pr.head:
            reasons.append(f"the {where} tip {tip[:7]} is not the PR's head {pr.head[:7]}")
    holders = _holders(run, branch)
    own = run.checkout.resolve() in holders
    dirty = own and bool(git(run, "status", "--porcelain").stdout.strip())
    if dirty:
        reasons.append(f"{run.checkout} has changed or untracked files")
    reasons += [f"it is checked out in {path}" for path in holders if path != run.checkout.resolve()]
    lines = []
    if pr.state == "MERGED" and own and not dirty:
        switch = git(run, "switch", "--quiet", default, check=False)
        if switch.returncode == 0:
            lines.append(f"Switched this checkout to {default}.")
        else:
            reasons.append(f"git switch {default} failed: {switch.stderr.strip()}")
    if reasons:
        return lines + [f"Kept {branch}: {'; '.join(reasons)}."]
    removed = []
    if local:
        git(run, "update-ref", "-d", f"refs/heads/{branch}", pr.head)
        git(run, "config", "--remove-section", f"branch.{branch}", check=False)
        removed.append(f"the local branch {branch}")
    if remote:
        git(run, "push", "--quiet", "origin", "--delete", branch)
        removed.append(f"the remote branch origin/{branch}")
    if remove_records:
        shutil.rmtree(core.records_dir(run.common_dir, branch), ignore_errors=True)
        removed.append(f"the records of {branch}")
    if removed:
        lines.append(f"Removed {_join(removed)}.")
    return lines


def records(run: core.Run, branch: str) -> list[dict]:
    """The branch's events from `records.jsonl`, oldest first; none when the file is missing."""
    path = core.records_dir(run.common_dir, branch) / core.RECORDS
    if not branch or not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def latest(recs: list[dict], event: str, **fields: object) -> dict | None:
    """The newest record of the event whose fields hold the given values, or None."""
    found = [r for r in recs if r["event"] == event and all(r.get(k) == v for k, v in fields.items())]
    return found[-1] if found else None


def view(run: core.Run, number: int) -> Pr:
    data = json.loads(gh(run, "pr", "view", str(number), "--json", "state,headRefOid"))
    return Pr(number, data["state"], data["headRefOid"])


def default_branch(run: core.Run) -> str:
    return gh(run, "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name").strip()


def git(run: core.Run, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=run.checkout, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc


def gh(run: core.Run, *args: str) -> str:
    proc = subprocess.run(["gh", *args], cwd=run.checkout, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def _holders(run: core.Run, branch: str) -> list[Path]:
    """The worktrees that have the branch checked out."""
    holders, path = [], None
    for line in git(run, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            path = line.removeprefix("worktree ")
        elif line == f"branch refs/heads/{branch}":
            holders.append(Path(path).resolve())
    return holders


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
