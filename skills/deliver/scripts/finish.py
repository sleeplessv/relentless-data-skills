"""deliver.py finish: the last command of every run (#256 rules 9, 43 to 47; #231 rule 37).

`finish` works on the run mark's run. With no mark it works only on a run whose earlier `finish`
left something to clean, such as a PR waiting for its owner: the newest run in the checked-out
branch's records must end in a `finish` record with `"waiting": true`. Run again after the
owner merges that PR, it cleans up. Any other call with no mark refuses `finish.no-mark`.
In order, it:

1. prints the state line, from the run's records and the PR's state on GitHub;
2. calls cleanup, which removes the branches and the records only after a merge, under its
   guards, switches the checkout to the default branch after a merge, and names what it kept;
3. appends a `finish` record (`run`, `waiting`) when the records are kept, `waiting` being true
   when cleanup left something a later `finish` should remove;
4. removes the run mark, unless cleanup stopped partway after leaving the branch: then the mark
   stays, or is written again, so the next `finish` finds the run.

The state line names the ticket as `#<N>` when `request.md` holds a ticket source, and the
branch otherwise. Its forms are in `STATE`. A ready PR that waits says why in the words of the
merge line `merge` recorded for its head commit, and gives no reason when there is none.
"""
from __future__ import annotations

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
        branch, run_id = run.mark["branch"], run.mark["run"]
        recs = cleanup.run_records(cleanup.records(run, branch), run_id)
    else:
        branch = cleanup.git(run, "branch", "--show-current").stdout.strip()
        recs = cleanup.run_records(cleanup.records(run, branch))
        last = cleanup.latest(recs, "finish")
        if last is None or last.get("waiting") is not True:
            raise core.Refused("finish.no-mark", "deliver.py start")
        run_id = last.get("run")
    pr_record = cleanup.latest(recs, "pr")
    pr = cleanup.view(run, pr_record["number"]) if pr_record else None
    print(state_line(run, branch, recs, pr))
    done = cleanup.clean(run, branch, cleanup.default_branch(run), pr, recs, remove_records=True)
    for line in done.lines:
        print(line)
    if (core.records_dir(run.common_dir, branch) / core.RECORDS).is_file():
        core.append_record(run.common_dir, branch, "finish", run=run_id, waiting=done.unfinished)
    left = cleanup.git(run, "branch", "--show-current").stdout.strip() != branch
    if done.unfinished and left:
        core.write_mark(run.git_dir, run_id, branch)
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
    ready = cleanup.latest(recs, "ready", commit=pr.head)
    merge = cleanup.latest(recs, "merge", commit=pr.head)
    if merge or ready and ready.get("result") == "small edit":
        why = f" ({merge['merge_line'].removeprefix('merge: ')})" if merge else ""
        return STATE["ready"].format(who=who, why=why, number=pr.number)
    form = "review" if ready and ready.get("result") == "needs review" else "draft"
    return STATE[form].format(who=who, number=pr.number)
