"""`deliver.py save <kind>`: move an author's text from the drop folder into the records (#256 rule 24).

The kinds are request, requirements, plan and summary. `save <kind>` moves `.deliver/<kind>.md`
to `<kind>.md` in the branch's records, replacing an earlier one, and appends a `save` record:
`kind`, `file` and `commit`. `commit` is null when a tracked file is changed (#256 rule 28).
`save plan` first reads the plan with `plan.parse`: it refuses a requirement with no proof or a
plan it cannot read, and prints the door, which is one-way when the plan has no door line.
"""
from __future__ import annotations

import shutil
import subprocess

import core
import plan

KINDS = ("request", "requirements", "plan", "summary")
DROP = ".deliver"


def git(run: core.Run, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=run.checkout, capture_output=True, text=True)


def tied_commit(run: core.Run) -> str | None:
    """`HEAD`, or None when a tracked file is changed or there is no commit yet."""
    if git(run, "status", "--porcelain", "--untracked-files=no").stdout:
        return None
    head = git(run, "rev-parse", "--verify", "-q", "HEAD")
    return head.stdout.strip() if head.returncode == 0 else None


def main(args: list[str], run: core.Run) -> None:
    if len(args) != 1 or args[0] not in KINDS:
        raise core.UsageError(f"save takes one kind, one of {', '.join(KINDS)}")
    kind = args[0]
    name = f"{kind}.md"
    source = run.checkout / DROP / name
    if not source.is_file():
        raise core.Refused("save.missing-file", f"write {DROP}/{name}, then run deliver.py save {kind}",
                           file=f"{DROP}/{name}")
    door = None
    if kind == "plan":
        try:
            read = plan.parse(source.read_text(encoding="utf-8"))
        except plan.PlanError as e:
            raise core.Refused("save.bad-plan", f"fix {DROP}/{name}, then run deliver.py save plan",
                               error=str(e)) from None
        missing = [r.number for r in read.requirements if not r.proof]
        if missing:
            raise core.Refused("save.no-proof", f"name a proof for each in {DROP}/{name}, then run deliver.py save plan",
                               requirements=", ".join(missing))
        door = f"door: {read.door} ({read.door_reason})"
    commit = tied_commit(run)
    target = core.records_dir(run.common_dir, run.mark["branch"]) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source, target)
    run.record("save", kind=kind, file=name, commit=commit)
    print(f"Saved {name} {f'at {commit[:7]}' if commit else 'tied to no commit'}.")
    if door:
        print(door)
