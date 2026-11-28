"""`deliver.py save <kind>`: move an author's text from the drop folder into the records (#256 rule 24).

The kinds are request, requirements, plan and summary. `save <kind>` moves `.deliver/<kind>.md`
to `<kind>.md` in the branch's records, replacing an earlier one, and appends a `save` record:
`kind`, `file` and `commit`. `commit` is null when a tracked file is changed or `git status`
fails (#256 rule 28).
`save plan` first reads the plan with `plan.parse`: it refuses a requirement with no proof or a
plan it cannot read, and prints the door, which is one-way when the plan has no door line.

`save review <role>` saves a reviewer's report, which the session wrote word for word into
`.deliver/review.md` (spec #479, The review steps, step 4). The role is `requirements` or
`defect`. It refuses `save.missing-file` with no report, and `save.no-brief` unless the role's
newest brief is a review's (round 0) with no saved report yet: a save consumes its brief, so a
second save of one brief cannot add its findings twice. It refuses `save.tree-changed` when a
tracked file is changed or `HEAD` is not the brief's target commit, and `save.bad-review` at the
first line outside the report form of `findings.py`. It then moves the report to
`reviews/<role>-<round>.md` in the records and appends a `review` record: `role`, `round`,
`commit`, `file`, the requirement `answers`, and the `findings`, numbered, scoped against the
branch diff from the brief's fixed point and marked proven or not, by `findings.py`. It prints
each finding with what it needs next.

`save callback <role>` saves a call-back report from `.deliver/callback.md` the same way, against
the role's newest brief, which must be a call-back's (round 1 or 2). It also refuses
`save.unknown-finding` when a resolution line names a number that is not one of that role's
earlier findings. Its record holds `resolutions` in place of `answers`, and it prints each named
finding with its new state, then the new findings.
"""
from __future__ import annotations

import shutil
import subprocess

import core
import findings
import plan
import render

KINDS = ("request", "requirements", "plan", "summary")
DROP = ".deliver"


def git(run: core.Run, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=run.checkout, capture_output=True, text=True)


def tied_commit(run: core.Run) -> str | None:
    """`HEAD`, or None when a tracked file is changed, `git status` fails or there is no commit yet."""
    status = git(run, "status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0 or status.stdout:
        return None
    head = git(run, "rev-parse", "--verify", "-q", "HEAD")
    return head.stdout.strip() if head.returncode == 0 else None


def main(args: list[str], run: core.Run) -> None:
    if args[:1] in (["review"], ["callback"]) and len(args) == 2 and args[1] in findings.REPORTERS:
        return review(args[1], run, args[0] == "callback")
    if len(args) != 1 or args[0] not in KINDS:
        raise core.UsageError(f"save takes one kind, one of {', '.join(KINDS)}, or review or callback and a role, "
                              f"one of {', '.join(findings.REPORTERS)}")
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


def review(role: str, run: core.Run, callback: bool = False) -> None:
    kind = "callback" if callback else "review"
    command = f"deliver.py save {kind} {role}"
    source = run.checkout / DROP / f"{kind}.md"
    if not source.is_file():
        raise core.Refused("save.missing-file", f"write {DROP}/{kind}.md, then run {command}", file=f"{DROP}/{kind}.md")
    folder = core.records_dir(run.common_dir, run.mark["branch"])
    records = render._records(folder)
    briefed = [(i, r) for i, r in enumerate(records) if r["event"] == "brief" and r.get("role") == role]
    again = f"deliver.py brief callback {role}" if callback else f"deliver.py brief {role} --model <id>"
    if not briefed:
        raise core.Refused("save.no-brief", again, why=f"no {role} brief is saved")
    at, brief = briefed[-1]
    if (brief["round"] > 0) != callback:
        raise core.Refused("save.no-brief", again, why=f"the newest {role} brief, {brief['path']}, is for a "
                           f"{'review' if brief['round'] == 0 else 'call-back'}")
    if any(r["event"] == "review" and r.get("role") == role and r.get("round") == brief["round"] for r in records[at:]):
        raise core.Refused("save.no-brief", again, why=f"the newest {role} brief, {brief['path']}, already has its "
                           "saved report")
    commit = tied_commit(run)
    if commit is None:
        raise core.Refused("save.tree-changed", f"commit or restore the changed files, then {command}",
                           why="a tracked file is changed")
    rebrief = again if callback else f"deliver.py brief {role} --model {brief['model']}"
    if commit != brief["commit"]:
        raise core.Refused("save.tree-changed", f"{rebrief}, then start the reviewer again with its line",
                           why=f"HEAD is {commit[:7]}, not the reviewed commit {brief['commit'][:7]}")
    restart = (f"start the reviewer again with `Read {folder / brief['path']} and follow it.`, write its final "
               f"message into {DROP}/{kind}.md, then {command}")
    try:
        answers, found = findings.parse(source.read_text(encoding="utf-8"), role, callback)
    except findings.BadLine as e:
        raise core.Refused("save.bad-review", restart, file=f"{DROP}/{kind}.md", number=e.number, line=e.line) from None
    earlier = [f["number"] for f in findings.all_findings(records) if f["reviewer"] == role]
    if unknown := [n for n in answers if callback and n not in earlier]:
        raise core.Refused("save.unknown-finding", restart, finding=unknown[0], role=role)
    diff = git(run, "-c", "core.quotePath=false", "diff", "--src-prefix=a/", "--dst-prefix=b/", "--unified=0", "--no-color", "--no-ext-diff", brief["fixed_point"], commit)
    if diff.returncode != 0:
        raise RuntimeError(f"git diff failed ({diff.returncode}): {diff.stderr.strip()}")
    numbered = findings.number(found, records, role, findings.changed_lines(diff.stdout))
    name = f"reviews/{role}-{brief['round']}.md"
    (folder / "reviews").mkdir(parents=True, exist_ok=True)
    shutil.move(source, folder / name)
    named = {"resolutions": answers} if callback else {"answers": answers}
    run.record("review", role=role, round=brief["round"], commit=commit, file=name, **named, findings=numbered)
    records = render._records(folder)
    every = {f["number"]: f for f in findings.all_findings(records)}
    print(f"Saved the {findings.REPORTERS[role]}{' call-back' if callback else ''} of {commit[:7]}.")
    for f in [every[n] for n in answers if callback] + numbered:
        scope = "in scope" if f["scope"] == "in" else "out of scope"
        print(f"{f['number']} ({scope}, {'proven' if f['proven'] else 'not proven'}) {f['where']}: "
              f"{f['text'].rstrip('.')}. Next: {findings.next_step(f, records)}.")
    if not numbered and not callback:
        print("No findings.")
