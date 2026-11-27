"""deps: the installed upstream skills against the upstream contract (#177; #231 rules 41 to 43; #256).

The contract is `upstream.toml` at the plugin root: one table per upstream dependency, each with
`takes`, `supplies` and `folder_hash`. `deliver.py deps` finds each one installed, works out its
folder hash and prints one line per difference: `<skill>: not installed`, or `<skill>: folder
hash <installed> differs from the contract's <recorded>`. With no difference it prints
`Upstream skills match the contract.` It writes nothing, and refuses only when a skill in
`REQUIRED` is missing.

Preflight runs two checks of this module on a run, after git and `gh`: `check_required_skills`
stops when a skill in `REQUIRED` is missing, and `check_skill_hashes` warns, in one line, about
each of them whose hash differs. The planning skills are compared by `deps` only (#177 rule 17).
`ready` reads `review_skill_hashes` for the measurement block's `review skills` line.

A skill is found in the first of these folders that holds its `SKILL.md`, where `<config>` is
`$CLAUDE_CONFIG_DIR` or `~/.claude`:

1. `<config>/skills/<name>`, the user's skills folder;
2. `<checkout>/.claude/skills/<name>`, the project's, when run inside a git working tree;
3. `<installPath>/skills/<name>` for each plugin listed in `<config>/plugins/installed_plugins.json`,
   in the file's order.

The folder hash is the git tree id of the folder, the value the skills installer records as
`skillFolderHash` and upstream's own tree holds: SHA-1 over the files' bytes, names and modes
(executable or not, symbolic link), with empty folders and `.git` left out. It is the same on
every machine and whatever order the files were written in.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tomllib
from pathlib import Path

import core

CONTRACT = Path(__file__).resolve().parent.parent / "upstream.toml"
REQUIRED = ("code-review", "ponytail-review", "pr")  # read during a run (#177 rule 9; #231 rule 42)
REVIEW = ("code-review", "ponytail-review")  # their hashes go into the measurement block (#177 rule 16)
MATCH = "Upstream skills match the contract."


def load_contract() -> dict[str, dict]:
    return tomllib.loads(CONTRACT.read_text(encoding="utf-8"))


def find(name: str, checkout: Path | None) -> Path | None:
    """The installed folder of skill `name`, or None when it is installed nowhere."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    roots = [config, *([checkout / ".claude"] if checkout else []), *_plugin_folders(config)]
    for root in roots:
        folder = root / "skills" / name
        if (folder / "SKILL.md").is_file():
            return folder
    return None


def _plugin_folders(config: Path) -> list[Path]:
    try:
        plugins = json.loads((config / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))["plugins"]
        return [Path(install["installPath"]) for installs in plugins.values() for install in installs]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def folder_hash(folder: Path) -> str:
    """The git tree id of `folder`, as `git add -A` then `git write-tree` would give it."""
    return _tree(os.fsencode(folder)) or _object(b"tree", b"")


def _tree(folder: bytes) -> str | None:
    entries = []
    with os.scandir(folder) as found:
        for entry in found:
            if entry.name == b".git":
                continue
            if entry.is_symlink():
                mode, key, sha = b"120000", entry.name, _object(b"blob", os.readlink(entry.path))
            elif entry.is_dir():
                mode, key, sha = b"40000", entry.name + b"/", _tree(entry.path)
                if sha is None:
                    continue
            else:
                executable = entry.stat().st_mode & stat.S_IXUSR
                mode, key = (b"100755" if executable else b"100644"), entry.name
                with open(entry.path, "rb") as f:
                    sha = _object(b"blob", f.read())
            entries.append((key, mode + b" " + entry.name + b"\0" + bytes.fromhex(sha)))
    if not entries:
        return None
    return _object(b"tree", b"".join(line for _, line in sorted(entries)))


def _object(kind: bytes, body: bytes) -> str:
    return hashlib.sha1(kind + b" %d\0" % len(body) + body).hexdigest()


def difference(name: str, recorded: str, folder: Path | None) -> str | None:
    """The one line for a skill that differs from its contract entry, or None."""
    if folder is None:
        return f"{name}: not installed"
    installed = folder_hash(folder)
    return None if installed == recorded else f"{name}: folder hash {installed} differs from the contract's {recorded}"


def missing_required(checkout: Path | None) -> list[str]:
    return [name for name in REQUIRED if find(name, checkout) is None]


def review_skill_hashes(checkout: Path | None) -> dict[str, str | None]:
    """Each review skill's installed folder hash, None where it is not installed, for `ready`."""
    return {name: (folder_hash(folder) if (folder := find(name, checkout)) else None) for name in REVIEW}


def check_required_skills(ctx):
    """Preflight: stop when code-review, ponytail-review or pr is not installed."""
    # preflight imports this module, so the result types come from the module that made `ctx`:
    # an import of preflight here would be circular, and a test loads it under another name.
    preflight = sys.modules[type(ctx).__module__]
    if missing := missing_required(ctx.run.checkout):
        skills = ", ".join(missing)
        return preflight.Stop("preflight.missing-skill", f"install {skills}, then run {preflight.RERUN}", {"skills": skills})
    return None


def check_skill_hashes(ctx):
    """Preflight: one warning line for the required skills whose folder hash differs from the contract."""
    preflight = sys.modules[type(ctx).__module__]
    contract = load_contract()
    lines = [line for name in REQUIRED
             if (line := difference(name, contract[name]["folder_hash"], find(name, ctx.run.checkout)))]
    return preflight.Warn("; ".join(lines)) if lines else None


def main(args: list[str], run: core.Run | None) -> None:
    if args:
        raise core.UsageError(f"deps takes no arguments, got: {' '.join(args)}")
    checkout = run.checkout if run else None
    if missing := missing_required(checkout):
        skills = ", ".join(missing)
        raise core.Refused("deps.missing-skill", f"install {skills}, then run deliver.py deps", skills=skills)
    contract = load_contract()
    lines = [line for name, entry in contract.items()
             if (line := difference(name, entry["folder_hash"], find(name, checkout)))]
    print("\n".join(lines) or MATCH)
