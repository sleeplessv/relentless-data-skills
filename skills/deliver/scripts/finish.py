"""deliver.py finish: the last command of every run (#256 rules 9, 43 to 47; #231 rule 37).

`finish` works on the run mark's branch, or, with no mark, on the checked-out branch's records,
so a run whose mark is already gone can still be finished: run again after the owner merges the
PR, it cleans up that PR. With neither a mark nor records it refuses `finish.no-mark`. In order,
it:

1. prints the state line, from the saved records and the PR's state on GitHub;
2. calls cleanup, which removes the branches and the records only after a merge, under its
   guards, switches the checkout to the default branch after a merge, and names what it kept;
3. removes the run mark, always.

The state line names the ticket as `#<N>` when `request.md` holds a ticket source, and the
branch otherwise. Its forms are in `STATE`; a ready PR that waits says why in the words of the
merge line `merge` recorded for its head commit.
"""
from __future__ import annotations

import core
import cleanup
import render

STATE = {
    "merged": "{who} merged: PR #{number}",
    "closed": "{who} closed unmerged: PR #{number}",
    "ready": "{who} ready, waits for you ({why}): PR #{number}",
    "draft": "{who} draft: PR #{number}",
    "review": "{who} draft, needs a review: PR #{number}",
    "none": "{who} not started: no PR was opened",
}
NOT_RUN = "merge not run"


def main(args: list[str], run: core.Run | None) -> None:
    if args:
        raise core.UsageError(f"finish takes no arguments, got: {' '.join(args)}")
    if run is None:
        raise core.Refused("finish.no-mark", "deliver.py start")
    if run.mark:
        branch = run.mark["branch"]
    else:
        branch = cleanup.git(run, "branch", "--show-current").stdout.strip()
    recs = cleanup.records(run, branch)
    if run.mark is None and not recs:
        raise core.Refused("finish.no-mark", "deliver.py start")
    pr_record = cleanup.latest(recs, "pr")
    pr = cleanup.view(run, pr_record["number"]) if pr_record else None
    print(state_line(run, branch, recs, pr))
    for line in cleanup.clean(run, branch, cleanup.default_branch(run), pr, recs, remove_records=True):
        print(line)
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
    if ready and ready.get("result") == "small edit":
        merge = cleanup.latest(recs, "merge", commit=pr.head)
        why = merge["merge_line"].removeprefix("merge: ") if merge else NOT_RUN
        return STATE["ready"].format(who=who, why=why, number=pr.number)
    form = "review" if ready and ready.get("result") == "needs review" else "draft"
    return STATE[form].format(who=who, number=pr.number)
