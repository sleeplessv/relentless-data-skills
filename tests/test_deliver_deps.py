"""deliver.py deps, the upstream contract and preflight's two upstream-skill checks.

The folder hash and the contract are tested in this process. Everything else runs deliver.py at
its command line in a throwaway world whose home folder holds the installed stand-in skills.

    python3 -m unittest tests.test_deliver_deps
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

deps = deliver_kit.load("deps")
preflight = deliver_kit.load("preflight")
STACK = "warning: no docs/agents/stack.toml: every stack setting has its default\n"


def recorded(world: deliver_kit.World, name: str) -> str:
    """The folder hash the world's plugin copy holds in its contract for `name`."""
    contract = (world.script.parent.parent / "upstream.toml").read_text(encoding="utf-8")
    return tomllib.loads(contract)[name]["folder_hash"]


def build(root: Path, files: list[tuple[str, str]], executable: tuple[str, ...] = ()) -> Path:
    """Write `files` (path, text) under `root` in the order given."""
    for name, text in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for name in executable:
        (root / name).chmod(0o755)
    return root


DEMO = [("SKILL.md", "---\nname: demo\n---\n"), ("references/notes.md", "demo notes\n"),
        ("scripts/run.sh", "#!/bin/sh\necho hi\n")]


class FolderHash(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="deliver-deps-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_known_value(self):
        # Worked out once with `git add -A` and `git write-tree` on this folder.
        folder = build(self.root / "demo", DEMO, executable=("scripts/run.sh",))
        self.assertEqual(deps.folder_hash(folder), "7e927ba6e898ee88d6cc19d541f44ebf1db77cd1")

    def test_stable_across_file_order(self):
        first = build(self.root / "a", DEMO)
        second = build(self.root / "b", list(reversed(DEMO)))
        self.assertEqual(deps.folder_hash(first), deps.folder_hash(second))

    def test_changes_when_a_nested_file_changes(self):
        folder = build(self.root / "demo", DEMO)
        before = deps.folder_hash(folder)
        (folder / "references" / "notes.md").write_text("demo notes!\n", encoding="utf-8")
        self.assertNotEqual(deps.folder_hash(folder), before)

    def test_matches_git_on_links_modes_and_empty_folders(self):
        folder = build(self.root / "demo", [*DEMO, ("a-b.md", "x\n"), ("a/b.md", "y\n"), (".git", "gitdir: x\n")],
                       executable=("scripts/run.sh",))
        (folder / "empty" / "inner").mkdir(parents=True)
        (folder / "link.md").symlink_to("references/notes.md")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.root),
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        git = ["git", f"--git-dir={self.root / 'g'}", f"--work-tree={folder}"]
        subprocess.run(["git", "init", "-q", "--bare", str(self.root / "g")], env=env, check=True)
        subprocess.run([*git, "add", "-A"], env=env, check=True)
        tree = subprocess.run([*git, "write-tree"], env=env, check=True, capture_output=True, text=True)
        self.assertEqual(deps.folder_hash(folder), tree.stdout.strip())


class Contract(unittest.TestCase):
    def test_six_entries_with_their_three_fields(self):
        contract = deps.load_contract()
        self.assertEqual(list(contract), list(deliver_kit.UPSTREAM))
        for name, entry in contract.items():
            with self.subTest(name):
                self.assertEqual(sorted(entry), ["folder_hash", "supplies", "takes"])
                self.assertRegex(entry["folder_hash"], r"\A[0-9a-f]{40}\Z")
                self.assertTrue(entry["takes"].strip() and entry["supplies"].strip())


class Deps(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.folders = self.world.install_upstream()

    def change(self, name: str) -> tuple[str, str]:
        """Change a nested file of an installed skill; return its contract hash and its new hash."""
        (self.folders[name] / "references" / "notes.md").write_text("edited\n", encoding="utf-8")
        return recorded(self.world, name), deps.folder_hash(self.folders[name])

    def assert_ends(self, result, code, stdout, stderr=""):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, stderr))

    def test_unchanged_copies_print_one_line(self):
        self.assert_ends(self.world.deliver("deps"), 0, "Upstream skills match the contract.\n")

    def test_changed_copy_prints_one_line_naming_it(self):
        recorded, installed = self.change("to-tickets")
        self.assert_ends(self.world.deliver("deps"), 0,
                         f"to-tickets: folder hash {installed} differs from the contract's {recorded}\n")

    def test_one_line_per_difference_in_contract_order(self):
        recorded, installed = self.change("ponytail-review")
        shutil.rmtree(self.folders["triage"])
        self.assert_ends(self.world.deliver("deps"), 0,
                         f"ponytail-review: folder hash {installed} differs from the contract's {recorded}\n"
                         "triage: not installed\n")

    def test_missing_planning_skill_is_a_line_not_a_refusal(self):
        for name in ("to-spec", "to-tickets", "triage"):
            shutil.rmtree(self.folders[name])
        self.assert_ends(self.world.deliver("deps"), 0,
                         "to-spec: not installed\nto-tickets: not installed\ntriage: not installed\n")

    def test_deps_missing_skill(self):
        shutil.rmtree(self.folders["code-review"])
        shutil.rmtree(self.folders["pr"])
        self.assert_ends(self.world.deliver("deps"), 10,
                         "REFUSED deps.missing-skill: a required upstream skill is not installed: code-review, pr\n"
                         "Next: install code-review, pr, then run deliver.py deps\n")

    def test_deps_missing_skill_outside_a_repo_and_with_a_changed_copy(self):
        self.change("code-review")
        shutil.rmtree(self.folders["ponytail-review"])
        self.assert_ends(self.world.deliver("deps", cwd=self.world.home), 10,
                         "REFUSED deps.missing-skill: a required upstream skill is not installed: ponytail-review\n"
                         "Next: install ponytail-review, then run deliver.py deps\n")

    def test_a_folder_without_skill_md_is_not_installed(self):
        (self.folders["to-spec"] / "SKILL.md").unlink()
        self.assert_ends(self.world.deliver("deps"), 0, "to-spec: not installed\n")

    def test_writes_nothing(self):
        self.change("pr")
        self.world.deliver("deps")
        self.assertFalse(self.world.state.exists())
        self.assertEqual(self.world.git(self.world.work, "status", "--porcelain", "--ignored"), "")
        common = Path(self.world.git(self.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        self.assertFalse((common / "deliver").exists())

    def test_arguments_exit_2_with_usage(self):
        result = self.world.deliver("deps", "--all")
        usage = deliver_kit.load("deliver").USAGE
        self.assert_ends(result, 2, "", f"deliver.py: deps takes no arguments, got: --all\n\n{usage}\n")


class WhereSkillsAreFound(unittest.TestCase):
    """The user's skills folder, the project's, then each installed plugin's, first match winning."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.folders = self.world.install_upstream()
        self.config = self.world.home / ".claude"

    def move(self, name: str, root: Path) -> Path:
        target = root / "skills" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(self.folders[name], target)
        return target

    def plugins(self, *install_paths: Path, config: Path | None = None) -> None:
        listing = (config or self.config) / "plugins" / "installed_plugins.json"
        listing.parent.mkdir(parents=True, exist_ok=True)
        plugins = {f"p{i}@market": [{"scope": "user", "installPath": str(path)}] for i, path in enumerate(install_paths)}
        listing.write_text(json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8")

    def test_a_symlinked_install_is_hashed_through_the_link(self):
        real = self.world.root / "agents" / "pr"
        real.parent.mkdir()
        shutil.move(self.folders["pr"], real)
        (self.config / "skills" / "pr").symlink_to(real)
        self.assertEqual(self.world.deliver("deps").stdout, "Upstream skills match the contract.\n")

    def test_found_in_the_project_folder(self):
        self.move("code-review", self.world.work / ".claude")
        self.assertEqual(self.world.deliver("deps").stdout, "Upstream skills match the contract.\n")
        self.assertEqual(self.world.deliver("deps", cwd=self.world.home).returncode, 10)

    def test_found_in_a_plugin_folder(self):
        plugin = self.config / "plugins" / "cache" / "market" / "kit" / "1.0.0"
        self.move("ponytail-review", plugin)
        self.plugins(self.world.root / "nowhere", plugin)
        self.assertEqual(self.world.deliver("deps").stdout, "Upstream skills match the contract.\n")

    def test_the_users_folder_wins_over_the_project_and_plugins(self):
        plugin = self.world.root / "plugin-cache"
        changed = self.world.install_skill("pr", plugin)
        self.world.install_skill("pr", self.world.work / ".claude")
        for folder in (changed, self.world.work / ".claude" / "skills" / "pr"):
            (folder / "SKILL.md").write_text("another\n", encoding="utf-8")
        self.plugins(plugin)
        self.assertEqual(self.world.deliver("deps").stdout, "Upstream skills match the contract.\n")

    def test_the_project_folder_wins_over_plugins(self):
        plugin = self.world.root / "plugin-cache"
        self.world.install_skill("triage", plugin)
        (plugin / "skills" / "triage" / "SKILL.md").write_text("another\n", encoding="utf-8")
        self.plugins(plugin)
        self.move("triage", self.world.work / ".claude")
        self.assertEqual(self.world.deliver("deps").stdout, "Upstream skills match the contract.\n")

    def test_claude_config_dir_replaces_the_home_folder(self):
        config = self.world.root / "config"
        shutil.move(self.config, config)
        self.assertEqual(self.world.deliver("deps").returncode, 10)
        result = self.world.deliver("deps", CLAUDE_CONFIG_DIR=str(config))
        self.assertEqual((result.returncode, result.stdout), (0, "Upstream skills match the contract.\n"))

    def test_an_unreadable_plugin_list_is_no_plugins(self):
        listing = self.config / "plugins" / "installed_plugins.json"
        listing.parent.mkdir()
        for text in ("{", '{"plugins": []}', '{"plugins": {"p@m": [{}]}}'):
            with self.subTest(text):
                listing.write_text(text, encoding="utf-8")
                self.assertEqual(self.world.deliver("deps").stdout, "Upstream skills match the contract.\n")


class Preflight(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark(run="run-4")
        self.folders = self.world.install_upstream()

    def change(self, name: str) -> str:
        (self.folders[name] / "SKILL.md").write_text("edited\n", encoding="utf-8")
        installed = deps.folder_hash(self.folders[name])
        return f"{name}: folder hash {installed} differs from the contract's {recorded(self.world, name)}"

    def test_checks_follow_settings_with_the_stop_before_the_warning(self):
        names = [(check.__module__, check.__name__) for check in preflight.CHECKS]
        at = names.index(("deps", "check_required_skills"))
        self.assertEqual(names[at + 1], ("deps", "check_skill_hashes"))
        self.assertLess(names.index((preflight.__name__, "check_settings")), at)

    def test_preflight_missing_skill(self):
        shutil.rmtree(self.folders["ponytail-review"])
        self.change("code-review")
        result = self.world.deliver("preflight")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            10,
            STACK + "REFUSED preflight.missing-skill: a required upstream skill is not installed: ponytail-review\n"
            "Next: install ponytail-review, then run deliver.py preflight\n",
            "",
        ))
        self.assertEqual([(r["result"], r["stops"]) for r in self.world.records()],
                         [("stop", ["preflight.missing-skill"])])
        self.assertEqual([(s["run"], s["code"]) for s in self.world.state_lines("preflight-stops.jsonl")],
                         [("run-4", "preflight.missing-skill")])

    def test_changed_required_skill_is_one_warning(self):
        line = self.change("pr")
        result = self.world.deliver("preflight")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f"{STACK}warning: {line}\nPreflight passed.\n", ""))
        self.assertEqual(self.world.records()[0]["warnings"],
                         ["no docs/agents/stack.toml: every stack setting has its default", line])

    def test_several_changed_skills_share_the_one_warning_line(self):
        lines = [self.change("code-review"), self.change("pr")]
        result = self.world.deliver("preflight")
        self.assertEqual((result.returncode, result.stdout),
                         (0, f"{STACK}warning: {'; '.join(lines)}\nPreflight passed.\n"))

    def test_planning_skills_are_not_checked_on_a_run(self):
        for name in ("to-spec", "to-tickets"):
            shutil.rmtree(self.folders[name])
        self.change("triage")
        result = self.world.deliver("preflight")
        self.assertEqual((result.returncode, result.stdout), (0, f"{STACK}Preflight passed.\n"))


class ReviewSkillHashes(unittest.TestCase):
    def test_hashes_of_the_review_skills_for_ready(self):
        world = deliver_kit.World(self.addCleanup)
        folders = world.install_upstream(("code-review", "pr"))
        with mock.patch.dict(os.environ, {"HOME": str(world.home)}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            hashes = deps.review_skill_hashes(world.work)
        self.assertEqual(hashes, {"code-review": deps.folder_hash(folders["code-review"]), "ponytail-review": None})


if __name__ == "__main__":
    unittest.main()
