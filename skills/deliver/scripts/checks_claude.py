"""Preflight's checks of Claude Code itself (#178 rules 38 to 40; spec #407 reading 8).

Each check is a function of preflight's `Context` that returns None, a `Warn` or a `Stop`, and
reads only Claude Code's own files and the session's environment. When a check cannot tell for
certain, it stops: a stop it should not have made costs the owner one look, and a pass it should
not have made lets the guards be bypassed. No stop becomes a warning.

What the checks read:

- Settings: user (`settings.json` in Claude Code's folder), project (`.claude/settings.json`
  in the checkout), local (`.claude/settings.local.json`) and managed (`MANAGED_SETTINGS` for
  this platform). A missing file has no settings. A file that is not a JSON object stops.
- Claude Code's folder: `$CLAUDE_CONFIG_DIR` as the environment gives it, else `~/.claude`.
- Enabled plugins: an `enabledPlugins` key whose value in the most specific settings file that
  sets it (managed over local over project over user) is true. Each one's hooks are in every
  install of it that `plugins/installed_plugins.json` lists for this checkout: `hooks/hooks.json`,
  and the hooks its manifest names, as files or inline. A plugin that is enabled but not
  installed has no hooks.
- Known hooks: `known_hooks` in `lists.toml`, through `settings.read_lists`. See `is_known`.

The environment variables, file names and setting keys the checks read are named below. Each
comment says whether the signal was seen on a real session and describes the layout read
inside its file. The tests' fixtures in `tests/deliver_claude_inputs/` record the seen ones.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

import settings

PLUGIN = "deliver"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
READER = "deliver-reader"
RERUN = "deliver.py preflight"
PLUGIN_KEY = f"{PLUGIN}@relentless-data-skills"

# Seen: Claude Code's folder is ~/.claude. Not yet seen: a session with CLAUDE_CONFIG_DIR set.
CONFIG_DIR_VAR = "CLAUDE_CONFIG_DIR"
# Not yet seen: no managed settings file was on the machine read.
MANAGED_SETTINGS = {
    "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    "linux": Path("/etc/claude-code/managed-settings.json"),
}
# Not yet seen: the key was in no settings file read.
HOOKS_OFF_KEY = "disableAllHooks"
# Seen: `hooks.PreToolUse` in user settings and in a plugin's hooks/hooks.json, a list of
# {"matcher", "hooks": [{"type": "command", "command"}]}; `enabledPlugins` in user settings, keyed
# `<plugin>@<marketplace>`, values true.
ENABLED_PLUGINS_KEY = "enabledPlugins"
# Seen: {"plugins": {"<plugin>@<marketplace>": [{"scope": "user", "installPath"}]}}. Not yet seen:
# an install of another scope, read here as applying only where its `projectPath` is the checkout.
INSTALLED_PLUGINS = Path("plugins") / "installed_plugins.json"
INSTALL_SCOPES = ("user", "managed")
PROJECT_SCOPES = ("project", "local")
# Not yet seen: a manifest's `hooks`, read as a path, a list of paths, or inline hooks.
MANIFESTS = (Path(".claude-plugin") / "plugin.json", Path("plugin.json"))
# Seen: the shell tool's name in the hook inputs of tests/deliver_guard_inputs/.
SHELL_TOOL = "Bash"
PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"
# Interpreters a known hook command may name before its script.
INTERPRETERS = ("python3", "python")
# Seen: the trust record is ~/.claude.json, `projects` keyed by absolute folder path, each with
# this boolean. Not yet seen: where it lives with CLAUDE_CONFIG_DIR set (read here inside that
# folder), and whether a trusted parent folder covers a child (read here as not: exact folder only).
TRUST_FILE = ".claude.json"
TRUST_KEY = "hasTrustDialogAccepted"
# Seen: CLAUDE_CODE_ENTRYPOINT=cli in an interactive session. Not yet seen: the print-mode value,
# read from the review of the installed package as sdk-cli.
ENTRYPOINT_VAR = "CLAUDE_CODE_ENTRYPOINT"
PRINT_ENTRYPOINT = "sdk-cli"
# Not yet seen: any variable of a remote or scheduled session. A remote session is read as
# CLAUDE_CODE_REMOTE set, a scheduled one as CLAUDE_CODE_HOST_SCHEDULED_RUN set (the review read
# that marker in the installed package). CLAUDE_CODE_SESSION_ATTENDED is not read: the review read
# it as 0 in an owner-started print-mode session.
BACKGROUND_VARS = ("CLAUDE_CODE_REMOTE", "CLAUDE_CODE_HOST_SCHEDULED_RUN")
# Seen unset in a real session, beside CLAUDE_EFFORT=medium, which does not count. Set to any
# value, the empty string included, it gives no line.
EFFORT_VAR = "CLAUDE_CODE_EFFORT_LEVEL"
EFFORT_WARNING = f"{EFFORT_VAR} is unset"


class Unreadable(Exception):
    """A file Claude Code reads cannot be read as what it should hold."""

    def __init__(self, path: Path, error: str):
        super().__init__(error)
        self.path = path
        self.error = error


def _result(ctx):
    # The result types come from the module that made `ctx`, as in check_guard.
    return sys.modules[type(ctx).__module__]


def _unreadable(ctx, e: Unreadable):
    return _result(ctx).Stop("preflight.claude-unreadable", f"fix {e.path}, then run {RERUN}",
                             {"path": str(e.path), "error": e.error})


def config_dir() -> Path:
    return Path(os.environ[CONFIG_DIR_VAR]) if os.environ.get(CONFIG_DIR_VAR) else Path.home() / ".claude"


def read_object(path: Path) -> dict | None:
    """A JSON object file, or None when it does not exist."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise Unreadable(path, str(e)) from None
    if not isinstance(data, dict):
        raise Unreadable(path, "its top level is not a JSON object")
    return data


def settings_files(checkout: Path) -> list[Path]:
    files = [config_dir() / "settings.json", checkout / ".claude" / "settings.json",
             checkout / ".claude" / "settings.local.json"]
    managed = MANAGED_SETTINGS.get(sys.platform)
    return files + [managed] if managed else files


def read_settings(checkout: Path) -> list[tuple[Path, dict]]:
    return [(path, data) for path in settings_files(checkout) if (data := read_object(path)) is not None]


def check_background(ctx):
    """Stop in a remote or scheduled session, which nobody can stop (rule 38)."""
    for var in BACKGROUND_VARS:
        if value := os.environ.get(var):
            return _result(ctx).Stop("preflight.background", f"start the run from an interactive Claude Code session in {ctx.run.checkout}",
                                     {"var": var, "value": value})
    return None


def check_trust(ctx):
    """Stop where Claude Code's trust record does not trust the checkout; print mode counts as trusted (rule 38)."""
    if os.environ.get(ENTRYPOINT_VAR) == PRINT_ENTRYPOINT:
        return None
    path = (Path(os.environ[CONFIG_DIR_VAR]) if os.environ.get(CONFIG_DIR_VAR) else Path.home()) / TRUST_FILE
    try:
        record = read_object(path) or {}
    except Unreadable as e:
        return _unreadable(ctx, e)
    projects = record.get("projects", {})
    if not isinstance(projects, dict):
        return _unreadable(ctx, Unreadable(path, "projects is not an object"))
    folder = ctx.run.checkout
    entry = projects.get(str(folder))
    if isinstance(entry, dict) and entry.get(TRUST_KEY) is True:
        return None
    return _result(ctx).Stop("preflight.untrusted", f"start Claude Code in {folder}, accept its trust dialog, then run {RERUN}",
                             {"folder": str(folder), "path": str(path)})


def check_hooks_on(ctx):
    """Stop when a settings file switches every hook off (rule 38)."""
    try:
        files = read_settings(ctx.run.checkout)
    except Unreadable as e:
        return _unreadable(ctx, e)
    for path, data in files:
        if data.get(HOOKS_OFF_KEY, False) is not False:
            return _result(ctx).Stop("preflight.hooks-off", f'set "{HOOKS_OFF_KEY}": false in {path}, then run {RERUN}',
                                     {"path": str(path), "key": HOOKS_OFF_KEY})
    return None


def check_shell_hooks(ctx):
    """Stop on a shell-tool PreToolUse hook not on the known hooks list (rule 38)."""
    try:
        files = read_settings(ctx.run.checkout)
        sources = [(path, None, None, data) for path, data in files] + _plugin_hooks(files, ctx.run.checkout)
        for path, plugin, key, data in sources:
            for command in _shell_commands(path, data):
                if not is_known(command, plugin):
                    fix = f"turn off the plugin {key} with /plugin" if key else f"remove that hook from {path}"
                    return _result(ctx).Stop("preflight.unknown-hook", f"{fix}, then run {RERUN}",
                                             {"path": str(path), "command": command})
    except Unreadable as e:
        return _unreadable(ctx, e)
    return None


def _plugin_hooks(files: list[tuple[Path, dict]], checkout: Path) -> list[tuple[Path, str, str, dict]]:
    """(file, plugin name, plugin key, hooks JSON) for each hook source of each enabled plugin's
    installs that apply to this checkout. `files` run from least to most specific."""
    state = {}
    for path, data in files:
        plugins = data.get(ENABLED_PLUGINS_KEY, {})
        if not isinstance(plugins, dict) or not all(isinstance(on, bool) for on in plugins.values()):
            raise Unreadable(path, f"{ENABLED_PLUGINS_KEY} is not an object of true and false")
        state.update(plugins)
    enabled = sorted(key for key, on in state.items() if on)
    if not enabled:
        return []
    path = config_dir() / INSTALLED_PLUGINS
    installed = (read_object(path) or {}).get("plugins", {})
    if not isinstance(installed, dict):
        raise Unreadable(path, "plugins is not an object")
    out = []
    for key in enabled:
        installs = installed.get(key, [])
        if not isinstance(installs, list) or not all(isinstance(i, dict) and isinstance(i.get("installPath"), str) for i in installs):
            raise Unreadable(path, f"{key} is not a list of installs with an installPath")
        for install in installs:
            if _applies(install, checkout, path, key):
                root = Path(install["installPath"])
                out += [(source, key.partition("@")[0], key, data) for source, data in _hook_sources(root)]
    return out


def _applies(install: dict, checkout: Path, path: Path, key: str) -> bool:
    """Whether an install applies to the checkout. A project install applies in its folder and
    below; a scope this does not know cannot be told, so it stops."""
    scope = install.get("scope")
    if scope in INSTALL_SCOPES:
        return True
    project = install.get("projectPath")
    if scope not in PROJECT_SCOPES or not isinstance(project, str):
        raise Unreadable(path, f"an install of {key} has a scope this check does not know: {scope}")
    return checkout == Path(project) or Path(project) in checkout.parents


def _hook_sources(root: Path) -> list[tuple[Path, dict]]:
    """An install's hooks: `hooks/hooks.json` if it exists, and each `hooks` its manifest names.

    A manifest's `hooks` is a path from the install's root, inline hooks, or a list of either.
    A path it names that cannot be read stops.
    """
    out = []
    if (data := read_object(root / "hooks" / "hooks.json")) is not None:
        out.append((root / "hooks" / "hooks.json", data))
    for manifest in (root / name for name in MANIFESTS):
        given = (read_object(manifest) or {}).get("hooks")
        for item in given if isinstance(given, list) else [] if given is None else [given]:
            if isinstance(item, str):
                file = root / item
                data = read_object(file)
                if data is None:
                    raise Unreadable(file, "the plugin's manifest names it, and it does not exist")
                out.append((file, data))
            elif isinstance(item, dict):
                out.append((manifest, item if "hooks" in item else {"hooks": item}))
            else:
                raise Unreadable(manifest, "hooks is not a path, an object or a list of them")
    return out


def _shell_commands(path: Path, data: dict) -> list[str]:
    """Each hook of a PreToolUse entry whose matcher may match the shell tool, as its command.

    A hook that is not a command hook is given as its JSON, which no known hook matches.
    """
    hooks = data.get("hooks", {})
    entries = hooks.get("PreToolUse", []) if isinstance(hooks, dict) else None
    if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get("hooks", []), list) for e in entries):
        raise Unreadable(path, "hooks.PreToolUse is not a list of entries with a hooks list")
    commands = []
    for entry in entries:
        if matches_shell(entry.get("matcher")):
            for hook in entry.get("hooks", []):
                command = hook.get("command") if isinstance(hook, dict) and hook.get("type") == "command" else None
                commands.append(command if isinstance(command, str) else json.dumps(hook))
    return commands


def matches_shell(matcher: object) -> bool:
    """Whether a hook matcher may match the shell tool; a matcher that cannot be read may."""
    if not isinstance(matcher, str) or SHELL_TOOL in matcher.split("|"):
        return True
    try:
        return re.search(matcher, SHELL_TOOL) is not None
    except re.error:
        return True


def is_known(command: str, plugin: str | None) -> bool:
    """Whether a hook command runs one known hook and nothing else.

    `plugin` is the enabled plugin whose hooks file holds the command, or None for a settings
    file. A known hook runs its script as `[python3|python] <path>`, with no other shell syntax:

    - from its plugin, as `${CLAUDE_PLUGIN_ROOT}/<script>`;
    - from a settings file, as an absolute path ending `/<plugin>/<script>`.

    A command of this plugin's own `hooks/hooks.json` that names a known entry's script is known
    too, from that entry's plugin only: deliver's guard is registered through a launcher line.
    """
    for entry in settings.read_lists()["known_hooks"]:
        if plugin not in (None, entry["plugin"]):
            continue
        root = f"{PLUGIN_ROOT_VAR}/{entry['script']}"
        if plugin and root in command and command in _own_commands():
            return True
        path = _plain_script(command, plugin is not None)
        if path is None:
            continue
        if plugin and path == root:
            return True
        if not plugin and path.startswith("/") and ".." not in path.split("/") and path.endswith(f"/{entry['plugin']}/{entry['script']}"):
            return True
    return False


def _plain_script(command: str, in_plugin: bool) -> str | None:
    """The script path of `[python3|python] <path>`, or None for any other command."""
    rest = command.replace(PLUGIN_ROOT_VAR, "", 1) if in_plugin else command
    if re.search(r"[;&|<>`()$\n\r]", rest):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if len(words) == 2 and words[0] in INTERPRETERS:
        return words[1]
    return words[0] if len(words) == 1 else None


def _own_commands() -> list[str]:
    data = read_object(PLUGIN_ROOT / "hooks" / "hooks.json") or {}
    return [hook.get("command") for entry in data.get("hooks", {}).get("PreToolUse", []) for hook in entry.get("hooks", [])]


def check_reader(ctx):
    """Stop when the plugin lacks the reader's definition file (#256 rule 48)."""
    path = PLUGIN_ROOT / "agents" / f"{READER}.md"
    if path.is_file():
        return None
    return _result(ctx).Stop(
        "preflight.no-reader",
        f"run claude plugin uninstall {PLUGIN_KEY} and claude plugin install {PLUGIN_KEY}, then run {RERUN}",
        {"path": str(path)},
    )


def check_roles(ctx):
    """Stop when a user or project role file has the name of one of deliver's roles (#231 rule 42)."""
    roles = {path.stem for path in (PLUGIN_ROOT / "agents").glob("*.md")}
    try:
        for folder in (config_dir() / "agents", ctx.run.checkout / ".claude" / "agents"):
            for path in _role_files(folder):
                name = path.stem if path.stem in roles else _role_name(path)
                if name in roles:
                    return _result(ctx).Stop(
                        "preflight.role-clash",
                        f"rename the role in {path}, in its file name and its name: line, or remove the file, then run {RERUN}",
                        {"path": str(path), "role": name},
                    )
    except Unreadable as e:
        return _unreadable(ctx, e)
    return None


def _role_files(folder: Path) -> list[Path]:
    """The `.md` files under a role folder; a folder in it that cannot be listed stops."""
    if not os.path.lexists(folder):
        return []

    def fail(error: OSError):
        raise Unreadable(Path(error.filename or folder), error.strerror or str(error))

    return sorted(Path(top) / name for top, _, names in os.walk(folder, onerror=fail) for name in names if name.endswith(".md"))


def _role_name(path: Path) -> str | None:
    """The `name:` of a role file's front matter. A link to nothing is no role: Claude Code has
    no file to load. A file that cannot be read stops."""
    if path.is_symlink() and not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise Unreadable(path, e.strerror or str(e)) from None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        key, _, value = line.partition(":")
        if key.strip() == "name":
            return value.strip().strip("'\"")
    return None


def check_plugin_twice(ctx):
    """Stop when deliver is also in Claude Code's user-level skills folder (#181 rule 23)."""
    path = config_dir() / "skills" / PLUGIN
    if not os.path.lexists(path):
        return None
    remove = "rm" if path.is_symlink() or not path.is_dir() else "rm -r"
    return _result(ctx).Stop("preflight.plugin-twice", f"{remove} {shlex.quote(str(path))}, then run {RERUN}",
                             {"path": str(path)})


def check_agents_at_once(ctx):
    """Claude Code starts the one reader a small edit needs, so this passes (#178 check table)."""
    return None


def check_effort(ctx):
    """Warn when CLAUDE_CODE_EFFORT_LEVEL is unset (#178 check table)."""
    return None if EFFORT_VAR in os.environ else _result(ctx).Warn(EFFORT_WARNING)
