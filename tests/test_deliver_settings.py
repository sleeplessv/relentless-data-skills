"""Stack settings: every key and default, what replaces and what only adds, and a missing file.

settings.py imports nothing of the program, so these tests load it alone and point it at a
stack settings file in a temporary folder.

    python3 -m unittest tests.test_deliver_settings
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

settings = deliver_kit.load("settings")
LISTS = settings.read_lists()

DEFAULTS = {
    "stop_at_ready": False,
    "follow_ups": True,
    "check_slots": 1,
    "ports_command": "",
    "setup_command": "",
    "check_command": "",
    "small_edit": {
        "critical_paths": LISTS["critical_paths"],
        "dependents_command": "",
        "dependents_limit": 5,
        "exclude_tests": ["tests/**", "test/**", "**/__tests__/**", "**/test_*.*", "**/*_test.*", "**/*.test.*",
                          "**/*.spec.*"],
        "exclude_generated": ["**/*.lock", "**/package-lock.json", "**/pnpm-lock.yaml", "**/uv.lock", "**/poetry.lock",
                              "**/go.sum"],
    },
    "reach": {"read": "", "build": ""},
    "run": {},
    "one_way": {"extra": LISTS["one_way_commands"], "paths": LISTS["one_way_paths"]},
    "labels": {"follow_up": "needs-triage", "ready": "ready-for-agent", "miss": "miss", "skip": ["spec", "prd"]},
}


class Load(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="deliver-settings-"))
        self.addCleanup(shutil.rmtree, self.repo, True)

    def load(self, text: str | None):
        if text is not None:
            (self.repo / "docs" / "agents").mkdir(parents=True)
            (self.repo / "docs" / "agents" / "stack.toml").write_text(text, encoding="utf-8")
        return settings.load(self.repo)

    def test_missing_file_gives_every_default_and_one_warning(self):
        self.assertEqual(self.load(None), (DEFAULTS, ["no docs/agents/stack.toml: every stack setting has its default"]))

    def test_empty_file_gives_every_default_and_no_warning(self):
        self.assertEqual(self.load(""), (DEFAULTS, []))

    def test_a_set_value_replaces_its_default(self):
        loaded, warnings = self.load(
            'stop_at_ready = true\nfollow_ups = false\ncheck_slots = 2\nports_command = "./ports"\n'
            'setup_command = "make setup"\ncheck_command = "make check"\n'
            '[small_edit]\ndependents_command = "./count"\ndependents_limit = 3\n'
            '[reach]\nread = "./can-read"\nbuild = "./can-build"\n'
            '[run]\n"models/**" = "dbt build -s {paths}"\n'
            '[labels]\nfollow_up = "later"\nready = "go"\nmiss = "missed"\nskip = ["epic"]\n'
        )
        expected = {
            **DEFAULTS,
            "stop_at_ready": True, "follow_ups": False, "check_slots": 2, "ports_command": "./ports",
            "setup_command": "make setup", "check_command": "make check",
            "small_edit": {**DEFAULTS["small_edit"], "dependents_command": "./count", "dependents_limit": 3},
            "reach": {"read": "./can-read", "build": "./can-build"},
            "run": {"models/**": "dbt build -s {paths}"},
            "labels": {"follow_up": "later", "ready": "go", "miss": "missed", "skip": ["epic"]},
        }
        self.assertEqual((loaded, warnings), (expected, []))

    def test_an_exclude_list_replaces_its_default(self):
        loaded, _ = self.load('[small_edit]\nexclude_tests = ["spec/**"]\nexclude_generated = []\n')
        self.assertEqual((loaded["small_edit"]["exclude_tests"], loaded["small_edit"]["exclude_generated"]),
                         (["spec/**"], []))

    def test_critical_paths_and_one_way_additions_only_add(self):
        loaded, _ = self.load(
            '[small_edit]\ncritical_paths = ["billing/**"]\n'
            '[one_way]\nextra = ["\\\\bterraform\\\\s+apply\\\\b"]\npaths = ["infra/**"]\n'
        )
        self.assertEqual(loaded["small_edit"]["critical_paths"], LISTS["critical_paths"] + ["billing/**"])
        self.assertEqual(loaded["one_way"]["extra"], LISTS["one_way_commands"] + [r"\bterraform\s+apply\b"])
        self.assertEqual(loaded["one_way"]["paths"], LISTS["one_way_paths"] + ["infra/**"])

    def test_an_empty_addition_keeps_the_built_in_list(self):
        loaded, _ = self.load('[small_edit]\ncritical_paths = []\n[one_way]\nextra = []\npaths = []\n')
        self.assertEqual(loaded, DEFAULTS)

    def test_the_stack_settings_file_and_agents_md_are_always_critical(self):
        loaded, _ = self.load('[small_edit]\ncritical_paths = ["billing/**"]\n')
        self.assertIn("docs/agents/stack.toml", loaded["small_edit"]["critical_paths"])
        self.assertIn("**/AGENTS.md", loaded["small_edit"]["critical_paths"])

    def test_an_unknown_key_is_ignored(self):
        self.assertEqual(self.load('colour = "blue"\n[small_edit]\nshade = 1\n'), (DEFAULTS, []))

    def test_a_file_that_is_not_toml_is_refused(self):
        with self.assertRaises(settings.SettingsError) as raised:
            self.load("[small_edit\n")
        self.assertTrue(str(raised.exception).startswith("docs/agents/stack.toml is not TOML: "))

    def test_a_known_key_of_the_wrong_type_is_refused(self):
        cases = {
            "check_slots = '2'\n": "docs/agents/stack.toml: check_slots must be int",
            "follow_ups = 1\n": "docs/agents/stack.toml: follow_ups must be bool",
            "small_edit = 1\n": "docs/agents/stack.toml: small_edit must be a table",
            "[small_edit]\ncritical_paths = [1]\n": "docs/agents/stack.toml: small_edit.critical_paths must be a list of strings",
            "[one_way]\nextra = 'x'\n": "docs/agents/stack.toml: one_way.extra must be a list of strings",
            "[run]\n'models/**' = 1\n": "docs/agents/stack.toml: [run] maps path globs to command strings",
        }
        for text, message in cases.items():
            with self.subTest(text):
                shutil.rmtree(self.repo / "docs", ignore_errors=True)
                with self.assertRaises(settings.SettingsError) as raised:
                    self.load(text)
                self.assertEqual(str(raised.exception), message)


if __name__ == "__main__":
    unittest.main()
