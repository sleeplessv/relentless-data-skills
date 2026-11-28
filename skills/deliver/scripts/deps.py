"""deps: the installed upstream skills against the upstream contract (#177; #231 rules 41 to 43; #256).

The contract is `upstream.toml` at the plugin root: one table per upstream dependency, each with
`takes`, `supplies` and `folder_hash`. `deliver.py deps` finds each one installed, works out its
folder hash and prints one line per difference: `<skill>: not installed`, or `<skill>: folder
hash <installed> differs from the contract's <recorded>`. With no difference it prints
`Upstream skills match the contract.` It saves no record, writes nothing to the machine
directory or the checkout, and refuses only when a skill in `REQUIRED` is missing.

Preflight runs two checks of this module: `check_required_skills` stops when a skill in
`REQUIRED` is missing, and `check_skill_hashes` warns, in one line, about each of them whose
hash differs. They are meant to run after the harness, git and `gh` checks, which later tickets
add before them in `preflight.CHECKS`. The planning skills are compared by `deps` only (#177
rule 17). `review_skill_hashes` is for `ready`, a later ticket, to fill the measurement block's
`review skills` line; nothing calls it yet.

Off Claude Code, a skill is found in the first folder of `checks_harness.skill_roots` that holds
it. On Claude Code, it is found in the first of these places that holds it, where `<config>` is
`$CLAUDE_CONFIG_DIR` or `~/.claude`:

1. `<config>/skills/<name>`, the user's skills folder;
2. `<checkout>/.claude/skills/<name>`, the project's, when run inside a git working tree;
3. each plugin in Claude Code's plugin registry, in the registry's order, that is installed for
   the user, by the organisation (`managed`), or for this checkout (a `project` or `local`
   install whose `projectPath` is the checkout or a folder in it). The registry is
   `installed_plugins.json` in `$CLAUDE_CODE_PLUGIN_CACHE_DIR`, or else in `<config>/plugins`
   (`<config>/cowork_plugins` when `CLAUDE_CODE_USE_COWORK_PLUGINS` is set). A plugin publishes
   skills from its `skills` folder and from each path its `.claude-plugin/plugin.json` or its
   marketplace entry lists under `skills`. Such a path is one skill when it holds `SKILL.md`,
   named by its front matter's `name` or else its folder name, as Claude Code names it;
   otherwise each folder in it that holds `SKILL.md` is a skill named by that folder.

The folder hash is the git tree id of the folder: SHA-1 over every file's bytes, name and mode
(executable or not, symbolic link), with empty folders and `.git` left out. It counts every
other file in the folder, also one a `.gitignore` names, so it equals `git add -A` then `git
write-tree` only on a folder that ignores nothing. That is the value the skills installer
records as `skillFolderHash` and upstream's own tree holds. It is the same on every machine and
whatever order the files were written in.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tomllib
from pathlib import Path

import checks_harness
import core

CONTRACT = Path(__file__).resolve().parent.parent / "upstream.toml"
REQUIRED = ("code-review", "ponytail-review", "pr")  # read during a run (#177 rule 9; #231 rule 42)
REVIEW = ("code-review", "ponytail-review")  # their hashes go into the measurement block (#177 rule 16)
MATCH = "Upstream skills match the contract."


def load_contract() -> dict[str, dict]:
    return tomllib.loads(CONTRACT.read_text(encoding="utf-8"))


def find(name: str, checkout: Path | None) -> Path | None:
    """The installed folder of skill `name` on this harness, or None when it is installed nowhere."""
    if (harness := checks_harness.detect()) != checks_harness.CLAUDE_CODE:
        return next((root / name for root in checks_harness.skill_roots(harness, checkout)
                     if (root / name / "SKILL.md").is_file()), None)
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    for root in (config, *([checkout / ".claude"] if checkout else [])):
        if (root / "skills" / name / "SKILL.md").is_file():
            return root / "skills" / name
    for plugin, path in _plugin_skill_paths(_registry_dir(config), checkout):
        if (path / "SKILL.md").is_file():
            if _skill_name(path, plugin) == name:
                return path
        elif (path / name / "SKILL.md").is_file():
            return path / name
    return None


def _registry_dir(config: Path) -> Path:
    if cache := os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR"):
        return Path(cache).expanduser()
    return config / ("cowork_plugins" if os.environ.get("CLAUDE_CODE_USE_COWORK_PLUGINS") else "plugins")


def _plugin_skill_paths(registry: Path, checkout: Path | None) -> list[tuple[str, Path]]:
    """Each plugin installed for this checkout, with each of its skills paths, in the registry's order.

    An unreadable registry is no plugins; an unreadable manifest or marketplace skips that plugin.
    """
    errors = (OSError, ValueError, KeyError, TypeError, AttributeError)
    try:
        plugins = _read_json(registry / "installed_plugins.json")["plugins"]
        installs = [(plugin_id, install) for plugin_id, entries in plugins.items() for install in entries]
    except errors:
        return []
    paths = []
    for plugin_id, install in installs:
        try:
            if not _applies(install, checkout):
                continue
            plugin, _, marketplace = plugin_id.partition("@")
            root = Path(install["installPath"])
            declared = _declared(_manifest(root)) + _declared(_marketplace_entry(registry, marketplace, plugin))
            paths += [(plugin, path) for path in (root / "skills", *(root / path for path in declared))]
        except errors:
            continue
    return paths


def _applies(install: dict, checkout: Path | None) -> bool:
    if install.get("scope") in ("user", "managed"):
        return True
    project = install.get("projectPath")
    if not project or checkout is None:
        return False
    project, checkout = Path(project).resolve(), checkout.resolve()
    return project == checkout or checkout in project.parents


def _manifest(root: Path) -> dict:
    path = root / ".claude-plugin" / "plugin.json"
    return _read_json(path) if path.is_file() else {}


def _marketplace_entry(registry: Path, marketplace: str, plugin: str) -> dict:
    known = registry / "known_marketplaces.json"
    location = (_read_json(known) if known.is_file() else {}).get(marketplace, {}).get("installLocation")
    path = Path(location) / ".claude-plugin" / "marketplace.json" if location else None
    if path is None or not path.is_file():
        return {}
    return next((entry for entry in _read_json(path).get("plugins", []) if entry.get("name") == plugin), {})


def _declared(manifest: dict) -> list[str]:
    skills = manifest.get("skills", [])
    return [skills] if isinstance(skills, str) else list(skills)


def _skill_name(folder: Path, plugin: str) -> str:
    """A skill's name as Claude Code reads it: the front matter's `name`, else the folder's name."""
    lines = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace").splitlines()
    if lines[:1] == ["---"]:
        for line in lines[1:]:
            if line == "---":
                break
            key, _, value = line.partition(":")
            if key.strip() == "name" and (value := value.strip().strip("'\"")):
                return value.removeprefix(f"{plugin}:") or folder.name
    return folder.name


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def folder_hash(folder: Path) -> str:
    """The git tree id of every file under `folder` but `.git`, whatever a `.gitignore` says."""
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
