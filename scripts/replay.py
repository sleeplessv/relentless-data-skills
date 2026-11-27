#!/usr/bin/env python3
"""Rerun one ticket of the replay set with one agent. `--help` gives the steps and the files."""
from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

sys.dont_write_bytecode = True  # importing the siblings would otherwise write scripts/__pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
import draw  # noqa: E402  (a sibling script, not an installed package)
import scan  # noqa: E402

VERSION = "direct"
GENERATION_TWO = ("deliver", "squad")
MARKED = draw.GENERATION_ONE + GENERATION_TWO
# Tool caches a sandboxed command may read and write, under the home folder.
CACHES = (".cache/uv", ".cache/pip", "Library/Caches/pip", ".npm")
# The only hosts a sandboxed command may reach: package registries. GitHub is not one.
REGISTRIES = ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org")
# The sandbox's temporary folder, in both of its spellings on macOS: the one folder a command may put a Unix socket in.
SOCKETS = (f"/tmp/claude-{os.getuid()}", f"/private/tmp/claude-{os.getuid()}")
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
   the clone, in a process group made for the replay. What setup starts runs on
   through the session. It is stopped once the session has ended, before step 4
   commits the working tree, and on every other way the replay ends: a setup
   that fails, a start that is refused, an error, Ctrl-C or SIGTERM. SIGKILL to
   the replay leaves it running, and a process that starts its own group or
   session is not followed.
3. Starts one headless Claude Code session in the clone: `claude -p` on the
   entry's model, with the ticket's title and body as its whole prompt on
   standard input, prompts switched off (--permission-mode bypassPermissions),
   and the confinement below.
4. Commits whatever the clone's working tree holds into the version's repo:
   every file git would add, and every file or link the clone's index lists,
   ignored or not. The replay reads each name in the index as the bytes git
   holds it, in any locale. The replay's own git commands, gh's aside, set
   GIT_CONFIG_NOSYSTEM to 1 and GIT_CONFIG_GLOBAL to {os.devnull}, which
   switch off git's default lookups of the system config file and of the user
   config files (~/.gitconfig and $XDG_CONFIG_HOME/git/config); a config file
   that a repo's own config names with include.path is still read. They carry
   no GIT_* variable from the caller. The version's repo records the tree. A
   private repo, made beside it for this step, lists a copy of the clone's
   index and reads objects from the clone's .git/objects and from the folders
   its alternates file names that exist. Neither repo reads
   the clone's config, so nothing the session left in the clone's .git/ runs.
   Git's default
   attribute and ignore files still apply: $XDG_CONFIG_HOME/git/attributes and git/ignore (by default under
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
only to {", ".join(REGISTRIES)}; local port binding; Unix sockets only in the
sandbox's temporary folder, /tmp/claude-<uid> and its spelling
/private/tmp/claude-<uid>, and in no other folder; the file tools held to the
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
removed. After a session ran, the clone and the version's repo are kept. A clone
index that is not a regular file, or that the replay cannot copy or list with
git, ends the replay with one line on standard error and nothing recorded. Git
lists a split index with its shared index and a sparse index with the trees
in the clone's objects. A listing that exits 0 but writes to standard error,
as git does when it cannot read such a tree, counts as one git cannot list.
A row that cannot be written, after the version was
recorded, ends it with one line on standard error that says the version is
recorded without its row and names the command that writes the row from the session's log,
python3 scripts/scan.py SESSION; the version's line stays in versions.jsonl, and
the scan's own warnings are printed only when the row is written. A clone or version repo
already in place is an error: remove both to replay the ticket again. Exit 2:
bad usage."""


class ReplayError(Exception):
    """Ends the replay with exit 1."""


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """`args` run to the end, with what it prints decoded in the locale. A byte the locale cannot decode, as in a path
    under the C locale, is kept as Python keeps it in a file name, so no output ends the replay with a traceback."""
    return subprocess.run(args, text=True, errors="surrogateescape", capture_output=True, stdin=subprocess.DEVNULL,
                          env=env)


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
            "network": {"allowedDomains": list(REGISTRIES), "strictAllowlist": True, "allowLocalBinding": True,
                        "allowUnixSockets": list(SOCKETS)},
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


def tracked(store: Path, clone: Path) -> list[bytes]:
    """The paths the clone's index lists, as the bytes git holds them. Empty when the clone's .git/ is a folder with no
    index file in it. The index must be a regular file, which is copied as data into a private git folder with the
    shared index beside it that a split index names, and listed there; the version's repo is not touched. An index
    that --help's exit paragraph says the replay cannot list raises ReplayError."""
    index = clone / ".git" / "index"

    def unreadable(why: str) -> ReplayError:
        return ReplayError(f"the clone's index {str(index)!r} cannot be read ({why}).")
    try:
        info = os.lstat(index)
    except FileNotFoundError:
        try:  # a .git that is gone, or a link to nothing, is not a git folder with no index in it
            os.stat(index.parent)
        except OSError as error:
            raise unreadable(error.strerror) from None
        return []
    except OSError as error:  # an unsearchable .git, or a .git that is a file naming another folder
        raise unreadable(error.strerror) from None
    if not stat.S_ISREG(info.st_mode):  # a link or a folder: native git follows some, the replay reads none
        raise unreadable("not a regular file")
    try:  # every step of making, filling and listing the private folder ends, if it fails, in the index's one line
        with tempfile.TemporaryDirectory(dir=store.parent, ignore_cleanup_errors=True) as private:
            meta = Path(private)
            made = run("git", "init", "-q", "--bare", private, env=plain())
            if made.returncode:
                raise unreadable(f"git init exited {made.returncode}")
            shutil.copyfile(index, meta / "index")
            base = shared_index((meta / "index").read_bytes())  # a split index reads the one it names: found by
            if base:  # name, as git finds it, for .git/ may be searchable and not readable
                shared = index.parent / f"sharedindex.{base}"
                with contextlib.suppress(OSError):  # it may be missing, unreadable or a link to anywhere: git fails
                    if stat.S_ISREG(shared.lstat().st_mode):  # below, as native git does when it cannot read it
                        shutil.copyfile(shared, meta / shared.name)
            # A sparse index names trees, which are in the clone's objects or in a folder its alternates file names.
            # They are read through links with names of the replay's own, so the private alternates file holds no
            # path of the caller's, and it lists only the folders that exist: git reports an entry that names no
            # folder on standard error.
            (meta / "objects" / "info" / "alternates").write_text(
                "".join(f"../{name}\n" for name in borrowed(index.parent / "objects", meta)))
            listing = ["git", "-c", "advice.sparseIndexExpanded=false", "-C", str(clone), "ls-files", "-z"]
            listed = subprocess.run(listing, stdin=subprocess.DEVNULL, capture_output=True,
                                    env=trusted(meta, clone, "index"))
    except OSError as error:
        raise unreadable(error.strerror or type(error).__name__) from None
    if listed.returncode:
        raise unreadable(f"git ls-files exited {listed.returncode}")
    if listed.stderr:  # the rule --help's exit paragraph gives for a listing that exits 0
        raise unreadable("git ls-files reported an error")
    paths = [Path(os.fsdecode(path)) for path in listed.stdout.split(b"\0") if path]
    # Each path must name a file or link in the clone itself: not under .git/, and not reached through a link
    # or as a folder, which a forced add would take whole, ignored files and all. os.path answers False where the
    # name cannot be looked up, too long for one, which Path raises for before Python 3.14.
    return [os.fsencode(path) for path in paths if ".." not in path.parts and path.parts[0] != ".git"
            and not any(os.path.islink(clone / Path(*path.parts[:end])) for end in range(1, len(path.parts)))
            and (os.path.islink(clone / path) or os.path.isfile(clone / path))]


def shared_index(data: bytes) -> str | None:
    """The hex name of the shared index that the last `link` extension of the index bytes `data` names, as git reads
    it; None when there is none. The entries are stepped over as git's single-threaded read steps over them, in
    versions 2 to 4 with 20-byte object names, the size of the private folder's. Where git cannot read the bytes, any
    answer does: the listing fails."""
    end = len(data) - 20  # the checksum
    if end < 12 or data[:4] != b"DIRC" or not 2 <= int.from_bytes(data[4:8]) <= 4:
        return None
    version, at, previous_length = int.from_bytes(data[4:8]), 12, None
    try:
        for _ in range(int.from_bytes(data[8:12])):
            flags = int.from_bytes(data[at + 60:at + 62])
            name_at = at + 62 + (2 if flags & 0x4000 else 0)  # the extended flag adds two bytes of flags
            length, copied = flags & 0xFFF, 0
            if version == 4:  # a varint of bytes to strip from the previous name, then the rest of this one
                strip, name_at = data[name_at] & 127, name_at + 1
                while data[name_at - 1] & 128:
                    strip, name_at = ((strip + 1) << 7) + (data[name_at] & 127), name_at + 1
                if previous_length is not None:  # the first entry has no name before it, and git ignores its strip
                    copied = previous_length - strip
            if length == 0xFFF:  # too long for the flags: the name runs to its NUL
                length = data.index(b"\0", name_at) - name_at + copied
            at = name_at + length + 1 - copied if version == 4 else at + ((name_at - at + length + 8) & ~7)
            if copied < 0 or at > end:
                return None
            previous_length = length
    except (IndexError, ValueError):  # the bytes end inside an entry
        return None
    base = None
    while at + 8 <= end:  # each link extension git reads replaces the base the one before it named
        size = int.from_bytes(data[at + 4:at + 8])
        if data[at:at + 4] == b"link":
            base = data[at + 8:at + 28].hex()
        at += 8 + size
    return base


def borrowed(objects: Path, meta: Path) -> list[str]:
    """Link into `meta` the clone's objects folder, less its info/ folder, and each folder its alternates file names
    that exists; the links' names. The objects folder is linked by the names git reads in it, not by listing it,
    which needs no read permission and finds the info/ folder as git does on a file system that ignores case."""
    mirror = meta / "clone-objects"
    mirror.mkdir()
    for name in ("pack", *(f"{number:02x}" for number in range(256))):
        (mirror / name).symlink_to(objects / name)
    names = ["clone-objects"]
    try:
        lines = (objects / "info" / "alternates").read_bytes().split(b"\n")
    except FileNotFoundError:
        lines = []
    for line in lines:  # git's format: one folder a line, relative to the objects folder; # starts a comment
        if line and not line.startswith((b"#", b'"')) and (objects / os.fsdecode(line)).is_dir():
            names.append(f"alternate-{len(names)}")
            (meta / names[-1]).symlink_to(objects / os.fsdecode(line))
    return names


def snapshot(store: Path, clone: Path, base: str) -> str:
    """Write the clone's working tree, as it stands, into the version's repo as a tree."""
    env = trusted(store, clone)
    git(clone, "read-tree", base, env=env)
    git(clone, "add", "-A", env=env)
    paths = tracked(store, clone)
    if paths:
        (store / "replay-tracked").write_bytes(b"\0".join(paths))
        git(clone, "add", "-f", f"--pathspec-from-file={store / 'replay-tracked'}", "--pathspec-file-nul", env=env)
        (store / "replay-tracked").unlink()
    return git(clone, "write-tree", env=env)


def remove(made: list[Path]) -> None:
    for path in made:
        shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def signals_held():
    """SIGINT and SIGTERM wait until the block ends."""
    held = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, held)


class SetupGroup:
    """The process group for what setup starts, made for one replay and held by a keeper that only waits, so the group
    outlives setup's shell. The invariant: `stop()` runs on every way out of the try that made the group, and ends
    each process still in it; the replay's handlers of SIGINT and SIGTERM, from `stopping()`, stop the group before
    they raise, so an exception a signal raises, even just before a call of `stop()`, leaves no process of it running.
    A process that starts its own group or session is not in it."""

    def __init__(self) -> None:
        self.keeper: subprocess.Popen | None = None

    def run(self, command: str, cwd: Path) -> int:
        """Run `command` with sh in the group, which this makes first; the command's exit code."""
        with signals_held():  # a signal that comes now waits until the keeper is held, where stop() reaches it
            self.keeper = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                                           stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, process_group=0)
        return subprocess.Popen(command, shell=True, cwd=cwd, stdin=subprocess.DEVNULL,
                                process_group=self.keeper.pid).wait()

    def stop(self) -> None:
        """Kill what is left in the group and reap the keeper. A call after one that finished does nothing."""
        with signals_held():
            keeper = self.keeper
            if keeper is None:
                return
            try:  # the keeper is not reaped yet, so the group's id is still its own
                os.killpg(keeper.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.keeper = None  # after the signal; the group is no one's from here
            keeper.wait()
            keeper.stdin.close()

    def stopping(self, handler: Callable[[int, object], None]) -> Callable[[int, object], None]:
        """The signal handler `handler`, run once the group is stopped."""
        def stop_first(number: int, frame: object) -> None:
            self.stop()
            handler(number, frame)
        return stop_first


def record(state: Path, version: dict) -> None:
    path = state / "versions.jsonl"
    with open(state / "versions.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = [text for text in (path.read_text().splitlines() if path.is_file() else [])
                if text.strip() and [json.loads(text).get(key) for key in ("label", "ticket", "version")]
                != [version["label"], version["ticket"], version["version"]]]
        scan.write_private(path, "".join(text + "\n" for text in [*kept, json.dumps(version)]))


def replay(label: str, ticket: int, group: SetupGroup) -> int:
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
        try:
            if store.exists():
                raise ReplayError(f"{store} is already in place. Remove it and {clone} to replay the ticket again.")
            made.append(store)
            cut(listed["repo"], label, found, clone, store)
            setup = listed.get("setup")
            if setup:
                code = group.run(setup, clone)
                if code:
                    raise ReplayError(f"the setup command exited {code}; no session started.")
            before = snapshot(store, clone, found["base_commit"])
            prompt = f"{found['title']}\n\n{found['body']}"
            status = subprocess.run(command(clone, found["model"], session), cwd=clone, input=prompt, text=True,
                                    env=environment()).returncode
        finally:  # after the session, or on any way out before it ends: before the working tree is committed
            group.stop()
    except BaseException:
        group.stop()  # finishes a stop that an exception cut short
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
    warnings = io.StringIO()  # what the scan and the row writer say stays unsaid when the row cannot be written
    with contextlib.redirect_stderr(warnings):
        try:  # nothing the log holds may stop the record
            row = scan.scan(session, log)
            skills = row["skills"]
            not_direct = skills is None or any(skill.split(":")[-1] in MARKED for skill in skills)
        except (Exception, SystemExit) as failure:  # scan exits on a line that is not JSON
            print(f"replay: the session's log could not be scanned ({failure}); its row is left blank.",
                  file=sys.stderr)
            row, skills, not_direct = scan.scan(session, Path()), None, True  # a path that is no file: blanks
    version = {"label": label, "ticket": ticket, "version": VERSION, "commit": commit,
               "repo": str(store.relative_to(state)), "base_commit": found["base_commit"],
               "clone": str(clone.relative_to(state)), "exit_status": status, "session": session, "skills": skills,
               "not_direct": not_direct}
    record(state, version)
    try:
        with contextlib.redirect_stderr(warnings):
            scan.write_row(row)
    except Exception as error:  # a full disk, a lock that is a folder, a row json cannot write
        raise ReplayError(f"{label}-{ticket} {VERSION} is recorded at {commit} without its row "
                          f"({getattr(error, 'strerror', None) or type(error).__name__}). Write the row with: "
                          f"python3 scripts/scan.py {session}") from None
    sys.stderr.write(warnings.getvalue())
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
    group = SetupGroup()
    signal.signal(signal.SIGTERM, group.stopping(draw.terminated))
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:  # not where the caller has Ctrl-C ignored
        signal.signal(signal.SIGINT, group.stopping(signal.default_int_handler))
    try:
        return replay(argv[0], int(argv[1]), group)
    except (ReplayError, draw.DrawError) as error:
        print(f"replay: {error}", file=sys.stderr)
        return 1
    except draw.Terminated:
        print("replay: stopped by SIGTERM.", file=sys.stderr)
        return 128 + signal.SIGTERM


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
