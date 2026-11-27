"""Stack settings: the repo's `docs/agents/stack.toml` read over every default.

The keys and defaults are #179 rule 5's, with `check_command` and `[one_way] paths` from its two
amendments. A repo's value replaces the default, with three exceptions that only add: the repo's
`[small_edit] critical_paths`, `[one_way] extra` and `[one_way] paths` come after the built-in
lists of `lists.toml`, which the loaded settings hold first. A missing file gives every default
and one warning. A file that is not TOML, or a known key of the wrong type, raises
`SettingsError`; a key this module does not know is ignored.

This module imports nothing of the program, so any subcommand or test can load it alone. A new
setting is one entry in `DEFAULTS`; a new list that only adds is one entry in `ADD_ONLY`.
"""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

PATH = "docs/agents/stack.toml"
LISTS = Path(__file__).with_name("lists.toml")
MISSING = f"no {PATH}: every stack setting has its default"

DEFAULTS: dict = {
    "stop_at_ready": False,
    "follow_ups": True,
    "check_slots": 1,
    "ports_command": "",
    "setup_command": "",
    "check_command": "",
    "small_edit": {
        "critical_paths": [],
        "dependents_command": "",
        "dependents_limit": 5,
        "exclude_tests": [
            "tests/**", "test/**", "**/__tests__/**", "**/test_*.*", "**/*_test.*", "**/*.test.*", "**/*.spec.*",
        ],
        "exclude_generated": [
            "**/*.lock", "**/package-lock.json", "**/pnpm-lock.yaml", "**/uv.lock", "**/poetry.lock", "**/go.sum",
        ],
    },
    "reach": {"read": "", "build": ""},
    "run": {},
    "one_way": {"extra": [], "paths": []},
    "labels": {
        "follow_up": "needs-triage",
        "ready": "ready-for-agent",
        "miss": "miss",
        "skip": ["spec", "prd"],
    },
}

# (table, key) of a repo list that is added after a built-in list of lists.toml.
ADD_ONLY = {
    ("small_edit", "critical_paths"): "critical_paths",
    ("one_way", "extra"): "one_way_commands",
    ("one_way", "paths"): "one_way_paths",
}


class SettingsError(Exception):
    """The stack settings file cannot be read as settings."""


def read_lists() -> dict:
    with LISTS.open("rb") as f:
        return tomllib.load(f)


def load(checkout: Path) -> tuple[dict, list[str]]:
    """Return the settings for the checkout and the warnings reading them gave."""
    settings = copy.deepcopy(DEFAULTS)
    warnings = []
    try:
        text = (checkout / PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        repo = {}
        warnings.append(MISSING)
    else:
        try:
            repo = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise SettingsError(f"{PATH} is not TOML: {e}") from None
    _merge(settings, repo, "")
    lists = read_lists()
    for (table, key), built_in in ADD_ONLY.items():
        settings[table][key] = lists[built_in] + settings[table][key]
    return settings, warnings


def _merge(into: dict, repo: dict, prefix: str) -> None:
    for key, value in repo.items():
        if key not in into:
            continue
        name = prefix + key
        default = into[key]
        if name == "run":
            if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
                raise SettingsError(f"{PATH}: [run] maps path globs to command strings")
            into[key] = dict(value)
        elif isinstance(default, dict):
            if not isinstance(value, dict):
                raise SettingsError(f"{PATH}: {name} must be a table")
            _merge(default, value, name + ".")
        elif type(value) is not type(default) or (isinstance(value, list) and not all(isinstance(v, str) for v in value)):
            want = "a list of strings" if isinstance(default, list) else type(default).__name__
            raise SettingsError(f"{PATH}: {name} must be {want}")
        else:
            into[key] = value
