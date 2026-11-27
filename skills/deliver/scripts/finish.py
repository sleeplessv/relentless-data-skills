"""deliver.py finish: the last command of every run (#256 rules 9, 43 to 47; #231 rule 37).

`finish` works on the run mark's run and its records (`cleanup.run_records`). With no mark it
only resumes a run whose earlier `finish` left its PR waiting: the checked-out branch's records
must end in a `finish` record with `"waiting": true`, and that record's run and PR are the ones
resumed. Run again after the owner merges that PR, it cleans up. Any other
call with no mark refuses `finish.no-mark`. In order, it:

1. prints the state line, from the run's records and the PR's state on GitHub;
2. calls cleanup, which removes the branches and the records only after a merge, under its
   guards, switches a clean checkout to the default branch after a merge, and names what it kept;
3. appends a `finish` record (`run`, `started`, `pr`, `waiting`) when the run's records are kept, `waiting`
   being true only when cleanup left something a later `finish` can still remove. A reason no
   later `finish` changes (a closed PR, a branch this run did not create) closes the run;
4. removes the run mark, unless cleanup stopped partway after leaving the branch: then a mark
   that exists stays exactly as it is, and a missing one is written, so the next `finish` finds
   the run.

The state line names the ticket as `#<N>` when `request.md` holds a ticket source, and the
branch otherwise. Its forms are in `STATE`. A ready PR that waits says why only when the newest
`ready` or `merge` record on its head commit is a `merge` record, in the words of its merge line.
"""
from __future__ import annotations

import json

import cleanup
import core
import render

STATE = {
    "merged": "{who} merged: PR #{number}",
    "closed": "{who} closed unmerged: PR #{number}",
    "ready": "{who} ready, waits for you{why}: PR #{number}",
    "draft": "{who} draft: PR #{number}",
    "review": "{who} draft, needs a review: PR #{number}",
    "none": "{who} not started: no PR was opened",
}
KEPT_MARK = "Kept the run mark, so deliver.py finish can finish the cleanup."


def main(args: list[str], run: core.Run | None) -> None:
    if args:
        raise core.UsageError(f"finish takes no arguments, got: {' '.join(args)}")
    if run is None:
        raise core.Refused("finish.no-mark", "deliver.py start")
    if run.mark:
        branch, run_id, started = run.mark["branch"], run.mark["run"], run.mark.get("started")
        log = cleanup.records(run, branch)
        recs = cleanup.run_records(log, run_id, started)
        pr_record = cleanup.latest(recs, "pr")
        number = pr_record["number"] if pr_record else None
    else:
        branch = cleanup.git(run, "branch", "--show-current").stdout.strip()
        log = cleanup.records(run, branch)
        last = log[-1] if log else {}
        if last.get("event") != "finish" or last.get("waiting") is not True or last.get("pr") is None:
            raise core.Refused("finish.no-mark", "deliver.py start")
        run_id, started, number = last.get("run"), last.get("started"), last["pr"]
        recs = cleanup.run_records(log, run_id, started)
    pr = cleanup.view(run, number) if number is not None else None
    print(state_line(run, branch, recs, pr))
    done = cleanup.clean(run, branch, cleanup.default_branch(run), pr, remove_records=True,
                         created=cleanup.created(recs, branch, run_id), later=cleanup.later_run(log, run_id, started))
    for line in done.lines:
        print(line)
    if recs and (core.records_dir(run.common_dir, branch) / core.RECORDS).is_file():
        core.append_record(run.common_dir, branch, "finish", run=run_id, started=started, pr=number,
                           waiting=done.unfinished)
    left = cleanup.git(run, "branch", "--show-current").stdout.strip() != branch
    if done.unfinished and left:
        if not run.mark:
            mark = core.write_mark(run.git_dir, run_id, branch)
            if started:  # the run's records keep their bound
                (run.git_dir / core.MARK).write_text(json.dumps({**mark, "started": started}) + "\n", encoding="utf-8")
        print(KEPT_MARK)
    else:
        (run.git_dir / core.MARK).unlink(missing_ok=True)


def state_line(run: core.Run, branch: str, recs: list[dict], pr: cleanup.Pr | None) -> str:
    who = branch
    request = core.records_dir(run.common_dir, branch) / "request.md"
    if request.is_file():
        try:
            ticket = render.read_source(request.read_text(encoding="utf-8"))[1]
        except render.Unreadable:
            ticket = None
        who = f"#{ticket}" if ticket else branch
    if pr is None:
        return STATE["none"].format(who=who)
    if pr.state in ("MERGED", "CLOSED"):
        return STATE[pr.state.lower()].format(who=who, number=pr.number)
    decision = [r for r in recs if r["event"] in ("ready", "merge") and r.get("commit") == pr.head]
    newest = decision[-1] if decision else None
    if newest and newest["event"] == "merge":
        why = f" ({newest['merge_line'].removeprefix('merge: ')})"
        return STATE["ready"].format(who=who, why=why, number=pr.number)
    result = newest.get("result") if newest else None
    if result == "small edit":
        return STATE["ready"].format(who=who, why="", number=pr.number)
    return STATE["review" if result == "needs review" else "draft"].format(who=who, number=pr.number)
