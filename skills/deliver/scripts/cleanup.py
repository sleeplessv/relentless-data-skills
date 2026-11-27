"""Cleanup after a merge: the branch, its remote branch and its records (#256 rules 9, 44 to 47).

`clean` is the one cleanup, called by `merge` after a merge and by `finish`. It removes the local
branch, the branch on `origin` and, when `finish` asks, the branch's records, only when all of
these hold:

- this run created the branch: the run's `start` record carries `"branch_created": true`;
- GitHub shows the PR merged;
- the PR's head commit equals the local tip and the remote tip, each where it still exists. The
  test is equality and never ancestry, because a squash merge leaves the branch's commits out of
  the target's history;
- the checkout cleanup runs in has no changed or untracked file, whatever branch it is on and
  whatever `status.showUntrackedFiles` says;
- no other worktree has the branch checked out.

When one fails, nothing is removed and one `Kept <branch>: <reasons>.` line names each failed
guard. The default branch is never touched. Nothing passes `--force`. In order, cleanup deletes
the remote branch with `git push origin --delete`, switches the checkout to the default branch
when the checkout has the branch, deletes the local branch with `git update-ref -d` against the
PR's head commit (git refuses if the tip has moved), and removes the records. A step that fails
stops it there, and a `Kept` line names what remains and why. Records are only the branch's
own: a folder holding another branch's `records.jsonl` (`topic/child` under `topic`) stays.
Stage 3 starts no author worktree, so cleanup removes none.

A run's records are the branch's records from that run's `start` record up to the next run's
(`run_records`), so an earlier run on the same branch never decides for a later one.

The helpers `git`, `gh`, `records`, `run_records`, `latest` and `view` are shared with `merge`
and `finish`.
"""
from __future__ import annotations

import json
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


@dataclass
class Cleaned:
    """What cleanup printed, and whether it left something a later `finish` should still remove."""

    lines: list[str]
    unfinished: bool


def clean(run: core.Run, branch: str, default: str, pr: Pr | None, recs: list[dict], *,
          remove_records: bool) -> Cleaned:
    """Remove what every guard allows and say what was removed or kept."""
    what = f"{branch} and its records" if remove_records else branch
    if branch == default:
        return Cleaned([f"Kept {what}: {branch} is the default branch."], False)
    if pr is None:
        return Cleaned([f"Kept {what}: no PR was opened."], False)
    final, reasons = [], []  # final: no later finish will change it
    if not latest(recs, "start", branch_created=True):
        final.append("this run did not create it")
    if pr.state == "CLOSED":
        final.append(f"PR #{pr.number} is closed, not merged")
    elif pr.state != "MERGED":
        reasons.append(f"PR #{pr.number} is {pr.state.lower()}, not merged")
    local = git(run, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).stdout.strip() or None
    listed = git(run, "ls-remote", "origin", f"refs/heads/{branch}", check=False)
    if listed.returncode != 0:
        reasons.append(f"git ls-remote origin failed: {_said(listed)}")
    remote = listed.stdout.split("\t")[0].strip() or None
    for where, tip in (("local", local), ("remote", remote)):
        if tip and tip != pr.head:
            reasons.append(f"the {where} tip {tip[:7]} is not the PR's head {pr.head[:7]}")
    status = git(run, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none", check=False)
    clean_tree = status.returncode == 0 and not status.stdout.strip()
    if status.returncode != 0:
        reasons.append(f"git status failed in {run.checkout}: {_said(status)}")
    elif not clean_tree:
        reasons.append(f"{run.checkout} has changed or untracked files")
    holders = _holders(run, branch)
    here = run.checkout.resolve()
    reasons += [f"it is checked out in {path}" for path in holders if path != here]
    lines = []
    if final or reasons:
        if pr.state == "MERGED" and here in holders and clean_tree:
            switch = git(run, "switch", "--quiet", default, check=False)
            if switch.returncode == 0:
                lines.append(f"Switched this checkout to {default}.")
            else:
                reasons.append(f"git switch {default} failed: {_said(switch)}")
        return Cleaned(lines + [f"Kept {what}: {'; '.join(final + reasons)}."], bool(reasons))
    removed = []

    def stop(kept: str, why: str) -> Cleaned:
        done = [f"Removed {_join(removed)}."] if removed else []
        return Cleaned(lines + done + [f"Kept {kept}: {why}."], True)

    rest = " and its records" if remove_records else ""
    if remote:
        push = git(run, "push", "--quiet", "origin", "--delete", branch, check=False)
        if push.returncode != 0:
            return stop(what, f"git push origin --delete {branch} failed: {_said(push)}")
        removed.append(f"the remote branch origin/{branch}")
    if here in holders:
        switch = git(run, "switch", "--quiet", default, check=False)
        if switch.returncode != 0:
            return stop(f"the local branch {branch}{rest}", f"git switch {default} failed: {_said(switch)}")
        lines.append(f"Switched this checkout to {default}.")
    if local:
        delete = git(run, "update-ref", "-d", f"refs/heads/{branch}", pr.head, check=False)
        if delete.returncode != 0:
            return stop(f"the local branch {branch}{rest}", f"git update-ref -d failed: {_said(delete)}")
        git(run, "config", "--remove-section", f"branch.{branch}", check=False)
        removed.append(f"the local branch {branch}")
    if remove_records:
        try:
            remove_records_of(run, branch)
        except OSError as e:
            return stop(f"the records of {branch}", str(e))
        removed.append(f"the records of {branch}")
    if removed:
        lines.append(f"Removed {_join(removed)}.")
    return Cleaned(lines, False)


def remove_records_of(run: core.Run, branch: str) -> None:
    """Delete the branch's own record files, leave any other branch's folder below, prune empty folders."""
    top = run.common_dir / "deliver" / "branches"
    folder = core.records_dir(run.common_dir, branch)
    if folder.is_dir():
        _clear(folder)
    while folder != top and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


def _clear(folder: Path) -> None:
    # records.jsonl goes last, so a removal that fails partway leaves the run findable.
    for entry in sorted(folder.iterdir(), key=lambda e: e.name == core.RECORDS):
        if entry.is_dir() and not entry.is_symlink():
            if (entry / core.RECORDS).exists():
                continue  # the records of another branch, named <branch>/<entry>
            _clear(entry)
            if not any(entry.iterdir()):
                entry.rmdir()
        else:
            entry.unlink()


def records(run: core.Run, branch: str) -> list[dict]:
    """The branch's events from `records.jsonl`, oldest first; none when the file is missing."""
    path = core.records_dir(run.common_dir, branch) / core.RECORDS
    if not branch or not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_records(recs: list[dict], run_id: str | None = None) -> list[dict]:
    """One run's records: from its `start` record to the next `start` record.

    The run's `start` record is the newest one carrying `"run": run_id`, or else the newest one.
    With no `start` record at all, every record counts.
    """
    starts = [i for i, r in enumerate(recs) if r["event"] == "start"]
    if not starts:
        return recs
    mine = [i for i in starts if run_id is not None and recs[i].get("run") == run_id]
    first = (mine or starts)[-1]
    later = [i for i in starts if i > first]
    return recs[first:later[0]] if later else recs[first:]


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
        raise RuntimeError(f"git {' '.join(args)} failed ({proc.returncode}): {_said(proc)}")
    return proc


def gh(run: core.Run, *args: str) -> str:
    proc = subprocess.run(["gh", *args], cwd=run.checkout, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed ({proc.returncode}): {_said(proc)}")
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


def _said(proc: subprocess.CompletedProcess) -> str:
    """What a failed git command printed, on one line."""
    return " ".join(proc.stderr.split())


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
