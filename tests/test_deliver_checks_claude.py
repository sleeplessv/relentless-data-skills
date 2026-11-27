"""Preflight's checks of Claude Code itself (#421): each stop of #178 rule 38, the three other stops
and the effort warning.

Most cases call a check directly, with HOME, the environment and the managed settings path
pointed at a temporary folder. A few run `deliver.py preflight` at its command line in a
throwaway world, for the whole printed output.

The fixtures in `deliver_claude_inputs/` record what was seen on a real Claude Code session,
shape only: `<home>` and `<checkout>` stand for the test's folders.

- `interactive-env.json`: the Claude Code variables of an interactive session.
- `user-settings.json`: user settings with snowman's guard as a plain command hook and the
  `deliver` plugin enabled.
- `installed_plugins.json`: the installed plugins record, with `deliver` in the plugin cache.
- `trust-record.json`: `~/.claude.json`, with the checkout trusted.

A case whose signal was not seen on a real session says `not_yet_seen` in its name.

    python3 -m unittest tests.test_deliver_checks_claude
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

preflight = deliver_kit.load("preflight")
claude = deliver_kit.load("checks_claude")
core = deliver_kit.load("core")
settings = deliver_kit.load("settings")

INPUTS = Path(__file__).resolve().parent / "deliver_claude_inputs"
PLUGIN = deliver_kit.REPO_ROOT / "skills" / "deliver"
SNOWMAN = deliver_kit.REPO_ROOT / "skills" / "snowman"
DELIVER_KEY = "deliver@relentless-data-skills"
RERUN = "then run deliver.py preflight"
EFFORT = ("CLAUDE_CODE_EFFORT_LEVEL is unset, so the session runs at Claude Code's default effort")


def recorded(name: str, **places: Path) -> str:
    text = (INPUTS / name).read_text(encoding="utf-8")
    for key, path in places.items():
        text = text.replace(f"<{key}>", str(path))
    return text


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def hook(command: str, matcher: str | None = "Bash") -> dict:
    entry = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry["matcher"] = matcher
    return {"hooks": {"PreToolUse": [entry]}}


class Home:
    """Claude Code's files under a home folder: settings, plugins, the trust record and roles."""

    def __init__(self, home: Path, checkout: Path):
        self.home = home
        self.checkout = checkout
        self.claude = home / ".claude"

    def settings(self, scope: str = "user", data: dict | str | None = None, **keys) -> Path:
        path = {"user": self.claude / "settings.json",
                "project": self.checkout / ".claude" / "settings.json",
                "local": self.checkout / ".claude" / "settings.local.json"}.get(scope) or Path(scope)
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() and data is None else {}
        text = data if isinstance(data, str) else json.dumps({**old, **(data or {}), **keys})
        return write(path, text)

    def recorded_user_settings(self) -> None:
        write(self.claude / "settings.json", recorded("user-settings.json", home=self.home))
        write(self.claude / "plugins" / "installed_plugins.json", recorded("installed_plugins.json", home=self.home))
        root = self.claude / "plugins" / "cache" / "relentless-data-skills" / "deliver" / "0.1.0"
        shutil.copytree(PLUGIN / "hooks", root / "hooks")

    def plugin(self, name: str, hooks: dict | str, enabled: bool | None = True) -> Path:
        """Install a plugin with this hooks file, and enable it in user settings unless `enabled` is None."""
        key = f"{name}@market"
        root = self.claude / "plugins" / "cache" / "market" / name / "1.0.0"
        hooks_file = write(root / "hooks" / "hooks.json", hooks if isinstance(hooks, str) else json.dumps(hooks))
        installed = self.claude / "plugins" / "installed_plugins.json"
        record = json.loads(installed.read_text()) if installed.exists() else {"version": 2, "plugins": {}}
        record["plugins"][key] = [{"scope": "user", "installPath": str(root), "version": "1.0.0"}]
        write(installed, json.dumps(record))
        if enabled is not None:
            user = self.claude / "settings.json"
            data = json.loads(user.read_text()) if user.exists() else {}
            data.setdefault("enabledPlugins", {})[key] = enabled
            write(user, json.dumps(data))
        return hooks_file

    def trust(self, trusted: bool | None = True) -> Path:
        projects = {} if trusted is None else {str(self.checkout): {"hasTrustDialogAccepted": trusted}}
        return write(self.home / ".claude.json", json.dumps({"projects": projects}))


class Checks(unittest.TestCase):
    """Each check called directly on a temporary home and checkout."""

    def setUp(self):
        root = Path(os.path.realpath(tempfile.mkdtemp(prefix="deliver-claude-")))
        self.addCleanup(shutil.rmtree, str(root), True)
        self.root = root
        self.checkout = root / "work"
        self.checkout.mkdir()
        self.home = Home(root / "home", self.checkout)
        self.home.home.mkdir()
        self.managed = root / "managed-settings.json"
        self.env({})
        patch = mock.patch.dict(claude.MANAGED_SETTINGS, {sys.platform: self.managed})
        patch.start()
        self.addCleanup(patch.stop)
        self.ctx = preflight.Context(core.Run(self.checkout, self.checkout / ".git", self.checkout / ".git", {}))

    def env(self, variables: dict) -> None:
        """Set the whole environment: HOME and PATH, then these variables, and nothing of this session."""
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home.home), "PATH": os.environ.get("PATH", ""),
                                             **variables}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def refused(self, result) -> list[str]:
        self.assertIsInstance(result, preflight.Stop)
        return core.Refused(result.code, result.next_command, **result.fields).lines()

    # Hooks switched off.

    def test_hooks_off_in_project_settings(self):
        path = self.home.settings("project", disableAllHooks=True)
        self.assertEqual(self.refused(claude.check_hooks_on(self.ctx)), [
            f"REFUSED preflight.hooks-off: Claude Code's hooks are switched off: {path} sets disableAllHooks",
            f'Next: set "disableAllHooks": false in {path}, {RERUN}',
        ])

    def test_hooks_off_in_local_settings(self):
        path = self.home.settings("local", disableAllHooks=True)
        self.assertEqual(claude.check_hooks_on(self.ctx).fields["path"], str(path))

    def test_hooks_off_in_managed_settings_not_yet_seen(self):
        self.home.settings(str(self.managed), disableAllHooks=True)
        self.assertEqual(claude.check_hooks_on(self.ctx).fields["path"], str(self.managed))

    def test_hooks_off_value_that_is_not_false_stops(self):
        self.home.settings("user", disableAllHooks="true")
        self.assertEqual(claude.check_hooks_on(self.ctx).code, "preflight.hooks-off")

    def test_hooks_on_when_false_or_absent_in_every_file(self):
        self.assertIsNone(claude.check_hooks_on(self.ctx))
        for scope in ("user", "project", "local", str(self.managed)):
            self.home.settings(scope, disableAllHooks=False)
        self.home.settings("user", data={"theme": "dark"})
        self.assertIsNone(claude.check_hooks_on(self.ctx))

    def test_preflight_claude_unreadable(self):
        path = self.home.settings("local", data="{not json")
        self.assertEqual(self.refused(claude.check_hooks_on(self.ctx)), [
            f"REFUSED preflight.claude-unreadable: Claude Code's file {path} cannot be read: "
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
            f"Next: fix {path}, {RERUN}",
        ])

    def test_settings_whose_top_level_is_not_an_object_stops(self):
        path = self.home.settings("user", data="[]")
        for check in (claude.check_hooks_on, claude.check_shell_hooks):
            self.assertEqual(self.refused(check(self.ctx))[0],
                             f"REFUSED preflight.claude-unreadable: Claude Code's file {path} cannot be read: "
                             "its top level is not a JSON object")

    # Unknown hook on the shell tool.

    def test_delivers_own_registration_passes(self):
        self.home.recorded_user_settings()
        self.assertIsNone(claude.check_shell_hooks(self.ctx))

    def test_snowman_guard_in_user_settings_passes(self):
        write(self.home.claude / "settings.json", recorded("user-settings.json", home=self.home.home))
        self.assertIsNone(claude.check_shell_hooks(self.ctx))

    def test_snowman_guard_from_its_plugin_passes(self):
        self.home.plugin("snowman", (SNOWMAN / "hooks" / "hooks.json").read_text())
        self.assertIsNone(claude.check_shell_hooks(self.ctx))

    def test_preflight_unknown_hook(self):
        path = self.home.settings("user", hook("python3 /opt/tools/audit.py"))
        self.assertEqual(self.refused(claude.check_shell_hooks(self.ctx)), [
            "REFUSED preflight.unknown-hook: a hook deliver does not know runs on shell commands: "
            f"{path} registers python3 /opt/tools/audit.py",
            f"Next: remove that hook from {path}, {RERUN}",
        ])

    def test_unknown_hook_from_an_enabled_plugin_names_the_plugin(self):
        path = self.home.plugin("audit", hook("${CLAUDE_PLUGIN_ROOT}/audit.sh"))
        self.assertEqual(self.refused(claude.check_shell_hooks(self.ctx)), [
            "REFUSED preflight.unknown-hook: a hook deliver does not know runs on shell commands: "
            f"{path} registers ${{CLAUDE_PLUGIN_ROOT}}/audit.sh",
            f"Next: turn off the plugin audit@market with /plugin, {RERUN}",
        ])

    def test_unknown_hook_stops_in_each_place_for_each_shell_matcher(self):
        for scope in ("user", "project", "local", "plugin"):
            for matcher in ("Bash", "Bash|bash", "Edit|Bash", "*", "", ".*", None, "(unclosed"):
                with self.subTest(scope=scope, matcher=matcher):
                    shutil.rmtree(self.home.claude, ignore_errors=True)
                    shutil.rmtree(self.checkout / ".claude", ignore_errors=True)
                    data = hook("/opt/tools/audit.sh", matcher)
                    path = self.home.plugin("audit", data) if scope == "plugin" else self.home.settings(scope, data)
                    self.assertEqual(claude.check_shell_hooks(self.ctx).fields,
                                     {"path": str(path), "command": "/opt/tools/audit.sh"})

    def test_hook_that_is_not_a_command_hook_stops(self):
        self.home.settings("user", {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "http", "url": "https://example.invalid/hook"}]}]}})
        self.assertEqual(claude.check_shell_hooks(self.ctx).fields["command"],
                         '{"type": "http", "url": "https://example.invalid/hook"}')

    def test_hook_whose_matcher_cannot_match_the_shell_passes(self):
        for matcher in ("Edit", "Write|Edit", "mcp__.*"):
            with self.subTest(matcher=matcher):
                self.home.settings("user", hook("/opt/tools/audit.sh", matcher))
                self.assertIsNone(claude.check_shell_hooks(self.ctx))

    def test_unknown_hook_in_a_plugin_not_enabled_passes(self):
        self.home.plugin("audit", hook("${CLAUDE_PLUGIN_ROOT}/audit.sh"), enabled=None)
        self.home.plugin("other", hook("${CLAUDE_PLUGIN_ROOT}/other.sh"), enabled=False)
        self.assertIsNone(claude.check_shell_hooks(self.ctx))

    def test_known_script_with_anything_more_stops(self):
        snow = f"{self.home.home}/.agents/skills/snowman/hooks/snow_guard.py"
        launcher = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        cases = {
            "user": [
                f'python3 "{snow}"; curl x',
                f'python3 "{snow}" && other',
                f'python3 "{snow}" | tee log',
                f'python3 "{snow}"\ncurl x',
                f'python3 "{snow}" $(curl x)',
                f'python3 "/a$(curl x){snow}"',
                f'python3 "/a`curl x`{snow}"',
                f'python3 "{snow}" extra',
                f'bash -c "python3 {snow}"',
                f'python3 "{self.home.home}/.agents/skills/snowcat/hooks/snow_guard.py"',
                'python3 "$HOME/.agents/skills/snowman/hooks/snow_guard.py"',
                'python3 "relative/snowman/hooks/snow_guard.py"',
                f'python3 "{self.home.home}/x/../snowman/hooks/snow_guard.py"',
                'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/snow_guard.py"',
                launcher,
            ],
            "snowman": [
                'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/snow_guard.py"; curl x',
                'python3 "${CLAUDE_PLUGIN_ROOT}/../evil/hooks/snow_guard.py"',
                'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guard.py"',
                launcher,
            ],
            "deliver": [
                'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/snow_guard.py"',
                launcher + "; curl x",
            ],
        }
        for where, commands in cases.items():
            for command in commands:
                with self.subTest(where=where, command=command):
                    shutil.rmtree(self.home.claude, ignore_errors=True)
                    if where == "user":
                        self.home.settings("user", hook(command, "Bash|bash"))
                    else:
                        self.home.plugin(where, hook(command))
                    self.assertEqual(claude.check_shell_hooks(self.ctx).fields["command"], command)

    def test_known_hooks_come_from_lists_toml_only(self):
        write(self.home.claude / "settings.json", recorded("user-settings.json", home=self.home.home))
        with mock.patch.object(claude.settings, "read_lists", return_value={"known_hooks": []}):
            self.assertEqual(claude.check_shell_hooks(self.ctx).code, "preflight.unknown-hook")
        source = (deliver_kit.SCRIPTS / "checks_claude.py").read_text(encoding="utf-8")
        for entry in settings.read_lists()["known_hooks"]:
            for value in (entry["plugin"] + "/", entry["script"], Path(entry["script"]).name):
                self.assertNotIn(value, source)

    def test_installed_plugins_record_that_cannot_be_read_stops(self):
        self.home.plugin("audit", hook("${CLAUDE_PLUGIN_ROOT}/audit.sh"))
        installed = write(self.home.claude / "plugins" / "installed_plugins.json", '{"plugins": []}')
        self.assertEqual(self.refused(claude.check_shell_hooks(self.ctx))[0],
                         f"REFUSED preflight.claude-unreadable: Claude Code's file {installed} cannot be read: "
                         "plugins is not an object")

    def test_config_dir_from_the_environment_not_yet_seen(self):
        config = self.root / "config"
        path = write(config / "settings.json", json.dumps(hook("/opt/tools/audit.sh")))
        write(config / ".claude.json", json.dumps({"projects": {str(self.checkout): {"hasTrustDialogAccepted": True}}}))
        self.env({"CLAUDE_CONFIG_DIR": str(config)})
        self.assertEqual(claude.check_shell_hooks(self.ctx).fields["path"], str(path))
        self.assertIsNone(claude.check_trust(self.ctx))

    # Untrusted folder.

    def test_trusted_folder_passes(self):
        write(self.home.home / ".claude.json", recorded("trust-record.json", checkout=self.checkout))
        self.assertIsNone(claude.check_trust(self.ctx))

    def test_preflight_untrusted(self):
        record = self.home.trust(False)
        self.assertEqual(self.refused(claude.check_trust(self.ctx)), [
            f"REFUSED preflight.untrusted: Claude Code does not trust {self.checkout}: "
            f"{record} records no accepted trust dialog for it",
            f"Next: start Claude Code in {self.checkout}, accept its trust dialog, {RERUN}",
        ])

    def test_folder_with_no_entry_or_no_record_stops(self):
        self.assertEqual(claude.check_trust(self.ctx).code, "preflight.untrusted")
        self.home.trust(None)
        self.assertEqual(claude.check_trust(self.ctx).code, "preflight.untrusted")

    def test_trusted_parent_folder_does_not_count_not_yet_seen(self):
        write(self.home.home / ".claude.json", json.dumps({"projects": {str(self.root): {"hasTrustDialogAccepted": True}}}))
        self.assertEqual(claude.check_trust(self.ctx).code, "preflight.untrusted")

    def test_print_mode_counts_as_trusted_not_yet_seen(self):
        self.home.trust(False)
        self.env({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})
        self.assertIsNone(claude.check_trust(self.ctx))

    def test_trust_record_that_cannot_be_read_stops(self):
        record = write(self.home.home / ".claude.json", "{")
        self.assertEqual(claude.check_trust(self.ctx).fields["path"], str(record))
        self.assertEqual(claude.check_trust(self.ctx).code, "preflight.claude-unreadable")

    # Background session nobody can stop.

    def test_preflight_background_remote_session_not_yet_seen(self):
        self.env({"CLAUDE_CODE_REMOTE": "true"})
        self.assertEqual(self.refused(claude.check_background(self.ctx)), [
            "REFUSED preflight.background: this Claude Code session runs where nobody can stop it: "
            "CLAUDE_CODE_REMOTE is true",
            f"Next: start the run from an interactive Claude Code session in {self.checkout}",
        ])

    def test_unattended_session_stops_not_yet_seen(self):
        self.env({**json.loads(recorded("interactive-env.json")), "CLAUDE_CODE_SESSION_ATTENDED": "0"})
        self.assertEqual(claude.check_background(self.ctx).fields,
                         {"var": "CLAUDE_CODE_SESSION_ATTENDED", "value": "0"})

    def test_interactive_session_passes(self):
        self.env(json.loads(recorded("interactive-env.json")))
        self.assertIsNone(claude.check_background(self.ctx))

    # The other stops and the warning.

    def test_preflight_role_clash(self):
        path = write(self.home.claude / "agents" / "deliver-reader.md", "---\nname: my-reader\n---\n")
        self.assertEqual(self.refused(claude.check_roles(self.ctx)), [
            f"REFUSED preflight.role-clash: the role file {path} has the name of deliver's role deliver-reader",
            f"Next: rename the role in {path}, in its file name and its name: line, or remove the file, {RERUN}",
        ])

    def test_project_role_named_in_its_front_matter_stops(self):
        path = write(self.checkout / ".claude" / "agents" / "reader.md", "---\ndescription: x\nname: 'deliver-reader'\n---\n")
        self.assertEqual(claude.check_roles(self.ctx).fields, {"path": str(path), "role": "deliver-reader"})

    def test_other_roles_pass(self):
        write(self.home.claude / "agents" / "reviewer.md", "---\nname: reviewer\n---\nname: deliver-reader\n")
        write(self.checkout / ".claude" / "agents" / "notes.md", "name: deliver-reader\n")
        self.assertIsNone(claude.check_roles(self.ctx))

    def test_preflight_plugin_twice(self):
        folder = self.home.claude / "skills" / "deliver"
        folder.mkdir(parents=True)
        self.assertEqual(self.refused(claude.check_plugin_twice(self.ctx)), [
            f"REFUSED preflight.plugin-twice: deliver is also in Claude Code's user-level skills folder: {folder}",
            f"Next: rm -r {folder}, {RERUN}",
        ])
        folder.rmdir()
        folder.symlink_to(self.root / "gone")
        self.assertEqual(self.refused(claude.check_plugin_twice(self.ctx))[1], f"Next: rm {folder}, {RERUN}")

    def test_other_user_skills_pass(self):
        (self.home.claude / "skills" / "snowman").mkdir(parents=True)
        self.assertIsNone(claude.check_plugin_twice(self.ctx))

    def test_preflight_no_reader(self):
        plugin = self.root / "plugin"
        shutil.copytree(PLUGIN / "hooks", plugin / "hooks")
        (plugin / "agents").mkdir()
        reader = plugin / "agents" / "deliver-reader.md"
        with mock.patch.object(claude, "PLUGIN_ROOT", plugin):
            self.assertEqual(self.refused(claude.check_reader(self.ctx)), [
                f"REFUSED preflight.no-reader: the deliver plugin has no reader role file: {reader} is missing",
                f"Next: run claude plugin uninstall {DELIVER_KEY} and claude plugin install {DELIVER_KEY}, {RERUN}",
            ])
        self.assertIsNone(claude.check_reader(self.ctx))

    def test_effort_set_prints_nothing_and_claude_effort_does_not_count(self):
        self.env({"CLAUDE_EFFORT": "medium"})
        self.assertEqual(claude.check_effort(self.ctx), preflight.Warn(EFFORT))
        self.env({"CLAUDE_CODE_EFFORT_LEVEL": "high"})
        self.assertIsNone(claude.check_effort(self.ctx))

    def test_agents_at_once_passes_for_one_reader(self):
        self.assertIsNone(claude.check_agents_at_once(self.ctx))

    def test_harness_checks_run_after_settings_and_before_the_probe(self):
        names = [check.__name__ for check in preflight.CHECKS]
        self.assertEqual(names[:11], [
            "check_settings", "check_background", "check_trust", "check_hooks_on", "check_shell_hooks",
            "check_reader", "check_roles", "check_plugin_twice", "check_agents_at_once", "check_effort",
            "check_guard_probe",
        ])


class Preflight(unittest.TestCase):
    """`deliver.py preflight` at its command line, on Claude Code's files as recorded."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark(run="run-1")
        self.world.probe()
        write(self.world.work / "docs" / "agents" / "stack.toml", 'check_command = "make check"\n')
        self.home = Home(self.world.home, self.world.work)
        self.home.recorded_user_settings()
        self.session = json.loads(recorded("interactive-env.json"))

    def test_clean_run_prints_one_line_naming_no_adapter(self):
        result = self.world.deliver("preflight", **self.session)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "Preflight passed.\n", ""))
        self.assertNotIn("adapter", result.stdout)

    def test_effort_unset_is_one_warning_naming_no_adapter(self):
        result = self.world.deliver("preflight", CLAUDE_CODE_EFFORT_LEVEL=None, **self.session)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f"warning: {EFFORT}\nPreflight passed.\n", ""))
        self.assertNotIn("adapter", result.stdout)

    def test_preflight_hooks_off(self):
        path = self.home.settings("user", disableAllHooks=True)
        result = self.world.deliver("preflight", **self.session)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (10, (
            f"REFUSED preflight.hooks-off: Claude Code's hooks are switched off: {path} sets disableAllHooks\n"
            f'Next: set "disableAllHooks": false in {path}, {RERUN}\n'), ""))
        self.assertEqual([line["stops"] for line in self.world.records()], [["preflight.hooks-off"]])


if __name__ == "__main__":
    unittest.main()
