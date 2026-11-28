"""deliver.py ready: run the small test and mark the PR ready, or refuse (#256 ready row, rules 30 and 34).

`ready` reads the run's records, the saved plan, the stack settings and the committed branch. In
order, it refuses:

1. `ready.no-preflight` unless the newest `preflight` record of the run mark's run is a pass;
2. `ready.drop-folder` while `.deliver/` holds any file;
3. `ready.no-pr` while the branch's records hold no `pr` record;
4. `ready.unreadable` when the saved plan cannot be read, and `ready.bad-settings` when the stack
   settings cannot be read;
5. `ready.no-pass` when a command proof, or a set `check_command`, has no counted pass on `HEAD`.
   A `check` record counts when its `command` is the proof's command, or `check_command`,
   character for character, it exited 0, it selected something, and its `commit` is the full
   `HEAD`. `render.counted` holds every condition but the last, for the Evidence lines too; `ready`
   compares the commit with `HEAD` itself;
6. `ready.bad-query` when a proof that is not a command proof names a query (the word `query`
   outside its code spans) and is not one query proof: the word `query` first and one code span,
   the query command;
7. `ready.no-query-numbers` when a query proof lacks its before or its after number. Its before
   number is a check of that command that exited 0 at a commit in the history of the merge base
   with `origin/<default branch>`; its after number is a counted pass on `HEAD`. A check holds a
   number when the last non-blank line of its saved output is a number and nothing else (`118`,
   `-3`, `0.25`).

It then runs the small test (`small_test.measure`) on `HEAD` against `origin/<default branch>`.
A change that fails it gets a `ready` record with result `needs review` and the refusal
`ready.needs-review`, which names no next command, and the PR stays a draft (#267 rule 40). A
change that passes is refused `ready.stale-pr` when the PR's head commit on GitHub is not the
full `HEAD` it tested, before anything is written to the PR. Otherwise it gets, in this order: its description rendered again from the saved records
with the blast radius, the door and the measurement block (`gh pr edit`), `gh pr ready`, the
`ready` record with result `small edit`, and one call of `scan.start_background()`.

The measurement block holds the spec's keys in order (#407), each value from the records or a
fixed value of the small edit: `harness` and `preflight warnings` from the passing preflight,
`slot wait` summed over the checks written since the run mark's start, `review skills` from
`deps.review_skill_hashes`, `roles: author`, no findings, follow-ups or fix rounds, no waiver, and
`merge: pending` until `merge` writes its line. No value holds a session id.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

import core
import deps
import plan
import render
import save
import scan
import settings
import small_test

DROP = ".deliver"
QUERY = re.compile(r"query\b[^`]*`([^`]+)`[^`]*", re.IGNORECASE)
NAMES_QUERY = re.compile(r"\bquery\b", re.IGNORECASE)
NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")
VERSION = json.loads((Path(__file__).resolve().parent.parent / "plugin.json").read_text(encoding="utf-8"))["version"]
AGAIN = "deliver.py ready"


def main(args: list[str], run: core.Run) -> None:
    if args:
        raise core.UsageError(f"ready takes no arguments, got: {' '.join(args)}")
    branch = run.mark["branch"]
    folder = core.records_dir(run.common_dir, branch)
    records = render._records(folder)
    preflights = [r for r in records if r["event"] == "preflight" and r.get("run") == run.mark["run"]]
    if not preflights or preflights[-1].get("result") != "pass":
        raise core.Refused("ready.no-preflight", "deliver.py preflight", run=run.mark["run"])
    left = sorted(p.name for p in (run.checkout / DROP).glob("*"))
    if left:
        kind = left[0][:-3] if left[0].endswith(".md") else ""
        fix = f"deliver.py save {kind}" if kind in save.KINDS else f"move {DROP}/{left[0]} out of {DROP}/, then {AGAIN}"
        raise core.Refused("ready.drop-folder", fix, files=", ".join(left))
    prs = [r for r in records if r["event"] == "pr"]
    if not prs:
        raise core.Refused("ready.no-pr", "deliver.py pr", branch=branch)
    head = _git(run, "rev-parse", "HEAD").strip()
    saved, stack = passes_on_head(run, records, head, "ready", AGAIN)
    default = _gh(run, "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name").strip()
    base = f"origin/{default}"
    for requirement in saved.requirements:
        if query := QUERY.fullmatch(requirement.proof.strip()):
            _query_numbers(run, folder, records, requirement.number, query.group(1), head, base, branch)
        elif not render.COMMAND.match(requirement.proof) and NAMES_QUERY.search(re.sub(r"`[^`]*`", "", requirement.proof)):
            raise core.Refused("ready.bad-query", f"give {requirement.number} one query proof in {DROP}/plan.md, "
                               "then deliver.py save plan", requirement=requirement.number)

    result = small_test.measure(run.checkout, base, stack, saved.door,
                                {r.number: r.proof for r in saved.requirements})
    if not result["passed"]:
        _record(run, head, "needs review", result)
        raise core.Refused("ready.needs-review", why=result["reason"].removeprefix("needs review: "))

    number, url = prs[-1]["number"], prs[-1]["url"]
    remote = _gh(run, "pr", "view", str(number), "--json", "headRefOid", "--jq", ".headRefOid").strip()
    if remote != head:
        raise core.Refused("ready.stale-pr", "deliver.py pr", number=number, remote=remote[:7] or "unknown",
                           commit=head[:7])
    try:
        body = render.description(folder, blast=("low", _blast(result, stack)), door=(result["door"], saved.door_reason),
                                  measurement=_measurement(run, records, preflights[-1], result))
    except render.Unreadable as e:
        raise core.Refused("ready.unreadable", f"rewrite {DROP}/{e.kind}.md, then deliver.py save {e.kind}",
                           kind=e.kind, why=str(e)) from None
    fd, body_file = tempfile.mkstemp(prefix="deliver-ready-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        _gh(run, "pr", "edit", str(number), "--body-file", body_file)
    finally:
        os.unlink(body_file)
    _gh(run, "pr", "ready", str(number))
    _record(run, head, "small edit", result)
    scan.start_background(preflights[-1].get("harness"), run)
    print(f"{result['reason']}.")
    print(f"Marked PR #{number} ready: {url}")


def passes_on_head(run: core.Run, records: list[dict], head: str, prefix: str, again: str) -> tuple[plan.Plan, dict]:
    """The saved plan and the stack settings, once each command proof and `check_command` has a counted pass on `head`.

    Refuses `<prefix>.unreadable`, `<prefix>.bad-settings` or `<prefix>.no-pass`; `ready` and `brief` share it.
    """
    try:
        saved = plan.read(run)
        if saved is None:
            raise plan.PlanError("it is not saved")
    except plan.PlanError as e:
        raise core.Refused(f"{prefix}.unreadable", f"rewrite {DROP}/plan.md, then deliver.py save plan",
                           kind="plan", why=str(e)) from None
    try:
        stack, _ = settings.load(run.checkout)
    except settings.SettingsError as e:
        raise core.Refused(f"{prefix}.bad-settings", f"fix {settings.PATH}, then {again}", error=str(e)) from None
    commands = [m.group(1) for r in saved.requirements if (m := render.COMMAND.match(r.proof))]
    for command in commands + ([stack["check_command"]] if stack["check_command"] else []):
        if not any(render.counted(r, command) and r["commit"] == head for r in records):
            raise core.Refused(f"{prefix}.no-pass", f"deliver.py check -- {shlex.quote(command)}", command=command,
                               commit=head[:7])
    return saved, stack


def _query_numbers(run: core.Run, folder: Path, records: list[dict], rid: str, command: str, head: str, base: str,
                   branch: str) -> None:
    """Refuse unless the query has saved numbers from before the change and on `HEAD`."""
    fork = _git(run, "merge-base", base, "HEAD").strip()
    numbers = [r for r in records if r["event"] == "check" and r.get("command") == command and r.get("exit") == 0
               and r.get("commit") and _number(folder, r)]
    before = any(subprocess.run(["git", "merge-base", "--is-ancestor", r["commit"], fork], cwd=run.checkout,
                                capture_output=True).returncode == 0 for r in numbers)
    after = any(render.counted(r, command) and r["commit"] == head for r in numbers)
    missing = [word for word, found in (("before", before), ("after", after)) if not found]
    if missing:
        check = f"deliver.py check -- {shlex.quote(command)}"
        fix = check if missing == ["after"] else f"git switch --detach {fork[:7]}, {check}, git switch {branch}"
        raise core.Refused("ready.no-query-numbers", fix, requirement=rid, command=command,
                           missing=" and ".join(missing))


def _number(folder: Path, record: dict) -> bool:
    """Whether the check's saved output ends in a number: its last non-blank line is one and nothing else."""
    try:
        text = (folder / record.get("output", "")).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and bool(NUMBER.fullmatch(lines[-1]))


def _blast(result: dict, stack: dict) -> str:
    lines = result["small_test"]["lines"]
    dependents = result["small_test"]["dependents"]
    counted = f"{lines} line" + ("" if lines == 1 else "s")
    feeds = (f"the dependents command counts {dependents['count']}, within the limit of "
             f"{stack['small_edit']['dependents_limit']}") if dependents else "no dependents command is set"
    return f"{counted}, no critical path changed, and {feeds}"


def _measurement(run: core.Run, records: list[dict], preflight: dict, result: dict) -> dict[str, str]:
    """The measurement block's keys and values in the spec's order (#407). No value holds a session id."""
    started = run.mark.get("started", "")
    wait = sum(r.get("slot_wait_s") or 0 for r in records if r["event"] == "check" and r.get("at", "") >= started)
    hashes = deps.review_skill_hashes(run.checkout)
    dependents = result["small_test"]["dependents"]
    lines = result["small_test"]["lines"]
    return {
        "version": VERSION,
        "path": "small edit",
        "harness": preflight.get("harness") or "unknown",
        "small test": f"pass, {lines} line{'' if lines == 1 else 's'}, no critical path, "
                      + (f"{dependents['count']} dependents" if dependents else "no dependents command"),
        "door": result["door"],
        "roles": "author",  # the session is the author on the small edit; the scan reads each agent's model
        "findings": "0",
        # A hand-over to the owner, written by later stages as "<n>, handed to the owner", is what the
        # scan's miss test reads here (scan.py); the small edit has no review, so no fix round and no hand-over.
        "fix rounds": "0",
        "follow-ups": "0",
        "slot wait": f"{wait:.1f}s",
        "review skills": ", ".join(f"{name} {digest or 'not installed'}" for name, digest in hashes.items()),
        "preflight warnings": "; ".join(preflight.get("warnings") or []) or "none",
        "waiver": "none",
        "merge": "pending",
    }


def _record(run: core.Run, head: str, outcome: str, result: dict) -> None:
    run.record("ready", commit=head, result=outcome, small_test=result["small_test"], door=result["door"],
               door_paths=result["door_paths"])


def _git(run: core.Run, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=run.checkout, capture_output=True, text=True, check=True).stdout


def _gh(run: core.Run, *args: str) -> str:
    proc = subprocess.run(["gh", *args], cwd=run.checkout, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout
