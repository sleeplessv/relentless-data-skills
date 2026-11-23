"""Tests for skills/snowman/scripts/snowman.py.

Standard library only, like the script itself. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here ever talks to Snowflake: execute() tests replace run_snow with
fake_snow, only TestRunSnow patches subprocess.run, and stage mode never
executes by design.
"""
from __future__ import annotations

import codecs
import contextlib
import errno
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tracemalloc
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "snowman"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import snowman  # noqa: E402


SINGLE_CONN_FRONTMATTER = """\
---
connection: analytics
---
# Project context
"""

MULTI_ENV_FRONTMATTER = """\
---
environments:
  dev:
    connection: acme_dev
  prod:
    connection: acme_prod
default_env: dev
---
# Project context
"""


Outcome = snowman.SnowResult

OK = Outcome(0, b"[]", "")


def fake_snow(outcomes: dict[str, Outcome]):
    """A stand-in for snowman.run_snow keyed by subcommand (``args[0]``).

    ``outcomes`` maps ``"sql"`` or ``"connection"`` to the result run_snow
    would return, so tests describe results instead of scripting call order.
    A subcommand with no outcome raises KeyError. ``fake.calls`` records
    every ``(args, env)`` pair.
    """
    calls: list[tuple[list, dict]] = []

    def run(args: list[str], env: dict, *, timeout=None) -> Outcome:
        calls.append((args, env))
        return outcomes[args[0]]

    run.calls = calls
    return run


def connection_listing(connection: str, parameters: dict) -> Outcome:
    """A successful `snow connection list --format JSON` outcome."""
    return Outcome(
        0, json.dumps([{"connection_name": connection, "parameters": parameters}]).encode(), ""
    )


class SnowmanTestCase(unittest.TestCase):
    """Shared helpers: Blocked assertions and temp projects passed by path.

    Resolution is tested by passing a start path. Only the entry points
    (execute, stage, main) still read the CWD, and their tests use ``enter``.
    """

    def setUp(self) -> None:
        self._original_cwd = os.getcwd()
        self.addCleanup(os.chdir, self._original_cwd)
        # Recovery copies go to tempfile's default dir; keep them in one this test removes.
        self.temp_root = self.make_bare_dir()
        patcher = mock.patch.object(tempfile, "tempdir", str(self.temp_root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_blocked(self, fn, *args, match: str = "", **kwargs) -> str:
        """Assert `fn(...)` raises Blocked; return the reason for further checks."""
        with self.assertRaises(snowman.Blocked) as cm:
            fn(*args, **kwargs)
        reason = str(cm.exception)
        if match:
            self.assertIn(match, reason)
        return reason

    def make_project(self, frontmatter: str = SINGLE_CONN_FRONTMATTER) -> Path:
        """Create a temp project with .snowman/context.md; return its root."""
        root = self.make_bare_dir()
        snowman_dir = root / ".snowman"
        snowman_dir.mkdir()
        (snowman_dir / "context.md").write_text(frontmatter, encoding="utf-8")
        return root

    def make_bare_dir(self) -> Path:
        """Create a temp dir with no context file; return it."""
        root = Path(tempfile.mkdtemp(prefix="snowman-test-")).resolve()
        self.addCleanup(self._rmtree, root)
        return root

    def enter(self, path: Path) -> Path:
        """chdir into `path` for tests that go through execute, stage, or main."""
        os.chdir(path)
        return path

    def umask_022(self) -> None:
        """Set umask 022, the common default, for the rest of the test."""
        self.addCleanup(os.umask, os.umask(0o022))

    def link_gitignore(self, directory: Path) -> Path:
        """Make `directory/.gitignore` a symlink to a `*` file elsewhere; return the target."""
        target = self.make_bare_dir() / "shared-ignore"
        target.write_bytes(b"*\n")
        directory.mkdir(parents=True)
        (directory / ".gitignore").symlink_to(target)
        return target

    def assert_link_refused(self, reason: str, directory: Path, target: Path) -> None:
        """Assert the refusal says what to do, and the link and its target are untouched."""
        link = directory / ".gitignore"
        self.assertIn(f"{link} is a symbolic link", reason)
        self.assertIn("Replace the link with a regular file that contains the line *.", reason)
        self.assertTrue(link.is_symlink())
        self.assertEqual(Path(os.readlink(link)), target)
        self.assertEqual(target.read_bytes(), b"*\n")
        self.assertEqual([p.name for p in directory.iterdir()], [".gitignore"])

    def assert_git_ignores(self, root: Path, path: Path) -> None:
        """Assert `path` is a file and `git check-ignore` in a repo at `root` reports it ignored."""
        self.assertTrue(path.is_file(), f"{path} is not a file")  # git ignores an absent path too
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        check = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(path)])
        self.assertEqual(check.returncode, 0, f"{path} is not ignored")  # 0 = ignored

    @staticmethod
    def _rmtree(path: Path) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


class TestStripForAnalysis(SnowmanTestCase):
    def test_block_comments_removed(self):
        self.assertNotIn("DROP", snowman.strip_for_analysis("SELECT 1 /* DROP */"))

    def test_multiline_block_comments_removed(self):
        cleaned = snowman.strip_for_analysis("SELECT 1 /* line1\nDROP TABLE t\n*/")
        self.assertNotIn("DROP", cleaned)

    def test_dash_line_comments_removed(self):
        self.assertNotIn("DELETE", snowman.strip_for_analysis("SELECT 1 -- DELETE\n"))

    def test_slash_line_comments_removed(self):
        self.assertNotIn("DELETE", snowman.strip_for_analysis("SELECT 1 // DELETE\n"))

    def test_string_literals_blanked(self):
        self.assertNotIn("DROP", snowman.strip_for_analysis("SELECT 'DROP TABLE t'"))

    def test_escaped_quotes_stay_inside_literal(self):
        cleaned = snowman.strip_for_analysis("SELECT 'it''s a DROP'")
        self.assertNotIn("DROP", cleaned)

    def test_dollar_quoted_strings_blanked(self):
        cleaned = snowman.strip_for_analysis("SELECT $$DROP TABLE t; it's$$ AS s")
        self.assertNotIn("DROP", cleaned)
        self.assertNotIn(";", cleaned)
        snowman.enforce_read_only("SELECT $$DROP$$")  # must not raise


class TestKeywordsIn(SnowmanTestCase):
    def test_returns_bare_words_case_insensitively(self):
        found = snowman.keywords_in("select 1; Drop table t; insert into x", {"DROP", "INSERT", "USE"})
        self.assertEqual(found, {"DROP", "INSERT"})

    def test_ignores_words_embedded_in_identifiers(self):
        self.assertEqual(snowman.keywords_in("SELECT created, updates FROM t", {"UPDATE", "CREATE"}), set())


class TestEnforceReadOnly(SnowmanTestCase):
    def assert_allowed(self, sql: str) -> None:
        snowman.enforce_read_only(sql)  # must not raise

    def test_allowed_leading_keywords(self):
        for sql in (
            "SELECT 1",
            "WITH t AS (SELECT 1) SELECT * FROM t",
            "SHOW TABLES IN SCHEMA x",
            "DESCRIBE TABLE t",
            "DESC TABLE t",
            "EXPLAIN SELECT 1",
        ):
            with self.subTest(sql=sql):
                self.assert_allowed(sql)

    def test_pipe_operator_projection_allowed(self):
        self.assert_allowed(
            'SHOW TERSE TABLES IN SCHEMA a.b LIMIT 50 ->> SELECT "name","kind" FROM $1'
        )
        self.assert_allowed('DESCRIBE TABLE t ->> SELECT "name","type","null?" FROM $1')

    def test_lowercase_select_allowed(self):
        self.assert_allowed("select 1")

    def test_read_functions_with_write_keyword_names_are_allowed(self):
        self.assert_allowed("SELECT REPLACE('abc', 'a', 'z'), GET(PARSE_JSON('{}'), 'a')")
        self.assert_blocked(snowman.enforce_read_only, "GET @stage file:///tmp/")
        self.assert_blocked(snowman.enforce_read_only, "CREATE OR REPLACE TABLE t (a INT)")

    def test_operational_selects_are_blocked(self):
        for sql in (
            "SELECT SYSTEM$CANCEL_QUERY('id')",
            'SELECT "SYSTEM$CANCEL_QUERY"(\'id\')',
            "SELECT system$abort_transaction(1)",
            "SELECT seq.nextval",
            'SELECT "seq"."NEXTVAL"',
            "SELECT * FROM TABLE(GETNEXTVAL(seq))",
        ):
            with self.subTest(sql=sql):
                self.assert_blocked(snowman.enforce_read_only, sql)

    def test_trailing_semicolon_is_one_statement(self):
        self.assert_allowed("SELECT 1;")

    def test_keywords_inside_strings_do_not_block(self):
        self.assert_allowed("SELECT * FROM t WHERE note = 'DROP TABLE users'")

    def test_keywords_inside_comments_do_not_block(self):
        self.assert_allowed("SELECT 1 -- TODO: DELETE old rows manually\n")

    def test_semicolon_inside_string_is_not_a_statement_break(self):
        self.assert_allowed("SELECT * FROM t WHERE note = 'a; b'")

    def test_column_names_containing_keywords_do_not_block(self):
        self.assert_allowed("SELECT created, updates FROM t")

    def test_blocks_write_leading_keywords(self):
        for sql in (
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x = 1",
            "DELETE FROM t",
            "DROP TABLE t",
            "TRUNCATE TABLE t",
            "USE DATABASE d",
            "SET x = 1",
        ):
            with self.subTest(sql=sql):
                self.assert_blocked(snowman.enforce_read_only, sql)

    def test_blocks_write_keyword_smuggled_via_cte(self):
        self.assert_blocked(
            snowman.enforce_read_only,
            "WITH t AS (SELECT 1) INSERT INTO x SELECT * FROM t",
            match="INSERT",
        )

    def test_blocks_multiple_statements(self):
        self.assert_blocked(
            snowman.enforce_read_only, "SELECT 1; SELECT 2", match="multiple statements"
        )

    def test_blocks_empty_query(self):
        self.assert_blocked(snowman.enforce_read_only, "   ", match="empty")

    def test_blocks_comment_only_query(self):
        self.assert_blocked(snowman.enforce_read_only, "-- nothing here\n")

    def test_blocks_when_no_leading_keyword(self):
        self.assert_blocked(snowman.enforce_read_only, "42", match="leading SQL keyword")

    def test_blocks_dollar_signs_split_across_two_literals(self):
        # '$$' inside two separate '...' literals must not pair up into one
        # dollar-quoted string that swallows the statements between them.
        self.assert_blocked(
            snowman.enforce_read_only,
            "SELECT 'x$$' || 'y'; DROP TABLE t; SELECT '$$z'",
        )
        self.assert_blocked(
            snowman.enforce_read_only,
            "SELECT 'a$$b'; DELETE FROM t WHERE c = '$$'",
        )

    def test_blocks_dollar_signs_split_across_two_quoted_identifiers(self):
        self.assert_blocked(
            snowman.enforce_read_only,
            'SELECT 1 AS "$$"; DROP TABLE t; SELECT 1 AS "$$"',
        )

    def test_blocks_statement_hidden_behind_backslash_escaped_quote(self):
        # Snowflake reads \' as an escaped quote, so the literal ends at the
        # second ' and the DROP is a real second statement.
        self.assert_blocked(snowman.enforce_read_only, "SELECT 'a\\'';DROP TABLE t;--'")

    def test_allows_backslash_escapes_inside_literals(self):
        self.assert_allowed("SELECT 'it\\'s'")
        self.assert_allowed("SELECT '\\\\'")

    def test_allows_dollar_quoted_literal(self):
        self.assert_allowed("SELECT $$DROP$$")

    def test_mixed_dollar_and_single_quoted_literals(self):
        sql = "SELECT $$a$$ , 'b$$c' , $$d$$"
        self.assertNotIn("$$", snowman.strip_for_analysis(sql))
        self.assert_allowed(sql)


class TestParseFrontmatter(SnowmanTestCase):
    def write_context(self, text: str) -> Path:
        root = self.make_bare_dir()
        context = root / "context.md"
        context.write_text(text, encoding="utf-8")
        return context

    def test_single_connection(self):
        context = self.write_context(SINGLE_CONN_FRONTMATTER)
        top, environments = snowman.parse_frontmatter(context)
        self.assertEqual(top.get("connection"), "analytics")
        self.assertEqual(environments, {})

    def test_environments_map(self):
        context = self.write_context(MULTI_ENV_FRONTMATTER)
        top, environments = snowman.parse_frontmatter(context)
        self.assertEqual(top.get("default_env"), "dev")
        self.assertEqual(environments["dev"]["connection"], "acme_dev")
        self.assertEqual(environments["prod"]["connection"], "acme_prod")

    def test_comments_blanks_and_quotes_tolerated(self):
        context = self.write_context(
            "---\n"
            "# a comment\n"
            "\n"
            "connection: 'quoted_conn'\n"
            "---\n"
        )
        top, _ = snowman.parse_frontmatter(context)
        self.assertEqual(top.get("connection"), "quoted_conn")

    def test_inline_comments_stripped_from_values(self):
        context = self.write_context(
            "---\n"
            "environments:  # one per account\n"
            "  dev:\n"
            "    connection: acme_dev  # key-pair auth\n"
            "  prod:\n"
            "    connection: acme_prod\n"
            "default_env: dev  # prod needs --env\n"
            "---\n"
        )
        top, environments = snowman.parse_frontmatter(context)
        self.assertEqual(top.get("default_env"), "dev")
        self.assertEqual(environments["dev"]["connection"], "acme_dev")
        self.assertEqual(environments["prod"]["connection"], "acme_prod")

    def test_missing_frontmatter_blocks(self):
        context = self.write_context("# just a heading\n")
        self.assert_blocked(snowman.parse_frontmatter, context, match="frontmatter")

    def test_dashes_inside_a_value_do_not_close_the_frontmatter(self):
        context = self.write_context("---\nconnection: analytics---dev\n---\n")
        top, _ = snowman.parse_frontmatter(context)
        self.assertEqual(top.get("connection"), "analytics---dev")

    def test_missing_closing_line_blocks(self):
        context = self.write_context(
            "---\nconnection: analytics\n# Notes\nconnection: from_the_notes\n"
        )
        self.assert_blocked(snowman.parse_frontmatter, context, match="no closing `---`")

    def test_delimiters_must_equal_three_dashes(self):
        cases = {
            "opening ---suffix": ("---suffix\nconnection: analytics\n---\n", "no YAML frontmatter"),
            "closing with a trailing space": ("---\nconnection: analytics\n--- \n", "no closing `---`"),
        }
        for name, (text, match) in cases.items():
            with self.subTest(name):
                context = self.write_context(text)
                self.assert_blocked(snowman.parse_frontmatter, context, match=match)

    def test_crlf_line_endings_parse(self):
        context = self.write_context("---\r\nconnection: analytics\r\n---\r\n# notes\r\n")
        top, _ = snowman.parse_frontmatter(context)
        self.assertEqual(top.get("connection"), "analytics")

    def test_line_separator_in_a_comment_does_not_start_a_line(self):
        cases = {
            "closes the frontmatter": "---\n# pasted\u2028---\nconnection: analytics\n---\n",
            "sets the connection": "---\nconnection: analytics\n# pasted\u2028connection: prod\n---\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                top, _ = snowman.parse_frontmatter(self.write_context(text))
                self.assertEqual(top.get("connection"), "analytics")

    def test_nested_keys_do_not_replace_environment_fields(self):
        context = self.write_context(
            "---\n"
            "environments:\n"
            "  dev:\n"
            "    extras:\n"
            "      connection: nested_dev\n"
            "    connection: acme_dev\n"
            "  prod:\n"
            "    connection: acme_prod\n"
            "    extras:\n"
            "      connection: nested_prod\n"
            "default_env: dev\n"
            "---\n"
        )
        _, environments = snowman.parse_frontmatter(context)
        self.assertEqual(environments["dev"], {"connection": "acme_dev"})
        self.assertEqual(environments["prod"], {"connection": "acme_prod"})

    def test_environment_name_with_a_value_blocks(self):
        context = self.write_context(
            "---\n"
            "environments:\n"
            "  dev:\n"
            "    connection: acme_dev\n"
            "  prod: &production\n"
            "    connection: acme_prod\n"
            "default_env: dev\n"
            "---\n"
        )
        self.assert_blocked(snowman.parse_frontmatter, context, match="'prod'")


class TestResolveTarget(SnowmanTestCase):
    """resolve_target: context lookup, frontmatter, connection choice, .env."""

    def resolve(self, start: Path, env: str | None = None, **kwargs) -> snowman.Target:
        return snowman.resolve_target(start, None, env, **kwargs)

    def test_legacy_single_connection(self):
        root = self.make_project(SINGLE_CONN_FRONTMATTER)
        self.assertEqual(
            self.resolve(root),
            snowman.Target("analytics", None, root, root / ".snowman", None),
        )

    def test_reads_the_frontmatter_once(self):
        root = self.make_project(MULTI_ENV_FRONTMATTER)
        with mock.patch.object(
            snowman, "parse_frontmatter", wraps=snowman.parse_frontmatter
        ) as parse:
            self.resolve(root, "prod")
        self.assertEqual(parse.call_count, 1)

    def test_walks_up_from_a_nested_start(self):
        root = self.make_project()
        nested = root / "models" / "marts"
        nested.mkdir(parents=True)
        target = self.resolve(nested)
        self.assertEqual(target.project_root, root)
        self.assertEqual(target.snowman_dir, root / ".snowman")

    def test_blocks_without_bootstrap(self):
        root = self.make_bare_dir()
        self.assert_blocked(self.resolve, root, match="bootstrap")

    def test_legacy_rejects_env_flag(self):
        root = self.make_project(SINGLE_CONN_FRONTMATTER)
        self.assert_blocked(self.resolve, root, "dev", match="--env was given")

    def test_legacy_missing_connection_blocks(self):
        root = self.make_project("---\nowner: someone\n---\n")
        self.assert_blocked(self.resolve, root, match="no `connection:`")

    def test_multi_env_explicit(self):
        root = self.make_project(MULTI_ENV_FRONTMATTER)
        target = self.resolve(root, "prod")
        self.assertEqual((target.connection, target.environment), ("acme_prod", "prod"))

    def test_multi_env_falls_back_to_default(self):
        root = self.make_project(MULTI_ENV_FRONTMATTER)
        target = self.resolve(root)
        self.assertEqual((target.connection, target.environment), ("acme_dev", "dev"))

    def test_multi_env_unknown_env_blocks(self):
        root = self.make_project(MULTI_ENV_FRONTMATTER)
        self.assert_blocked(self.resolve, root, "staging", match="unknown environment")

    def test_multi_env_no_default_and_no_flag_blocks(self):
        root = self.make_project("---\nenvironments:\n  dev:\n    connection: acme_dev\n---\n")
        self.assert_blocked(self.resolve, root, match="default_env")

    def test_both_forms_blocks(self):
        root = self.make_project(
            "---\n"
            "connection: legacy\n"
            "environments:\n"
            "  dev:\n"
            "    connection: acme_dev\n"
            "default_env: dev\n"
            "---\n"
        )
        self.assert_blocked(self.resolve, root, match="exactly one form")

    def test_stage_requires_explicit_env(self):
        root = self.make_project(MULTI_ENV_FRONTMATTER)
        self.assert_blocked(self.resolve, root, for_stage=True, match="requires --env")

    def test_stage_with_env_resolves(self):
        root = self.make_project(MULTI_ENV_FRONTMATTER)
        target = self.resolve(root, "prod", for_stage=True)
        self.assertEqual(target.environment, "prod")

    def test_env_without_connection_value_blocks(self):
        root = self.make_project(
            "---\nenvironments:\n  dev:\n    role: analyst\ndefault_env: dev\n---\n"
        )
        self.assert_blocked(self.resolve, root, match="no `connection:` value")

    def test_connection_override_skips_context(self):
        root = self.make_bare_dir()
        target = snowman.resolve_target(root, "bootstrap_conn", None)
        self.assertEqual(target, snowman.Target("bootstrap_conn", None, None, None, None))

    def test_connection_override_blocks_in_a_configured_project(self):
        root = self.make_project()
        nested = root / "models" / "marts"
        nested.mkdir(parents=True)
        for start in (root, nested):
            with self.subTest(start=start):
                self.assert_blocked(
                    snowman.resolve_target, start, "other_conn", None, match="bootstrap only"
                )

    def test_empty_connection_override_blocks(self):
        root = self.make_project()
        self.assert_blocked(snowman.resolve_target, root, "", None, match="--connection")

    def test_empty_connection_override_blocks_without_context(self):
        root = self.make_bare_dir()
        self.assert_blocked(snowman.resolve_target, root, "", None, match="empty name")

    def test_env_file_at_project_root(self):
        root = self.make_project()
        (root / ".env").write_text("X=1\n", encoding="utf-8")
        nested = root / "a"
        nested.mkdir()
        self.assertEqual(self.resolve(nested).env_file, root / ".env")

    def test_env_file_above_project_root_is_found(self):
        parent = self.make_bare_dir()
        (parent / ".env").write_text("X=1\n", encoding="utf-8")
        root = parent / "project"
        (root / ".snowman").mkdir(parents=True)
        (root / ".snowman" / "context.md").write_text(SINGLE_CONN_FRONTMATTER, encoding="utf-8")
        self.assertEqual(self.resolve(root).env_file, parent / ".env")

    def test_env_file_below_project_root_is_ignored(self):
        root = self.make_project()
        nested = root / "a"
        nested.mkdir()
        (nested / ".env").write_text("X=1\n", encoding="utf-8")
        self.assertIsNone(self.resolve(nested).env_file)

    def test_bootstrap_mode_walks_up_for_env_file(self):
        root = self.make_bare_dir()
        (root / ".env").write_text("X=1\n", encoding="utf-8")
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        target = snowman.resolve_target(nested, "c", None)
        self.assertEqual(target.env_file, root / ".env")


class TestEnvAlias(SnowmanTestCase):
    """`prd` and `prod` resolve to each other only when one is undefined."""

    PROD_ONLY = MULTI_ENV_FRONTMATTER
    PRD_ONLY = MULTI_ENV_FRONTMATTER.replace("  prod:\n", "  prd:\n")
    BOTH = MULTI_ENV_FRONTMATTER.replace(
        "default_env:", "  prd:\n    connection: acme_prd\ndefault_env:"
    )

    def resolve(self, frontmatter: str, env: str | None = None, **kwargs) -> tuple:
        """Resolve in a temp project; return (connection, environment, stderr)."""
        root = self.make_project(frontmatter)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            target = snowman.resolve_target(root, None, env, **kwargs)
        return target.connection, target.environment, stderr.getvalue()

    def test_prd_resolves_to_prod_when_only_prod_is_defined(self):
        connection, environment, _ = self.resolve(self.PROD_ONLY, "prd")
        self.assertEqual((connection, environment), ("acme_prod", "prod"))

    def test_prod_resolves_to_prd_when_only_prd_is_defined(self):
        connection, environment, _ = self.resolve(self.PRD_ONLY, "prod")
        self.assertEqual((connection, environment), ("acme_prod", "prd"))

    def test_alias_is_announced_in_one_stderr_line(self):
        for frontmatter, requested, resolved in (
            (self.PROD_ONLY, "prd", "prod"),
            (self.PRD_ONLY, "prod", "prd"),
        ):
            with self.subTest(requested=requested):
                _, _, err = self.resolve(frontmatter, requested)
                self.assertEqual(err.count("\n"), 1, err)
                self.assertTrue(err.startswith(f"# environment: '{requested}' is not defined"), err)
                self.assertTrue(err.endswith(f"using its alias '{resolved}'\n"), err)

    def test_exact_match_wins_when_both_are_defined(self):
        for requested, connection in (("prd", "acme_prd"), ("prod", "acme_prod")):
            with self.subTest(requested=requested):
                self.assertEqual(
                    self.resolve(self.BOTH, requested), (connection, requested, "")
                )

    def test_exact_match_prints_no_note(self):
        self.assertEqual(self.resolve(self.PROD_ONLY, "prod"), ("acme_prod", "prod", ""))

    def test_neither_defined_still_blocks(self):
        root = self.make_project(
            "---\nenvironments:\n  dev:\n    connection: acme_dev\ndefault_env: dev\n---\n"
        )
        for requested in ("prd", "prod"):
            with self.subTest(requested=requested):
                reason = self.assert_blocked(
                    snowman.resolve_target, root, None, requested, match="unknown environment"
                )
                self.assertIn(repr(requested), reason)

    def test_only_prd_and_prod_are_aliased(self):
        root = self.make_project(self.PROD_ONLY)
        for requested in ("production", "PRD", "development", "stg"):
            with self.subTest(requested=requested):
                self.assert_blocked(
                    snowman.resolve_target, root, None, requested, match="unknown environment"
                )

    def test_default_env_resolves_through_the_alias(self):
        frontmatter = self.PROD_ONLY.replace("default_env: dev", "default_env: prd")
        connection, environment, err = self.resolve(frontmatter)
        self.assertEqual((connection, environment), ("acme_prod", "prod"))
        self.assertIn("using its alias 'prod'", err)

    def test_aliased_default_env_does_not_satisfy_staging(self):
        # Staging keeps requiring an explicit --env, whichever name default_env uses.
        root = self.make_project(self.PROD_ONLY.replace("default_env: dev", "default_env: prd"))
        self.assert_blocked(
            snowman.resolve_target, root, None, None, for_stage=True, match="requires --env"
        )

    def test_staging_through_the_alias_matches_the_defined_name(self):
        # The staged file must name the real target, so an alias cannot hide it.
        fixed = datetime(2026, 1, 2, 3, 4, 5)
        staged = {}
        for requested in ("prod", "prd"):
            root = self.enter(self.make_project(self.PROD_ONLY))
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                self.assertEqual(snowman.stage("DROP TABLE t", "teardown", requested, now=fixed), 0)
            [path] = (root / ".snowman" / "staged").glob("*.sql")
            body = path.read_text(encoding="utf-8").replace(str(root), "<root>")
            staged[requested] = (path.name, body, stderr.getvalue())
        self.assertEqual(staged["prd"][:2], staged["prod"][:2])
        name, body, _ = staged["prd"]
        self.assertIn("prod__teardown", name)
        self.assertIn("-- target environment: prod (connection: acme_prod)", body)
        self.assertIn("-- WARNING: contains DROP", body)
        self.assertNotIn("alias", staged["prod"][2])
        self.assertIn("using its alias 'prod'", staged["prd"][2])

    def test_query_through_the_alias_keeps_the_read_only_guard(self):
        self.enter(self.make_project(self.PROD_ONLY))
        snow = fake_snow({})
        with mock.patch.object(snowman, "run_snow", snow):
            self.assert_blocked(snowman.execute, "DROP TABLE t", env="prd", match="non-read-only")
        self.assertEqual(snow.calls, [])

    def test_main_queries_the_aliased_connection_and_says_so(self):
        self.enter(self.make_project(self.PROD_ONLY))
        snow = fake_snow({"sql": OK})
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(snowman, "run_snow", snow), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = snowman.main(["snowman.py", "--env", "prd", "SELECT 1"])
        self.assertEqual(code, 0)
        [(args, _)] = snow.calls
        self.assertEqual(args[args.index("--connection") + 1], "acme_prod")
        self.assertIn("using its alias 'prod'", stderr.getvalue())
        self.assertNotIn("alias", stdout.getvalue())

    def test_main_still_blocks_an_unknown_environment(self):
        self.enter(self.make_project(self.PRD_ONLY))
        snow = fake_snow({})
        stderr = io.StringIO()
        with mock.patch.object(snowman, "run_snow", snow), contextlib.redirect_stderr(stderr):
            code = snowman.main(["snowman.py", "--env", "production", "SELECT 1"])
        self.assertEqual(code, snowman.BLOCK)
        self.assertTrue(stderr.getvalue().startswith("BLOCKED: unknown environment 'production'"))
        self.assertEqual(snow.calls, [])


class TestDotenv(SnowmanTestCase):
    def write_env(self, text: str) -> Path:
        root = self.make_bare_dir()
        env_file = root / ".env"
        env_file.write_text(text, encoding="utf-8")
        return env_file

    def test_parses_values_quotes_and_export(self):
        env_file = self.write_env(
            "# comment\n"
            "\n"
            "PLAIN=value\n"
            "export EXPORTED=yes\n"
            "SINGLE='quoted one'\n"
            'DOUBLE="quoted two"\n'
        )
        parsed = snowman.load_dotenv(env_file)
        self.assertEqual(parsed["PLAIN"], "value")
        self.assertEqual(parsed["EXPORTED"], "yes")
        self.assertEqual(parsed["SINGLE"], "quoted one")
        self.assertEqual(parsed["DOUBLE"], "quoted two")

    def test_inline_comment_dropped_from_unquoted_value(self):
        env_file = self.write_env("PRIVATE_KEY_PASSPHRASE=secret  # prod key\n")
        self.assertEqual(snowman.load_dotenv(env_file)["PRIVATE_KEY_PASSPHRASE"], "secret")

    def test_hash_inside_quoted_value_kept(self):
        env_file = self.write_env('A="se #cret"\nB=\'x # y\'\nC=pa#ss\n')
        parsed = snowman.load_dotenv(env_file)
        self.assertEqual(parsed, {"A": "se #cret", "B": "x # y", "C": "pa#ss"})

    def test_inline_comment_dropped_after_quoted_value(self):
        env_file = self.write_env('A="q" # c\n')
        self.assertEqual(snowman.load_dotenv(env_file)["A"], "q")

    def test_comment_only_value_is_empty(self):
        env_file = self.write_env("B=  # only\n")
        self.assertEqual(snowman.load_dotenv(env_file)["B"], "")

    def test_malformed_lines_skipped(self):
        env_file = self.write_env("no_equals_sign\n123BAD=x\nGOOD=1\n")
        parsed = snowman.load_dotenv(env_file)
        self.assertEqual(parsed, {"GOOD": "1"})

    def test_line_separator_in_a_comment_does_not_start_a_line(self):
        env_file = self.write_env("# pasted\u2028SNOWFLAKE_ACCOUNT=other\nGOOD=1\r\n")
        self.assertEqual(snowman.load_dotenv(env_file), {"GOOD": "1"})

    def test_process_env_wins_over_dotenv(self):
        env_file = self.write_env("SNOWMAN_TEST_VAR=from_dotenv\nSNOWMAN_ONLY=relayed\n")
        with mock.patch.dict(os.environ, {"SNOWMAN_TEST_VAR": "from_process"}):
            merged = snowman.snow_env(env_file)
        self.assertEqual(merged["SNOWMAN_TEST_VAR"], "from_process")
        self.assertEqual(merged["SNOWMAN_ONLY"], "relayed")

    def test_no_env_file_returns_process_env(self):
        merged = snowman.snow_env(None)
        self.assertEqual(merged, dict(os.environ))


class TestFindUp(SnowmanTestCase):
    def test_walks_up(self):
        root = self.make_bare_dir()
        (root / ".env").write_text("X=1\n", encoding="utf-8")
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(snowman.find_up(nested, ".env"), root / ".env")

    def test_nested_relative_path(self):
        root = self.make_project()
        nested = root / "a"
        nested.mkdir()
        self.assertEqual(
            snowman.find_up(nested, ".snowman/context.md"), root / ".snowman" / "context.md"
        )

    def test_none_when_absent(self):
        root = self.make_bare_dir()
        self.assertIsNone(snowman.find_up(root, ".env"))


class TestStage(SnowmanTestCase):
    def run_stage(self, *args, **kwargs) -> str:
        return self.run_stage_with_stderr(*args, **kwargs)[0]

    def run_stage_with_stderr(self, *args, **kwargs) -> tuple[str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(snowman.stage(*args, **kwargs), 0)
        return stdout.getvalue(), stderr.getvalue()

    def staged_files(self, root: Path) -> list:
        return sorted((root / ".snowman" / "staged").glob("*.sql"))

    def make_named_project(self, name: str, frontmatter: str = SINGLE_CONN_FRONTMATTER) -> Path:
        """Create a project in a directory called `name`; skip if the filesystem refuses it."""
        root = self.make_bare_dir() / name
        try:
            (root / ".snowman").mkdir(parents=True)
        except OSError as exc:
            self.skipTest(f"filesystem refuses {name!r}: {exc}")
        (root / ".snowman" / "context.md").write_text(frontmatter, encoding="utf-8")
        return root

    def test_stages_file_without_executing(self):
        root = self.enter(self.make_project())
        output = self.run_stage("CREATE TABLE t (id INT)", "create-t", None)
        self.assertIn("STAGED (not executed)", output)
        files = self.staged_files(root)
        self.assertEqual(len(files), 1)
        body = files[0].read_text(encoding="utf-8")
        self.assertIn("-- staged by snowman, NOT executed", body)
        self.assertIn("-- purpose: create-t", body)
        self.assertIn("snow sql -f", body)
        self.assertIn("--connection analytics", body)
        self.assertIn("CREATE TABLE t (id INT)", body)

    def test_run_command_disables_templating_and_keeps_ampersand(self):
        root = self.enter(self.make_project())
        output = self.run_stage("UPDATE t SET brand = 'F&W'", "fix-brand", None)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        self.assertIn("UPDATE t SET brand = 'F&W'", body)
        run_line = next(line for line in output.splitlines() if line.startswith("run with: "))
        run_args = shlex.split(run_line.removeprefix("run with: "))
        self.assertEqual(run_args[run_args.index("--enable-templating") + 1], "NONE")
        self.assertIn(f"-- run with: {shlex.join(run_args)}", body)

    def test_printed_path_is_absolute_from_a_subdirectory(self):
        # The space makes the run command's path need shell quoting.
        root = self.make_named_project("my project")
        (root / "models").mkdir()
        self.enter(root / "models")
        output = self.run_stage("SELECT 1", "noop", None)
        [staged] = self.staged_files(root)
        self.assertIn(f"STAGED (not executed): {staged}\n", output)
        run_line = next(line for line in output.splitlines() if line.startswith("run with: "))
        run_args = shlex.split(run_line.removeprefix("run with: "))
        self.assertEqual(run_args[run_args.index("-f") + 1], str(staged))

    def test_line_break_in_the_path_stays_inside_the_header_comment(self):
        root = self.enter(self.make_named_project("Quarter\nOne"))
        self.run_stage("SELECT 1", "noop", None)
        header, sql = self.staged_files(root)[0].read_text(encoding="utf-8").split("\n\n", 1)
        self.assertIn("Quarter", header)
        self.assertTrue(all(line.startswith("-- ") for line in header.split("\n")), header)
        self.assertEqual(sql, "SELECT 1\n")

    def test_unicode_line_separator_in_env_name_stays_verbatim_in_header(self):
        env = "QA\u2028Blue"
        root = self.enter(self.make_project(MULTI_ENV_FRONTMATTER.replace("  dev:", f"  {env}:")))
        self.run_stage("SELECT 1", "noop", env)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        self.assertIn(f"-- target environment: {env} (connection: acme_dev)\n", body)

    def test_accepts_multi_statement_dml(self):
        root = self.enter(self.make_project())
        self.run_stage("INSERT INTO t VALUES (1); UPDATE t SET x = 2;", "backfill", None)
        self.assertEqual(len(self.staged_files(root)), 1)

    def test_destructive_keywords_warn_but_never_block(self):
        root = self.enter(self.make_project())
        _, err = self.run_stage_with_stderr("DROP TABLE old; TRUNCATE TABLE older;", "teardown", None)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        warning = "WARNING: contains DROP, TRUNCATE. Review carefully before running"
        self.assertIn(f"-- {warning}", body)
        self.assertEqual(err, f"{warning}\n")

    def test_non_destructive_script_has_no_warning(self):
        root = self.enter(self.make_project())
        _, err = self.run_stage_with_stderr("INSERT INTO t VALUES (1)", "insert-row", None)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        self.assertNotIn("WARNING", body)
        self.assertEqual(err, "")

    def test_maintains_gitignore(self):
        root = self.enter(self.make_project())
        self.run_stage("SELECT 1", "noop", None)
        gitignore = root / ".snowman" / "staged" / ".gitignore"
        self.assertEqual(gitignore.read_text(encoding="utf-8"), "*\n")

    def test_narrower_gitignore_gets_a_catch_all_rule(self):
        root = self.enter(self.make_project())
        gitignore = root / ".snowman" / "staged" / ".gitignore"
        gitignore.parent.mkdir()
        gitignore.write_bytes(b"# caf\xe9 notes\n*.tmp\n *")
        self.run_stage("SELECT 1", "noop", None)
        [staged] = self.staged_files(root)
        self.assert_git_ignores(root, staged)
        self.assertEqual(gitignore.read_bytes(), b"# caf\xe9 notes\n*.tmp\n *\n*\n")

    def test_staged_file_and_directory_are_owner_only(self):
        self.umask_022()
        root = self.enter(self.make_project())
        (root / ".snowman" / "staged").mkdir(mode=0o755)
        self.run_stage("SELECT 1", "noop", None)
        [staged] = self.staged_files(root)
        self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
        self.assertEqual(staged.parent.stat().st_mode & 0o777, 0o700)

    def test_failed_write_leaves_no_staged_file(self):
        # A lone surrogate, as from a non-UTF-8 argv byte, fails UTF-8 encoding.
        root = self.enter(self.make_project())
        with self.assertRaises(UnicodeEncodeError):
            snowman.stage("SELECT '\ud800'", "noop", None)
        self.assertEqual(sorted(p.name for p in (root / ".snowman" / "staged").iterdir()),
                         [".gitignore"])

    def test_interrupt_before_the_first_write_leaves_no_staged_file(self):
        root = self.enter(self.make_project())
        with mock.patch.object(snowman.shlex, "join", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            snowman.stage("SELECT 1", "noop", None)
        self.assertEqual(self.staged_files(root), [])

    def test_linked_gitignore_blocks_staging_and_is_left_alone(self):
        root = self.enter(self.make_project())
        staged = root / ".snowman" / "staged"
        target = self.link_gitignore(staged)
        reason = self.assert_blocked(snowman.stage, "SELECT 1", "noop", None)
        self.assert_link_refused(reason, staged, target)

    def test_empty_script_blocks(self):
        self.enter(self.make_project())
        self.assert_blocked(snowman.stage, "   ", "noop", None, match="empty")

    def test_name_normalised_to_slug(self):
        root = self.enter(self.make_project())
        self.run_stage("SELECT 1", "Add  User--Table!", None)
        self.assertIn("add-user-table", self.staged_files(root)[0].name)

    def test_unusable_name_blocks(self):
        self.enter(self.make_project())
        self.assert_blocked(snowman.stage, "SELECT 1", "!!!", None, match="empty slug")

    def test_multi_env_requires_env_flag(self):
        self.enter(self.make_project(MULTI_ENV_FRONTMATTER))
        self.assert_blocked(
            snowman.stage, "SELECT 1", "noop", None, match="requires --env"
        )

    def test_multi_env_stamps_env_in_filename_and_header(self):
        root = self.enter(self.make_project(MULTI_ENV_FRONTMATTER))
        self.run_stage("SELECT 1", "noop", "prod")
        staged = self.staged_files(root)[0]
        self.assertIn("prod__noop", staged.name)
        body = staged.read_text(encoding="utf-8")
        self.assertIn("-- target environment: prod (connection: acme_prod)", body)

    def test_env_name_with_slash_is_slugged_only_in_the_filename(self):
        root = self.enter(self.make_project(MULTI_ENV_FRONTMATTER.replace("  dev:", "  team/dev:")))
        self.run_stage("SELECT 1", "noop", "team/dev", now=datetime(2026, 1, 2, 3, 4, 5))
        [staged] = self.staged_files(root)
        self.assertEqual(staged.name, "20260102-030405__team-dev__noop.sql")
        body = staged.read_text(encoding="utf-8")
        self.assertIn("-- target environment: team/dev (connection: acme_dev)", body)

    def test_filename_collision_bumps_suffix(self):
        root = self.enter(self.make_project())
        fixed = datetime(2026, 1, 2, 3, 4, 5)
        self.run_stage("SELECT 1", "noop", None, now=fixed)
        self.run_stage("SELECT 2", "noop", None, now=fixed)
        names = [f.name for f in self.staged_files(root)]
        self.assertEqual(
            names,
            ["20260102-030405__noop-1.sql", "20260102-030405__noop.sql"],
        )

    def test_concurrent_writer_is_not_overwritten(self):
        # Patching exists() reproduces the old exists()-then-write race, where
        # another writer took the name after the check.
        root = self.enter(self.make_project())
        staged = root / ".snowman" / "staged"
        staged.mkdir()
        theirs = staged / "20260102-030405__noop.sql"
        theirs.write_text("theirs\n", encoding="utf-8")
        with mock.patch.object(Path, "exists", return_value=False):
            self.run_stage("SELECT 2", "noop", None, now=datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(theirs.read_text(encoding="utf-8"), "theirs\n")
        self.assertIn("SELECT 2", (staged / "20260102-030405__noop-1.sql").read_text(encoding="utf-8"))

    def test_stage_blocks_without_context(self):
        self.enter(self.make_bare_dir())
        self.assert_blocked(snowman.stage, "SELECT 1", "noop", None, match="bootstrap")


class TestRenderRows(SnowmanTestCase):
    """Output shaping: CSV by default, nulls as empty cells, nested as JSON."""

    def test_csv_header_then_rows(self):
        text, footers, _ = snowman.render_rows(
            [{"A": 1, "B": "x"}, {"A": 2, "B": "y"}], fmt="csv", max_rows=50, max_cell=200, max_output=16000
        )
        self.assertEqual(text, "A,B\n1,x\n2,y\n")
        self.assertEqual(footers, [])

    def test_null_renders_empty_with_footer(self):
        text, footers, _ = snowman.render_rows(
            [{"A": None, "B": "x"}], fmt="csv", max_rows=50, max_cell=200, max_output=16000
        )
        self.assertEqual(text, "A,B\n,x\n")
        self.assertEqual(footers, ["# empty cells are NULL"])

    def test_empty_string_is_quoted_and_noted(self):
        text, footers, _ = snowman.render_rows(
            [{"A": "", "B": "x"}], fmt="csv", max_rows=50, max_cell=200, max_output=16000
        )
        self.assertEqual(text, 'A,B\n"",x\n')
        self.assertEqual(footers, ['# "" is an empty string'])

    def test_null_and_empty_string_share_one_footer(self):
        text, footers, _ = snowman.render_rows(
            [{"A": "", "B": None}, {"A": None, "B": ""}], fmt="csv", max_rows=50, max_cell=200, max_output=16000
        )
        self.assertEqual(text, 'A,B\n"",\n,""\n')
        self.assertEqual(footers, ['# empty cells are NULL; "" is an empty string'])

    def test_json_mode_keeps_null_and_empty_string_distinct_without_footer(self):
        text, footers, _ = snowman.render_rows(
            [{"A": "", "B": None}], fmt="json", max_rows=50, max_cell=200
        )
        self.assertEqual(text, '[{"A":"","B":null}]\n')
        self.assertEqual(footers, [])

    def test_cells_with_comma_quote_or_newline_are_quoted(self):
        text, _, _ = snowman.render_rows(
            [{"A": "a,b", "B": 'say "hi"', "C": "l1\nl2", "D": "plain"}],
            fmt="csv", max_rows=50, max_cell=200,
        )
        self.assertEqual(text, 'A,B,C,D\n"a,b","say ""hi""","l1\nl2",plain\n')

    def test_types_footer_lists_only_types_csv_cannot_show(self):
        describe = [
            {"name": "ID", "type": "NUMBER(38,0)"},
            {"name": "AMOUNT", "type": "NUMBER(10,2)"},
            {"name": "NAME", "type": "VARCHAR(16777216)"},
            {"name": "OK", "type": "BOOLEAN"},
            {"name": "TS", "type": "TIMESTAMP_NTZ(9)"},
            {"name": "D", "type": "DATE"},
            {"name": "F", "type": "FLOAT"},
            {"name": "O", "type": "OBJECT"},
            {"name": "V", "type": "VARIANT"},
        ]
        _, footers, _ = snowman.render_rows(
            [{"ID": 1}], fmt="csv", max_rows=50, max_cell=200, types=describe
        )
        self.assertEqual(
            footers,
            ["# types: AMOUNT NUMBER(10,2), TS TIMESTAMP_NTZ(9), D DATE, F FLOAT, "
             "O OBJECT, V VARIANT"],
        )

    def test_types_footer_absent_when_all_plain_or_no_describe(self):
        describe = [{"name": "ID", "type": "NUMBER"}, {"name": "S", "type": "VARCHAR(10)"}]
        _, footers, _ = snowman.render_rows(
            [{"ID": 1}], fmt="csv", max_rows=50, max_cell=200, types=describe
        )
        self.assertEqual(footers, [])
        _, footers, _ = snowman.render_rows([{"ID": 1}], fmt="csv", max_rows=50, max_cell=200)
        self.assertEqual(footers, [])

    def test_nested_values_render_as_compact_json(self):
        text, _, _ = snowman.render_rows(
            [{"O": {"k": [1, 2]}, "L": ["a", None]}], fmt="csv", max_rows=50, max_cell=200, max_output=16000
        )
        self.assertEqual(text, 'O,L\n"{""k"":[1,2]}","[""a"",null]"\n')

    def test_numbers_untouched_and_booleans_lowercase(self):
        text, _, _ = snowman.render_rows(
            [{"F": 3.14159265358979, "I": 7, "B": True, "C": False}],
            fmt="csv", max_rows=50, max_cell=200,
        )
        self.assertEqual(text, "F,I,B,C\n3.14159265358979,7,true,false\n")

    def test_first_cell_starting_with_hash_is_quoted(self):
        text, _, _ = snowman.render_rows(
            [{"TAG": "#top", "N": 1}, {"TAG": "plain", "N": 2}, {"TAG": "#", "N": 3}],
            fmt="csv", max_rows=50, max_cell=200,
        )
        self.assertEqual(text, 'TAG,N\n"#top",1\nplain,2\n"#",3\n')

    def test_first_cell_hash_quoted_in_single_column_result(self):
        text, _, _ = snowman.render_rows([{"TAG": "#only"}], fmt="csv", max_rows=50, max_cell=200)
        self.assertEqual(text, 'TAG\n"#only"\n')

    def test_empty_result_prints_zero_rows_note(self):
        text, footers, _ = snowman.render_rows([], fmt="csv", max_rows=50, max_cell=200)
        self.assertEqual(text, "")
        self.assertEqual(footers, ["# 0 rows"])

    def test_cell_truncation_suffix_and_footer(self):
        text, footers, _ = snowman.render_rows(
            [{"S": "abcdefghij"}], fmt="csv", max_rows=50, max_cell=4
        )
        self.assertEqual(text, "S\nabcd…(+6 chars)\n")
        self.assertEqual(
            footers, ["# some cells truncated to 4 chars; pass --max-cell 0 for full values"]
        )

    def test_truncate_cell_exact(self):
        self.assertEqual(snowman.truncate_cell("abcdefghij", 4), ("abcd…(+6 chars)", True))
        self.assertEqual(snowman.truncate_cell("abcd", 4), ("abcd", False))
        self.assertEqual(snowman.truncate_cell("abcdefghij", 0), ("abcdefghij", False))

    def test_row_cap_footer(self):
        rows = [{"N": i} for i in range(1203)]
        text, footers, _ = snowman.render_rows(rows, fmt="csv", max_rows=50, max_cell=200)
        self.assertEqual(text.count("\n"), 51)  # header + 50 rows
        self.assertEqual(
            footers,
            ["# showing 50 of 1203 rows; narrow the query or raise --max-rows/--max-output"],
        )

    def test_max_rows_zero_is_unlimited(self):
        rows = [{"N": i} for i in range(1203)]
        text, footers, _ = snowman.render_rows(rows, fmt="csv", max_rows=0, max_cell=200)
        self.assertEqual(text.count("\n"), 1204)
        self.assertEqual(footers, [])

    def test_footer_order_types_null_truncation_cap(self):
        rows = [{"S": "abcdefghij", "N": None}] * 3
        _, footers, _ = snowman.render_rows(
            rows, fmt="csv", max_rows=2, max_cell=4,
            types=[{"name": "N", "type": "DATE"}],
        )
        self.assertEqual(
            [f.split(";")[0] for f in footers],
            ["# types: N DATE",
             "# empty cells are NULL",
             "# some cells truncated to 4 chars",
             "# showing 2 of 3 rows"],
        )
        self.assertEqual(footers[-1], "# showing 2 of 3 rows; narrow the query or raise --max-rows/--max-output")

    def test_json_output_is_compact_and_parseable(self):
        rows = [{"O": {"k": 1}, "S": "abcdefghij", "N": None}]
        text, footers, _ = snowman.render_rows(rows, fmt="json", max_rows=50, max_cell=4)
        self.assertEqual(text, '[{"O":"{\\"k\\"…(+3 chars)","S":"abcd…(+6 chars)","N":null}]\n')
        self.assertEqual(json.loads(text)[0]["O"], '{"k"…(+3 chars)')
        self.assertEqual(
            footers, ["# some cells truncated to 4 chars; pass --max-cell 0 for full values",
                      "# truncated nested JSON cells are shown as JSON text strings"]
        )


PANEL_STDERR = (
    "╭─ Error ──────────────────────────────────────────────────────────────────────╮\n"
    "│ 002003 (42S02): 01c6d3f7-020b-2af1-0004-fc4708a01dca: SQL compilation error: │\n"
    "│ Object 'NONEXISTENT_TABLE_XYZ' does not exist or not authorized.             │\n"
    "╰──────────────────────────────────────────────────────────────────────────────╯\n"
)
PANEL_CLEANED = (
    "ERROR: 002003 (42S02): 01c6d3f7-020b-2af1-0004-fc4708a01dca: SQL compilation "
    "error: Object 'NONEXISTENT_TABLE_XYZ' does not exist or not authorized.\n"
)


class TestCleanSnowStderr(SnowmanTestCase):
    def test_rich_panel_becomes_one_error_line(self):
        self.assertEqual(snowman.clean_snow_stderr(PANEL_STDERR), PANEL_CLEANED)

    def test_two_consecutive_panels_become_two_error_lines(self):
        second = (
            "╭─ Error ───────────────╮\n"
            "│ second failure here   │\n"
            "╰───────────────────────╯\n"
        )
        self.assertEqual(
            snowman.clean_snow_stderr(PANEL_STDERR + second),
            PANEL_CLEANED + "ERROR: second failure here\n",
        )

    def test_blank_panel_lines_do_not_double_space(self):
        panel = (
            "╭─ Error ───────────────╮\n"
            "│ first part            │\n"
            "│                       │\n"
            "│ second part           │\n"
            "╰───────────────────────╯\n"
        )
        self.assertEqual(snowman.clean_snow_stderr(panel), "ERROR: first part second part\n")

    def test_plain_stderr_passes_through(self):
        self.assertEqual(snowman.clean_snow_stderr("some snow error\n"), "some snow error\n")

    def test_empty_stderr_stays_empty(self):
        self.assertEqual(snowman.clean_snow_stderr(""), "")


class TestCreatePrivateFile(SnowmanTestCase):
    def test_timestamp_base_and_suffix(self):
        root = self.make_bare_dir()
        with snowman.create_private_file(root, "noop", ".sql", datetime(2026, 1, 2, 3, 4, 5)) as (path, _):
            pass
        self.assertEqual(path, root / "20260102-030405__noop.sql")
        self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_bumps_while_the_path_exists(self):
        root = self.make_bare_dir()
        now = datetime(2026, 1, 2, 3, 4, 5)
        (root / "20260102-030405__noop.sql").touch()
        (root / "20260102-030405__noop-1.sql").touch()
        with snowman.create_private_file(root, "noop", ".sql", now) as (path, _):
            pass
        self.assertEqual(path.name, "20260102-030405__noop-2.sql")
        self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_close_that_raises_removes_the_file(self):
        root = self.make_bare_dir()
        with self.assertRaises(OSError):
            with snowman.create_private_file(root, "noop", ".sql", datetime.now()) as (path, out):
                out.write("SELECT 1")
                os.close(out.fileno())  # the buffered write then fails at close
        self.assertEqual(list(root.iterdir()), [])

    def test_interrupt_after_the_exclusive_open_closes_and_removes_the_file(self):
        root = self.make_bare_dir()
        opened = []

        def recording_open(*args, **kwargs):
            opened.append(real_open(*args, **kwargs))
            return opened[-1]

        real_open = os.open
        with mock.patch.object(snowman.os, "open", recording_open), \
                mock.patch("snowman.open", create=True, side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            with snowman.create_private_file(root, "noop", ".sql", datetime.now()):
                pass
        self.assertEqual(list(root.iterdir()), [])
        with self.assertRaises(OSError):
            os.fstat(opened[0])  # the descriptor was closed

    def test_interrupted_encoder_setup_closes_once_and_removes_the_file(self):
        # open() closes a descriptor it owns when building the stream fails.
        root = self.make_bare_dir()
        closed = []

        def recording_close(fd):
            closed.append(fd)
            real_close(fd)

        real_close = os.close
        with mock.patch.object(snowman.os, "close", recording_close), \
                mock.patch.object(codecs.IncrementalEncoder, "__init__", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            with snowman.create_private_file(root, "noop", ".sql", datetime.now()):
                pass
        self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(len(closed), 1)
        with self.assertRaises(OSError):
            os.fstat(closed[0])  # the descriptor was closed

    def test_close_that_raises_after_a_clean_block_removes_the_file(self):
        root = self.make_bare_dir()

        def failing_close(fd):
            real_close(fd)
            raise OSError(errno.EIO, "close failed")

        real_close = os.close
        with mock.patch.object(snowman.os, "close", failing_close), self.assertRaises(OSError):
            with snowman.create_private_file(root, "noop", ".sql", datetime.now()) as (_, out):
                out.write("SELECT 1")
        self.assertEqual(list(root.iterdir()), [])


class TestSpillFullResult(SnowmanTestCase):
    def test_writes_full_untruncated_json_and_gitignore(self):
        root = self.make_project()
        snowman_dir = root / ".snowman"
        rows = [{"N": i, "S": "x" * 500, "V": None} for i in range(70)]
        fixed = datetime(2026, 9, 3, 18, 12, 0)
        path = snowman.spill_full_result(rows, "SELECT 1", snowman_dir, now=fixed)
        self.assertEqual(path.parent, root / ".snowman" / "results")
        self.assertRegex(path.name, r"^20260903-181200__[0-9a-f]{8}\.json$")
        body = path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(body), {"rows": rows, "types": []})
        self.assertIn("x" * 500, body)
        self.assertNotIn("…", body)
        gitignore = root / ".snowman" / "results" / ".gitignore"
        self.assertEqual(gitignore.read_text(encoding="utf-8"), "*\n")

    def test_gitignore_that_unignores_json_gets_a_catch_all_rule(self):
        root = self.make_project()
        gitignore = root / ".snowman" / "results" / ".gitignore"
        gitignore.parent.mkdir()
        gitignore.write_text("*\n!*.json\n", encoding="utf-8")
        path = snowman.spill_full_result([{"N": 1}], "SELECT 1", root / ".snowman")
        self.assert_git_ignores(root, path)
        self.assertEqual(gitignore.read_text(encoding="utf-8"), "*\n!*.json\n*\n")

    def test_gitignore_whose_last_line_only_looks_like_a_catch_all_gets_one(self):
        # Git keeps a trailing tab, and a bare CR does not end a line for it.
        for data in (b"*.tmp\n*\t\n", b"*.tmp\r*\n"):
            with self.subTest(data=data):
                root = self.make_project()
                gitignore = root / ".snowman" / "results" / ".gitignore"
                gitignore.parent.mkdir()
                gitignore.write_bytes(data)
                path = snowman.spill_full_result([{"N": 1}], "SELECT 1", root / ".snowman")
                self.assert_git_ignores(root, path)
                self.assertEqual(gitignore.read_bytes(), data + b"*\n")

    def test_unterminated_catch_all_is_left_as_is(self):
        # Read-only, so an append would raise PermissionError.
        root = self.make_project()
        gitignore = root / ".snowman" / "results" / ".gitignore"
        gitignore.parent.mkdir()
        gitignore.write_bytes(b"*.tmp\n*")
        gitignore.chmod(0o400)
        path = snowman.spill_full_result([{"N": 1}], "SELECT 1", root / ".snowman")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["rows"], [{"N": 1}])
        self.assert_git_ignores(root, path)
        self.assertEqual(gitignore.read_bytes(), b"*.tmp\n*")

    def test_crlf_catch_all_is_left_as_is(self):
        root = self.make_project()
        gitignore = root / ".snowman" / "results" / ".gitignore"
        gitignore.parent.mkdir()
        gitignore.write_bytes(b"*.tmp\r\n*\r\n")
        path = snowman.spill_full_result([{"N": 1}], "SELECT 1", root / ".snowman")
        self.assert_git_ignores(root, path)
        self.assertEqual(gitignore.read_bytes(), b"*.tmp\r\n*\r\n")

    @unittest.skipIf(sys.platform == "win32", "needs RLIMIT_FSIZE and SIGXFSZ")
    def test_failed_gitignore_append_keeps_the_existing_rules(self):
        # A file-size limit of 0 makes any write fail with EFBIG, in a child process.
        results = self.make_project() / ".snowman" / "results"
        results.mkdir()
        (results / ".gitignore").write_bytes(b"*.tmp\n")
        child = subprocess.run([sys.executable, "-c", (
            "import resource, signal, sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(SKILL_DIR / 'scripts')!r})\n"
            "import snowman\n"
            "signal.signal(signal.SIGXFSZ, signal.SIG_IGN)\n"
            "resource.setrlimit(resource.RLIMIT_FSIZE, (0, resource.getrlimit(resource.RLIMIT_FSIZE)[1]))\n"
            "try:\n"
            "    snowman.gitignored_dir(Path(sys.argv[1]))\n"
            "except OSError as exc:\n"
            "    print(type(exc).__name__)\n"
        ), str(results)], capture_output=True, text=True)
        self.assertEqual(child.stdout, "OSError\n", child.stderr)
        self.assertEqual((results / ".gitignore").read_bytes(), b"*.tmp\n")

    def test_interrupt_before_the_first_write_leaves_no_result_file(self):
        root = self.make_project()
        with mock.patch.object(snowman.json, "dump", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            snowman.spill_full_result([{"N": 1}], "SELECT 1", root / ".snowman")
        self.assertEqual(sorted(p.name for p in (root / ".snowman" / "results").iterdir()),
                         [".gitignore"])

    def test_result_file_and_directory_are_owner_only(self):
        self.umask_022()
        path = snowman.spill_full_result([{"N": 1}], "SELECT 1", self.make_project() / ".snowman")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_failed_write_leaves_no_result_file(self):
        # The first rows encode and reach the file before the lone surrogate fails.
        root = self.make_project()
        rows = [{"S": "x" * 100_000}, {"S": "\ud800"}]
        with self.assertRaises(UnicodeEncodeError):
            snowman.spill_full_result(rows, "SELECT 1", root / ".snowman")
        self.assertEqual(sorted(p.name for p in (root / ".snowman" / "results").iterdir()),
                         [".gitignore"])

    def test_same_sql_in_the_same_second_keeps_both_results(self):
        snowman_dir = self.make_project() / ".snowman"
        fixed = datetime(2026, 9, 3, 18, 12, 0)
        first = snowman.spill_full_result([{"N": 1}], "SELECT 1", snowman_dir, now=fixed)
        second = snowman.spill_full_result([{"N": 2}], "SELECT 1", snowman_dir, now=fixed)
        self.assertNotEqual(first, second)
        self.assertEqual(second.name, first.stem + "-1.json")
        self.assertIn("1", first.read_text(encoding="utf-8"))
        self.assertIn("2", second.read_text(encoding="utf-8"))

    def test_concurrent_writer_does_not_lose_the_result(self):
        # Patching exists() reproduces the old exists()-then-write race, where
        # another writer took the name after the check.
        snowman_dir = self.make_project() / ".snowman"
        fixed = datetime(2026, 9, 3, 18, 12, 0)
        first = snowman.spill_full_result([{"N": 1}], "SELECT 1", snowman_dir, now=fixed)
        with mock.patch.object(Path, "exists", return_value=False):
            second = snowman.spill_full_result([{"N": 2}], "SELECT 1", snowman_dir, now=fixed)
        self.assertEqual(second.name, first.stem + "-1.json")
        self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["rows"], [{"N": 1}])
        self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["rows"], [{"N": 2}])


class TestRunSnow(SnowmanTestCase):
    """The one place subprocess.run is patched: run_snow owns the snow argv."""

    def test_prepends_snow_keeps_stdout_bytes_and_decodes_stderr(self):
        completed = types.SimpleNamespace(returncode=5, stdout=b"[]\n", stderr=b"bad \xff\n")
        with mock.patch.object(snowman.subprocess, "run", return_value=completed) as run:
            result = snowman.run_snow(["sql", "-q", "SELECT 1"], {"A": "1"})
        self.assertEqual(result, (5, b"[]\n", "bad �\n"))
        self.assertIs(result.stdout, completed.stdout)
        self.assertEqual(run.call_args[0][0], ["snow", "sql", "-q", "SELECT 1"])
        self.assertEqual(run.call_args[1]["env"], {"A": "1"})
        self.assertTrue(run.call_args[1]["capture_output"])
        self.assertIsNone(run.call_args[1]["timeout"])

    def test_relays_timeout(self):
        completed = types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(snowman.subprocess, "run", return_value=completed) as run:
            snowman.run_snow(["connection", "list"], {}, timeout=30)
        self.assertEqual(run.call_args[1]["timeout"], 30)

    def test_missing_binary_blocks(self):
        with mock.patch.object(snowman.subprocess, "run", side_effect=FileNotFoundError):
            self.assert_blocked(snowman.run_snow, ["sql"], {}, match="`snow` CLI not found")


class TestExecute(SnowmanTestCase):
    def run_execute(self, outcomes: dict, *args, **kwargs) -> tuple:
        """Run execute() against fake snow outcomes; return (code, stdout, stderr).

        ``self.snow`` keeps the fake so a test can inspect ``self.snow.calls``.
        """
        self.snow = fake_snow(outcomes)
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(snowman, "run_snow", self.snow), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = snowman.execute(*args, **kwargs)
        return code, stdout.getvalue(), stderr.getvalue()

    def sql_args(self) -> list:
        """The argv of the one `snow sql` call the fake recorded."""
        sql_calls = [args for args, _ in self.snow.calls if args[0] == "sql"]
        self.assertEqual(len(sql_calls), 1)
        return sql_calls[0]

    def test_blocked_sql_never_reaches_snow(self):
        self.enter(self.make_project())
        snow = fake_snow({})
        with mock.patch.object(snowman, "run_snow", snow):
            self.assert_blocked(snowman.execute, "DROP TABLE t")
        self.assertEqual(snow.calls, [])

    def test_json_stdout_is_one_array_with_metadata_on_stderr(self):
        self.enter(self.make_project())
        schema = [{"name": "V", "type": "VARIANT"}]
        for rows in ([{"V": {"a": 1}}], []):
            with self.subTest(rows=rows):
                payload = json.dumps([rows, schema]).encode()
                code, out, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1", fmt="json")
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(out), rows)
                self.assertIn("# types: V VARIANT", err)

    def test_empty_results_retain_plain_columns_and_types(self):
        self.enter(self.make_project())
        schema = [{"name": "ID", "type": "NUMBER(38,0)"}, {"name": "NAME", "type": "VARCHAR"}]
        for fmt, expected in (("csv", "ID,NAME\n"), ("json", "[]\n")):
            with self.subTest(fmt=fmt):
                _, out, err = self.run_execute(
                    {"sql": Outcome(0, json.dumps([[], schema]).encode(), "")}, "SELECT 1", fmt=fmt,
                )
                self.assertEqual(out, expected)
                self.assertIn("# types: ID NUMBER(38,0), NAME VARCHAR", err)
                self.assertIn("# 0 rows", err)
                self.sql_args()

    def test_multiline_csv_never_shares_stream_with_metadata(self):
        import csv

        self.enter(self.make_project())
        payload = json.dumps([{"V": "first\n# 0 rows\nlast", "N": None}]).encode()
        _, out, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(list(csv.reader(io.StringIO(out))), [["V", "N"], ["first\n# 0 rows\nlast", ""]])
        self.assertEqual(err, "# empty cells are NULL\n")

    def test_all_truncated_previews_save_lossless_rows_and_schema(self):
        root = self.enter(self.make_project())
        rows = [{"V": {"deep": ["x" * 1000] * 1000}, "DDL": "a" * 5000}]
        schema = [{"name": "V", "type": "VARIANT"}, {"name": "DDL", "type": "VARCHAR"}]
        for fmt in ("csv", "json"):
            with self.subTest(fmt=fmt):
                _, out, err = self.run_execute({"sql": Outcome(0, json.dumps([rows, schema]).encode(), "")}, "SELECT 1", fmt=fmt)
                self.assertLessEqual(len(out.encode("utf-8")), 16000)
                if fmt == "json":
                    self.assertEqual(len(json.loads(out)), 1)
                path = Path(err.split("full result: ")[1].splitlines()[0])
                saved = json.loads((root / path).read_text())
                self.assertEqual(saved, {"rows": rows, "types": schema})

    def test_output_budget_omits_complete_rows_in_both_formats(self):
        import csv

        self.enter(self.make_project())
        rows = [{f"C{i}": "é" * 200 for i in range(100)}] * 50
        for fmt in ("csv", "json"):
            with self.subTest(fmt=fmt):
                _, out, err = self.run_execute({"sql": Outcome(0, json.dumps(rows).encode(), "")}, "SELECT 1", fmt=fmt)
                self.assertLessEqual(len(out.encode("utf-8")), 16000)
                if fmt == "json":
                    self.assertEqual(json.loads(out), [])
                else:
                    self.assertEqual(len(list(csv.reader(io.StringIO(out)))), 1)
                self.assertIn("showing 0 of 50 rows", err)
                self.assertIn("full result:", err)

    def test_large_schema_notes_are_bounded_and_preserved_in_artifact(self):
        root = self.enter(self.make_project())
        schema = [{"name": "é" * 200 + str(i), "type": "VARIANT"} for i in range(100)]
        _, out, err = self.run_execute({"sql": Outcome(0, json.dumps([[], schema]).encode(), "")}, "SELECT 1", fmt="json")
        self.assertEqual(json.loads(out), [])
        self.assertLessEqual(len(err.splitlines()[0].encode("utf-8")), 1024)
        self.assertIn("type notes shortened", err)
        path = root / err.split("full result: ")[1].splitlines()[0]
        self.assertEqual(json.loads(path.read_text())["types"], schema)

    def test_wide_empty_plain_schema_is_bounded_and_saved(self):
        root = self.enter(self.make_project())
        schema = [{"name": "COL" + str(i) + "x" * 200, "type": "VARCHAR"} for i in range(100)]
        for fmt in ("csv", "json"):
            with self.subTest(fmt=fmt):
                _, out, err = self.run_execute(
                    {"sql": Outcome(0, json.dumps([[], schema]).encode(), "")}, "SELECT 1", fmt=fmt,
                )
                self.assertEqual(out, "[]\n" if fmt == "json" else "")
                self.assertLessEqual(len(err.splitlines()[0].encode()), 1024)
                self.assertIn("type notes shortened", err)
                path = root / err.split("full result: ")[1].splitlines()[0]
                self.assertEqual(json.loads(path.read_text()), {"rows": [], "types": schema})

    def test_invalid_limits_block_before_snow_is_called(self):
        for limits in ({"max_rows": -1}, {"max_cell": -1}, {"max_output": -1},
                       {"fmt": "json", "max_output": 1}, {"fmt": "json", "max_output": 2}):
            with self.subTest(limits=limits):
                self.assert_blocked(self.run_execute, {}, "SELECT 1", **limits)
                self.assertEqual(self.snow.calls, [])

    def test_smallest_json_budget_keeps_valid_empty_array(self):
        self.enter(self.make_project())
        _, out, err = self.run_execute({"sql": Outcome(0, b'[{"N":1}]', "")}, "SELECT 1", fmt="json", max_output=3)
        self.assertEqual(out, "[]\n")
        self.assertIn("full result:", err)

    def test_malformed_success_output_is_refused_without_raw_stdout(self):
        self.enter(self.make_project())
        for payload in (b"not json" * 10000, b'{"error":"bad"}', b'[[1],[]]'):
            with self.subTest(payload=payload[:20]):
                with self.assertRaisesRegex(snowman.ResultProcessingError, "unexpected snow output"):
                    self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")

    def test_runs_snow_with_resolved_connection_and_no_templating(self):
        # Without --enable-templating NONE, snow renders &W in 'F&W' and fails.
        self.enter(self.make_project())
        code, _, _ = self.run_execute({"sql": OK}, "SELECT 'F&W'")
        self.assertEqual(code, 0)
        self.assertEqual(
            self.sql_args(),
            ["sql", "-q", "SELECT 'F&W'\n;DESCRIBE RESULT LAST_QUERY_ID()",
             "--connection", "analytics",
             "--format", "JSON_EXT", "--enhanced-exit-codes", "--enable-templating", "NONE"],
        )

    def test_context_warehouse_is_applied_for_selected_environment(self):
        for context, env, expected in (
            (SINGLE_CONN_FRONTMATTER.replace("connection: analytics", "connection: analytics\ndefault_warehouse: SMALL_WH"), None, "SMALL_WH"),
            (MULTI_ENV_FRONTMATTER.replace("connection: acme_prod", "connection: acme_prod\n    default_warehouse: PROD_WH"), "prod", "PROD_WH"),
        ):
            with self.subTest(env=env):
                self.enter(self.make_project(context))
                self.run_execute({"sql": OK}, "SELECT 1", env=env)
                args = self.sql_args()
                self.assertEqual(args[args.index("--warehouse") + 1], expected)

    def test_warehouse_flag_overrides_context_warehouse(self):
        context = SINGLE_CONN_FRONTMATTER.replace(
            "connection: analytics", "connection: analytics\ndefault_warehouse: SMALL_WH"
        )
        self.enter(self.make_project(context))
        self.run_execute({"sql": OK}, "SELECT 1", warehouse="BIG_WH")
        args = self.sql_args()
        self.assertEqual(args.count("--warehouse"), 1)
        self.assertEqual(args[args.index("--warehouse") + 1], "BIG_WH")

    def test_describe_appended_after_trailing_semicolon_and_comment(self):
        self.assertEqual(
            snowman.with_describe("SELECT 1;  "),
            "SELECT 1\n;DESCRIBE RESULT LAST_QUERY_ID()",
        )
        self.assertEqual(
            snowman.with_describe("SELECT 1 -- note;"),
            "SELECT 1\n;DESCRIBE RESULT LAST_QUERY_ID()",
        )
        self.assertEqual(
            snowman.with_describe("SELECT 1; -- done\n/* end */"),
            "SELECT 1\n;DESCRIBE RESULT LAST_QUERY_ID()",
        )
        self.assertEqual(
            snowman.with_describe("SELECT ';' AS S;;"),
            "SELECT ';' AS S\n;DESCRIBE RESULT LAST_QUERY_ID()",
        )

    def test_trailing_literal_or_quoted_identifier_is_kept(self):
        for sql in (
            "SELECT 1 WHERE x = 'abc'",
            "SELECT 1 WHERE x = 'a; b'",
            "SELECT 1 WHERE x = 'abc  '",
            'SELECT 1 FROM "My Table"',
            "SELECT $$raw$$",
        ):
            self.assertEqual(
                snowman.with_describe(sql + ";  -- c"),
                f"{sql}\n;DESCRIBE RESULT LAST_QUERY_ID()",
            )

    def test_failed_query_stdout_fragment_is_not_relayed(self):
        self.enter(self.make_project())
        for fragment in (b"[\n", b"[]\n"):
            code, out, err = self.run_execute(
                {"sql": Outcome(5, fragment, PANEL_STDERR)}, "SELECT 1"
            )
            self.assertEqual(code, 5)
            self.assertEqual(out, "")
            self.assertEqual(err, PANEL_CLEANED)

    def test_two_statement_result_yields_rows_and_types_footer(self):
        self.enter(self.make_project())
        payload = json.dumps([
            [{"A": 1, "B": "1.50"}],
            [{"name": "A", "type": "NUMBER(1,0)", "kind": "COLUMN"},
             {"name": "B", "type": "NUMBER(10,2)", "kind": "COLUMN"}],
        ]).encode()
        code, out, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(code, 0)
        self.assertEqual(out, "A,B\n1,1.50\n")
        self.assertEqual(err, "# types: B NUMBER(10,2)\n")

    def test_two_statement_empty_result_reports_zero_rows(self):
        self.enter(self.make_project())
        payload = json.dumps([[], [{"name": "A", "type": "DATE"}]]).encode()
        _, out, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(out, "A\n")
        self.assertIn("# 0 rows\n", err)

    def test_split_result_shapes(self):
        self.assertEqual(snowman.split_result([[{"A": 1}], [{"name": "A"}]]),
                         ([{"A": 1}], [{"name": "A"}]))
        self.assertEqual(snowman.split_result([{"A": 1}]), ([{"A": 1}], None))
        self.assertEqual(snowman.split_result([]), ([], None))
        self.assertEqual(snowman.split_result({"error": 1}), (None, None))
        self.assertEqual(snowman.split_result([1, 2]), (None, None))

    def test_json_ext_result_rendered_as_csv_with_footers(self):
        self.enter(self.make_project())
        payload = json.dumps(
            [{"A": 1, "O": {"k": 1}, "N": None}, {"A": 2, "O": [1], "N": "x" * 300}],
            indent=4,
        ).encode()
        code, out, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "A,O,N")
        self.assertEqual(lines[1], '1,"{""k"":1}",')
        self.assertEqual(lines[2], '2,[1],' + "x" * 200 + "…(+100 chars)")
        self.assertEqual(
            err.splitlines()[:2],
            ["# empty cells are NULL",
             "# some cells truncated to 200 chars; pass --max-cell 0 for full values"],
        )
        self.assertEqual(lines[3:], [])
        self.assertIn("# full result:", err)

    def test_row_cap_spills_full_result_with_recovery_on_stderr(self):
        root = self.enter(self.make_project())
        rows = [{"N": i} for i in range(1203)]
        code, out, err = self.run_execute({"sql": Outcome(0, json.dumps(rows).encode(), "")}, "SELECT 1")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 51)
        self.assertIn("# showing 50 of 1203 rows", err)
        rel = err.split("full result: ")[1].splitlines()[0]
        self.assertRegex(rel, r"^\.snowman/results/\d{8}-\d{6}__[0-9a-f]{8}\.json$")
        self.assertEqual(json.loads((root / rel).read_text())["rows"], rows)

    def test_one_row_preview_holds_no_copy_of_the_row_list(self):
        # A copy of the row list costs one 8-byte pointer per row. From the
        # moment the JSON is parsed, the run may not add half that.
        if tracemalloc.is_tracing():
            self.skipTest("reset_peak would discard the peak of a runner that already traces")
        self.enter(self.make_project())
        rows = 100_000
        payload = json.dumps([{"N": i} for i in range(rows)]).encode()
        split_result, bytes_after_parse = snowman.split_result, []

        def split_and_mark(result):
            bytes_after_parse.append(tracemalloc.get_traced_memory()[0])
            tracemalloc.reset_peak()
            return split_result(result)

        tracemalloc.start()
        self.addCleanup(tracemalloc.stop)
        with mock.patch.object(snowman, "split_result", split_and_mark):
            code, _, _ = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1", max_rows=1)
        after_parse_peak = tracemalloc.get_traced_memory()[1]
        self.assertEqual(code, 0)
        self.assertLess(after_parse_peak - bytes_after_parse[0], rows * 4)

    def test_spill_path_is_relative_to_cwd(self):
        root = self.enter(self.make_project())
        sub = root / "analysis" / "q1"
        sub.mkdir(parents=True)
        self.enter(sub)
        payload = json.dumps([{"N": i} for i in range(60)]).encode()
        _, _, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        rel = err.split("full result: ")[1].splitlines()[0]
        self.assertTrue(rel.startswith("../../.snowman/results/"), rel)
        self.assertEqual((Path.cwd() / rel).resolve(), root / ".snowman" / "results" / Path(rel).name)
        self.assertTrue((Path.cwd() / rel).is_file())

    def test_linked_results_gitignore_blocks_before_querying(self):
        root = self.enter(self.make_project())
        results = root / ".snowman" / "results"
        target = self.link_gitignore(results)
        self.snow = fake_snow({})
        with mock.patch.object(snowman, "run_snow", self.snow):
            reason = self.assert_blocked(snowman.execute, "SELECT 1")
        self.assertEqual(self.snow.calls, [])
        self.assert_link_refused(reason, results, target)

    def test_bootstrap_truncation_saves_in_private_temporary_directory(self):
        root = self.enter(self.make_bare_dir())
        rows = [{"N": i} for i in range(60)]
        _, out, err = self.run_execute(
            {"sql": Outcome(0, json.dumps(rows).encode(), "")}, "SELECT 1", connection_override="c"
        )
        self.assertIn("# showing 50 of 60 rows", err)
        path = Path(err.split("full result: ")[1].splitlines()[0])
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())["rows"], rows)
        self.assertFalse((root / ".snowman").exists())

    def test_max_rows_zero_and_json_flag(self):
        self.enter(self.make_project())
        payload = json.dumps([{"N": i} for i in range(60)]).encode()
        _, out, _ = self.run_execute(
            {"sql": Outcome(0, payload, "")}, "SELECT 1", max_rows=0, fmt="json"
        )
        self.assertEqual(json.loads(out), [{"N": i} for i in range(60)])

    def test_empty_result_notes_zero_rows(self):
        self.enter(self.make_project())
        _, out, _ = self.run_execute({"sql": Outcome(0, b"[]\n", "")}, "SELECT 1")
        self.assertEqual(out, "")

    def test_failed_query_raw_stdout_is_suppressed(self):
        self.enter(self.make_project())
        code, out, _ = self.run_execute(
            {"sql": Outcome(3, b"not json at all\n", "")}, "SELECT 1"
        )
        self.assertEqual(code, 3)
        self.assertEqual(out, "")

    def test_sql_error_panel_cleaned_and_exit_code_forwarded(self):
        self.enter(self.make_project())
        code, out, err = self.run_execute(
            {"sql": Outcome(5, b"", PANEL_STDERR)}, "SELECT 1"
        )
        self.assertEqual(code, 5)
        self.assertEqual(out, "")
        self.assertEqual(err, PANEL_CLEANED)

    def test_forwards_snow_exit_code_and_stderr(self):
        self.enter(self.make_project())
        code, out, err = self.run_execute(
            {"sql": Outcome(1, b"", "some snow error\n")}, "SELECT 1"
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "some snow error\n")

    def test_multi_env_picks_connection(self):
        self.enter(self.make_project(MULTI_ENV_FRONTMATTER))
        self.run_execute({"sql": OK}, "SELECT 1", env="prod")
        self.assertIn("acme_prod", self.sql_args())

    def test_multi_env_default_fallback(self):
        self.enter(self.make_project(MULTI_ENV_FRONTMATTER))
        self.run_execute({"sql": OK}, "SELECT 1")
        self.assertIn("acme_dev", self.sql_args())

    def test_connection_override_skips_context(self):
        self.enter(self.make_bare_dir())  # no context file at all
        code, _, _ = self.run_execute({"sql": OK}, "SELECT 1", connection_override="bootstrap_conn")
        self.assertEqual(code, 0)
        self.assertIn("bootstrap_conn", self.sql_args())

    def test_blocks_without_context_and_without_override(self):
        self.enter(self.make_bare_dir())
        snow = fake_snow({})
        with mock.patch.object(snowman, "run_snow", snow):
            self.assert_blocked(snowman.execute, "SELECT 1", match="bootstrap")
        self.assertEqual(snow.calls, [])

    def test_empty_connection_override_never_reaches_snow(self):
        self.enter(self.make_project())
        snow = fake_snow({})
        with mock.patch.object(snowman, "run_snow", snow):
            self.assert_blocked(snowman.execute, "SELECT 1", connection_override="")
        self.assertEqual(snow.calls, [])

    def test_dotenv_relayed_to_snow_process_env_wins(self):
        root = self.enter(self.make_project())
        (root / ".env").write_text(
            "RELAYED_ONLY=from_dotenv\nALREADY_SET=from_dotenv\n", encoding="utf-8"
        )
        with mock.patch.dict(os.environ, {"ALREADY_SET": "from_process"}):
            self.run_execute({"sql": OK}, "SELECT 1")
        _, env = self.snow.calls[0]
        self.assertEqual(env["RELAYED_ONLY"], "from_dotenv")
        self.assertEqual(env["ALREADY_SET"], "from_process")

    def test_bootstrap_mode_relays_dotenv_found_above_cwd(self):
        root = self.make_bare_dir()
        (root / ".env").write_text("FROM_ABOVE=yes\n", encoding="utf-8")
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        self.enter(nested)
        self.run_execute({"sql": OK}, "SELECT 1", connection_override="c")
        _, env = self.snow.calls[0]
        self.assertEqual(env["FROM_ABOVE"], "yes")

    def test_missing_snow_cli_blocks(self):
        self.enter(self.make_project())
        with mock.patch.object(snowman, "run_snow", side_effect=snowman.Blocked("`snow` CLI not found on PATH.")):
            self.assert_blocked(snowman.execute, "SELECT 1", match="`snow` CLI not found")

    def test_auth_failure_inside_rich_panel_still_hints(self):
        self.enter(self.make_project())
        panel = (
            "╭─ Error ──────────────────────────────────────────────────╮\n"
            "│ 250001 (08001): Failed to connect to DB: could not       │\n"
            "│ decrypt private key                                      │\n"
            "╰──────────────────────────────────────────────────────────╯\n"
        )
        code, _, err = self.run_execute(
            {"sql": Outcome(1, b"", panel),
             "connection": connection_listing("analytics", {"authenticator": "SNOWFLAKE_JWT"})},
            "SELECT 1",
        )
        self.assertEqual(code, 1)
        self.assertEqual(
            err.splitlines()[0],
            "ERROR: 250001 (08001): Failed to connect to DB: could not decrypt private key",
        )
        self.assertNotIn("│", err)
        self.assertIn("hint: this looks like a key-pair auth failure", err)

    def test_non_auth_failure_gets_no_hint(self):
        self.enter(self.make_project())
        code, _, err = self.run_execute(
            {"sql": Outcome(1, b"", "syntax error\n")}, "SELECT 1"
        )
        self.assertEqual(code, 1)
        self.assertNotIn("hint:", err)
        self.assertEqual([args[0] for args, _ in self.snow.calls], ["sql"])


class TestAuthHintFor(SnowmanTestCase):
    """auth_hint_for: the trigger regex, the lookup, the classification, the wording."""

    def hint(self, stderr: str, lookup: Outcome | None = None, env_file=None) -> str | None:
        outcomes = {} if lookup is None else {"connection": lookup}
        with mock.patch.object(snowman, "run_snow", fake_snow(outcomes)):
            return snowman.auth_hint_for(stderr, "analytics", env_file, {})

    def test_none_for_non_auth_errors(self):
        for message in ("syntax error: unexpected token 'FROM'", "some snow error"):
            with self.subTest(message=message):
                self.assertIsNone(self.hint(message))

    def test_auth_looking_errors_get_a_hint(self):
        for message in (
            "could not decrypt private key",
            "JWT token is invalid",
            "OAuth access token expired or invalid",
            "Failed to authenticate: 250001",
        ):
            with self.subTest(message=message):
                hint = self.hint(message, connection_listing("analytics", {}))
                self.assertTrue(hint.startswith("hint: "), hint)

    def test_browser_connection(self):
        for value in ("OAUTH_AUTHORIZATION_CODE", "EXTERNALBROWSER", "externalbrowser"):
            with self.subTest(authenticator=value):
                hint = self.hint(
                    "OAuth access token expired",
                    connection_listing("analytics", {"authenticator": value}),
                )
                self.assertIn("authenticates in a browser", hint)
                self.assertIn("snow connection test -c analytics", hint)
                self.assertNotIn("PRIVATE_KEY_PASSPHRASE", hint)

    def test_bad_byte_in_another_field_still_classifies(self):
        listing = connection_listing("analytics", {"authenticator": "EXTERNALBROWSER", "user": "X"})
        listing = listing._replace(stdout=listing.stdout.replace(b'"X"', b'"\xff"'))
        self.assertIn(b"\xff", listing.stdout)
        with mock.patch.object(snowman, "run_snow", fake_snow({"connection": listing})):
            params = snowman.connection_params("analytics", {})
        self.assertEqual(params, {"authenticator": "EXTERNALBROWSER", "user": "�"})
        hint = self.hint("OAuth access token expired", listing)
        self.assertIn("authenticates in a browser", hint)
        self.assertNotIn("PRIVATE_KEY_PASSPHRASE", hint)

    def test_keypair_connection(self):
        for params in ({"authenticator": "SNOWFLAKE_JWT"}, {"private_key_file": "/k.pem"}):
            with self.subTest(params=params):
                hint = self.hint(
                    "could not decrypt private key", connection_listing("analytics", params)
                )
                self.assertIn("key-pair auth failure", hint)
                self.assertIn("no .env file was found", hint)
                self.assertNotIn("snow connection test", hint)

    def test_unknown_connection_gets_combined_hint(self):
        for label, lookup in (
            ("not listed", connection_listing("other", {"authenticator": "SNOWFLAKE_JWT"})),
            ("other authenticator", connection_listing("analytics", {"authenticator": "OAUTH_CLIENT_CREDENTIALS"})),
            ("empty parameters", connection_listing("analytics", {})),
            ("garbage output", Outcome(0, b"not json", "")),
        ):
            with self.subTest(lookup=label):
                hint = self.hint("JWT token is invalid", lookup)
                self.assertIn("PRIVATE_KEY_PASSPHRASE", hint)
                self.assertIn("snow connection test -c analytics", hint)

    def test_missing_snow_during_lookup_still_hints(self):
        with mock.patch.object(snowman, "run_snow", side_effect=snowman.Blocked("missing")):
            hint = snowman.auth_hint_for("JWT token is invalid", "analytics", None, {})
        self.assertIn("PRIVATE_KEY_PASSPHRASE", hint)

    def test_mentions_loaded_dotenv(self):
        hint = self.hint(
            "bad passphrase",
            connection_listing("analytics", {"authenticator": "SNOWFLAKE_JWT"}),
            env_file=Path("/p/.env"),
        )
        self.assertIn("a .env was loaded from /p/.env", hint)


class TestMainCli(SnowmanTestCase):
    def test_result_shape_errors_report_query_already_ran_without_stdout(self):
        self.enter(self.make_project())
        for payload in (b"", b" \n", b"not json", b'{"error":"bad"}', b'[[1],[]]',
                        b'[{"A":1},{"B":2}]', b'[[{"A":1},{"A":2,"B":3}],[]]'):
            with self.subTest(payload=payload):
                snow = fake_snow({"sql": Outcome(0, payload, "")})
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(snowman, "run_snow", snow), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = snowman.main(["snowman.py", "--json", "SELECT 1"])
                self.assertEqual(len(snow.calls), 1)
                self.assertEqual(code, 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertTrue(stderr.getvalue().startswith("ERROR: query already ran;"))
                self.assertNotIn("BLOCKED:", stderr.getvalue())
                self.assertIn("Do not rerun automatically", stderr.getvalue())

    def test_processing_failures_preserve_received_payload_privately(self):
        self.enter(self.make_project())
        payloads = [b"not json secret", b'{"error":"secret"}', b'[{"A":1},{"B":2}]',
                    b'[[1],[]]', b'[[{"A":1}],[{"name":42,"type":"DATE"}]]',
                    json.dumps([{"A": chr(0xD800)}]).encode()]
        for payload in payloads:
            with self.subTest(payload=payload):
                snow = fake_snow({"sql": Outcome(0, payload, "")})
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(snowman, "run_snow", snow), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = snowman.main(["snowman.py", "SELECT 1"])
                self.assertEqual(code, 1)
                self.assertEqual(len(snow.calls), 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("query already ran", stderr.getvalue())
                self.assertNotIn("secret", stderr.getvalue())
                path = Path(stderr.getvalue().split("# raw CLI stdout: ")[1].splitlines()[0])
                self.assertEqual(path.read_bytes(), payload)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertIn("Inspect this file locally", stderr.getvalue())

    def test_subprocess_recovery_preserves_invalid_utf8_bytes(self):
        root = self.enter(self.make_project())
        # Not JSON, then valid JSON whose string holds a bad byte or an encoded surrogate.
        for payload in (b"not json \xff\r\n", b'[{"A":"secret \xe9"}]\n',
                        b'[{"A":"secret \xed\xa0\x80"}]\n'):
            with self.subTest(payload=payload):
                calls = root / "calls.txt"
                calls.unlink(missing_ok=True)
                binary = root / "snow"
                binary.write_text(
                    f"#!{sys.executable}\nimport sys\n"
                    f"with open({str(calls)!r}, 'a') as out: out.write('call\\n')\n"
                    f"sys.stdout.buffer.write({payload!r})\n"
                )
                binary.chmod(0o700)
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.dict(os.environ, {"PATH": str(root)}), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = snowman.main(["snowman.py", "SELECT 1"])
                self.assertEqual(code, 1)
                self.assertEqual(calls.read_text(), "call\n")
                self.assertEqual(stdout.getvalue(), "")
                self.assertNotIn("not json", stderr.getvalue())
                self.assertNotIn("secret", stderr.getvalue())
                self.assertNotIn("�", stderr.getvalue())
                path = Path(stderr.getvalue().split("# raw CLI stdout: ")[1].splitlines()[0])
                self.assertEqual(path.read_bytes(), payload)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_recovery_copy_lands_in_the_test_owned_temp_dir(self):
        error = snowman.preserve_failed_result(b"payload", "reason.")
        path = Path(str(error).split("# raw CLI stdout: ")[1].splitlines()[0])
        self.assertEqual(path.parent, self.temp_root)
        self.doCleanups()
        self.assertFalse(path.exists())

    def test_empty_cli_output_reports_no_payload_to_recover(self):
        self.enter(self.make_project())
        for payload in (b"", b" \n"):
            with self.subTest(payload=payload):
                snow = fake_snow({"sql": Outcome(0, payload, "")})
                stderr = io.StringIO()
                with mock.patch.object(snowman, "run_snow", snow), contextlib.redirect_stderr(stderr):
                    self.assertEqual(snowman.main(["snowman.py", "SELECT 1"]), 1)
                self.assertIn("no result output received", stderr.getvalue())
                self.assertNotIn("# raw CLI stdout:", stderr.getvalue())
                self.assertEqual(len(snow.calls), 1)

    def test_recovery_storage_failure_reports_no_saved_copy(self):
        self.enter(self.make_project())
        snow = fake_snow({"sql": Outcome(0, b"invalid secret payload", "")})
        stderr = io.StringIO()
        with mock.patch.object(snowman, "run_snow", snow), \
                mock.patch.object(tempfile, "mkstemp", side_effect=OSError("disk full")), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(snowman.main(["snowman.py", "SELECT 1"]), 1)
        self.assertIn("could not save recovery copy", stderr.getvalue())
        self.assertNotIn("# raw CLI stdout:", stderr.getvalue())
        self.assertNotIn("secret", stderr.getvalue())
        self.assertEqual(len(snow.calls), 1)

    def test_spill_error_reports_query_already_ran_without_stdout(self):
        root = self.enter(self.make_project())
        (root / ".snowman" / "results").write_text("not a directory")
        snow = fake_snow({"sql": Outcome(0, json.dumps([{"DDL": "x" * 500}]).encode(), "")})
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(snowman, "run_snow", snow), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = snowman.main(["snowman.py", "SELECT 1"])
        self.assertEqual(len(snow.calls), 1)
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(stderr.getvalue().startswith("ERROR: query already ran;"))
        self.assertIn("cannot save full result", stderr.getvalue())
        path = Path(stderr.getvalue().split("# raw CLI stdout: ")[1].splitlines()[0])
        self.assertEqual(json.loads(path.read_text()), [{"DDL": "x" * 500}])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("BLOCKED:", stderr.getvalue())

    def assert_usage_error(self, argv: list, match: str) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as cm:
            snowman.main(["snowman.py", *argv])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn(match, stderr.getvalue())

    def test_stage_requires_name(self):
        self.assert_usage_error(["--stage", "SELECT 1"], "--stage requires --name")

    def test_name_requires_stage(self):
        self.assert_usage_error(
            ["--name", "noop", "SELECT 1"], "--name is only valid with --stage"
        )

    def test_connection_invalid_with_stage(self):
        self.assert_usage_error(
            ["--stage", "--name", "noop", "--connection", "c", "SELECT 1"],
            "--connection is not valid with --stage",
        )

    def test_connection_and_env_are_mutually_exclusive(self):
        self.assert_usage_error(
            ["--connection", "c", "--env", "dev", "SELECT 1"], "use one"
        )

    def test_empty_connection_is_still_a_given_flag(self):
        # A bare dir keeps a run that slips past the parser away from real files.
        self.enter(self.make_bare_dir())
        cases = {
            "with --stage": (
                ["--stage", "--name", "noop", "--connection", "", "SELECT 1"],
                "--connection is not valid with --stage",
            ),
            "with --env": (["--connection", "", "--env", "dev", "SELECT 1"], "use one"),
        }
        for name, (argv, match) in cases.items():
            with self.subTest(name):
                self.assert_usage_error(argv, match)

    def test_json_invalid_with_stage(self):
        self.assert_usage_error(
            ["--stage", "--name", "noop", "--json", "SELECT 1"],
            "--json is only valid when executing",
        )

    def test_main_passes_output_flags_to_execute(self):
        with mock.patch.object(snowman, "execute", return_value=0) as execute:
            argv = ["snowman.py", "--max-rows", "5", "--max-cell", "10", "--json", "SELECT 1"]
            self.assertEqual(snowman.main(argv), 0)
        execute.assert_called_once_with(
            "SELECT 1", connection_override=None, env=None, fmt="json", max_rows=5, max_cell=10, max_output=16000, warehouse=None
        )

    def test_main_output_flag_defaults(self):
        with mock.patch.object(snowman, "execute", return_value=0) as execute:
            self.assertEqual(snowman.main(["snowman.py", "SELECT 1"]), 0)
        execute.assert_called_once_with(
            "SELECT 1", connection_override=None, env=None, fmt="csv", max_rows=50, max_cell=200, max_output=16000, warehouse=None
        )

    def test_main_routes_to_execute(self):
        self.enter(self.make_project())
        snow = fake_snow({"sql": OK})
        with mock.patch.object(snowman, "run_snow", snow):
            self.assertEqual(snowman.main(["snowman.py", "SELECT 1"]), 0)
        self.assertEqual(len(snow.calls), 1)

    def run_main_blocked(self, argv: list) -> str:
        """Run main() expecting a refusal; return stderr after checking the exit code."""
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(snowman.main(["snowman.py", *argv]), snowman.BLOCK)
        return stderr.getvalue()

    def test_main_renders_refusal_once_and_exits_2(self):
        self.enter(self.make_project())
        snow = fake_snow({})
        with mock.patch.object(snowman, "run_snow", snow):
            err = self.run_main_blocked(["DROP TABLE t"])
        self.assertEqual(snow.calls, [])
        self.assertEqual(err, "BLOCKED: non-read-only statement (leading keyword: DROP).\n")

    def test_main_renders_stage_refusal(self):
        self.enter(self.make_project(MULTI_ENV_FRONTMATTER))
        err = self.run_main_blocked(["--stage", "--name", "noop", "SELECT 1"])
        self.assertTrue(err.startswith("BLOCKED: staging in a multi-environment project"), err)

    def test_main_renders_missing_snow_cli(self):
        self.enter(self.make_project())
        with mock.patch.object(
            snowman, "run_snow", side_effect=snowman.Blocked("`snow` CLI not found on PATH.")
        ):
            err = self.run_main_blocked(["SELECT 1"])
        self.assertEqual(err, "BLOCKED: `snow` CLI not found on PATH.\n")

    def test_main_passes_warehouse_to_stage(self):
        root = self.enter(self.make_project())
        with contextlib.redirect_stdout(io.StringIO()):
            snowman.main(["snowman.py", "--stage", "--name", "noop", "--warehouse", "BIG_WH", "DROP TABLE t"])
        [staged] = (root / ".snowman" / "staged").glob("*.sql")
        self.assertIn("--warehouse BIG_WH", staged.read_text())

    def test_main_routes_to_stage(self):
        root = self.enter(self.make_project())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(
                snowman.main(["snowman.py", "--stage", "--name", "noop", "DROP TABLE t"]),
                0,
            )
        self.assertTrue(list((root / ".snowman" / "staged").glob("*.sql")))



class TestDocumentedInvocation(unittest.TestCase):
    """The docs' query invocation hands SQL to the wrapper unchanged."""

    # Leading spaces, double quotes, $1, an odd apostrophe, an ampersand, a backtick and a backslash.
    SQL = """  SHOW TABLES ->> SELECT "name" FROM $1 WHERE "name" <> 'F&W' -- it's `x` \\n"""

    def docs(self) -> dict[str, str]:
        paths = [SKILL_DIR / "SKILL.md", *sorted((SKILL_DIR / "references").glob("*.md"))]
        return {p.name: p.read_text(encoding="utf-8") for p in paths}

    def run_block(self, prefix: str = "") -> dict:
        """Run the Run queries block under bash and zsh with a fake `uv`; map shell to result."""
        run_queries = self.docs()["SKILL.md"].split("## Run queries", 1)[1]
        block = re.search(r"```bash\n(.*?)```", run_queries, re.S).group(1)
        self.assertIn("<SQL>", block)
        script = prefix + block.replace("<SQL>", self.SQL).replace("<skill-dir>", "/skill")
        shells = [sh for sh in ("bash", "zsh") if shutil.which(sh)]
        if not shells:
            self.skipTest("neither bash nor zsh on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            uv = Path(tmp) / "uv"
            uv.write_text(
                f"#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ['PATH']}"}
            return {
                sh: subprocess.run([sh, "-c", script], env=env, capture_output=True, text=True, check=False)
                for sh in shells
            }

    def test_run_queries_block_passes_sql_unchanged(self):
        for sh, done in self.run_block().items():
            with self.subTest(shell=sh):
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(
                    json.loads(done.stdout),
                    ["run", "--python", "3.13", "--no-project",
                     "/skill/scripts/snowman.py", self.SQL + "\n"],
                )

    def test_failed_assignment_never_reaches_the_wrapper(self):
        # A read-only SQL keeps its old value; the old query must not run.
        for sh, done in self.run_block("readonly SQL='SELECT 17'\n").items():
            with self.subTest(shell=sh):
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(done.stdout, "")

    def test_other_examples_point_to_run_queries(self):
        for name, text in self.docs().items():
            lines = text.splitlines()
            with self.subTest(doc=name):
                self.assertNotIn('"<SQL>"', text)
            for i, line in enumerate(lines):
                if '"$SQL"' not in line:
                    continue
                window = "\n".join(lines[max(0, i - 5):i + 2])
                with self.subTest(doc=name, line=i + 1):
                    self.assertTrue("#run-queries)" in window or "<<'SQL'" in window, line)
        self.assertIn("(../SKILL.md#run-queries)", self.docs()["workflows.md"])

    def test_ampersand_workaround_is_gone(self):
        guardrails = self.docs()["guardrails.md"]
        self.assertNotIn("LIKE 'F%W'", guardrails)
        self.assertNotIn("CHR(38)", guardrails)

    def test_list_substitute_prefers_directory_table(self):
        row = next(line for line in self.docs()["guardrails.md"].splitlines()
                   if line.startswith("| `LIST @stage/path` |"))
        substitute = row.split("|")[2]
        queries = re.findall(r"`(SELECT [^`]+)`", substitute)
        self.assertEqual(len(queries), 2, substitute)
        self.assertIn("FROM DIRECTORY(@stage) WHERE STARTSWITH(RELATIVE_PATH, 'path')", queries[0])
        self.assertIn("METADATA$FILENAME", queries[1])
        self.assertIn("omits empty files", substitute.split(queries[1], 1)[1])
        for sql in queries:
            with self.subTest(sql=sql):
                snowman.enforce_read_only(sql)


if __name__ == "__main__":
    unittest.main()
