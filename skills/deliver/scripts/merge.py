"""deliver.py merge: merge the run's PR, or say why it waits (#176 rules 15 to 19; #256 merge row).

`merge` reads only the records of the marked run (`cleanup.run_records`), and reads them again
after the CI wait. In order, it:

1. refuses `merge.no-pr` when the run's records hold no `pr` record, and `merge.not-open` unless
   GitHub shows that PR open;
2. refuses `merge.bad-body` when the PR description's measurement block has no closing fence
   before its `</details>`, so the merge line could not be written;
3. refuses `merge.not-ready` unless a `ready` record is tied to the PR's head commit. When that
   record's door is not `two-way` it refuses `merge.one-way`, whatever the small test found;
   otherwise it refuses `merge.not-ready` unless the record's result is `small edit`;
4. refuses `merge.withheld` when the stack setting `stop_at_ready` is set, when the run's `start`
   record carries `"stop_at_ready": true` (`--stop-at-ready` or the setting when `start` ran), or when
   GitHub's review decision needs an approval or shows changes requested (no admin bypass is
   ever tried). `merge.one-way` and `merge.withheld` first write the merge line and the `merge`
   record;
5. refuses `merge.behind` or `merge.conflicting` as GitHub reports them, which sends the PR back
   to its author;
6. reads CI with `gh pr checks`: a failed or cancelled check refuses `merge.ci-red`, and pending
   checks wait through `gh pr checks --watch`, then CI is read again. "No checks reported" is
   trusted only after a second look: a workflow run listed for the head commit, or a workflow in
   the head commit's tree whose triggers would run on this branch's push or on a PR into its
   base, refuses `merge.ci-unknown`, since CI may not have started. A workflow whose triggers or
   branch filters this script cannot fully read counts as one that would run. With neither, the
   merge line records `checks: none reported`;
7. reads the PR and the run's records again and runs steps 1 to 5 again on what they show now,
   the head commit included, and refuses `merge.mergeable-unknown` while GitHub has not worked out
   whether the PR can merge. A `BLOCKED` merge state here, with CI done, is withheld by the
   branch rules;
8. reads the method from the base branch's history (`merge.no-history` when it cannot be read)
   and refuses `merge.behind` unless the base branch's tip on `origin` is in the head commit's
   history;
9. merges with `gh pr merge <PR> --<method> --match-head-commit <head>`, then confirms with `gh pr
   view`, routing by the state it shows and not by the exit code: a PR that is not merged
   refuses `merge.not-merged`;
10. writes the merge line into the description as GitHub holds it then, appends the `merge`
   record and calls cleanup.

The merge line is `merge: <value>` in the PR description's measurement block. It replaces a
`merge:` line there or is added at the end of the block, and a block holding only the line is
added when the description has none. Every value it can take is in `LINE` below. The line never
claims a merge that did not happen.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

import cleanup
import core
import render
import settings

KEY = "merge"
# Every value of the merge line.
LINE = {
    "merged": "by the session, {method}",
    "no-checks": ", checks: none reported",
    "one-way": "left to the owner, one-way door",
    "setting": f"withheld, stop_at_ready is set in {settings.PATH}",
    "start": "withheld, stop at ready was given at start",
    "approval": "withheld, the branch rules need an approval the agent cannot give",
    "changes": "withheld, a reviewer requested changes",
    "blocked": "withheld, the branch rules block the merge and the agent does not bypass them",
}
VIEW = "state,headRefOid,baseRefName,mergeStateStatus,mergeable,reviewDecision,body"
RED = ("fail", "cancel")
PR_NUMBER = re.compile(r"\(#\d+\)$")
FINISH = "deliver.py finish"
AGAIN = "deliver.py merge"
BACK = "git pull --no-rebase origin {base}, then deliver.py check, deliver.py pr and deliver.py ready again"
# Workflow events whose runs report checks on a PR's head commit.
CI_EVENTS = ("push", "pull_request", "pull_request_target")
EVENT = re.compile(r"[a-z_]+")
# A branch filter this script reads: plain characters and single `*`. Anything else counts as CI.
PLAIN = re.compile(r"(?:[A-Za-z0-9._/-]|\*(?!\*))+")


def main(args: list[str], run: core.Run) -> None:
    if args:
        raise core.UsageError(f"merge takes no arguments, got: {' '.join(args)}")
    branch = run.mark["branch"]
    run_id, started = run.mark["run"], run.mark.get("started")
    recs = cleanup.run_records(cleanup.records(run, branch), run_id, started)
    pr_record = cleanup.latest(recs, "pr")
    if pr_record is None:
        raise core.Refused("merge.no-pr", "deliver.py pr", branch=branch)
    number = pr_record["number"]
    pr = _view(run, number)
    head = pr["headRefOid"]
    _eligible(run, branch, recs, number, pr, head, ci_done=False)
    no_checks = _ci(run, number, head, branch, pr["baseRefName"])
    pr = _view(run, number)
    log = cleanup.records(run, branch)
    recs = cleanup.run_records(log, run_id, started)
    _eligible(run, branch, recs, number, pr, head, ci_done=True)
    method = _method(run, pr["baseRefName"])
    _base_in(run, pr["baseRefName"], head, branch, number)
    merged = subprocess.run(
        ["gh", "pr", "merge", str(number), f"--{method}", "--match-head-commit", head],
        cwd=run.checkout, capture_output=True, text=True)
    after = cleanup.view(run, number)
    if after.state != "MERGED":
        sys.stderr.write(merged.stderr)
        raise core.Refused("merge.not-merged", f"gh pr view {number}", number=number, state=after.state.lower())
    print(f"Merged PR #{number} with {method} at {head[:7]}.")
    line = LINE["merged"].format(method=method) + (LINE["no-checks"] if no_checks else "")
    _write(run, branch, number, head, method, line)
    default = cleanup.default_branch(run)
    for out in cleanup.clean(run, branch, default, after, remove_records=False, created=cleanup.created(recs, branch, run_id),
                             later=cleanup.later_run(log, run_id, started)).lines:
        print(out)


def _view(run: core.Run, number: int) -> dict:
    """The PR as GitHub shows it, read a second time when its mergeability is not worked out yet."""
    pr = json.loads(cleanup.gh(run, "pr", "view", str(number), "--json", VIEW))
    if "UNKNOWN" in (pr["mergeable"], pr["mergeStateStatus"]):
        pr = json.loads(cleanup.gh(run, "pr", "view", str(number), "--json", VIEW))
    return pr


def _eligible(run: core.Run, branch: str, recs: list[dict], number: int, pr: dict, head: str, *,
              ci_done: bool) -> None:
    """Refuse unless the PR, as GitHub shows it now, may be merged at `head`."""
    base = pr["baseRefName"]
    if pr["state"] != "OPEN":
        raise core.Refused("merge.not-open", FINISH, number=number, state=pr["state"].lower())
    if with_line(pr["body"], f"{KEY}: ") is None:
        raise core.Refused("merge.bad-body", f"close the measurement block in PR #{number}'s description, then {AGAIN}",
                           number=number)
    ready = cleanup.latest(recs, "ready", commit=pr["headRefOid"])
    if ready is None or pr["headRefOid"] != head:
        raise core.Refused("merge.not-ready", "deliver.py ready", commit=pr["headRefOid"][:7])
    if ready.get("door") != "two-way":
        _write(run, branch, number, head, None, LINE["one-way"])
        raise core.Refused("merge.one-way", FINISH, number=number)
    if ready.get("result") != "small edit":
        raise core.Refused("merge.not-ready", "deliver.py ready", commit=head[:7])
    if why := _withheld(run, recs, pr, ci_done):
        _write(run, branch, number, head, None, LINE[why])
        raise core.Refused("merge.withheld", FINISH, why=LINE[why].removeprefix("withheld, "))
    if pr["mergeable"] == "CONFLICTING" or pr["mergeStateStatus"] == "DIRTY":
        raise core.Refused("merge.conflicting", BACK.format(base=base), number=number, base=base)
    if pr["mergeStateStatus"] == "BEHIND":
        raise core.Refused("merge.behind", BACK.format(base=base), number=number, base=base)
    if ci_done and "UNKNOWN" in (pr["mergeable"], pr["mergeStateStatus"]):
        raise core.Refused("merge.mergeable-unknown", AGAIN, number=number)


def _withheld(run: core.Run, recs: list[dict], pr: dict, ci_done: bool) -> str | None:
    """The key in `LINE` of the first reason the merge is withheld, or None."""
    try:
        stack, _ = settings.load(run.checkout)
    except settings.SettingsError as e:
        raise core.Refused("merge.bad-settings", f"fix {settings.PATH}, then {AGAIN}", error=str(e)) from None
    if stack["stop_at_ready"]:
        return "setting"
    if (cleanup.latest(recs, "start") or {}).get("stop_at_ready") is True:
        return "start"
    if pr["reviewDecision"] == "REVIEW_REQUIRED":
        return "approval"
    if pr["reviewDecision"] == "CHANGES_REQUESTED":
        return "changes"
    if ci_done and pr["mergeStateStatus"] == "BLOCKED":
        return "blocked"
    return None


def _ci(run: core.Run, number: int, head: str, branch: str, base: str) -> bool:
    """Wait out pending checks; return True when there is no CI at all. Refuse on red or unknown CI."""
    while True:
        look = subprocess.run(["gh", "pr", "checks", str(number), "--json", "name,bucket"],
                              cwd=run.checkout, capture_output=True, text=True)
        if look.stdout.strip():
            checks = json.loads(look.stdout)
        elif "no checks reported" in look.stderr:
            checks = []
        else:
            raise RuntimeError(f"gh pr checks {number} failed ({look.returncode}): {look.stderr.strip()}")
        red = [c["name"] for c in checks if c["bucket"] in RED]
        if red:
            raise core.Refused("merge.ci-red", BACK.format(base=base), commit=head[:7], checks=", ".join(red))
        pending = [c["name"] for c in checks if c["bucket"] == "pending"]
        if not pending:
            break
        print(f"Waiting for pending checks on PR #{number}: {', '.join(pending)}.", flush=True)
        subprocess.run(["gh", "pr", "checks", str(number), "--watch"], cwd=run.checkout,
                       capture_output=True, text=True)
    if checks:
        return False
    runs = json.loads(cleanup.gh(run, "run", "list", "--commit", head, "--json", "databaseId"))
    if runs:
        raise core.Refused("merge.ci-unknown", AGAIN, commit=head[:7], why="a workflow run is listed for it")
    if why := _workflow_ci(run, head, branch, base):
        raise core.Refused("merge.ci-unknown", AGAIN, commit=head[:7], why=why)
    return True


def _workflow_ci(run: core.Run, head: str, branch: str, base: str) -> str | None:
    """Why CI may still report on `head`, read from the workflows in its tree, or None."""
    if not _have(run, head, branch):
        return f"the workflows of {head[:7]} cannot be read"
    tree = cleanup.git(run, "ls-tree", f"{head}", ".github/", check=False)
    if tree.returncode != 0:
        return f"the workflows of {head[:7]} cannot be read"
    if not tree.stdout.strip():
        return None
    listed = cleanup.git(run, "ls-tree", "-z", "--name-only", f"{head}:.github/workflows", check=False)
    if listed.returncode != 0:
        has = cleanup.git(run, "ls-tree", f"{head}:.github", "workflows", check=False)
        return None if has.returncode == 0 and not has.stdout.strip() else f"the workflows of {head[:7]} cannot be read"
    for name in sorted(n for n in listed.stdout.split("\0") if n):
        if not name.endswith((".yml", ".yaml")):
            continue
        shown = cleanup.git(run, "cat-file", "blob", f"{head}:.github/workflows/{name}", check=False)
        triggers = triggers_of(shown.stdout) if shown.returncode == 0 else None
        if triggers is None:
            return f".github/workflows/{name} has triggers this script cannot read"
        for event in CI_EVENTS:
            if event in triggers and _runs(triggers[event], branch if event == "push" else base, event):
                return f".github/workflows/{name} runs on {event}"
    return None


def _have(run: core.Run, head: str, branch: str) -> bool:
    """Whether the head commit is in this clone, fetched from the PR's branch when it is not."""
    if cleanup.git(run, "cat-file", "-e", f"{head}^{{commit}}", check=False).returncode == 0:
        return True
    cleanup.git(run, "fetch", "--quiet", "origin", branch, check=False)
    return cleanup.git(run, "cat-file", "-e", f"{head}^{{commit}}", check=False).returncode == 0


def triggers_of(text: str) -> dict[str, dict | None] | None:
    """A workflow's `on:` events, each with its branch and tag filters, or None when it cannot be read.

    Reads the forms `on: push`, `on: [push, pull_request]` and a block of events, each with no
    value or with `branches`, `branches-ignore`, `tags` and `tags-ignore` lists, inline or as a
    block, at whatever indentation the file's top level has. Other filters (paths, types) are
    ignored, which can only count more runs. A file with no top-level `on:`, or with a form not
    listed here, cannot be read.
    """
    lines = [re.sub(r"(^|\s)#.*$", "", raw).rstrip() for raw in text.splitlines()]
    lines = [line for line in lines if line.strip() and line.strip() != "---"]
    if not lines:
        return None
    top = min(len(line) - len(line.lstrip()) for line in lines)
    if "\t" in "".join(line[:len(line) - len(line.lstrip())] for line in lines):
        return None
    lines = [line[top:] for line in lines]
    at = next((i for i, line in enumerate(lines) if re.match(r"""^(on|"on"|'on'|true)\s*:""", line)), None)
    if at is None:
        return None
    rest = lines[at].split(":", 1)[1].strip()
    if rest.startswith("{"):
        return None
    if rest:
        names = _flow_list(rest) if rest.startswith("[") else [_unquote(rest)]
        if names is None or not all(EVENT.fullmatch(n) for n in names):
            return None
        return dict.fromkeys(names)
    block = []
    for line in lines[at + 1:]:
        if line and not line[0].isspace():
            break
        if line.strip():
            block.append(line)
    if not block:
        return None
    indent = len(block[0]) - len(block[0].lstrip())
    events: dict[str, dict | None] = {}
    event = key = None
    for line in block:
        depth, item = len(line) - len(line.lstrip()), line.strip()
        if depth == indent:
            key = None
            if item.startswith("- "):
                if not EVENT.fullmatch(_unquote(item[2:])):
                    return None
                event, events[_unquote(item[2:])] = None, None
                continue
            name, _, value = item.partition(":")
            if value.strip() not in ("", "null", "~", "{}"):
                return None
            event = _unquote(name)
            if not EVENT.fullmatch(event):
                return None
            events[event] = None
        elif depth < indent or event is None:
            return None
        elif item.startswith("- "):
            if key is not None:  # a list right under an event, as `schedule` has, holds no filter
                events[event][key].append(_unquote(item[2:]))
        else:
            filters = events[event] = events[event] or {}
            name, _, value = item.partition(":")
            name, value = _unquote(name), value.strip()
            key = None if value else name
            values = (_flow_list(value) if value.startswith("[") else [_unquote(value)]) if value else []
            if values is None:
                return None
            filters[name] = values
    return events


def _runs(filters: dict | None, name: str, event: str) -> bool:
    """Whether an event with these filters runs for the branch `name` (the head for push, the base for PRs)."""
    if not filters:
        return True
    include, exclude = filters.get("branches"), filters.get("branches-ignore")
    if include is None and exclude is None:
        return not (event == "push" and ("tags" in filters or "tags-ignore" in filters))
    patterns = (include or []) + (exclude or [])
    if any(not PLAIN.fullmatch(p) for p in patterns):
        return True  # a pattern this script does not fully read (`!`, `**`, `?`, `+`, `[...]`): count the run
    if include is not None:
        return any(_glob(p, name) for p in include)
    return not any(_glob(p, name) for p in exclude)


def _glob(pattern: str, name: str) -> bool:
    """A filter pattern of `PLAIN` characters, where `*` matches any run of characters but `/`."""
    return re.fullmatch(re.escape(pattern).replace(r"\*", "[^/]*"), name) is not None


def _flow_list(text: str) -> list[str] | None:
    if not (text.startswith("[") and text.endswith("]")):
        return None
    return [_unquote(item) for item in text[1:-1].split(",") if item.strip()]


def _unquote(text: str) -> str:
    text = text.strip()
    return text[1:-1] if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"" else text


def _method(run: core.Run, base: str) -> str:
    """The method the newest PR landed on the base branch shows; squash when no PR has landed.

    A commit on the base branch's first-parent line is a PR landing when it has two parents, its
    subject names a PR (`(#N)` or "Merge pull request #"), or GitHub committed it later than it was
    authored, as a rebase merge does. Other commits, such as a direct push or an edit made on
    GitHub, are skipped.
    """
    fetch = cleanup.git(run, "fetch", "--quiet", "origin", base, check=False)
    if fetch.returncode != 0:
        raise core.Refused("merge.no-history", f"git fetch origin {base}, then {AGAIN}", base=base,
                           error=fetch.stderr.strip())
    log = cleanup.git(run, "log", "--first-parent", "--format=%P%x1f%cn%x1f%at%x1f%ct%x1f%s",
                      f"refs/remotes/origin/{base}", "--", check=False)
    if log.returncode != 0:
        raise core.Refused("merge.no-history", f"git fetch origin {base}, then {AGAIN}", base=base,
                           error=log.stderr.strip())
    for line in log.stdout.splitlines():
        parents, committer, authored, committed, subject = line.split("\x1f", 4)
        if len(parents.split()) > 1:
            return "merge"
        if PR_NUMBER.search(subject) or subject.startswith("Merge pull request #"):
            return "squash"
        if committer == "GitHub" and authored != committed:
            return "rebase"
    return "squash"


def _base_in(run: core.Run, base: str, head: str, branch: str, number: int) -> None:
    """Refuse `merge.behind` unless the tip of `origin/<base>`, fetched by `_method`, is in the head's history."""
    if not _have(run, head, branch):
        raise core.Refused("merge.no-history", f"git fetch origin {branch}, then {AGAIN}", base=branch,
                           error=f"the head commit {head[:7]} is not in this clone")
    within = cleanup.git(run, "merge-base", "--is-ancestor", f"refs/remotes/origin/{base}", head, check=False)
    if within.returncode == 1:
        raise core.Refused("merge.behind", BACK.format(base=base), number=number, base=base)
    if within.returncode != 0:
        raise core.Refused("merge.no-history", f"git fetch origin {base}, then {AGAIN}", base=base,
                           error=cleanup._said(within))


def _write(run: core.Run, branch: str, number: int, head: str, method: str | None, value: str) -> None:
    """Put the merge line into the PR description as GitHub holds it now, and append the `merge` record."""
    line = f"{KEY}: {value}"
    body = json.loads(cleanup.gh(run, "pr", "view", str(number), "--json", "body"))["body"]
    new = with_line(body, line)
    if new is None:
        print(f"Kept PR #{number}'s description: its measurement block has no closing line, "
              f"so it does not say {line}")
    else:
        fd, body_file = tempfile.mkstemp(prefix="deliver-merge-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new)
            cleanup.gh(run, "pr", "edit", str(number), "--body-file", body_file)
        finally:
            os.unlink(body_file)
    core.append_record(run.common_dir, branch, "merge", commit=head, method=method, merge_line=line)


def with_line(body: str, line: str) -> str | None:
    """The description with the merge line in its measurement block, which is added if missing.

    None when the last block opens but its closing fence does not come before its `</details>`.
    """
    lines = body.replace("\r\n", "\n").rstrip("\n").split("\n")
    opening, closing = list(render.MEASUREMENT_OPEN), render.MEASUREMENT_CLOSE[0]
    starts = [i for i in range(len(lines)) if lines[i:i + len(opening)] == opening]
    if not starts:
        return "\n".join([*lines, "", *opening, line, *render.MEASUREMENT_CLOSE]) + "\n"
    first = starts[-1] + len(opening)
    if closing not in lines[first:]:
        return None
    end = lines.index(closing, first)
    if "</details>" in lines[first:end] or "</details>" not in lines[end:]:
        return None
    old = [i for i in range(first, end) if lines[i].startswith(f"{KEY}:")]
    if old:
        lines[old[0]] = line
    else:
        lines.insert(end, line)
    return "\n".join(lines) + "\n"
