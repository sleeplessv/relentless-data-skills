"""Cleanup after a merge: the branch, its remote branch and its records (#256 rules 9, 44 to 47).

`clean` is the one cleanup, called by `merge` after a merge and by `finish`. It removes the local
branch, the branch on `origin` and, when `finish` asks, the branch's records, only when all of
these hold:

- this run created the branch (`created`), and no later run has started on the branch since;
- GitHub shows the PR merged;
- the PR's head commit equals the local tip and the remote tip, each where it still exists. The
  test is equality and never ancestry, because a squash merge leaves the branch's commits out of
  the target's history;
- the checkout cleanup runs in has no changed or untracked file, whatever branch it is on and
  whatever `status.showUntrackedFiles` says;
- no other worktree has the branch checked out;
- every git read behind these guards worked: a read that fails is a reason to keep, never
  taken as "absent".

When one fails, nothing is removed and one `Kept <branch>: <reasons>.` line names each failed
guard. The default branch is never touched. Nothing passes `--force`. After a merge, a clean
checkout goes back to the default branch from whatever branch it is on. In order, cleanup deletes
the remote branch with `git push origin --delete`, switches the checkout to the default branch,
deletes the local branch with `git update-ref -d` against the PR's head commit (git refuses if
the tip has moved), and removes the records. A step that fails stops it there, and a `Kept` line
names what remains and why. The records removed are the branch's own files, one by one: the
saved texts, the check output its `check` records name and, last, `records.jsonl`; then empty
folders go. A file the records do not name, such as another branch's below this one
(`topic/child` under `topic`), stays. Stage 3 starts no author worktree, so cleanup removes none.

A run's records are the branch's records from that run's own `start` record, which `deliver.py
start` appends, up to the next run's (`run_records`). A run begun before `start` wrote that record
falls back: in a log with no `start` record, its records are those written at or after its mark's
`started` time. A run with neither has no records, so another run's never decide for it.

The helpers `git`, `gh`, `records`, `run_records`, `later_run`, `latest` and `view` are shared
with `merge` and `finish`.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import core

# The texts `deliver.py save` keeps in a branch's records.
SAVED = ("request.md", "requirements.md", "plan.md", "summary.md")


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


def clean(run: core.Run, branch: str, default: str, pr: Pr | None, *, created: bool,
          remove_records: bool, later: bool = False) -> Cleaned:
    """Remove what every guard allows and say what was removed or kept.

    `created` is true when this run created the branch (`created` below). `later` is true when a
    later run has started on the branch: its branch and records stay.
    """
    what = f"{branch} and its records" if remove_records else branch
    if branch == default:
        return Cleaned([f"Kept {what}: {branch} is the default branch."], False)
    if pr is None:
        return Cleaned([f"Kept {what}: no PR was opened."], False)
    final, reasons = [], []  # final: no later finish will change it
    if not created:
        final.append("this run did not create it")
    if later:
        final.append("a later run has started on it")
    if pr.state == "CLOSED":
        final.append(f"PR #{pr.number} is closed, not merged")
    elif pr.state != "MERGED":
        reasons.append(f"PR #{pr.number} is {pr.state.lower()}, not merged")
    local = None
    found = git(run, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
    if found.returncode == 0:
        local = found.stdout.strip()
    elif found.returncode != 1 or found.stderr.strip():
        reasons.append(f"git rev-parse refs/heads/{branch} failed: {_said(found)}")
    remote = None
    listed = git(run, "ls-remote", "origin", f"refs/heads/{branch}", check=False)
    if listed.returncode == 0:
        remote = listed.stdout.split("\t")[0].strip() or None
    else:
        reasons.append(f"git ls-remote origin failed: {_said(listed)}")
    for where, tip in (("local", local), ("remote", remote)):
        if tip and tip != pr.head:
            reasons.append(f"the {where} tip {tip[:7]} is not the PR's head {pr.head[:7]}")
    status = git(run, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none", check=False)
    clean_tree = status.returncode == 0 and not status.stdout.strip()
    if status.returncode != 0:
        reasons.append(f"git status failed in {run.checkout}: {_said(status)}")
    elif not clean_tree:
        reasons.append(f"{run.checkout} has changed or untracked files")
    holders, error = _holders(run, branch)
    if error:
        reasons.append(error)
    here = run.checkout.resolve()
    reasons += [f"it is checked out in {path}" for path in holders if path != here]
    current = git(run, "branch", "--show-current", check=False)
    away = current.returncode != 0 or current.stdout.strip() != default
    lines = []

    def home() -> str | None:
        """Switch this checkout to the default branch; the reason it failed, or None."""
        switch = git(run, "switch", "--quiet", default, check=False)
        if switch.returncode != 0:
            return f"git switch {default} failed: {_said(switch)}"
        lines.append(f"Switched this checkout to {default}.")
        return None

    if final or reasons:
        if pr.state == "MERGED" and clean_tree and away and (why := home()):
            reasons.append(why)
        return Cleaned(lines + [f"Kept {what}: {'; '.join(final + reasons)}."], bool(reasons) and not final)
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
    if away and (why := home()):
        return stop(f"the local branch {branch}{rest}" if local else f"the records of {branch}", why)
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
    """Delete the branch's own record files one by one, `records.jsonl` last, then its empty folders.

    Its own files are the saved texts, the check output its `check` records name and the event
    log. Any other file in the folder, such as another branch's records below it, stays.
    """
    top = run.common_dir / "deliver" / "branches"
    folder = core.records_dir(run.common_dir, branch)
    named = set(SAVED)
    for r in records(run, branch):
        if r["event"] == "save" and isinstance(r.get("file"), str):
            named.add(r["file"])
        if r["event"] == "check" and isinstance(r.get("output"), str):
            named.add(r["output"])
    inside = folder.resolve()
    files = []
    for name in sorted(named):
        path = folder / name
        if path.resolve().parent.is_relative_to(inside) and path.name != core.RECORDS:
            files.append(path)
    for path in [*files, folder / core.RECORDS]:
        if path.is_symlink() or path.is_file():
            path.unlink()
    for path in sorted({p.parent for p in files} | {folder}, key=lambda p: len(p.parts), reverse=True):
        while path != top and path.is_relative_to(top) and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent


def records(run: core.Run, branch: str) -> list[dict]:
    """The branch's events from `records.jsonl`, oldest first; none when the file is missing."""
    path = core.records_dir(run.common_dir, branch) / core.RECORDS
    if not branch or not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_records(recs: list[dict], run_id: str | None = None, started: str | None = None) -> list[dict]:
    """One run's records: from its own `start` record to the next `start` record.

    The run's `start` record is the newest one carrying `"run": run_id`. In a log with no `start`
    record at all, the run's records begin at the first one written at or after `started`, the
    mark's start time. Otherwise the run has no records.
    """
    first = _start_of(recs, run_id, started)
    if first is None:
        return []
    later = [i for i, r in enumerate(recs) if i > first and r["event"] == "start"]
    return recs[first:later[0]] if later else recs[first:]


def later_run(recs: list[dict], run_id: str | None, started: str | None = None) -> bool:
    """Whether a run has started on the branch after the run `run_id`, by its `start` record."""
    first = _start_of(recs, run_id, started)
    return first is not None and any(r["event"] == "start" for r in recs[first + 1:])


def created(recs: list[dict], branch: str, run_id: str | None) -> bool:
    """Whether the run created the branch.

    Its `start` record says so with `"branch_created": true`. A run begun before `start` wrote
    that record has none: then the branch is the run's when it carries the name `deliver.py start`
    gives a branch it cuts, `deliver/<route>-<run>`.
    """
    start = latest(recs, "start")
    if start is not None:
        return start.get("branch_created") is True
    return bool(run_id) and re.fullmatch(rf"deliver/[a-z0-9-]+-{re.escape(run_id)}", branch) is not None


def _start_of(recs: list[dict], run_id: str | None, started: str | None) -> int | None:
    if any(r["event"] == "start" for r in recs):
        starts = [i for i, r in enumerate(recs) if r["event"] == "start" and r.get("run") == run_id]
        return starts[-1] if starts else None
    if started:  # a log with no start record at all: a run begun before start wrote one
        return next((i for i, r in enumerate(recs) if str(r.get("at", "")) >= started), None)
    return None


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


def _holders(run: core.Run, branch: str) -> tuple[list[Path], str | None]:
    """The worktrees that have the branch checked out, and why that cannot be read, if it cannot."""
    listed = git(run, "worktree", "list", "--porcelain", check=False)
    if listed.returncode != 0:
        return [], f"git worktree list failed: {_said(listed)}"
    holders, path = [], None
    for line in listed.stdout.splitlines():
        if line.startswith("worktree "):
            path = line.removeprefix("worktree ")
        elif line == f"branch refs/heads/{branch}":
            holders.append(Path(path).resolve())
    return holders, None


def _said(proc: subprocess.CompletedProcess) -> str:
    """What a failed git command printed, on one line."""
    return " ".join(proc.stderr.split())


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
