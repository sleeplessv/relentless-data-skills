"""deliver.py install [--remove] <harness>: set deliver up on a harness other than Claude Code, or take it off.

`install` copies the reader's file from `harness/<harness>/` in the skill to the harness's agents
folder and merges the guard's registration into the harness's user hook file, leaving every other
entry alone (spec #457, "Install"). On Cursor the reader's file goes into the checkout's
`.cursor/agents/`, with one line in the shared git directory's `info/exclude`, so it is run once per
checkout. A second run changes nothing and says so. `--remove` takes out exactly what `install`
writes, and removes folders it leaves empty. Claude Code refuses, as the plugin supplies both.

Each thing `install` writes is an item with a state (`ok`, `missing` or `differs`), an `apply` and
an `undo`. `checks_install` reads the same items, so preflight stops on the state `install` fixes.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

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
# Spec #457, "Harness detection": the first variable set names the harness.
DETECTION = (
    ("CORTEX_SESSION_ID", "cortex"),
    ("CODEX_THREAD_ID", "codex"),
    ("CURSOR_AGENT", "cursor"),
    ("ANTIGRAVITY_AGENT", "antigravity"),
    ("CLAUDECODE", "claude-code"),
)
# Per harness: the reader's folder under HOME (None: the checkout's `.cursor/agents/`) and the user hook file (#189).
TARGETS = {
    "cortex": (".snowflake/cortex/agents", ".snowflake/cortex/hooks.json"),
    "codex": (".codex/agents", ".codex/hooks.json"),
    "cursor": (None, ".cursor/hooks.json"),
    "antigravity": (".gemini/config/agents", ".gemini/config/hooks.json"),
}
CURSOR_AGENTS = Path(".cursor/agents")


def detect() -> str | None:
    """The harness this process runs in, or None in a plain shell."""
    return next((harness for var, harness in DETECTION if os.environ.get(var)), None)


def _prune(folder: Path, stop: Path) -> None:
    """Remove `folder` and its parents while they are empty, up to but not including `stop`."""
    while folder != stop and stop in folder.parents and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


class File:
    """A file copied whole from the skill."""

    def __init__(self, path: Path, data: bytes, stop: Path):
        self.path, self.data, self.stop = path, data, stop

    def state(self) -> str:
        if not self.path.is_file():
            return "missing"
        return "ok" if self.path.read_bytes() == self.data else "differs"

    def apply(self) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.data)
        return f"wrote {self.path}"

    def undo(self) -> str | None:
        if not self.path.is_file():
            return None
        self.path.unlink()
        _prune(self.path.parent, self.stop)
        return f"removed {self.path}"


class BadHookFile(Exception):
    pass


def _ours(entry: object) -> bool:
    return MARKER in json.dumps(entry)


class HookEntry:
    """Deliver's one entry in a list inside a JSON hook file, with the scalars its form needs.

    The registration is a fragment of the hook file: nested objects down to one list holding the
    entry, with scalars beside them (Cursor's `version`).
    """

    def __init__(self, path: Path, fragment: dict, stop: Path):
        self.path, self.stop = path, stop
        self.scalars = {k: v for k, v in fragment.items() if not isinstance(v, dict)}
        self.keys, node = [], fragment
        while isinstance(node, dict):
            key = next(k for k, v in node.items() if isinstance(v, (dict, list)))
            self.keys.append(key)
            node = node[key]
        self.entry = node[0]

    def _load(self) -> dict | None:
        if not self.path.is_file():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise BadHookFile(str(e)) from None
        if not isinstance(data, dict):
            raise BadHookFile("it does not hold a JSON object")
        return data

    def _walk(self, data: dict, make: bool) -> list | None:
        """The list deliver's entry goes in, made when `make`, or None when it is absent."""
        node = data
        for depth, key in enumerate(self.keys):
            last = depth == len(self.keys) - 1
            if key not in node:
                if not make:
                    return None
                node[key] = [] if last else {}
            node = node[key]
            if not isinstance(node, list if last else dict):
                kind = "a list" if last else "an object"
                raise BadHookFile(f"{'.'.join(self.keys[:depth + 1])} is not {kind}")
        return node

    def state(self) -> str:
        """`ok`, `missing` or `differs`; an unreadable file differs."""
        try:
            data = self._load()
            entries = [] if data is None else [e for e in (self._walk(data, make=False) or []) if _ours(e)]
        except BadHookFile:
            return "differs"
        if not entries:
            return "missing"
        return "ok" if entries == [self.entry] else "differs"

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def apply(self) -> str:
        data = self._load() or {}
        for key, value in self.scalars.items():
            data.setdefault(key, value)
        entries = self._walk(data, make=True)
        entries[:] = [e for e in entries if not _ours(e)] + [self.entry]
        self._save(data)
        return f"added deliver's guard to {self.path}"

    def undo(self) -> str | None:
        data = self._load()
        entries = None if data is None else self._walk(data, make=False)
        if not entries or not any(_ours(e) for e in entries):
            return None
        entries[:] = [e for e in entries if not _ours(e)]
        # Take out each container left empty, from the list up.
        for depth in range(len(self.keys), 0, -1):
            parent = data
            for key in self.keys[:depth - 1]:
                parent = parent[key]
            if parent[self.keys[depth - 1]]:
                break
            del parent[self.keys[depth - 1]]
        if all(key in self.scalars and data[key] == self.scalars[key] for key in data):
            self.path.unlink()
            _prune(self.path.parent, self.stop)
        else:
            self._save(data)
        return f"took deliver's guard out of {self.path}"


class ExcludeLine:
    """One line in a git `info/exclude` file."""

    def __init__(self, path: Path, line: str, stop: Path):
        self.path, self.line, self.stop = path, line, stop

    def _lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines() if self.path.is_file() else []

    def state(self) -> str:
        return "ok" if self.line in self._lines() else "missing"

    def apply(self) -> str:
        text = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text + ("\n" if text and not text.endswith("\n") else "") + self.line + "\n",
                             encoding="utf-8")
        return f"added {self.line} to {self.path}"

    def undo(self) -> str | None:
        lines = self._lines()
        if self.line not in lines:
            return None
        kept = [line for line in lines if line != self.line]
        if kept:
            self.path.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
        else:
            self.path.unlink()
            _prune(self.path.parent, self.stop)
        return f"took {self.line} out of {self.path}"


def items(harness: str, run: core.Run | None) -> list:
    """What `install` writes on `harness`, in the order it writes it."""
    home = Path.home()
    folder, hooks = TARGETS[harness]
    source = HARNESS_DIR / harness
    readers = sorted(p for p in source.iterdir() if p.name != "hooks.json")
    if folder is None:
        if run is None:
            raise core.Refused("install.not-a-checkout", harness=harness)
        found = [File(run.checkout / CURSOR_AGENTS / p.name, p.read_bytes(), run.checkout) for p in readers]
        found += [ExcludeLine(run.common_dir / "info" / "exclude", f"/{CURSOR_AGENTS / p.name}", run.common_dir)
                  for p in readers]
    else:
        found = [File(home / folder / p.name, p.read_bytes(), home) for p in readers]
    text = (source / "hooks.json").read_text(encoding="utf-8")
    fragment = json.loads(text.replace(json.dumps(GUARD_SLOT)[1:-1], json.dumps(shlex.quote(str(GUARD)))[1:-1]))
    return [*found, HookEntry(home / hooks, fragment, home)]


def check_harness(harness: str) -> None:
    """Refuse Claude Code, and a harness other than the one this session runs in."""
    if harness == "claude-code":
        raise core.Refused("install.claude-code", PLUGIN_LINE)
    detected = detect()
    if detected and detected != harness:
        raise core.Refused("install.wrong-harness", PLUGIN_LINE if detected == "claude-code"
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
    done = []
    for item in reversed(todo) if remove else todo:
        try:
            if remove:
                done.append((item, item.undo()))
            elif item.state() != "ok":
                done.append((item, item.apply()))
        except BadHookFile as e:
            raise core.Refused("install.bad-hook-file", f"fix {item.path}, then run {command}",
                               path=str(item.path), error=str(e)) from None
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
