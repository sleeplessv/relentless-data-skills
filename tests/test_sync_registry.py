"""Tests for scripts/sync_registry.py.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

The generator is the registry's only writer: marketplace.json's plugins
array and the README skills table are projections of skills/*/plugin.json.
These tests pin the projection (entry shape, table shape, escaping) and the
--check contract (drift or hand-edits fail CI) against a synthetic repo, so
they don't churn whenever a real skill's metadata changes. One test runs
--check against the real repo: committed registries must stay generated.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sync_registry.py"

PLUGIN = {
    "name": "alpha",
    "version": "0.1.0",
    "description": "Does alpha things | with a pipe.",
    "author": {"name": "sleeplessv"},
    "license": "Apache-2.0",
    "keywords": ["alpha"],
}

README_TEMPLATE = """# fake repo

## Skills

<!-- skills-table:begin -->
stale table
<!-- skills-table:end -->

## License
"""


def make_repo(root: Path, plugins: list[dict], readme: str = README_TEMPLATE) -> None:
    """Lay out the minimal repo shape sync_registry.py expects."""
    (root / "scripts").mkdir()
    (root / "scripts" / "sync_registry.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "fake", "owner": {"name": "x"}, "plugins": []}),
        encoding="utf-8",
    )
    (root / "README.md").write_text(readme, encoding="utf-8")
    for plugin in plugins:
        skill_dir = root / "skills" / plugin["name"]
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        (skill_dir / "plugin.json").write_text(json.dumps(plugin), encoding="utf-8")


def run(root: Path, mode: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "sync_registry.py"), mode],
        capture_output=True,
        text=True,
    )


class TestSyncRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_write_generates_marketplace_entry_with_source(self) -> None:
        make_repo(self.root, [PLUGIN])
        result = run(self.root, "--write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        marketplace = json.loads(
            (self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        (entry,) = marketplace["plugins"]
        self.assertEqual(entry["source"], "./skills/alpha")
        for key in ("name", "version", "description", "author", "license", "keywords"):
            self.assertEqual(entry[key], PLUGIN[key])
        # top-level marketplace metadata survives regeneration
        self.assertEqual(marketplace["name"], "fake")

    def test_write_generates_table_sorted_and_pipe_escaped(self) -> None:
        beta = dict(PLUGIN, name="beta", description="Beta.")
        make_repo(self.root, [beta, PLUGIN])
        run(self.root, "--write")
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("stale table", readme)
        self.assertIn("| Skill | What it does |", readme)
        self.assertIn(r"Does alpha things \| with a pipe.", readme)
        self.assertLess(
            readme.index("[`alpha`](skills/alpha/)"),
            readme.index("[`beta`](skills/beta/)"),
            "table rows must be sorted by skill name",
        )
        # content outside the markers is untouched
        self.assertIn("# fake repo", readme)
        self.assertIn("## License", readme)

    def test_check_passes_after_write_and_write_is_idempotent(self) -> None:
        make_repo(self.root, [PLUGIN])
        run(self.root, "--write")
        self.assertEqual(run(self.root, "--check").returncode, 0)
        result = run(self.root, "--write")
        self.assertIn("already in sync", result.stdout)

    def test_check_fails_on_hand_edited_marketplace(self) -> None:
        make_repo(self.root, [PLUGIN])
        run(self.root, "--write")
        marketplace_path = self.root / ".claude-plugin" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        marketplace["plugins"][0]["version"] = "9.9.9"
        marketplace_path.write_text(json.dumps(marketplace, indent=2) + "\n", encoding="utf-8")
        result = run(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("marketplace.json", result.stdout)

    def test_check_fails_on_unregistered_skill(self) -> None:
        make_repo(self.root, [PLUGIN])
        run(self.root, "--write")
        make_repo_dir = self.root / "skills" / "zeta"
        make_repo_dir.mkdir()
        (make_repo_dir / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        (make_repo_dir / "plugin.json").write_text(
            json.dumps(dict(PLUGIN, name="zeta")), encoding="utf-8"
        )
        self.assertEqual(run(self.root, "--check").returncode, 1)

    def test_fails_when_plugin_name_mismatches_directory(self) -> None:
        make_repo(self.root, [PLUGIN])
        (self.root / "skills" / "alpha" / "plugin.json").write_text(
            json.dumps(dict(PLUGIN, name="renamed")), encoding="utf-8"
        )
        result = run(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("expected the directory name", result.stdout)

    def test_fails_when_readme_markers_missing(self) -> None:
        make_repo(self.root, [PLUGIN], readme="# no markers\n")
        result = run(self.root, "--write")
        self.assertEqual(result.returncode, 1)
        self.assertIn("markers", result.stderr + result.stdout)

    def test_real_repo_registries_are_generated(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
