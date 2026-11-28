"""deliver.py install [--remove] <harness>: set deliver up on a harness other than Claude Code, or take it off.

`install` copies each role file (the reader and the two reviewers) from `harness/<harness>/` in the
skill to the harness's agents folder and merges the guard's registration into the harness's user hook
file, leaving every other entry alone (spec #457, "Install"; spec #479). On Cursor the role files go
into the checkout's `.cursor/agents/`, with one line each in the shared git directory's `info/exclude`,
so it is run once per checkout. A second run changes nothing and says so. `--remove` takes out
deliver's guard and deletes each role file that still matches the skill's copy. From the ledger
`install` keeps in the machine directory, a file it finds as `install` left it gets back the bytes it
held before, or is deleted if `install` made it; a file the owner changed since keeps those changes,
a folder `install` made is deleted if nothing else is in it, and the ledger goes once nothing is
installed. A role file the owner edited stays, and so does its exclude line. Claude Code refuses, as
the plugin supplies both.

Each thing `install` writes is an item with a state (`ok`, `missing` or `differs`), an `apply` and
an `undo`. `checks_install` reads the same items, so preflight stops on the state `install` fixes.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import checks_harness
import core

HERE = Path(__file__).resolve().parent
HARNESS_DIR = HERE.parent / "harness"
GUARD = HERE / "guard.py"
# scripts/gen_roles.py writes this slot into each hook file; install puts the guard's path in it.
GUARD_SLOT = "@GUARD@"
# The text in the registered command that marks an entry as deliver's.
MARKER = "deliver_guard="
PLUGIN_LINE = "claude plugin install deliver@relentless-data-skills"
TRUST_STEP = "Codex runs no hook you have not trusted: start codex, type /hooks, trust deliver's guard, then quit."
# Per harness, named as checks_harness names it: its folder in `harness/` (named as its adapter is), the role files'
# folder under HOME (None: the checkout's `.cursor/agents/`) and the user hook file (#189).
TARGETS = {
    "cortex-code": ("cortex", ".snowflake/cortex/agents", ".snowflake/cortex/hooks.json"),
    "codex": ("codex", ".codex/agents", ".codex/hooks.json"),
    "cursor": ("cursor", None, ".cursor/hooks.json"),
    "antigravity": ("antigravity", ".gemini/config/agents", ".gemini/config/hooks.json"),
}
CURSOR_AGENTS = Path(".cursor/agents")


def detect() -> str | None:
    """The harness this process runs in, or None in a plain shell.

    `checks_harness.detect` names a plain shell Claude Code too, so `CLAUDECODE` tells them apart here.
    """
    harness = checks_harness.detect()
    if harness == checks_harness.CLAUDE_CODE and not os.environ.get("CLAUDECODE"):
        return None
    return harness


def _make_parents(path: Path) -> list[str]:
    """Make the folders `path` needs, returning the ones that did not exist."""
    missing = [folder for folder in (path.parent, *path.parent.parents) if not folder.exists()]
    for folder in reversed(missing):
        folder.mkdir()
    return [str(folder) for folder in reversed(missing)]


class Ledger:
    """What `install` created and what each file it changed held before, so `--remove` undoes only that.

    It lives in the machine directory as `install-ledger.json`: the folders `install` made, each
    file's earlier bytes (None for a file it made), the keys it added to each hook file, and the
    folders it made for itself, which go with it once it records nothing. Without it, `--remove`
    still takes out what it can tell is deliver's.
    """

    PATH = "install-ledger.json"

    def __init__(self):
        self.path = core.state_dir() / self.PATH
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        self.dirs: list[str] = data.get("dirs", [])
        self.files: dict[str, str | None] = data.get("files", {})
        self.keys: dict[str, list[list[str]]] = data.get("keys", {})
        self.own: list[str] = data.get("own", [])
        self.changed = False

    def save(self) -> None:
        if not self.changed:
            return
        if self.files or self.keys:
            self.own += _make_parents(self.path)
            self.path.write_text(json.dumps({"dirs": self.dirs, "files": self.files, "keys": self.keys,
                                             "own": self.own}, indent=2) + "\n", encoding="utf-8")
            return
        # Nothing is installed: the ledger goes, with the folders it made for itself.
        self.path.unlink(missing_ok=True)
        for folder in map(Path, sorted(self.own, key=len, reverse=True)):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        self.own, self.dirs = [], []

    def before_write(self, path: Path) -> None:
        """Note the folders `path` needs that do not exist, make them, and note what `path` holds now."""
        self.dirs += _make_parents(path)
        if str(path) not in self.files:
            self.files[str(path)] = path.read_bytes().decode("latin-1") if path.is_file() else None
        self.changed = True

    def original(self, path: Path) -> bytes | None:
        text = self.files.get(str(path))
        return None if text is None else text.encode("latin-1")

    def restore(self, path: Path) -> None:
        """Put back what `path` held before `install`, deleting it and the folders `install` made if it held nothing."""
        before = self.original(path)
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        self.forget(path)
        folder = path.parent
        while str(folder) in self.dirs and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            self.dirs.remove(str(folder))
            folder = folder.parent

    def forget(self, path: Path) -> None:
        self.files.pop(str(path), None)
        self.keys.pop(str(path), None)
        self.changed = True


class File:
    """A file copied whole from the skill."""

    def __init__(self, path: Path, data: bytes):
        self.path, self.data = path, data

    def state(self) -> str:
        if not self.path.is_file():
            return "missing"
        return "ok" if self.path.read_bytes() == self.data else "differs"

    def apply(self, ledger: Ledger) -> str:
        ledger.before_write(self.path)
        self.path.write_bytes(self.data)
        return f"wrote {self.path}"

    def undo(self, ledger: Ledger) -> str | None:
        state = self.state()
        if state != "ok":
            if str(self.path) in ledger.files:
                ledger.forget(self.path)
            return None if state == "missing" else f"kept {self.path}: it differs from deliver's copy"
        if str(self.path) in ledger.files:
            ledger.restore(self.path)
        else:
            self.path.unlink()
        return f"removed {self.path}"


class BadHookFile(Exception):
    pass


def _ours(entry: object) -> bool:
    return MARKER in json.dumps(entry)


def _parse(text: bytes | str | None) -> dict:
    """A hook file's object; a missing or blank file is an empty one."""
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BadHookFile(str(e)) from None
    if not isinstance(data, dict):
        raise BadHookFile("it does not hold a JSON object")
    return data


class HookEntry:
    """Deliver's one entry in a list inside a JSON hook file, with the scalars its form needs.

    The registration is a fragment of the hook file: nested objects down to one list holding the
    entry, with scalars beside them (Cursor's `version`).
    """

    def __init__(self, path: Path, fragment: dict):
        self.path = path
        self.scalars = {k: v for k, v in fragment.items() if not isinstance(v, dict)}
        self.keys, node = [], fragment
        while isinstance(node, dict):
            key = next(k for k, v in node.items() if isinstance(v, (dict, list)))
            self.keys.append(key)
            node = node[key]
        self.entry = node[0]

    def _load(self) -> dict | None:
        return _parse(self.path.read_bytes()) if self.path.is_file() else None

    def _walk(self, data: dict, added: list | None = None) -> list | None:
        """The list deliver's entry goes in, or None when it is absent. With `added`, make what is
        missing and append each key path it made to `added`."""
        node = data
        for depth, key in enumerate(self.keys):
            last = depth == len(self.keys) - 1
            if key not in node:
                if added is None:
                    return None
                node[key] = [] if last else {}
                added.append(self.keys[:depth + 1])
            node = node[key]
            if not isinstance(node, list if last else dict):
                kind = "a list" if last else "an object"
                raise BadHookFile(f"{'.'.join(self.keys[:depth + 1])} is not {kind}")
        return node

    def state(self) -> str:
        """`ok`, `missing` or `differs`; an unreadable file differs."""
        try:
            data = self._load()
            entries = [] if data is None else [e for e in (self._walk(data) or []) if _ours(e)]
        except BadHookFile:
            return "differs"
        if not entries:
            return "missing"
        return "ok" if entries == [self.entry] else "differs"

    def apply(self, ledger: Ledger) -> str:
        data = self._load() or {}
        added = []
        for key, value in self.scalars.items():
            if key not in data:
                data[key] = value
                added.append([key])
        entries = self._walk(data, added)
        entries[:] = [e for e in entries if not _ours(e)] + [self.entry]
        ledger.before_write(self.path)
        known = ledger.keys.setdefault(str(self.path), [])
        known += [key for key in added if key not in known]
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return f"added deliver's guard to {self.path}"

    def undo(self, ledger: Ledger) -> str | None:
        data = self._load()
        entries = None if data is None else self._walk(data)
        if not entries or not any(_ours(e) for e in entries):
            return None
        entries[:] = [e for e in entries if not _ours(e)]
        recorded = str(self.path) in ledger.files
        # Take out what apply added, deepest first: a scalar, or a container that is empty again.
        # With no record, every container on deliver's path that is empty now.
        added = ledger.keys.get(str(self.path), []) if recorded else [self.keys[:n] for n in range(1, len(self.keys) + 1)]
        for key_path in sorted(added, key=len, reverse=True):
            parent = data
            for key in key_path[:-1]:
                parent = parent.get(key) if isinstance(parent, dict) else None
            value = parent.get(key_path[-1], None) if isinstance(parent, dict) else None
            if isinstance(parent, dict) and key_path[-1] in parent and not (isinstance(value, (dict, list)) and value):
                del parent[key_path[-1]]
        if recorded and data == _parse(ledger.original(self.path)):
            ledger.restore(self.path)
        else:
            self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            ledger.forget(self.path)
        return f"took deliver's guard out of {self.path}"


class ExcludeLine:
    """One line in a git `info/exclude` file, for a role file in each of the repo's checkouts.

    `ours` is every line `install` writes to that file, so the last one out can give back its earlier bytes.
    """

    def __init__(self, path: Path, line: str, readers: list[Path], ours: list[str]):
        self.path, self.line, self.readers, self.ours = path, line, readers, ours

    def _lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines() if self.path.is_file() else []

    def state(self) -> str:
        return "ok" if self.line in self._lines() else "missing"

    def apply(self, ledger: Ledger) -> str:
        text = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        ledger.before_write(self.path)
        self.path.write_text(text + ("\n" if text and not text.endswith("\n") else "") + self.line + "\n",
                             encoding="utf-8")
        return f"added {self.line} to {self.path}"

    def undo(self, ledger: Ledger) -> str | None:
        lines = self._lines()
        if self.line not in lines:
            return None
        left = [reader for reader in self.readers if reader.exists()]
        if left:
            return f"kept {self.line} in {self.path}: {', '.join(map(str, left))} {'is' if len(left) == 1 else 'are'} still there"
        kept = [line for line in lines if line != self.line]
        before = ledger.original(self.path)
        if kept == (before or b"").decode("utf-8").splitlines():
            ledger.restore(self.path)
        else:
            self.path.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
            if not set(kept) & set(self.ours):
                ledger.forget(self.path)
        return f"took {self.line} out of {self.path}"


def items(harness: str, run: core.Run | None) -> list:
    """What `install` writes on `harness`, in the order it writes it."""
    home = Path.home()
    name, folder, hooks = TARGETS[harness]
    source = HARNESS_DIR / name
    readers = sorted(p for p in source.iterdir() if p.name != "hooks.json")
    if folder is None:
        if run is None:
            raise core.Refused("install.not-a-checkout", harness=harness)
        found = [File(run.checkout / CURSOR_AGENTS / p.name, p.read_bytes()) for p in readers]
        checkouts = _checkouts(run)
        lines = [f"/{CURSOR_AGENTS / p.name}" for p in readers]
        found += [ExcludeLine(run.common_dir / "info" / "exclude", line,
                              [checkout / CURSOR_AGENTS / p.name for checkout in checkouts], lines)
                  for p, line in zip(readers, lines)]
    else:
        found = [File(home / folder / p.name, p.read_bytes()) for p in readers]
    text = (source / "hooks.json").read_text(encoding="utf-8")
    fragment = json.loads(text.replace(json.dumps(GUARD_SLOT)[1:-1], json.dumps(shlex.quote(str(GUARD)))[1:-1]))
    return [*found, HookEntry(home / hooks, fragment)]


def _checkouts(run: core.Run) -> list[Path]:
    """Every checkout of the repo, as the exclude line covers each of them."""
    proc = subprocess.run(["git", "-C", str(run.checkout), "worktree", "list", "--porcelain"],
                          capture_output=True, text=True)
    found = [Path(line[len("worktree "):]) for line in proc.stdout.splitlines() if line.startswith("worktree ")]
    return found if proc.returncode == 0 and found else [run.checkout]


def check_harness(harness: str) -> None:
    """Refuse Claude Code, and a harness other than the one this session runs in."""
    if harness == "claude-code":
        raise core.Refused("install.claude-code", PLUGIN_LINE)
    detected = detect()
    if detected and detected != harness:
        # On Claude Code, `install claude-code` is no fix, so the refusal names no command.
        raise core.Refused("install.wrong-harness", None if detected == "claude-code"
                           else f"deliver.py install {detected}", harness=harness, detected=detected)


def main(args: list[str], run: core.Run | None) -> None:
    remove = "--remove" in args
    rest = [a for a in args if a != "--remove"]
    if len(rest) != 1 or rest[0] not in (*TARGETS, "claude-code"):
        raise core.UsageError(f"install takes one of {', '.join((*TARGETS, 'claude-code'))}, and --remove to undo it")
    harness = rest[0]
    check_harness(harness)
    todo = items(harness, run)
    command = f"deliver.py install {'--remove ' if remove else ''}{harness}"
    ledger = Ledger()
    done = []
    # On remove, each exclude line comes after the role files it covers, so it sees whether they stayed.
    for item in sorted(reversed(todo), key=lambda item: isinstance(item, ExcludeLine)) if remove else todo:
        try:
            if remove:
                done.append((item, item.undo(ledger)))
            elif item.state() != "ok":
                done.append((item, item.apply(ledger)))
        except BadHookFile as e:
            raise core.Refused("install.bad-hook-file", f"fix {item.path}, then run {command}",
                               path=str(item.path), error=str(e)) from None
        finally:
            ledger.save()
    changed = [(item, line) for item, line in done if line]
    if remove:
        print("\n".join(line for _, line in changed) if changed
              else f"nothing to remove: deliver is not installed on {harness}.")
        return
    if not changed:
        print(f"nothing changed: deliver is already installed on {harness}.")
        return
    print("\n".join(line for _, line in changed))
    if harness == "codex" and any(isinstance(item, HookEntry) for item, _ in changed):
        print(TRUST_STEP)
