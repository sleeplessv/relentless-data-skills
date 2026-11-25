#!/usr/bin/env python3
"""Rerun one ticket of the replay set with one agent. `--help` gives the steps and the files."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.dont_write_bytecode = True  # importing the siblings would otherwise write scripts/__pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
import draw  # noqa: E402  (a sibling script, not an installed package)
import scan  # noqa: E402

VERSION = "direct"
GENERATION_TWO = ("deliver", "fan-out")
# Tool caches a sandboxed command may read and write, under the home folder.
CACHES = (".cache/uv", ".cache/pip", "Library/Caches/pip", ".npm")
# The only hosts a sandboxed command may reach: package registries. GitHub is not one.
REGISTRIES = ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org")
# Variables the session must not inherit: a parent Claude Code session's own, and GitHub credentials.
KEPT = ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")
DROPPED = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_CONFIG_DIR")

HELP = f"""\
Rerun one ticket of the replay set with one agent, as its `{VERSION}` version.

Usage: python3 scripts/replay.py LABEL TICKET

LABEL and TICKET name an entry of a replay-set-<n>.json in the machine
directory, $DELIVER_STATE_DIR (default ~/.local/state/deliver). The replay:

1. Clones the repo that project-labels.json gives the label, with `gh repo
   clone`, and copies the history up to the entry's base_commit, and nothing
   after it, into a local bare repo, on the default branch's name. The kept
   clone is cut from that copy, which is its only remote. The full clone is
   removed before the session.
2. Runs the repo's setup command from repos.json, where it has one, with sh in
   the clone.
3. Starts one headless Claude Code session in the clone: `claude -p` on the
   entry's model, with the ticket's title and body as its whole prompt on
   standard input, prompts switched off (--permission-mode bypassPermissions),
   and the confinement below.
4. Commits whatever the clone's working tree holds, and records that commit as
   the ticket's {VERSION} version with the session's exit status.
5. Scans the session into scan-rows.jsonl. A session that loaded a skill of
   either generation ({", ".join(draw.GENERATION_ONE + GENERATION_TWO)}) is marked not direct.

Every session starts with --setting-sources project,local, --strict-mcp-config
with no MCP server, and these settings: the command sandbox on, a start refused
when the sandbox cannot start, no command run outside it; sandboxed writes only
to the clone, the temporary folder and the tool caches ~/{", ~/".join(CACHES)};
no sandboxed read under the home folder but the clone and those caches; network
only to {", ".join(REGISTRIES)}; the file tools held to the
clone; no claude.ai connector and no hook. It does not inherit the variables a
parent Claude Code session sets (CLAUDECODE, CLAUDE_CODE_*, and the rest of
CLAUDE_* but {" and ".join(KEPT)}) or a GitHub token. Nothing is pushed, and no PR
is opened.

Files, all in the machine directory:

  replays/<label>-<ticket>-{VERSION}/
                The clone, kept until its version is judged. Its HEAD is
                the version's commit.
  replays/<label>-<ticket>-{VERSION}.git/
                The clone's remote: the local copy of the history up to
                base_commit.
  versions.jsonl
                One JSON line per ticket and version, replaced when the same
                one is recorded again: label, ticket, version, commit,
                base_commit, clone, exit_status, session, skills, not_direct.
                clone is relative to the machine directory.

Exit 0: the version is recorded, whatever the session's exit status. Exit 1: an
error; no version is recorded, and no session started when the error came
before it. A clone or remote already in place is an error: remove both to
replay the ticket again. Exit 2: bad usage."""


class ReplayError(Exception):
    """Ends the replay with exit 1."""


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, stdin=subprocess.DEVNULL)


def git(clone: Path, *args: str) -> str:
    result = run("git", "-C", str(clone), *args)
    if result.returncode:
        raise ReplayError(f"`git {args[0]}` failed with exit {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def entry(state: Path, label: str, ticket: int) -> dict:
    for path in sorted(state.glob("replay-set-*.json")):
        for found in draw.read_json(path)["tickets"]:
            if found["label"] == label and found["ticket"] == ticket:
                return found
    raise ReplayError(f"no replay set in {state} holds project {label} ticket {ticket}.")


def repo(state: Path, label: str) -> dict:
    labels = draw.read_json(state / "project-labels.json")
    name = labels.get(label) if isinstance(labels, dict) else None
    for found in draw.read_json(state / "repos.json"):
        if name and found["repo"].lower() == name.lower():
            return found
    raise ReplayError(f"project {label} is not in both project-labels.json and repos.json.")


def settings(clone: Path) -> dict:
    """The confinement every session starts with."""
    home = Path.home()
    caches = [str(home / cache) for cache in CACHES]
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": [],
            "filesystem": {"denyRead": [str(home)], "allowRead": [str(clone), *caches], "allowWrite": caches},
            "network": {"allowedDomains": list(REGISTRIES), "strictAllowlist": True},
        },
        "permissions": {"blockReadsOutsideWorkingDirectories": True, "blockWritesOutsideWorkingDirectories": True},
        "disableClaudeAiConnectors": True,
        "disableAllHooks": True,
    }


def command(clone: Path, model: str, session: str) -> list[str]:
    return ["claude", "-p", "--model", model, "--session-id", session, "--permission-mode", "bypassPermissions",
            "--setting-sources", "project,local", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--settings", json.dumps(settings(clone))]


def environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not (key.startswith("CLAUDE") and key not in KEPT) and key not in DROPPED}
    env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
    return env


def cut(state: Path, label: str, ticket: int, found: dict, clone: Path, remote: Path) -> None:
    """Make the clone and its remote, holding the history up to base_commit and nothing after it."""
    with tempfile.TemporaryDirectory(dir=state) as work:
        source = Path(work) / "source"
        result = run("gh", "repo", "clone", repo(state, label)["repo"], str(source))
        if result.returncode:  # gh's message can name the repo, so it is not printed
            raise ReplayError(f"`gh repo clone` failed for project {label} with exit {result.returncode}.")
        base = found["base_commit"]
        git(source, "cat-file", "-e", f"{base}^{{commit}}")
        branch = git(source, "branch", "--show-current")  # the default branch, so origin/<it> is the base
        git(source, "init", "-q", "--bare", str(remote))
        git(source, "push", "-q", str(remote), f"{base}:refs/heads/{branch}")
    result = run("git", "clone", "-q", "--branch", branch, str(remote), str(clone))
    if result.returncode:
        raise ReplayError(f"`git clone` of the local copy failed with exit {result.returncode}.")
    for key, value in (("user.name", "replay"), ("user.email", "replay@localhost"), ("commit.gpgsign", "false")):
        git(clone, "config", key, value)


def record(state: Path, version: dict) -> None:
    path = state / "versions.jsonl"
    with open(state / "versions.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = [text for text in (path.read_text().splitlines() if path.is_file() else [])
                if text.strip() and [json.loads(text).get(key) for key in ("label", "ticket", "version")]
                != [version["label"], version["ticket"], version["version"]]]
        scan.write_private(path, "".join(text + "\n" for text in [*kept, json.dumps(version)]))


def replay(label: str, ticket: int) -> int:
    state = scan.state_dir()
    found = entry(state, label, ticket)
    replays = state / "replays"
    replays.mkdir(mode=0o700, exist_ok=True)
    name = f"{label}-{ticket}-{VERSION}"
    clone, remote = replays / name, replays / f"{name}.git"
    if clone.exists() or remote.exists():
        raise ReplayError(f"{clone} or {remote} is already in place. Remove both to replay the ticket again.")
    session = str(uuid.uuid4())
    try:
        cut(state, label, ticket, found, clone, remote)
        setup = repo(state, label).get("setup")
        if setup:
            code = subprocess.run(setup, shell=True, cwd=clone, stdin=subprocess.DEVNULL).returncode
            if code:
                raise ReplayError(f"the setup command exited {code}; no session started.")
        prompt = f"{found['title']}\n\n{found['body']}"
        status = subprocess.run(command(clone, found["model"], session), cwd=clone, input=prompt, text=True,
                                env=environment()).returncode
        _, log = scan.resolve(session)
        if not log.is_file():
            raise ReplayError(f"claude exited {status} and left no session log, so no session started.")
    except BaseException:
        shutil.rmtree(clone, ignore_errors=True)
        shutil.rmtree(remote, ignore_errors=True)
        raise
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "--allow-empty", "--no-verify", "-m", f"{VERSION} replay of {label}-{ticket}")
    row = scan.scan(session, log)
    scan.write_row(row)
    skills = row["skills"] or []
    version = {"label": label, "ticket": ticket, "version": VERSION, "commit": git(clone, "rev-parse", "HEAD"),
               "base_commit": found["base_commit"], "clone": str(clone.relative_to(state)), "exit_status": status,
               "session": session, "skills": skills,
               "not_direct": any(skill.split(":")[-1] in draw.GENERATION_ONE + GENERATION_TWO for skill in skills)}
    record(state, version)
    print(f"Recorded {label}-{ticket} {VERSION} at {version['commit']}: session exit {status}"
          + (", marked not direct." if version["not_direct"] else "."))
    return 0


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(HELP)
        return 0
    if len(argv) != 2 or not argv[1].isdecimal() or argv[0].startswith("-"):
        print(HELP, file=sys.stderr)
        return 2
    try:
        return replay(argv[0], int(argv[1]))
    except ReplayError as error:
        print(f"replay: {error}", file=sys.stderr)
        return 1
    except draw.DrawError as error:
        print(f"replay: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
