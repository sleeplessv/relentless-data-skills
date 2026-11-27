"""deliver.py pr: push the branch and open its draft PR, or re-render the open PR's description (#256 rule 33).

The description comes from the branch's saved records alone, through `render.description`, with
the blast radius pending until `ready` runs the small test. In order, `pr`:

1. refuses `pr.wrong-branch` when the checked-out branch is not the run mark's branch, before it
   reads a record or makes any outward call;
2. refuses `pr.not-saved` unless the records hold `request.md`, `summary.md` and `plan.md`, and
   `requirements.md` when the source is not a ticket, and the drop folder `.deliver/` holds no
   `<kind>.md` still to save;
3. renders the description, which ends in exit 20 with a question when a saved text looks like it
   holds a secret, before anything is pushed or sent to `gh`, and refuses `pr.unreadable` when a
   saved text cannot be read with certainty;
4. refuses `pr.default-branch` on the repo's default branch (`gh repo view`);
5. takes the title, the branch's first commit subject, through the same secret check (exit 20)
   and mask as the description;
6. pushes the branch to `origin`, never forced, and refuses `pr.push-rejected` when the push fails,
   advising a pull only when git reports a rejection;
7. edits the body of the branch's open PR, or opens a draft PR into the default branch with that
   title, passing the body as a temporary file under `TMPDIR` that is deleted after the call;
8. appends a `pr` record with the PR's `number` and `url`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import core
import mask
import render

DROP = ".deliver"
KINDS = ("request", "requirements", "plan", "summary")
RERUN = "deliver.py pr"


def main(args: list[str], run: core.Run) -> None:
    if args:
        raise core.UsageError(f"pr takes no arguments, got: {' '.join(args)}")
    branch = _git(run, "branch", "--show-current").stdout.strip()
    if branch != run.mark["branch"]:
        raise core.Refused("pr.wrong-branch", f"git switch {run.mark['branch']}", branch=branch or "no branch",
                           marked=run.mark["branch"])
    folder = core.records_dir(run.common_dir, branch)
    unsaved = _unsaved(run, folder)
    if unsaved:
        raise core.Refused("pr.not-saved", f"deliver.py save {unsaved[0]}", files=", ".join(unsaved))
    try:
        body = render.description(folder)
    except render.Unreadable as e:
        raise core.Refused("pr.unreadable", f"rewrite {DROP}/{e.kind}.md, then deliver.py save {e.kind}",
                           kind=e.kind, why=str(e)) from None
    default = _gh(run, "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name").strip()
    if branch == default:
        raise core.Refused("pr.default-branch", "git switch -c <type>/<name>", branch=branch)
    subjects = _git(run, "log", "--reverse", "--format=%s", f"origin/{default}..HEAD").stdout.splitlines()
    title = subjects[0] if subjects else branch
    render.refuse_secret("The PR title, the branch's first commit subject,", "commit subject", title)
    title = mask.mask(title)[0]
    push = _git(run, "push", "--set-upstream", "origin", branch, check=False)
    if push.returncode != 0:
        sys.stderr.write(push.stderr)
        rejected = "[rejected]" in push.stderr
        fix = f"git pull --no-rebase origin {branch}" if rejected else f"fix the error above, then {RERUN}"
        raise core.Refused("pr.push-rejected", fix, branch=branch)
    found = json.loads(_gh(run, "pr", "list", "--head", branch, "--state", "open", "--json", "number,url"))
    fd, body_file = tempfile.mkstemp(prefix="deliver-pr-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        if found:
            number, url = found[0]["number"], found[0]["url"]
            _gh(run, "pr", "edit", str(number), "--body-file", body_file)
            print(f"Updated the description of PR #{number}: {url}")
        else:
            url = _gh(run, "pr", "create", "--draft", "--base", default, "--head", branch,
                      "--title", title, "--body-file", body_file).strip().splitlines()[-1]
            number = int(url.rstrip("/").rsplit("/", 1)[-1])
            print(f"Opened draft PR #{number}: {url}")
    finally:
        os.unlink(body_file)
    run.record("pr", number=number, url=url)


def _unsaved(run: core.Run, folder: Path) -> list[str]:
    """The kinds still to save: missing from the records, or still in the drop folder."""
    request = folder / "request.md"
    ticket = request.is_file() and request.read_text(encoding="utf-8").startswith("Source: ticket #")
    kinds = ["request", "summary", "plan"] + ([] if ticket else ["requirements"])
    missing = [kind for kind in kinds if not (folder / f"{kind}.md").is_file()]
    drop = run.checkout / DROP
    waiting = [kind for kind in KINDS if (drop / f"{kind}.md").is_file()]
    return missing + [kind for kind in waiting if kind not in missing]


def _git(run: core.Run, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=run.checkout, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc


def _gh(run: core.Run, *args: str) -> str:
    proc = subprocess.run(["gh", *args], cwd=run.checkout, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout
