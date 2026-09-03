"""Tests for skills/dlt-bootstrap reference files.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

dlt-bootstrap ships no scripts — the bootstrap copies and fills
references/rule-template.md, so the template's structure is an interface:
the frontmatter keys are the skill's re-entry state and the body sections
are the house conventions agents rely on. These tests pin that interface,
plus the docs-map's durable entry points (URL *liveness* is CI's job, in
scripts/check_doc_urls.py).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "dlt-bootstrap"
RULE_TEMPLATE = SKILL_DIR / "references" / "rule-template.md"
DOCS_MAP = SKILL_DIR / "references" / "docs-map.md"
SKILL_MD = SKILL_DIR / "SKILL.md"

URL_RE = re.compile(r"=>\s*(\S+)")


def parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal frontmatter parser, mirroring scripts/lint_skill.py."""
    assert text.startswith("---"), "file must open with a frontmatter block"
    parts = text.split("---", 2)
    assert len(parts) >= 3, "frontmatter is not closed"
    fm: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#", "-")):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm


class TestRuleTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.text = RULE_TEMPLATE.read_text(encoding="utf-8")
        self.fm = parse_frontmatter(self.text)

    def test_frontmatter_reentry_state_keys(self) -> None:
        for key in (
            "managed_by",
            "bootstrapped",
            "source_types",
            "toolkits_installed",
            "pipeline_name",
            "destination",
            "dev_destination",
            "orchestration",
        ):
            self.assertIn(key, self.fm, f"rule template lost frontmatter key: {key}")

    def test_frontmatter_owner_and_house_defaults(self) -> None:
        self.assertEqual(self.fm["managed_by"], "dlt-bootstrap")
        self.assertEqual(self.fm["dev_destination"], "duckdb")
        self.assertEqual(self.fm["orchestration"], "prefect")

    def test_body_sections(self) -> None:
        for section in (
            "## Development loop",
            "## Secrets",
            "## Hardening and shipping",
            "## Warehouse inspection",
            "## Naming conventions",
        ):
            self.assertIn(section, self.text, f"rule template lost section: {section}")

    def test_credential_safety_line(self) -> None:
        # dltHub's installer does not add this for Claude Code; the template must.
        self.assertIn("never ask for credentials in chat", self.text)

    def test_steers_away_from_dlthub_platform_deployment(self) -> None:
        self.assertIn("Prefect flow", self.text)
        self.assertIn("**not** use dltHub-platform deployment", self.text)


class TestDocsMap(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOCS_MAP.read_text(encoding="utf-8")

    def test_durable_indexes_present(self) -> None:
        self.assertIn("https://dlthub.com/docs/llms.txt", self.text)
        self.assertIn("https://dlthub.com/docs/hub/llms.txt", self.text)

    def test_workbench_readme_is_the_command_source_of_truth(self) -> None:
        self.assertIn(
            "https://raw.githubusercontent.com/dlt-hub/dlthub-ai-workbench/master/README.md",
            self.text,
        )

    def test_every_mapped_url_is_https(self) -> None:
        urls = URL_RE.findall(self.text)
        self.assertGreater(len(urls), 0, "docs-map has no => URL entries")
        for url in urls:
            self.assertTrue(
                url.startswith("https://"), f"non-https docs-map entry: {url}"
            )


class TestSkillWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SKILL_MD.read_text(encoding="utf-8")

    def test_references_are_wired(self) -> None:
        self.assertIn("references/rule-template.md", self.text)
        self.assertIn("references/docs-map.md", self.text)

    def test_rule_filename_is_stated(self) -> None:
        # The committed rule's filename is how incremental mode finds it.
        self.assertIn("dlt-house-conventions.md", self.text)

    # The next two pin fixes from the 2026-06-12 live dry run — both broke
    # silently when missing.

    def test_mcp_extras_in_install_path(self) -> None:
        # Without dlthub[mcp] the workspace MCP never starts, and upstream's
        # own warning suggests a dlt[workspace] extra that does not exist.
        self.assertIn('uv add "dlthub[mcp]"', self.text)
        self.assertIn("dlt[workspace]", self.text)

    def test_secrets_gitignore_must_be_added_not_just_verified(self) -> None:
        # Neither uv init nor dlthub ai init gitignores .dlt/secrets.toml.
        self.assertIn("git check-ignore .dlt/secrets.toml", self.text)
        self.assertIn("if absent", self.text)


if __name__ == "__main__":
    unittest.main()
