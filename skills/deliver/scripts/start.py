"""deliver.py start: the first command of every run (#256 rules 17 to 23; #231 rules 35 and 36).

Routes, for one author:

- `start <ticket>` reads the ticket with `gh issue view` and runs the entry check
  (`entry_check.py`). A gap ends in exit 20 with one question, before anything is written.
- `start request` reads the request from `.deliver/request.md`, which the session wrote word for
  word. A request is never read from the command line.
- `start` with changes in the tree takes the whole tree as one change. With a clean tree it
  refuses and lists what it accepts.
- `start 1 2`, `start spec ...` and `start backlog` refuse: multi-ticket runs come later.

`--stop-at-ready`, anywhere among the arguments of a new run's `start`, says the owner said `stop
at ready` for this run. With `--resume` it is a usage error.

Where a run mark exists, every `start` but `start --resume` refuses, whatever its arguments.
Otherwise, in order, `start` reads the route's input; reads the stack settings, refusing
`preflight.bad-settings` before anything is written when they cannot be read; on the default
branch, a detached HEAD or a branch whose PR is merged, fetches `origin <default>` and cuts a
fresh branch from it (`deliver/ticket-<N>-<run>`, `deliver/request-<run>` or `deliver/tree-<run>`)
with `git switch`, which carries the tree's changes or refuses with nothing changed; adds `.deliver/` to the shared git directory's `info/exclude`;
writes the run mark (role `session`); appends the `start` record (`run`, `branch_created`, true
when it cut the branch, and `stop_at_ready`, true when the flag or the stack setting says so);
saves the request as the branch's `request.md` with its
`Source:` line (`render.py` reads it) and a `save` record; prints the requirements of a ticket,
so a preflight stop leaves them on screen; and runs preflight without the probe check. Once that
passes it prints the probe step. The session then runs the probe, which the guard refuses, and
`deliver.py start --resume`. `start` prints no run grant: the grant needs the probe check passed.

`start --resume` keeps the mark, prints where the run stands from its records, runs the whole
preflight, probe check included, and prints the grant line once it passes. The grant line names
"no merge: stop at ready" when the stack setting or the run's own `start` record says so.
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
from pathlib import Path

import core
import entry_check
import guard
import preflight
import settings

DROP = ".deliver"
REQUEST = f"{DROP}/request.md"
TICKET = re.compile(r"[1-9]\d*")
TREE_SOURCE = "Source: working tree, requirements written from the diff"
TEXTS = ("request", "requirements", "plan", "summary")
STOP_AT_READY = "--stop-at-ready"


def main(args: list[str], run: core.Run | None) -> None:
    said = STOP_AT_READY in args
    rest = [a for a in args if a != STOP_AT_READY]
    flag = f" {STOP_AT_READY}" if said else ""
    if said and rest == ["--resume"]:
        raise core.UsageError(f"{STOP_AT_READY} goes with the start of a new run, not with --resume")
    if run and run.mark and rest != ["--resume"]:
        raise core.Refused("start.run-in-progress", "deliver.py finish, to end it", run=run.mark["run"],
                           mark=run.git_dir / core.MARK)
    route, ticket = _route(rest, flag)
    if run is None:
        raise core.Refused("start.not-a-repo", f"run deliver.py start{flag} inside the repo", cwd=Path.cwd())
    if route == "resume":
        return resume(run)
    rerun = " ".join(["deliver.py start", *args])
    requirements: list[str] = []
    if route == "ticket":
        request, requirements = _ticket(run, ticket, rerun)
    elif route == "request":
        text = (run.checkout / REQUEST).read_text(encoding="utf-8") if (run.checkout / REQUEST).is_file() else ""
        if not text.strip():
            raise core.Refused("start.no-request", f"write the request word for word into {REQUEST}, then run {rerun}",
                               file=REQUEST)
        request = f"Source: conversation\n\n{text.strip('\n')}\n"
    else:
        if not _git(run, "status", "--porcelain", "--", ".", f":(exclude){DROP}").stdout:
            raise core.Refused("start.nothing-to-start")
        request = TREE_SOURCE + "\n"
    try:
        stack, _ = settings.load(run.checkout)
    except settings.SettingsError as e:
        raise core.Refused("preflight.bad-settings", f"fix {settings.PATH}, then run {rerun}", error=str(e)) from None
    run_id = secrets.token_hex(4)
    branch, cut = _branch(run, f"{route}-{ticket}" if ticket else route, run_id, rerun)
    _exclude(run)
    run.mark = core.write_mark(run.git_dir, run_id, branch)
    run.record("start", run=run_id, branch_created=cut, stop_at_ready=said or stack["stop_at_ready"])
    folder = core.records_dir(run.common_dir, branch)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.md").write_text(request, encoding="utf-8")
    if route == "request":
        (run.checkout / REQUEST).unlink()
    run.record("save", kind="request", file="request.md", commit=_tied_commit(run))
    print(f"Started run {run_id} on branch {branch}.")
    for number, requirement in enumerate(requirements, 1):
        print(f"R{number}: {requirement}")
    preflight.run(run, probe=False)
    print(f"Next: run {guard.PROBE}, which the guard refuses, then deliver.py start --resume")


def resume(run: core.Run) -> None:
    """Print where the marked run stands, rerun the whole preflight, and print the grant line."""
    if not run.mark:
        raise core.Refused("start.no-run", "deliver.py start")
    mark = run.mark
    folder = core.records_dir(run.common_dir, mark["branch"])
    path = folder / core.RECORDS
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    print(f"Resuming run {mark['run']} on branch {mark['branch']}, started {mark['started']}.")
    print(f"Saved: {', '.join(k for k in TEXTS if (folder / f'{k}.md').is_file()) or 'nothing'}.")
    checks = [r for r in records if r["event"] == "check"]
    if checks:
        print(f"Checks: {len(checks)}; the last, `{checks[-1]['command']}`, exited {checks[-1]['exit']} "
              f"at {_short(checks[-1]['commit'])}.")
    else:
        print("Checks: none.")
    newest = {r["event"]: r for r in records}
    if pr := newest.get("pr"):
        print(f"PR: #{pr['number']} {pr['url']}")
    if ready := newest.get("ready"):
        print(f"Ready: {ready['result']} at {_short(ready['commit'])}.")
    if merge := newest.get("merge"):
        print(f"Merged at {_short(merge['commit'])}.")
    preflight.run(run)
    stack = settings.load(run.checkout)[0]
    said = any(r["event"] == "start" and r.get("run") == mark["run"] and r.get("stop_at_ready") is True for r in records)
    print(grant_line({**stack, "stop_at_ready": stack["stop_at_ready"] or said}))


def grant_line(stack: dict) -> str:
    """#231 rules 35 and 36, one author: what the run may do that others can see."""
    if stack["stop_at_ready"]:
        merge = "mark it ready through the scripts, no merge: stop at ready"
    else:
        merge = "mark it ready and merge it through the scripts"
    follow_ups = ", file follow-up tickets" if stack["follow_ups"] else ""
    return f"Run grant: push this branch, open and update its PR, {merge}{follow_ups}."


def _route(args: list[str], flag: str) -> tuple[str, int | None]:
    if not args:
        return "tree", None
    if args == ["--resume"]:
        return "resume", None
    if args == ["request"]:
        return "request", None
    if len(args) == 1 and TICKET.fullmatch(args[0]):
        return "ticket", int(args[0])
    if args[0] in ("spec", "backlog") or (len(args) > 1 and all(TICKET.fullmatch(a) for a in args)):
        raise core.Refused("start.not-built", f"deliver.py start <one ticket>{flag}", form=" ".join(["start", *args]))
    raise core.UsageError(f"start takes one ticket number, request, --resume or nothing, got: {' '.join(args)}")


def _ticket(run: core.Run, number: int, rerun: str) -> tuple[str, list[str]]:
    """The ticket's request.md text and requirements, or exit 20 when the entry check finds a gap."""
    proc = _call(run, "gh", "issue", "view", str(number), "--json", "title,body,comments")
    if proc.returncode != 0:
        raise core.Refused("start.no-ticket", f"check the number and gh auth status, then run {rerun}",
                           ticket=number, error=proc.stderr.strip())
    issue = json.loads(proc.stdout)
    entry = entry_check.check(issue.get("body") or "", [c.get("body") or "" for c in issue.get("comments") or []])
    if entry.gaps:
        raise core.Question("\n".join([
            f"Ticket #{number} does not pass the entry check:", *(f"- {gap}" for gap in entry.gaps),
            f"Will you add what is missing to ticket #{number}? Then the session runs {rerun} again.",
        ]))
    quote = f"\n{entry.quote}\n" if entry.quote else ""
    return f"Source: ticket #{number}\n{quote}", entry.requirements


def _branch(run: core.Run, route: str, run_id: str, rerun: str) -> tuple[str, bool]:
    """The run's branch, and whether it was cut: the checked-out one, or a fresh one from origin's default branch."""
    default = _out(run, "gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name").strip()
    branch = _git(run, "branch", "--show-current").stdout.strip()
    if branch and branch != default:
        merged = json.loads(_out(run, "gh", "pr", "list", "--head", branch, "--state", "merged", "--json", "number"))
        if not merged:
            return branch, False
    fresh = f"deliver/{route}-{run_id}"
    fetch = _git(run, "fetch", "origin", default)
    if fetch.returncode != 0:
        raise core.Refused("start.fetch-failed", f"fix the error, then run {rerun}", branch=default,
                           error=fetch.stderr.strip())
    switch = _git(run, "switch", "--no-track", "-c", fresh, f"origin/{default}")
    if switch.returncode != 0:
        raise core.Refused("start.cannot-carry", f"commit or stash the changes git names, then run {rerun}",
                           branch=default, error=switch.stderr.strip())
    return fresh, True


def _exclude(run: core.Run) -> None:
    """Add `.deliver/` to the shared git directory's `info/exclude`, once."""
    exclude = run.common_dir / "info" / "exclude"
    text = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if f"{DROP}/" not in text.splitlines():
        exclude.parent.mkdir(exist_ok=True)
        newline = "\n" if text and not text.endswith("\n") else ""
        exclude.write_text(f"{text}{newline}{DROP}/\n", encoding="utf-8")


def _tied_commit(run: core.Run) -> str | None:
    """`HEAD`, or None when a tracked file is changed, as `save` stamps a saved text."""
    if _git(run, "status", "--porcelain", "--untracked-files=no").stdout:
        return None
    return _git(run, "rev-parse", "--verify", "-q", "HEAD").stdout.strip() or None


def _short(commit: str | None) -> str:
    return commit[:7] if commit else "no commit"


def _git(run: core.Run, *args: str) -> subprocess.CompletedProcess:
    return _call(run, "git", *args)


def _call(run: core.Run, *command: str) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=run.checkout, capture_output=True, text=True)


def _out(run: core.Run, *command: str) -> str:
    proc = _call(run, *command)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout
