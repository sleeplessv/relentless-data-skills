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
MARKED = draw.GENERATION_ONE + GENERATION_TWO
# Tool caches a sandboxed command may read and write, under the home folder.
CACHES = (".cache/uv", ".cache/pip", "Library/Caches/pip", ".npm")
# The only hosts a sandboxed command may reach: package registries. GitHub is not one.
REGISTRIES = ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org")
# Variables the session must not inherit: a parent Claude Code session's own, and GitHub credentials.
KEPT = ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")
DROPPED = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_CONFIG_DIR")
ORIGIN = "replay-origin.git"  # the clone's remote, inside its .git/
REF = f"refs/replay/{VERSION}"  # the version's commit, in the version's repo, outside refs/heads/ where branches live

HELP = f"""\
Rerun one ticket of the replay set with one agent, as its `{VERSION}` version.

Usage: python3 scripts/replay.py LABEL TICKET

LABEL and TICKET name an entry of a replay-set-<n>.json in the machine
directory, $DELIVER_STATE_DIR (default ~/.local/state/deliver). Sets, the repo
list and the label key are read as scripts/draw.py reads them. The replay:

1. Takes the ticket's clone folder, so no other replay of it can start, and
   clones the repo that project-labels.json gives the label with `gh repo
   clone`. It copies the history up to the entry's base_commit, and nothing
   after it, on the default branch's name, into the version's repo and into
   the clone, whose only remote is a bare copy inside its own .git/. Neither
   shares a file with the version's repo. The clone is checked out under the
   git settings of step 4. The full clone is removed before the session.
2. Runs the repo's setup command from repos.json, where it has one, with sh in
   the clone.
3. Starts one headless Claude Code session in the clone: `claude -p` on the
   entry's model, with the ticket's title and body as its whole prompt on
   standard input, prompts switched off (--permission-mode bypassPermissions),
   and the confinement below.
4. Commits whatever the clone's working tree holds into the version's repo:
   every file git would add, and every file or link the clone's index lists,
   ignored or not. The git settings of every git command the replay starts
   itself, gh's aside: no config file but the repo's own (none from the clone's .git/ here, so nothing
   the session left there runs; no user or system config file), and no GIT_*
   variable from the caller. Git's default attribute and ignore files still
   apply: $XDG_CONFIG_HOME/git/attributes and git/ignore (by default under
   ~/.config/) and the system attributes file. A start that left no session
   log and changed nothing is taken as no session: nothing is recorded.
5. Scans the session. A log that is missing or cannot be scanned gives the
   scan's row of blanks.
6. Records the commit as the ticket's {VERSION} version with the session's exit
   status, then writes the row to scan-rows.jsonl. A session that loaded a
   skill of either generation ({", ".join(MARKED)}), or whose
   skills the scan cannot tell, is marked not direct.

Every session starts with --setting-sources project,local, --strict-mcp-config
with no MCP server, and these settings: the command sandbox on, a start refused
when the sandbox cannot start, no command run outside it; sandboxed writes only
to the clone, the temporary folder and the tool caches ~/{", ~/".join(CACHES)};
no sandboxed read under the home folder but the clone and those caches; network
only to {", ".join(REGISTRIES)}; the file tools held to the
clone; no WebFetch or WebSearch tool; no claude.ai connector and no hook. It does not inherit the variables a
parent Claude Code session sets (CLAUDECODE, CLAUDE_CODE_*, and the rest of
CLAUDE_* but {" and ".join(KEPT)}) or a GitHub token. For git, its environment
sets GIT_CONFIG_GLOBAL to {os.devnull} and GIT_CONFIG_NOSYSTEM to 1, sets
core.excludesFile and core.attributesFile to {os.devnull} through
GIT_CONFIG_COUNT, and carries no other GIT_* variable of the caller's. These
settings replace git's default lookups of the system config file, of
~/.gitconfig, and of the config, ignore and attributes files under
$XDG_CONFIG_HOME/git/ (~/.config/git/ when XDG_CONFIG_HOME is unset).
Nothing is pushed, and no PR is opened.

Files, all in the machine directory:

  replays/<label>-<ticket>-{VERSION}/
                The clone, as the session left it, kept until its version is
                judged. Its remote is .git/{ORIGIN}.
  replays/<label>-<ticket>-{VERSION}.git/
                The version's repo, out of the session's reach: the history
                up to base_commit, the version's commit at {REF}, and
                replay-index, the index the commit was written from.
  versions.jsonl
                One JSON line per ticket and version, replaced when the same
                one is recorded again: label, ticket, version, commit, repo,
                base_commit, clone, exit_status, session, skills, not_direct.
                repo and clone are relative to the machine directory. skills
                is null when the scan cannot tell them; not_direct is then
                true.

Exit 0: the version is recorded, whatever the session's exit status; a scan
that failed is reported. Exit 1: an error. Before a session ran, or for a
start taken as no session, nothing is recorded and what the replay made is
removed. After a session ran, the clone and the version's repo are kept; the
version is recorded only when the error came while its row was written, and
then it has no row. A clone or version repo
already in place is an error: remove both to replay the ticket again. Exit 2:
bad usage."""


class ReplayError(Exception):
    """Ends the replay with exit 1."""


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, stdin=subprocess.DEVNULL, env=env)


def plain() -> dict[str, str]:
    """The environment for the replay's own git: the settings --help gives in step 4."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return {**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def git(where: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = run("git", "-C", str(where), *args, env=env or plain())
    if result.returncode:
        raise ReplayError(f"`git {args[0]}` failed with exit {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def entry(drawer: draw.Draw, label: str, ticket: int) -> dict:
    for _, path in sorted(drawer.sets().items()):
        for found in draw.read_json(path)["tickets"]:
            if found["label"] == label and found["ticket"] == ticket:
                return found
    raise ReplayError(f"no replay set in {drawer.state} holds project {label} ticket {ticket}.")


def repo(drawer: draw.Draw, label: str) -> dict:
    path = drawer.state / "project-labels.json"
    labels = draw.read_json(path) if path.is_file() else {}
    name = labels.get(label) if isinstance(labels, dict) else None
    found = drawer.repos().get(name.lower()) if isinstance(name, str) else None
    if not found:
        raise ReplayError(f"project {label} is not in both project-labels.json and repos.json.")
    return found


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
        # The sandbox binds commands only, not the web tools; a deny holds with prompts switched off.
        "permissions": {"blockReadsOutsideWorkingDirectories": True, "blockWritesOutsideWorkingDirectories": True,
                        "deny": ["WebFetch", "WebSearch"]},
        "disableClaudeAiConnectors": True,
        "disableAllHooks": True,
    }


def command(clone: Path, model: str, session: str) -> list[str]:
    return ["claude", "-p", "--model", model, "--session-id", session, "--permission-mode", "bypassPermissions",
            "--setting-sources", "project,local", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--settings", json.dumps(settings(clone))]


def environment() -> dict[str, str]:
    """The session's, with the git settings --help gives."""
    env = {key: value for key, value in plain().items()
           if not (key.startswith("CLAUDE") and key not in KEPT) and key not in DROPPED}
    return {**env, "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.excludesFile", "GIT_CONFIG_VALUE_0": os.devnull,
            "GIT_CONFIG_KEY_1": "core.attributesFile", "GIT_CONFIG_VALUE_1": os.devnull}


def trusted(store: Path, clone: Path, index: str = "replay-index") -> dict[str, str]:
    """Git with the version's repo as its repository and the clone as its working tree, in the plain
    environment: nothing the session wrote in the clone's .git/ (config, hooks, filters) applies."""
    return {**plain(), "GIT_DIR": str(store), "GIT_WORK_TREE": str(clone), "GIT_INDEX_FILE": str(store / index),
            "GIT_LITERAL_PATHSPECS": "1", "GIT_AUTHOR_NAME": "replay", "GIT_AUTHOR_EMAIL": "replay@localhost",
            "GIT_COMMITTER_NAME": "replay", "GIT_COMMITTER_EMAIL": "replay@localhost"}


def cut(source_repo: str, label: str, found: dict, clone: Path, store: Path) -> None:
    """Fill the version's repo and the empty clone folder with the history up to base_commit and nothing after it."""
    with tempfile.TemporaryDirectory(dir=store.parent) as work:
        source = Path(work) / "source"
        result = run("gh", "repo", "clone", source_repo, str(source))
        if result.returncode:  # gh's message can name the repo, so it is not printed
            raise ReplayError(f"`gh repo clone` failed for project {label} with exit {result.returncode}.")
        base = found["base_commit"]
        git(source, "cat-file", "-e", f"{base}^{{commit}}")
        branch = git(source, "branch", "--show-current")  # the default branch, so origin/<it> is the base
        git(source, "init", "-q", "--bare", f"--initial-branch={branch}", str(store))
        git(source, "push", "-q", str(store), f"{base}:refs/heads/{branch}")
    # --no-local copies the objects instead of hard-linking them, so no file of the store is the clone's.
    # origin/HEAD follows the store's HEAD.
    git(store, "clone", "-q", "--no-local", str(store), str(clone))
    git(clone, "clone", "-q", "--bare", "--no-local", str(store), str(clone / ".git" / ORIGIN))
    git(clone, "remote", "set-url", "origin", str(clone / ".git" / ORIGIN))
    for key, value in (("user.name", "replay"), ("user.email", "replay@localhost"), ("commit.gpgsign", "false")):
        git(clone, "config", key, value)


def tracked(store: Path, clone: Path) -> list[str]:
    """The paths the clone's index lists, read from a copy of the index file as data. None when the index is a
    link or not a file, or git cannot list the copy; a copy that cannot be made raises."""
    index = clone / ".git" / "index"
    if index.is_symlink() or not index.is_file():
        return []
    shutil.copyfile(index, store / "replay-clone-index")
    listed = run("git", "-C", str(clone), "ls-files", "-z", env=trusted(store, clone, "replay-clone-index"))
    (store / "replay-clone-index").unlink()
    paths = [Path(path) for path in listed.stdout.split("\0") if path] if listed.returncode == 0 else []
    # Each path must name a file or link in the clone itself: not under .git/, and not reached through a link
    # or as a folder, which a forced add would take whole, ignored files and all.
    return [str(path) for path in paths if ".." not in path.parts and path.parts[0] != ".git"
            and not any((clone / Path(*path.parts[:end])).is_symlink() for end in range(1, len(path.parts)))
            and ((clone / path).is_symlink() or (clone / path).is_file())]


def snapshot(store: Path, clone: Path, base: str) -> str:
    """Write the clone's working tree, as it stands, into the version's repo as a tree."""
    env = trusted(store, clone)
    git(clone, "read-tree", base, env=env)
    git(clone, "add", "-A", env=env)
    paths = tracked(store, clone)
    if paths:
        (store / "replay-tracked").write_text("\0".join(paths))
        git(clone, "add", "-f", f"--pathspec-from-file={store / 'replay-tracked'}", "--pathspec-file-nul", env=env)
        (store / "replay-tracked").unlink()
    return git(clone, "write-tree", env=env)


def remove(made: list[Path]) -> None:
    for path in made:
        shutil.rmtree(path, ignore_errors=True)


def record(state: Path, version: dict) -> None:
    path = state / "versions.jsonl"
    with open(state / "versions.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = [text for text in (path.read_text().splitlines() if path.is_file() else [])
                if text.strip() and [json.loads(text).get(key) for key in ("label", "ticket", "version")]
                != [version["label"], version["ticket"], version["version"]]]
        scan.write_private(path, "".join(text + "\n" for text in [*kept, json.dumps(version)]))


def replay(label: str, ticket: int) -> int:
    drawer = draw.Draw(0)
    state = drawer.state
    found = entry(drawer, label, ticket)
    config = scan.config_dir()
    if not config.is_absolute():  # the session runs in the clone, so a relative one would point elsewhere
        os.environ["CLAUDE_CONFIG_DIR"] = str(config.absolute())
    replays = state / "replays"
    replays.mkdir(mode=0o700, exist_ok=True)
    name = f"{label}-{ticket}-{VERSION}"
    clone, store = replays / name, replays / f"{name}.git"
    listed = repo(drawer, label)
    try:
        clone.mkdir(mode=0o700)  # the ticket's, from here on, until this replay ends
    except FileExistsError:
        raise ReplayError(f"{clone} is already in place. Remove it and {store} to replay the ticket again.")
    made = [clone]
    session = str(uuid.uuid4())
    try:
        if store.exists():
            raise ReplayError(f"{store} is already in place. Remove it and {clone} to replay the ticket again.")
        made.append(store)
        cut(listed["repo"], label, found, clone, store)
        setup = listed.get("setup")
        if setup:
            code = subprocess.run(setup, shell=True, cwd=clone, stdin=subprocess.DEVNULL).returncode
            if code:
                raise ReplayError(f"the setup command exited {code}; no session started.")
        before = snapshot(store, clone, found["base_commit"])
        prompt = f"{found['title']}\n\n{found['body']}"
        status = subprocess.run(command(clone, found["model"], session), cwd=clone, input=prompt, text=True,
                                env=environment()).returncode
    except BaseException:
        remove(made)
        raise
    _, log = scan.resolve(session)
    tree = snapshot(store, clone, found["base_commit"])  # if this fails, both are kept as the session left them
    if not log.is_file() and tree == before:
        remove(made)
        raise ReplayError(f"claude exited {status}, left no session log and changed nothing, so no session started.")
    commit = git(store, "commit-tree", "--no-gpg-sign", tree, "-p", found["base_commit"], "-m",
                 f"{VERSION} replay of {label}-{ticket}", env=trusted(store, clone))
    git(store, "update-ref", REF, commit, env=trusted(store, clone))
    try:  # nothing the log holds may stop the record
        row = scan.scan(session, log)
        skills = row["skills"]
        not_direct = skills is None or any(skill.split(":")[-1] in MARKED for skill in skills)
    except (Exception, SystemExit) as failure:  # scan exits on a line that is not JSON
        print(f"replay: the session's log could not be scanned ({failure}); its row is left blank.", file=sys.stderr)
        row, skills, not_direct = scan.scan(session, Path()), None, True  # a path that is no file: the row of blanks
    version = {"label": label, "ticket": ticket, "version": VERSION, "commit": commit,
               "repo": str(store.relative_to(state)), "base_commit": found["base_commit"],
               "clone": str(clone.relative_to(state)), "exit_status": status, "session": session, "skills": skills,
               "not_direct": not_direct}
    record(state, version)
    scan.write_row(row)
    print(f"Recorded {label}-{ticket} {VERSION} at {commit}: session exit {status}"
          + (", skills unknown, marked not direct." if skills is None
             else ", marked not direct." if version["not_direct"] else "."))
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
    except (ReplayError, draw.DrawError) as error:
        print(f"replay: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
