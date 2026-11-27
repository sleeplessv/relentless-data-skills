"""Exercise router's shell blocks and the invariants its files share."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "router"
SKILL_MD = SKILL_DIR / "SKILL.md"
README_MD = SKILL_DIR / "README.md"
CATALOG_MD = SKILL_DIR / "references" / "catalog.md"
HARNESSES_MD = SKILL_DIR / "references" / "harnesses.md"
ALL_FILES = (SKILL_MD, README_MD, CATALOG_MD, HARNESSES_MD)

SH_BLOCKS = re.findall(
    r"```sh\n(.*?)\n```",
    HARNESSES_MD.read_text(encoding="utf-8"),
    re.DOTALL,
)
PROBE, CORTEX_PROBE, CODEX_RESOLVER, DELEGATE_LOCATOR = range(4)

CORTEX_REJECTION = (
    "Error: __model_probe__ is not authorized or not available in your region. "
    "Please switch your agent configuration to use 'auto' for automatic model selection.\n"
    "\n"
    "Diagnostics:\n"
    "- Available models: claude-opus-5-5, claude-sonnet-5-5, openai-gpt-6.2-sol, gemini-4-carbon\n"
    "- Cross-region setting: no region restriction\n"
    "- Model allowlist: No model RBAC/allowlist restriction (request_id: 0000)\n"
)

MODEL_NAME = re.compile(r"`((?:Claude|GPT|Gemini)[^`]*)`")


def make_executable(directory: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    target = directory / name
    target.write_text(body, encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def run_block(block: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", block],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )


def table_rows(text: str, heading: str) -> list[list[str]]:
    """Return the body rows of the first table under a `## heading`."""
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]


class ShellBlockTests(unittest.TestCase):
    def test_expected_shell_block_count(self) -> None:
        self.assertEqual(len(SH_BLOCKS), 4)

    def test_probe_reports_clis_and_herdr_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            make_executable(bindir, "claude")
            make_executable(bindir, "codex")
            make_executable(bindir, "hc")

            res = run_block(SH_BLOCKS[PROBE], {"PATH": str(bindir), "HC_TERMINAL_ID": "t42"})
            self.assertEqual(res.returncode, 0)
            self.assertEqual(
                res.stdout.splitlines(),
                ["claude=yes", "codex=yes", "agy=no", "cortex=no", "herdr=yes"],
            )

            res_no_id = run_block(SH_BLOCKS[PROBE], {"PATH": str(bindir)})
            self.assertEqual(res_no_id.returncode, 0)
            self.assertIn("herdr=no", res_no_id.stdout.splitlines())

    def test_cortex_probe_prints_one_id_per_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            rejection = bindir / "rejection.txt"
            rejection.write_text(CORTEX_REJECTION, encoding="utf-8")
            # The stub answers only the call the block documents, and answers on
            # stderr with exit 1, as the real CLI does for an unknown model.
            make_executable(
                bindir,
                "cortex",
                "#!/bin/sh\n"
                '[ "$1" = "exec" ] && [ "$2" = "-m" ] && [ "$3" = "__model_probe__" ] || exit 2\n'
                f'cat "{rejection}" >&2\n'
                "exit 1\n",
            )
            res = run_block(SH_BLOCKS[CORTEX_PROBE], {"PATH": f"{bindir}:/usr/bin:/bin"})
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            self.assertEqual(
                res.stdout.splitlines(),
                ["claude-opus-5-5", "claude-sonnet-5-5", "openai-gpt-6.2-sol", "gemini-4-carbon"],
            )

    def test_cortex_probe_fails_when_no_list_is_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            make_executable(bindir, "cortex", "#!/bin/sh\necho 'Error: not signed in' >&2\nexit 1\n")
            res = run_block(SH_BLOCKS[CORTEX_PROBE], {"PATH": f"{bindir}:/usr/bin:/bin"})
            self.assertEqual(res.returncode, 1)
            self.assertEqual(res.stdout, "")
            self.assertIn("no model list", res.stderr)

    def test_codex_resolver_picks_lowest_priority_visible_slug(self) -> None:
        if shutil.which("jq") is None:
            self.skipTest("jq is not installed")
        catalog = {
            "models": [
                {"slug": "gpt-6.1-sol", "visibility": "list", "priority": 20},
                {"slug": "gpt-6.2-sol", "visibility": "list", "priority": 5},
                {"slug": "gpt-6.3-sol", "visibility": "hide", "priority": 1},
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
                '#!/bin/sh\n[ "$1" = "debug" ] && [ "$2" = "models" ] || exit 2\n'
                f"cat <<'EOF'\n{json.dumps(catalog)}\nEOF\n",
            )
            env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}")
            env.pop("WANT", None)

            for family, expected in (
                ("sol", "gpt-6.2-sol"),
                ("astra", "gpt-6.2-astra"),
                ("terra", "gpt-6.1-terra"),
                ("luna", "gpt-6-luna"),
            ):
                with self.subTest(family=family):
                    res = run_block(SH_BLOCKS[CODEX_RESOLVER], dict(env, WANT=family))
                    self.assertEqual(res.returncode, 0, msg=res.stderr)
                    self.assertEqual(res.stdout, f"MODEL={expected}\n")

            with self.subTest(want="an exact slug that is not the family's newest"):
                res = run_block(SH_BLOCKS[CODEX_RESOLVER], dict(env, WANT="gpt-6.1-sol"))
                self.assertEqual(res.returncode, 0, msg=res.stderr)
                self.assertEqual(res.stdout, "MODEL=gpt-6.1-sol\n")

            for want in ("unknown", "gpt-6.3-sol", "gpt-7-sol"):
                with self.subTest(want=want):
                    res = run_block(SH_BLOCKS[CODEX_RESOLVER], dict(env, WANT=want))
                    self.assertNotEqual(res.returncode, 0)
                    self.assertEqual(res.stdout, "")

            with self.subTest(family="unset"):
                res = run_block(SH_BLOCKS[CODEX_RESOLVER], env)
                self.assertNotEqual(res.returncode, 0)
                self.assertEqual(res.stdout, "")
                self.assertIn("WANT", res.stderr)

    def test_codex_resolver_fails_when_codex_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            make_executable(bindir, "codex", "#!/bin/sh\nexit 7\n")
            env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}", WANT="sol")
            res = run_block(SH_BLOCKS[CODEX_RESOLVER], env)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("codex debug models failed: 7", res.stderr)

    def test_herdr_delegate_locator_handles_present_and_absent_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = dict(os.environ, HOME=str(home))
            empty_res = run_block(SH_BLOCKS[DELEGATE_LOCATOR], env)
            self.assertEqual(empty_res.returncode, 0)
            self.assertEqual(empty_res.stdout, "DELEGATE=\n")

            skill_file = home / ".snowflake" / "cortex" / "skills" / "herdr-delegate" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("---\nname: herdr-delegate\n---\n", encoding="utf-8")
            found_res = run_block(SH_BLOCKS[DELEGATE_LOCATOR], env)
            self.assertEqual(found_res.returncode, 0)
            self.assertEqual(found_res.stdout, f"DELEGATE={skill_file}\n")


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = CATALOG_MD.read_text(encoding="utf-8")
        cls.models = table_rows(cls.catalog, "Models")
        cls.ids = table_rows(cls.catalog, "The ID each harness takes")

    def test_models_cover_four_classes_and_three_vendors(self) -> None:
        classes = {row[0].strip("`") for row in self.models}
        vendors = {row[1] for row in self.models}
        self.assertEqual(classes, {"apex", "strong", "standard", "light"})
        self.assertEqual(vendors, {"Google", "OpenAI", "Anthropic"})

    def test_every_price_parses_and_output_costs_more_than_input(self) -> None:
        for row in self.models:
            with self.subTest(model=row[2]):
                in_usd, out_usd, cache_usd = (float(cell) for cell in row[4:7])
                self.assertGreater(cache_usd, 0.0)
                self.assertGreater(in_usd, cache_usd)
                self.assertGreater(out_usd, in_usd)

    def test_every_model_has_one_row_in_each_table(self) -> None:
        priced = [row[2] for row in self.models]
        self.assertEqual(len(priced), len(set(priced)))
        self.assertEqual(sorted(priced), sorted(row[0] for row in self.ids))

    def test_every_model_the_skill_routes_to_is_in_the_catalog(self) -> None:
        priced = {row[2] for row in self.models}
        named = set(MODEL_NAME.findall(SKILL_MD.read_text(encoding="utf-8")))
        self.assertTrue(named)
        self.assertEqual(named - priced, set())

    def test_cortex_ids_for_openai_models_carry_the_prefix(self) -> None:
        cortex = {row[0]: row[4] for row in self.ids}
        openai = [row[2] for row in self.models if row[1] == "OpenAI"]
        self.assertTrue(openai)
        for model in openai:
            with self.subTest(model=model):
                self.assertRegex(cortex[model], r"^(`openai-gpt-[^`]+`|none)$")

    def test_prices_are_dated_and_sourced_from_each_vendor(self) -> None:
        self.assertRegex(self.catalog, r"As of \d{4}-\d{2}-\d{2}")
        for domain in ("claude.com", "openai.com", "google.com"):
            with self.subTest(domain=domain):
                self.assertRegex(self.catalog, rf"https://[\w.-]*{re.escape(domain)}/")

    def test_prices_live_only_in_the_catalog(self) -> None:
        for path in (SKILL_MD, README_MD, HARNESSES_MD):
            with self.subTest(path=path.name):
                self.assertIsNone(re.search(r"\bUSD\b|\$\d", path.read_text(encoding="utf-8")))


class VocabularyTests(unittest.TestCase):
    def test_no_term_the_glossary_lists_under_avoid(self) -> None:
        banned = (
            r"model tier",
            r"dispatch channel",
            r"\bcoordinator",
            r"\borchestrator\b(?!-mode)",
            r"\bhandoffs?\b",
            r"\bfrontier\b",
            r"\bverification\b",
            r"\bmain thread\b",
        )
        for path in ALL_FILES:
            content = path.read_text(encoding="utf-8").lower()
            for pattern in banned:
                with self.subTest(path=path.name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, content))

    def test_no_retired_model_is_named(self) -> None:
        banned = (
            r"\bo1\b",
            r"\bo3\b",
            r"\bo4\b",
            r"\bgpt-4",
            r"\bgpt-5",
            r"gpt-6\.1-sol",
            r"\bmythos\b",
        )
        for path in ALL_FILES:
            content = path.read_text(encoding="utf-8").lower()
            for pattern in banned:
                with self.subTest(path=path.name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, content))


if __name__ == "__main__":
    unittest.main()
