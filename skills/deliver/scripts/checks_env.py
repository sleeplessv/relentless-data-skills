"""Preflight's checks that do not depend on the harness (#178 check table, #256 rule 48).

`preflight.CHECKS` holds them in this order: Python, the writes, signing, `gh` and GitHub, and,
last, the repo's named commands. The GitHub check saves `gh repo view`'s answer in `ctx.repo`,
and the push, issue and branch-rule checks read it from there. A reach command runs as
`sh -c <command>` in the checkout, with no input. The dependents command runs through
`small_test`, as the small test runs it, on the first path `git ls-files` lists, or on no path
when it lists none.

Each runner handles a program it cannot start and output it cannot decode in its own way:

- `_run` turns a program that cannot start into a run that failed with exit 127, and keeps the
  output as bytes. Its callers decode diagnostics and the sample path with replacement, and give
  JSON answers to `json.loads` as bytes, which also reads UTF-16 and UTF-32. Bytes it cannot
  decode take the check's unreadable path.
- `check_gh_signed_in` runs `gh` itself and stops with `preflight.no-gh` when `gh` cannot start.
- `small_test` reads the dependents command's output as text. Preflight turns a program that
  cannot start, or output that is not UTF-8, into a dependents warning.

preflight imports this module, so each result type comes from the module that made `ctx`, as in
`check_guard`: an import of preflight here would be circular, and a test loads it under another
name.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import tempfile

import core
import settings
import small_test

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
SIGN_TEST = f"git commit-tree -S -m test {EMPTY_TREE}"
REPO_FIELDS = "nameWithOwner,defaultBranchRef,viewerPermission,hasIssuesEnabled"
CAN_PUSH = ("ADMIN", "MAINTAIN", "WRITE")
INSTALL_GH = "install gh from https://cli.github.com"


def _stop(ctx, code: str, fix: str, **fields: object):
    preflight = sys.modules[type(ctx).__module__]
    return preflight.Stop(code, f"{fix}, then run {preflight.RERUN}", fields)


def _warn(ctx, line: str):
    return sys.modules[type(ctx).__module__].Warn(line)


def _run(ctx, *args: str) -> subprocess.CompletedProcess:
    """Run `args` in the checkout with no input; output stays bytes, and a program that cannot start exits 127."""
    try:
        return subprocess.run(args, cwd=ctx.run.checkout, stdin=subprocess.DEVNULL, capture_output=True)
    except OSError as e:
        return subprocess.CompletedProcess(args, 127, b"", f"{args[0]}: {e.strerror or e}".encode())


def _last_line(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stdout + b"\n" + proc.stderr).decode("utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def _blocked(folder):
    """The file that sits where `folder` or one of its parents should be, if any."""
    for path in (*reversed(folder.parents), folder):
        if path.exists() and not path.is_dir():
            return path
    return None


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
        (core.records_dir(ctx.run.common_dir, ctx.run.mark["branch"]), ""),
        (core.state_dir(), ", or set DELIVER_STATE_DIR to a folder you can write"),
    )
    for folder, other_way in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tempfile.TemporaryFile(dir=folder).close()
        except OSError as e:
            blocked = _blocked(folder)
            if blocked:
                fix = f"move or delete the file {blocked}, which sits where a folder is needed"
            else:
                writable = next(p for p in (folder, *folder.parents) if p.exists())
                fix = f"`chmod u+w {shlex.quote(str(writable))}`"
            return _stop(ctx, "preflight.cannot-write", fix + other_way, path=folder, error=e.strerror or e)
    return None


def check_signing(ctx):
    """Stop when git signs commits in this checkout and a test signature fails."""
    if _run(ctx, "git", "config", "--type=bool", "--get", "commit.gpgsign").stdout.strip() != b"true":
        return None
    proc = _run(ctx, *SIGN_TEST.split())
    if proc.returncode == 0:
        return None
    return _stop(ctx, "preflight.no-signature", f"fix signing until `{SIGN_TEST}` works here", error=_last_line(proc))


def check_gh_signed_in(ctx):
    """Stop when `gh` cannot be started or holds no token; the token itself is never read."""
    try:
        proc = subprocess.run(["gh", "auth", "token"], cwd=ctx.run.checkout, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return _stop(ctx, "preflight.no-gh", INSTALL_GH, error=e.strerror or e)
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
        return _stop(ctx, "preflight.no-github", "`gh repo set-default` to name this checkout's GitHub repo, "
                     "or `gh auth status` if gh cannot reach GitHub", error=_last_line(proc))
    ctx.repo = repo
    return None


def check_push(ctx):
    """Stop when the signed-in account cannot push to the repo."""
    name, permission = ctx.repo["nameWithOwner"], ctx.repo.get("viewerPermission")
    if permission in CAN_PUSH:
        return None
    return _stop(ctx, "preflight.cannot-push", f"`gh auth login` as an account that can push to {name}",
                 repo=name, permission=permission or "none")


def check_issues(ctx):
    """Warn when follow-ups are on and the repo takes no new issues."""
    if not ctx.settings["follow_ups"] or ctx.repo.get("hasIssuesEnabled") is not False:
        return None
    return _warn(ctx, f'issues are off on {ctx.repo["nameWithOwner"]}, so each follow-up is listed as "follow-up not filed": '
                 f"turn issues on in the repo's settings, or set follow_ups = false in {settings.PATH}")


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
    return _warn(ctx, f"check_command is empty in {settings.PATH}, so ready relies on the check plan's commands: "
                 "set check_command there to the command that runs this repo's checks")


def check_reach(ctx):
    """Stop at the first reach command that fails; this build stage has no waiver."""
    for name, command in ctx.settings["reach"].items():
        if not command:
            continue
        proc = _run(ctx, "sh", "-c", command)
        if proc.returncode != 0:
            return _stop(ctx, "preflight.reach-failed", f"change [reach] {name} in {settings.PATH}, or what it "
                         f"reaches, until `{command}` exits 0", name=name, command=command,
                         exit=proc.returncode, error=_last_line(proc))
    return None


def check_dependents(ctx):
    """Warn when the dependents command fails as the small test reads it; an empty one runs nothing (#407 reading 13).

    It runs on a sample path, the first path `git ls-files` lists, since preflight has no changed
    paths yet: any tracked path is a real input, and a command that needs at least one path gets
    it. When git lists none, it runs on no path. Its count is not judged.
    """
    command = ctx.settings["small_edit"]["dependents_command"]
    if not command:
        return None
    tracked = _run(ctx, "git", "ls-files", "-z").stdout.split(b"\0")[0].decode("utf-8", errors="replace")
    paths = [tracked] if tracked else []
    try:
        result = small_test._dependents(ctx.run.checkout, command, paths)
    except (OSError, ValueError) as e:  # ValueError: output that is not UTF-8
        result = {"error": str(e)}
    if "error" not in result:
        return None
    run = " ".join([command, *map(shlex.quote, paths)])
    sample = f"the sample path {paths[0]}" if paths else "no path"
    return _warn(ctx, f"the dependents command `{run}` failed on {sample} ({result['error']}), and a failure on a "
                 f"change's own paths sends that change to review: fix [small_edit] dependents_command in "
                 f"{settings.PATH} until it prints a count first, or empty it")
