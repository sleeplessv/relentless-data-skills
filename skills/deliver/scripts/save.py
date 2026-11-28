"""`deliver.py save <kind>`: move an author's text from the drop folder into the records (#256 rule 24).

The kinds are request, requirements, plan and summary. `save <kind>` moves `.deliver/<kind>.md`
to `<kind>.md` in the branch's records, replacing an earlier one, and appends a `save` record:
`kind`, `file` and `commit`. `commit` is null when a tracked file is changed or `git status`
fails (#256 rule 28).
`save plan` first reads the plan with `plan.parse`: it refuses a requirement with no proof or a
plan it cannot read, and prints the door, which is one-way when the plan has no door line.

`save review <role>` saves a reviewer's report, which the session wrote word for word into
`.deliver/review.md` (spec #479, The review steps, step 4). The role is `requirements` or
`defect`. It refuses `save.missing-file` with no report, `save.no-brief` when no brief of that role
is recorded, `save.tree-changed` when a tracked file is changed or `HEAD` is not the brief's
target commit, and `save.bad-review` at the first line outside the report form of `findings.py`.
It then moves the report to `reviews/<role>-0.md` in the records and appends a `review` record:
`role`, `round` 0, `commit`, `file`, the requirement `answers`, and the `findings`, numbered,
scoped against the branch diff from the brief's fixed point and marked proven or not, by
`findings.py`. It prints each finding with what it needs next.
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
    if args[:1] == ["review"] and len(args) == 2 and args[1] in findings.REPORTERS:
        return review(args[1], run)
    if len(args) != 1 or args[0] not in KINDS:
        raise core.UsageError(f"save takes one kind, one of {', '.join(KINDS)}, or review and a role, "
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


def review(role: str, run: core.Run) -> None:
    source = run.checkout / DROP / "review.md"
    if not source.is_file():
        raise core.Refused("save.missing-file", f"write {DROP}/review.md, then run deliver.py save review {role}",
                           file=f"{DROP}/review.md")
    folder = core.records_dir(run.common_dir, run.mark["branch"])
    records = render._records(folder)
    briefs = [r for r in records if r["event"] == "brief" and r.get("role") == role and r.get("round") == 0]
    if not briefs:
        raise core.Refused("save.no-brief", f"deliver.py brief {role} --model <id>", role=role)
    brief = briefs[-1]
    commit = tied_commit(run)
    if commit is None:
        raise core.Refused("save.tree-changed", f"commit or restore the changed files, then deliver.py save review {role}",
                           why="a tracked file is changed")
    if commit != brief["commit"]:
        raise core.Refused("save.tree-changed", f"deliver.py brief {role} --model {brief['model']}, then start the "
                           "reviewer again with its line", why=f"HEAD is {commit[:7]}, not the reviewed commit "
                           f"{brief['commit'][:7]}")
    text = source.read_text(encoding="utf-8")
    try:
        answers, found = findings.parse(text, role)
    except findings.BadLine as e:
        raise core.Refused("save.bad-review", f"start the reviewer again with `Read {folder / brief['path']} and "
                           f"follow it.`, write its final message into {DROP}/review.md, then deliver.py save review "
                           f"{role}", number=e.number, line=e.line) from None
    diff = git(run, "diff", "--unified=0", "--no-color", "--no-ext-diff", brief["fixed_point"], commit)
    if diff.returncode != 0:
        raise RuntimeError(f"git diff failed ({diff.returncode}): {diff.stderr.strip()}")
    numbered = findings.number(found, records, role, findings.changed_lines(diff.stdout))
    name = f"reviews/{role}-0.md"
    (folder / "reviews").mkdir(parents=True, exist_ok=True)
    shutil.move(source, folder / name)
    run.record("review", role=role, round=0, commit=commit, file=name, answers=answers, findings=numbered)
    print(f"Saved the {findings.REPORTERS[role]} of {commit[:7]}.")
    for f in numbered:
        scope = "in scope" if f["scope"] == "in" else "out of scope"
        print(f"{f['number']} ({scope}, {'proven' if f['proven'] else 'not proven'}) {f['where']}: "
              f"{f['text'].rstrip('.')}. Next: {findings.next_step(f)}.")
    if not numbered:
        print("No findings.")
