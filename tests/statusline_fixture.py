"""Run skills/statusline/scripts/statusline.sh against a throwaway repo and PR cache.

Shared by tests/test_statusline.py and scripts/statusline_screenshots.py, so
the cache file name and PR shape live in one place. The cache is written
fresh, so the script never refreshes it, and a stub gh on PATH keeps
everything off the network.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "statusline" / "scripts" / "statusline.sh"
REPO_URL = "https://github.com/acme/widgets"


def pr(number, closes=(), branch=None, draft=False, fork=False, checks=()):
    """One entry of the cache, shaped like gh pr list --json output."""
    return {
        "number": number,
        "url": f"{REPO_URL}/pull/{number}",
        "isDraft": draft,
        "isCrossRepository": fork,
        "headRefName": branch or f"branch-{number}",
        "statusCheckRollup": list(checks),
        "closingIssuesReferences": [
            {"number": n, "url": f"{REPO_URL}/issues/{n}"} for n in closes
        ],
    }


def run_statusline(tmp: Path, branch, prs, status, repo_name="repo"):
    """Run the script in a new repo under `tmp` on `branch`, with `prs` cached.

    `tmp` must be resolved and must not already hold this setup. `status` is
    the status line JSON, without workspace.current_dir, which points at the
    repo. Return the output lines.
    """
    repo = tmp / repo_name
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q", "-b", branch], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    key = subprocess.run(
        ["cksum"], input=str(repo), capture_output=True, text=True, check=True
    ).stdout.split()[0]
    cache_dir = tmp / "cache" / "claude-statusline"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"prs-v2-{key}.json").write_text(json.dumps(prs))
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n")
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "XDG_CACHE_HOME": str(tmp / "cache"),
    }
    stdin = json.dumps({**status, "workspace": {"current_dir": str(repo)}})
    out = subprocess.run(
        ["sh", str(SCRIPT)], input=stdin, capture_output=True, text=True, env=env, check=True
    ).stdout
    return out.split("\n")
