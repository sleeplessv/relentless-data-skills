"""Exercise version checks and bumps through their CLI in real Git repositories."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSkillVersions(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "scripts").mkdir()
        for name in ("skill_versions.py", "sync_registry.py"):
            source = REPO_ROOT / "scripts" / name
            if source.exists():
                shutil.copy(source, self.root / "scripts" / name)
        (self.root / ".claude-plugin").mkdir()
        (self.root / ".claude-plugin/marketplace.json").write_text(
            json.dumps({"name": "test", "version": "1.0.0", "plugins": []})
        )
        (self.root / "README.md").write_text(
            "<!-- skills-table:begin -->\n<!-- skills-table:end -->\n"
        )
        self.add_skill("alpha")
        self.add_skill("beta")
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Version tests")
        self.git("config", "user.email", "versions@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.commit("Initial skills")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, text=True, capture_output=True, check=True
        ).stdout

    def commit(self, message: str) -> None:
        self.git("add", ".")
        self.git("commit", "-m", message)

    def add_skill(self, name: str, version: str = "0.1.0") -> None:
        folder = self.root / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\n---\nInstructions\n")
        (folder / "README.md").write_text("Documentation\n")
        (folder / "plugin.json").write_text(json.dumps({
            "name": name, "version": version, "description": f"Use {name}."
        }))

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts/skill_versions.py"),
             "--base", self.base, *args],
            cwd=self.root, text=True, capture_output=True,
        )

    def test_documentation_change_requires_a_bump(self) -> None:
        (self.root / "skills/alpha/README.md").write_text("Fixed typo\n")
        result = self.run_cli("--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("alpha", result.stdout)
        self.assertIn("0.1.0", result.stdout)

    def version(self, name: str) -> str:
        return json.loads((self.root / "skills" / name / "plugin.json").read_text())["version"]

    def set_version(self, name: str, version: object) -> None:
        manifest = self.root / "skills" / name / "plugin.json"
        content = json.loads(manifest.read_text())
        content["version"] = version
        manifest.write_text(json.dumps(content))

    def test_check_rejects_decreases_and_non_numeric_release_versions(self) -> None:
        for version in ("0.0.9", "0.1", "01.2.3", "1.0.0-beta", "1.0.0+build", 12, None):
            with self.subTest(version=version):
                self.set_version("alpha", version)
                result = self.run_cli("--check")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("alpha", result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_deliberate_minor_and_major_bumps_are_repeatable(self) -> None:
        for bump, expected in (("minor", "0.2.0"), ("major", "1.0.0")):
            with self.subTest(bump=bump):
                self.set_version("alpha", "0.1.0")
                (self.root / "skills/alpha/README.md").write_text("Update\n")
                result = self.run_cli("--write", "--bump", bump)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.version("alpha"), expected)
                self.assertEqual(self.run_cli("--write", "--bump", bump).returncode, 0)
                self.assertEqual(self.version("alpha"), expected)
                self.assertEqual(self.run_cli("--check").returncode, 0)

    def test_new_and_renamed_skills_start_at_initial_version_and_deleted_skills_disappear(self) -> None:
        self.git("rm", "-r", "skills/alpha")
        self.git("mv", "skills/beta", "skills/renamed")
        manifest = self.root / "skills/renamed/plugin.json"
        content = json.loads(manifest.read_text())
        content.update(name="renamed", version="0.2.0")
        manifest.write_text(json.dumps(content))
        self.add_skill("new", "1.0.0")
        self.git("add", "skills")
        result = self.run_cli("--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("0.1.0", result.stdout)
        result = self.run_cli("--write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version("new"), "0.1.0")
        self.assertEqual(self.version("renamed"), "0.1.0")
        catalog = json.loads((self.root / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual([entry["name"] for entry in catalog["plugins"]], ["new", "renamed"])
        self.assertEqual(self.run_cli("--check").returncode, 0)

    def test_missing_or_diverged_baseline_fails_without_traceback_or_writes(self) -> None:
        original = self.base
        self.base = "missing-ref"
        result = self.run_cli("--write")
        self.assertEqual(result.returncode, 1)
        self.assertIn("baseline", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.base = original
        self.git("checkout", "-b", "other")
        (self.root / "README.md").write_text("Other branch\n")
        self.commit("Advance other branch")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "main")
        result = self.run_cli("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ancestor", result.stdout)
        self.assertEqual(self.version("alpha"), "0.1.0")

    def test_untracked_new_skill_cannot_silently_enter_generated_registry(self) -> None:
        self.add_skill("untracked")
        result = self.run_cli("--write")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("git add", result.stdout)
        self.assertEqual(self.version("alpha"), "0.1.0")

    def test_deleting_last_skills_generates_an_empty_registry(self) -> None:
        self.git("rm", "-r", "skills")
        result = self.run_cli("--write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        catalog = json.loads((self.root / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(catalog["plugins"], [])
        self.assertEqual(self.run_cli("--check").returncode, 0)

    def test_symlinked_skill_directory_cannot_bypass_version_check(self) -> None:
        (self.root / "bundles").mkdir()
        self.git("mv", "skills/alpha", "bundles/alpha")
        (self.root / "skills/alpha").symlink_to("../bundles/alpha", target_is_directory=True)
        self.git("add", "skills/alpha")
        result = self.run_cli("--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("alpha", result.stdout)
        self.assertIn("symlink", result.stdout)

    def test_tracked_asset_edits_deletions_and_mode_changes_require_bumps(self) -> None:
        asset = self.root / "skills/alpha/asset with\na newline.bin"
        asset.write_bytes(b"\x00old")
        self.commit("Add asset")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("config", "core.filemode", "true")
        for action in ("edit", "delete", "executable"):
            with self.subTest(action=action):
                self.git("restore", "skills")
                if action == "edit":
                    asset.write_bytes(b"\x00new")
                elif action == "delete":
                    asset.unlink()
                else:
                    asset.chmod(0o755)
                result = self.run_cli("--check")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("alpha", result.stdout)

    def test_second_pull_request_and_content_revert_get_newer_versions(self) -> None:
        original = (self.root / "skills/alpha/README.md").read_text()
        (self.root / "skills/alpha/README.md").write_text("First change\n")
        self.assertEqual(self.run_cli("--write").returncode, 0)
        self.commit("First PR")
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "skills/alpha/README.md").write_text("Second change\n")
        self.assertEqual(self.run_cli("--check").returncode, 1)
        self.assertEqual(self.run_cli("--write").returncode, 0)
        self.assertEqual(self.version("alpha"), "0.1.2")
        self.commit("Second PR")
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "skills/alpha/README.md").write_text(original)
        self.set_version("alpha", "0.1.0")
        self.assertEqual(self.run_cli("--check").returncode, 1)
        self.assertEqual(self.run_cli("--write").returncode, 0)
        self.assertEqual(self.version("alpha"), "0.1.3")

    def test_partial_skill_deletion_and_invalid_metadata_block_all_writes(self) -> None:
        (self.root / "skills/alpha/README.md").write_text("Needs bump\n")
        (self.root / "skills/beta/plugin.json").unlink()
        result = self.run_cli("--write")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("beta", result.stdout)
        self.assertEqual(self.version("alpha"), "0.1.0")

    def test_repo_only_changes_and_net_reverted_edits_do_not_bump_skills(self) -> None:
        (self.root / "README.md").write_text(
            "Repo docs\n<!-- skills-table:begin -->\n<!-- skills-table:end -->\n"
        )
        skill_doc = self.root / "skills/alpha/README.md"
        original = skill_doc.read_text()
        skill_doc.write_text("Intermediate edit\n")
        self.commit("Work in progress")
        skill_doc.write_text(original)
        result = self.run_cli("--write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version("alpha"), "0.1.0")
        self.assertEqual(self.version("beta"), "0.1.0")

    def test_write_bumps_only_changed_skill_and_syncs_registry_once(self) -> None:
        (self.root / "skills/alpha/SKILL.md").write_text("Changed instructions\n")
        result = self.run_cli("--write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version("alpha"), "0.1.1")
        self.assertEqual(self.version("beta"), "0.1.0")
        marketplace = self.root / ".claude-plugin/marketplace.json"
        first = marketplace.read_bytes()
        catalog = json.loads(first)
        self.assertEqual(catalog["plugins"][0]["version"], "0.1.1")
        self.assertEqual(catalog["version"], "1.0.0")
        self.assertEqual(self.run_cli("--write").returncode, 0)
        self.assertEqual(self.version("alpha"), "0.1.1")
        self.assertEqual(marketplace.read_bytes(), first)
        self.assertEqual(self.run_cli("--check").returncode, 0)


if __name__ == "__main__":
    unittest.main()
