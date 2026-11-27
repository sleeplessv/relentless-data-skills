"""Preflight's checks that do not depend on the harness (#178 check table, #256 rule 48).

`preflight.CHECKS` holds them in this order: Python, the writes, signing, `gh` and GitHub, and,
last, the repo's named commands. The GitHub check saves `gh repo view`'s answer in `ctx.repo`,
and the push, issue and branch-rule checks read it from there. A repo's command runs as
`sh -c <command>` in the checkout, with no input.

preflight imports this module, so each result type comes from the module that made `ctx`, as in
`check_guard`: an import of preflight here would be circular, and a test loads it under another
name.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile

import core
import settings

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
SIGN_TEST = f"git commit-tree -S -m test {EMPTY_TREE}"
REPO_FIELDS = "nameWithOwner,defaultBranchRef,viewerPermission,hasIssuesEnabled"
CAN_PUSH = ("ADMIN", "MAINTAIN", "WRITE")


def _stop(ctx, code: str, fix: str, **fields: object):
    preflight = sys.modules[type(ctx).__module__]
    return preflight.Stop(code, f"{fix}, then run {preflight.RERUN}", fields)


def _warn(ctx, line: str):
    return sys.modules[type(ctx).__module__].Warn(line)


def _run(ctx, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ctx.run.checkout, stdin=subprocess.DEVNULL, capture_output=True, text=True)


def _last_line(proc: subprocess.CompletedProcess) -> str:
    lines = [line.strip() for line in (proc.stdout + "\n" + proc.stderr).splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def check_python(ctx):
    """Stop when the machine has neither `uv` nor a `python3` of 3.13 or newer."""
    if shutil.which("uv"):
        return None
    python = shutil.which("python3")
    if python and _run(ctx, python, "-c", "import sys; sys.exit(sys.version_info < (3, 13))").returncode == 0:
        return None
    return _stop(ctx, "preflight.no-python", "curl -LsSf https://astral.sh/uv/install.sh | sh")


def check_writable(ctx):
    """Stop when the branch's records folder or the machine directory cannot be written."""
    folders = (
        (core.records_dir(ctx.run.common_dir, ctx.run.mark["branch"]), "make that folder writable"),
        (core.state_dir(), "make that folder writable or set DELIVER_STATE_DIR to one that is"),
    )
    for folder, fix in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tempfile.TemporaryFile(dir=folder).close()
        except OSError as e:
            return _stop(ctx, "preflight.cannot-write", fix, path=folder, error=e.strerror or e)
    return None


def check_signing(ctx):
    """Stop when git signs commits in this checkout and a test signature fails."""
    if _run(ctx, "git", "config", "--type=bool", "--get", "commit.gpgsign").stdout.strip() != "true":
        return None
    proc = _run(ctx, *SIGN_TEST.split())
    if proc.returncode == 0:
        return None
    return _stop(ctx, "preflight.no-signature", f"fix signing until `{SIGN_TEST}` works here", error=_last_line(proc))


def check_gh_signed_in(ctx):
    """Stop when `gh` holds no token; the token itself is never read."""
    proc = subprocess.run(["gh", "auth", "token"], cwd=ctx.run.checkout, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None if proc.returncode == 0 else _stop(ctx, "preflight.gh-signed-out", "gh auth login")


def check_github(ctx):
    """Stop when `gh repo view` cannot read this repo from GitHub; keep its answer in `ctx.repo`."""
    proc = _run(ctx, "gh", "repo", "view", "--json", REPO_FIELDS)
    try:
        repo = json.loads(proc.stdout)
        readable = proc.returncode == 0 and all(
            isinstance(value, str) and value for value in (repo["nameWithOwner"], repo["defaultBranchRef"]["name"]))
    except (ValueError, TypeError, KeyError):
        readable = False
    if not readable:
        return _stop(ctx, "preflight.no-github", "fix what `gh repo view` prints here", error=_last_line(proc))
    ctx.repo = repo
    return None


def check_push(ctx):
    """Stop when the signed-in account cannot push to the repo."""
    name, permission = ctx.repo["nameWithOwner"], ctx.repo.get("viewerPermission")
    if permission in CAN_PUSH:
        return None
    return _stop(ctx, "preflight.cannot-push", f"gh auth login as an account that can push to {name}",
                 repo=name, permission=permission or "none")


def check_issues(ctx):
    """Warn when follow-ups are on and the repo takes no new issues."""
    if not ctx.settings["follow_ups"] or ctx.repo.get("hasIssuesEnabled") is not False:
        return None
    return _warn(ctx, f'issues are off on {ctx.repo["nameWithOwner"]}, so each follow-up is listed as "follow-up not filed"')


def check_branch_rules(ctx):
    """Warn when the target branch's rules need an approving review; an unreadable answer goes ahead."""
    branch = ctx.repo["defaultBranchRef"]["name"]
    proc = _run(ctx, "gh", "api", f"repos/{ctx.repo['nameWithOwner']}/rules/branches/{branch}")
    if proc.returncode != 0:
        return None
    try:
        approvals = [rule["parameters"]["required_approving_review_count"]
                     for rule in json.loads(proc.stdout) if rule["type"] == "pull_request"]
    except (ValueError, TypeError, KeyError):
        return None
    if not any(isinstance(n, int) and n > 0 for n in approvals):
        return None
    return _warn(ctx, f"{branch} needs an approving review the agent cannot give: run will end at ready")


def check_check_command(ctx):
    """Warn when the repo names no standard check command."""
    if ctx.settings["check_command"]:
        return None
    return _warn(ctx, f"check_command is empty in {settings.PATH}, so ready relies on the check plan's commands")


def check_reach(ctx):
    """Stop at the first reach command that fails; this build stage has no waiver."""
    for name, command in ctx.settings["reach"].items():
        if not command:
            continue
        proc = _run(ctx, "sh", "-c", command)
        if proc.returncode != 0:
            return _stop(ctx, "preflight.reach-failed", f"fix what `{command}` needs", name=name, command=command,
                         exit=proc.returncode, error=_last_line(proc))
    return None


def check_dependents(ctx):
    """Warn when the repo's dependents command fails; an empty one runs nothing (#407 reading 13)."""
    command = ctx.settings["small_edit"]["dependents_command"]
    if not command:
        return None
    proc = _run(ctx, "sh", "-c", command)
    if proc.returncode == 0:
        return None
    return _warn(ctx, f"the dependents command `{command}` failed with exit {proc.returncode}, so every change gets a review")
