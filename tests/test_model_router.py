"""Exercise model-router shell snippets and catalog invariants."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "model-router"
SKILL_MD = SKILL_DIR / "SKILL.md"
CATALOG_MD = SKILL_DIR / "references" / "catalog.md"
DISPATCH_MD = SKILL_DIR / "references" / "dispatch.md"

SH_BLOCKS = re.findall(
    r"```sh\n(.*?)\n```",
    DISPATCH_MD.read_text(encoding="utf-8"),
    re.DOTALL,
)


def make_executable(directory: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    target = directory / name
    target.write_text(body, encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


class ModelRouterDispatchTests(unittest.TestCase):
    def test_expected_shell_block_count(self) -> None:
        self.assertEqual(len(SH_BLOCKS), 3)

    def test_probe_reports_clis_and_herdr_state(self) -> None:
        probe = SH_BLOCKS[0]
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            make_executable(bindir, "claude")
            make_executable(bindir, "codex")
            make_executable(bindir, "hc")

            env_in_herdr = {"PATH": str(bindir), "HC_TERMINAL_ID": "t42"}
            res = subprocess.run(
                ["/bin/sh", "-c", probe],
                env=env_in_herdr,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(res.returncode, 0)
            self.assertEqual(
                res.stdout.splitlines(),
                [
                    "claude=yes",
                    "codex=yes",
                    "agy=no",
                    "cortex=no",
                    "herdr=yes",
                ],
            )

            env_outside_herdr = {"PATH": str(bindir)}
            res_no_id = subprocess.run(
                ["/bin/sh", "-c", probe],
                env=env_outside_herdr,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(res_no_id.returncode, 0)
            self.assertIn("herdr=no", res_no_id.stdout.splitlines())

    def test_codex_catalog_resolver_picks_lowest_priority_visible_slug(self) -> None:
        resolver = SH_BLOCKS[1]
        catalog = {
            "models": [
                {"slug": "gpt-6.1-sol", "visibility": "list", "priority": 20},
                {"slug": "gpt-6.2-sol", "visibility": "list", "priority": 5},
                {"slug": "gpt-6.3-sol", "visibility": "hidden", "priority": 1},
                {"slug": "gpt-6.2-astra", "visibility": "list", "priority": 2},
                {"slug": "gpt-6.1-terra", "visibility": "list", "priority": 10},
                {"slug": "gpt-6-luna", "visibility": "list", "priority": 30},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            make_executable(
                bindir,
                "codex",
                f"#!/bin/sh\n[ \"$1\" = \"debug\" ] && [ \"$2\" = \"models\" ] || exit 2\n"
                f"cat <<'EOF'\n{json.dumps(catalog)}\nEOF\n",
            )
            if shutil.which("jq") is None:
                # Fallback jq shim for minimal environments without jq installed.
                make_executable(
                    bindir,
                    "jq",
                    f"#!{sys.executable}\n"
                    "import json, sys\n"
                    "args = sys.argv[1:]\n"
                    "suffix = args[args.index('--arg') + 2]\n"
                    "data = json.load(sys.stdin)\n"
                    "hits = [m for m in data['models'] if m.get('visibility') == 'list' and m.get('slug', '').endswith(suffix)]\n"
                    "hits.sort(key=lambda m: m.get('priority', 999))\n"
                    "print(hits[0]['slug'] if hits else '')\n",
                )

            env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}")

            for family, expected in (
                ("sol", "gpt-6.2-sol"),
                ("astra", "gpt-6.2-astra"),
                ("terra", "gpt-6.1-terra"),
                ("luna", "gpt-6-luna"),
            ):
                with self.subTest(family=family):
                    run_env = dict(env, FAMILY=family)
                    res = subprocess.run(
                        ["/bin/sh", "-c", resolver],
                        env=run_env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(res.returncode, 0, msg=res.stderr)
                    self.assertEqual(res.stdout, f"MODEL={expected}\n")

            missing_env = dict(env, FAMILY="unknown")
            res_missing = subprocess.run(
                ["/bin/sh", "-c", resolver],
                env=missing_env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(res_missing.returncode, 0)

    def test_codex_catalog_resolver_fails_when_codex_fails(self) -> None:
        resolver = SH_BLOCKS[1]
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            make_executable(bindir, "codex", "#!/bin/sh\nexit 7\n")
            env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}", FAMILY="sol")
            res = subprocess.run(
                ["/bin/sh", "-c", resolver],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("codex debug models failed: 7", res.stderr)

    def test_herdr_delegate_locator_handles_present_and_absent_skill(self) -> None:
        locator = SH_BLOCKS[2]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = dict(os.environ, HOME=str(home))
            empty_res = subprocess.run(
                ["/bin/sh", "-c", locator],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(empty_res.returncode, 0)
            self.assertEqual(empty_res.stdout, "DELEGATE=\n")

            skill_file = home / ".agents" / "skills" / "herdr-delegate" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("---\nname: herdr-delegate\n---\n", encoding="utf-8")
            found_res = subprocess.run(
                ["/bin/sh", "-c", locator],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(found_res.returncode, 0)
            self.assertEqual(found_res.stdout, f"DELEGATE={skill_file}\n")


class ModelRouterCatalogTests(unittest.TestCase):
    def test_catalog_covers_four_classes_and_three_vendors(self) -> None:
        text = CATALOG_MD.read_text(encoding="utf-8")
        rows = [
            line
            for line in text.splitlines()
            if line.startswith("| `") and line.endswith("|")
        ]
        self.assertEqual(len(rows), 12)
        classes: set[str] = set()
        vendors: set[str] = set()
        for row in rows:
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            self.assertEqual(len(cells), 9, msg=row)
            cls = cells[0].strip("`")
            vendor = cells[1]
            in_usd = float(cells[4])
            out_usd = float(cells[5])
            self.assertIn(cls, {"apex", "strong", "standard", "light"})
            self.assertIn(vendor, {"Google", "OpenAI", "Anthropic"})
            self.assertGreater(in_usd, 0.0)
            self.assertGreater(out_usd, in_usd)
            classes.add(cls)
            vendors.add(vendor)
        self.assertEqual(classes, {"apex", "strong", "standard", "light"})
        self.assertEqual(vendors, {"Google", "OpenAI", "Anthropic"})

    def test_avoids_glossary_banned_phrase_model_tier(self) -> None:
        for path in (SKILL_MD, CATALOG_MD, DISPATCH_MD, SKILL_DIR / "README.md"):
            with self.subTest(path=path.name):
                self.assertNotIn("model tier", path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
