"""Tests for skills/snowman/scripts/snowman.py.

Standard library only, like the script itself. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here ever talks to Snowflake: execute() tests replace run_snow with
fake_snow, only TestRunSnow patches subprocess.run, and stage mode never
executes by design.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "snowman" / "scripts"))

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

OK = Outcome(0, "", "")


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
        0, json.dumps([{"connection_name": connection, "parameters": parameters}]), ""
    )


class SnowmanTestCase(unittest.TestCase):
    """Shared helpers: Blocked assertions and temp projects passed by path.

    Resolution is tested by passing a start path. Only the entry points
    (execute, stage, main) still read the CWD, and their tests use ``enter``.
    """

    def setUp(self) -> None:
        self._original_cwd = os.getcwd()
        self.addCleanup(os.chdir, self._original_cwd)

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

    def test_malformed_lines_skipped(self):
        env_file = self.write_env("no_equals_sign\n123BAD=x\nGOOD=1\n")
        parsed = snowman.load_dotenv(env_file)
        self.assertEqual(parsed, {"GOOD": "1"})

    def test_process_env_wins_over_dotenv(self):
        env_file = self.write_env("SNOWMAN_TEST_VAR=from_dotenv\nSNOWMAN_ONLY=relayed\n")
        with mock.patch.dict(os.environ, {"SNOWMAN_TEST_VAR": "from_process"}):
            merged = snowman.snow_env(env_file)
        self.assertEqual(merged["SNOWMAN_TEST_VAR"], "from_process")
        self.assertEqual(merged["SNOWMAN_ONLY"], "relayed")

    def test_no_env_file_returns_process_env(self):
        merged = snowman.snow_env(None)
        self.assertEqual(merged, dict(os.environ))


class TestFindEnvFile(SnowmanTestCase):
    def test_walks_up(self):
        root = self.make_bare_dir()
        (root / ".env").write_text("X=1\n", encoding="utf-8")
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(snowman.find_env_file(nested), root / ".env")

    def test_none_when_absent(self):
        root = self.make_bare_dir()
        self.assertIsNone(snowman.find_env_file(root))


class TestStage(SnowmanTestCase):
    def run_stage(self, *args, **kwargs) -> str:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(snowman.stage(*args, **kwargs), 0)
        return stdout.getvalue()

    def staged_files(self, root: Path) -> list:
        return sorted((root / ".snowman" / "staged").glob("*.sql"))

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

    def test_accepts_multi_statement_dml(self):
        root = self.enter(self.make_project())
        self.run_stage("INSERT INTO t VALUES (1); UPDATE t SET x = 2;", "backfill", None)
        self.assertEqual(len(self.staged_files(root)), 1)

    def test_destructive_keywords_warn_but_never_block(self):
        root = self.enter(self.make_project())
        self.run_stage("DROP TABLE old; TRUNCATE TABLE older;", "teardown", None)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        self.assertIn("WARNING", body)
        self.assertIn("DROP", body)
        self.assertIn("TRUNCATE", body)

    def test_non_destructive_script_has_no_warning(self):
        root = self.enter(self.make_project())
        self.run_stage("INSERT INTO t VALUES (1)", "insert-row", None)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        self.assertNotIn("WARNING", body)

    def test_maintains_gitignore(self):
        root = self.enter(self.make_project())
        self.run_stage("SELECT 1", "noop", None)
        gitignore = root / ".snowman" / "staged" / ".gitignore"
        self.assertEqual(gitignore.read_text(encoding="utf-8"), "*\n")

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

    def test_stage_blocks_without_context(self):
        self.enter(self.make_bare_dir())
        self.assert_blocked(snowman.stage, "SELECT 1", "noop", None, match="bootstrap")


class TestRenderRows(SnowmanTestCase):
    """Output shaping: CSV by default, nulls as empty cells, nested as JSON."""

    def test_csv_header_then_rows(self):
        text, footers = snowman.render_rows(
            [{"A": 1, "B": "x"}, {"A": 2, "B": "y"}], fmt="csv", max_rows=50, max_cell=200
        )
        self.assertEqual(text, "A,B\n1,x\n2,y\n")
        self.assertEqual(footers, [])

    def test_null_renders_empty_with_footer(self):
        text, footers = snowman.render_rows(
            [{"A": None, "B": "x"}], fmt="csv", max_rows=50, max_cell=200
        )
        self.assertEqual(text, "A,B\n,x\n")
        self.assertEqual(footers, ["# empty cells are NULL"])

    def test_empty_string_is_quoted_and_noted(self):
        text, footers = snowman.render_rows(
            [{"A": "", "B": "x"}], fmt="csv", max_rows=50, max_cell=200
        )
        self.assertEqual(text, 'A,B\n"",x\n')
        self.assertEqual(footers, ['# "" is an empty string'])

    def test_null_and_empty_string_share_one_footer(self):
        text, footers = snowman.render_rows(
            [{"A": "", "B": None}, {"A": None, "B": ""}], fmt="csv", max_rows=50, max_cell=200
        )
        self.assertEqual(text, 'A,B\n"",\n,""\n')
        self.assertEqual(footers, ['# empty cells are NULL; "" is an empty string'])

    def test_json_mode_keeps_null_and_empty_string_distinct_without_footer(self):
        text, footers = snowman.render_rows(
            [{"A": "", "B": None}], fmt="json", max_rows=50, max_cell=200
        )
        self.assertEqual(text, '[{"A":"","B":null}]\n')
        self.assertEqual(footers, [])

    def test_cells_with_comma_quote_or_newline_are_quoted(self):
        text, _ = snowman.render_rows(
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
        _, footers = snowman.render_rows(
            [{"ID": 1}], fmt="csv", max_rows=50, max_cell=200, types=describe
        )
        self.assertEqual(
            footers,
            ["# types: AMOUNT NUMBER(10,2), TS TIMESTAMP_NTZ(9), D DATE, F FLOAT, "
             "O OBJECT, V VARIANT"],
        )

    def test_types_footer_absent_when_all_plain_or_no_describe(self):
        describe = [{"name": "ID", "type": "NUMBER"}, {"name": "S", "type": "VARCHAR(10)"}]
        _, footers = snowman.render_rows(
            [{"ID": 1}], fmt="csv", max_rows=50, max_cell=200, types=describe
        )
        self.assertEqual(footers, [])
        _, footers = snowman.render_rows([{"ID": 1}], fmt="csv", max_rows=50, max_cell=200)
        self.assertEqual(footers, [])

    def test_nested_values_render_as_compact_json(self):
        text, _ = snowman.render_rows(
            [{"O": {"k": [1, 2]}, "L": ["a", None]}], fmt="csv", max_rows=50, max_cell=200
        )
        self.assertEqual(text, 'O,L\n"{""k"":[1,2]}","[""a"",null]"\n')

    def test_numbers_untouched_and_booleans_lowercase(self):
        text, _ = snowman.render_rows(
            [{"F": 3.14159265358979, "I": 7, "B": True, "C": False}],
            fmt="csv", max_rows=50, max_cell=200,
        )
        self.assertEqual(text, "F,I,B,C\n3.14159265358979,7,true,false\n")

    def test_first_cell_starting_with_hash_is_quoted(self):
        text, _ = snowman.render_rows(
            [{"TAG": "#top", "N": 1}, {"TAG": "plain", "N": 2}, {"TAG": "#", "N": 3}],
            fmt="csv", max_rows=50, max_cell=200,
        )
        self.assertEqual(text, 'TAG,N\n"#top",1\nplain,2\n"#",3\n')

    def test_first_cell_hash_quoted_in_single_column_result(self):
        text, _ = snowman.render_rows([{"TAG": "#only"}], fmt="csv", max_rows=50, max_cell=200)
        self.assertEqual(text, 'TAG\n"#only"\n')

    def test_empty_result_prints_zero_rows_note(self):
        text, footers = snowman.render_rows([], fmt="csv", max_rows=50, max_cell=200)
        self.assertEqual(text, "")
        self.assertEqual(footers, ["# 0 rows"])

    def test_cell_truncation_suffix_and_footer(self):
        text, footers = snowman.render_rows(
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
        text, footers = snowman.render_rows(
            rows, fmt="csv", max_rows=50, max_cell=200,
            full_note="full result: .snowman/results/20260903-181200__ab12cd34.csv",
        )
        self.assertEqual(text.count("\n"), 51)  # header + 50 rows
        self.assertEqual(
            footers,
            ["# showing 50 of 1203 rows; full result: "
             ".snowman/results/20260903-181200__ab12cd34.csv; add LIMIT or a "
             "WHERE filter to narrow, or pass --max-rows 0"],
        )

    def test_max_rows_zero_is_unlimited(self):
        rows = [{"N": i} for i in range(1203)]
        text, footers = snowman.render_rows(rows, fmt="csv", max_rows=0, max_cell=200)
        self.assertEqual(text.count("\n"), 1204)
        self.assertEqual(footers, [])

    def test_footer_order_types_null_truncation_cap(self):
        rows = [{"S": "abcdefghij", "N": None}] * 3
        _, footers = snowman.render_rows(
            rows, fmt="csv", max_rows=2, max_cell=4, full_note="full result: x.csv",
            types=[{"name": "N", "type": "DATE"}],
        )
        self.assertEqual(
            [f.split(";")[0] for f in footers],
            ["# types: N DATE",
             "# empty cells are NULL",
             "# some cells truncated to 4 chars",
             "# showing 2 of 3 rows"],
        )

    def test_json_output_is_compact_and_parseable(self):
        rows = [{"O": {"k": 1}, "S": "abcdefghij", "N": None}]
        text, footers = snowman.render_rows(rows, fmt="json", max_rows=50, max_cell=4)
        self.assertEqual(text, '[{"O":{"k":1},"S":"abcd…(+6 chars)","N":null}]\n')
        self.assertEqual(json.loads(text)[0]["O"], {"k": 1})
        self.assertEqual(
            footers, ["# some cells truncated to 4 chars; pass --max-cell 0 for full values"]
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


class TestUniquePath(SnowmanTestCase):
    def test_timestamp_base_and_suffix(self):
        root = self.make_bare_dir()
        path = snowman.unique_path(root, "noop", ".sql", datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(path, root / "20260102-030405__noop.sql")

    def test_bumps_while_the_path_exists(self):
        root = self.make_bare_dir()
        now = datetime(2026, 1, 2, 3, 4, 5)
        (root / "20260102-030405__noop.sql").touch()
        (root / "20260102-030405__noop-1.sql").touch()
        path = snowman.unique_path(root, "noop", ".sql", now)
        self.assertEqual(path.name, "20260102-030405__noop-2.sql")
        self.assertFalse(path.exists())


class TestSpillFullResult(SnowmanTestCase):
    def test_writes_full_untruncated_csv_and_gitignore(self):
        root = self.make_project()
        snowman_dir = root / ".snowman"
        rows = [{"N": i, "S": "x" * 500, "V": None} for i in range(70)]
        fixed = datetime(2026, 9, 3, 18, 12, 0)
        path = snowman.spill_full_result(rows, "SELECT 1", snowman_dir, now=fixed)
        self.assertEqual(path.parent, root / ".snowman" / "results")
        self.assertRegex(path.name, r"^20260903-181200__[0-9a-f]{8}\.csv$")
        body = path.read_text(encoding="utf-8")
        self.assertEqual(body.count("\n"), 71)
        self.assertIn("x" * 500, body)
        self.assertNotIn("…", body)
        gitignore = root / ".snowman" / "results" / ".gitignore"
        self.assertEqual(gitignore.read_text(encoding="utf-8"), "*\n")

    def test_same_sql_in_the_same_second_keeps_both_results(self):
        snowman_dir = self.make_project() / ".snowman"
        fixed = datetime(2026, 9, 3, 18, 12, 0)
        first = snowman.spill_full_result([{"N": 1}], "SELECT 1", snowman_dir, now=fixed)
        second = snowman.spill_full_result([{"N": 2}], "SELECT 1", snowman_dir, now=fixed)
        self.assertNotEqual(first, second)
        self.assertEqual(second.name, first.stem + "-1.csv")
        self.assertIn("1", first.read_text(encoding="utf-8"))
        self.assertIn("2", second.read_text(encoding="utf-8"))


class TestRunSnow(SnowmanTestCase):
    """The one place subprocess.run is patched: run_snow owns the snow argv."""

    def test_prepends_snow_and_decodes_output(self):
        completed = types.SimpleNamespace(returncode=5, stdout=b"[]\n", stderr=b"bad \xff\n")
        with mock.patch.object(snowman.subprocess, "run", return_value=completed) as run:
            result = snowman.run_snow(["sql", "-q", "SELECT 1"], {"A": "1"})
        self.assertEqual(result.returncode, 5)
        self.assertEqual(result.stdout, "[]\n")
        self.assertEqual(result.stderr, "bad �\n")
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

    def test_runs_snow_with_resolved_connection(self):
        self.enter(self.make_project())
        code, _, _ = self.run_execute({"sql": OK}, "SELECT 1")
        self.assertEqual(code, 0)
        self.assertEqual(
            self.sql_args(),
            ["sql", "-q", "SELECT 1\n;DESCRIBE RESULT LAST_QUERY_ID()",
             "--connection", "analytics",
             "--format", "JSON_EXT", "--enhanced-exit-codes"],
        )

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
        for fragment in ("[\n", "[]\n"):
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
        ])
        code, out, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(code, 0)
        self.assertEqual(out, "A,B\n1,1.50\n# types: B NUMBER(10,2)\n")
        self.assertEqual(err, "")

    def test_two_statement_empty_result_reports_zero_rows(self):
        self.enter(self.make_project())
        payload = json.dumps([[], [{"name": "A", "type": "DATE"}]])
        _, out, _ = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(out, "# 0 rows\n")

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
        )
        code, out, err = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "A,O,N")
        self.assertEqual(lines[1], '1,"{""k"":1}",')
        self.assertEqual(lines[2], '2,[1],' + "x" * 200 + "…(+100 chars)")
        self.assertEqual(
            lines[3:],
            ["# empty cells are NULL",
             "# some cells truncated to 200 chars; pass --max-cell 0 for full values"],
        )
        self.assertEqual(err, "")

    def test_row_cap_spills_full_result_and_footers(self):
        root = self.enter(self.make_project())
        payload = json.dumps([{"N": i} for i in range(1203)])
        code, out, _ = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), 52)  # header + 50 rows + footer
        footer = lines[-1]
        self.assertRegex(
            footer,
            r"^# showing 50 of 1203 rows; full result: "
            r"\.snowman/results/\d{8}-\d{6}__[0-9a-f]{8}\.csv; add LIMIT or a WHERE "
            r"filter to narrow, or pass --max-rows 0$",
        )
        rel = footer.split("full result: ")[1].split(";")[0]
        self.assertEqual((root / rel).read_text(encoding="utf-8").count("\n"), 1204)

    def test_spill_footer_path_is_relative_to_cwd(self):
        root = self.enter(self.make_project())
        sub = root / "analysis" / "q1"
        sub.mkdir(parents=True)
        self.enter(sub)
        payload = json.dumps([{"N": i} for i in range(60)])
        _, out, _ = self.run_execute({"sql": Outcome(0, payload, "")}, "SELECT 1")
        footer = out.splitlines()[-1]
        rel = footer.split("full result: ")[1].split(";")[0]
        self.assertTrue(rel.startswith("../../.snowman/results/"), rel)
        self.assertTrue((Path.cwd() / rel).is_file())
        self.assertEqual(
            (Path.cwd() / rel).resolve(), root / ".snowman" / "results" / Path(rel).name
        )

    def test_row_cap_in_bootstrap_mode_skips_spill(self):
        root = self.enter(self.make_bare_dir())
        payload = json.dumps([{"N": i} for i in range(60)])
        _, out, _ = self.run_execute(
            {"sql": Outcome(0, payload, "")}, "SELECT 1", connection_override="c"
        )
        self.assertIn(
            "# showing 50 of 60 rows; no context file yet so the full result was "
            "not saved; add LIMIT or a WHERE filter to narrow, or pass --max-rows 0",
            out,
        )
        self.assertFalse((root / ".snowman").exists())

    def test_max_rows_zero_and_json_flag(self):
        self.enter(self.make_project())
        payload = json.dumps([{"N": i} for i in range(60)])
        _, out, _ = self.run_execute(
            {"sql": Outcome(0, payload, "")}, "SELECT 1", max_rows=0, fmt="json"
        )
        self.assertEqual(json.loads(out), [{"N": i} for i in range(60)])

    def test_empty_result_notes_zero_rows(self):
        self.enter(self.make_project())
        _, out, _ = self.run_execute({"sql": Outcome(0, "[]\n", "")}, "SELECT 1")
        self.assertEqual(out, "# 0 rows\n")

    def test_unparseable_stdout_relayed_raw(self):
        self.enter(self.make_project())
        code, out, _ = self.run_execute(
            {"sql": Outcome(3, "not json at all\n", "")}, "SELECT 1"
        )
        self.assertEqual(code, 3)
        self.assertEqual(out, "not json at all\n")

    def test_json_object_stdout_relayed_raw_without_footer(self):
        self.enter(self.make_project())
        code, out, _ = self.run_execute(
            {"sql": Outcome(0, '{"a": 1}\n', "")}, "SELECT 1"
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, '{"a": 1}\n')

    def test_sql_error_panel_cleaned_and_exit_code_forwarded(self):
        self.enter(self.make_project())
        code, out, err = self.run_execute(
            {"sql": Outcome(5, "", PANEL_STDERR)}, "SELECT 1"
        )
        self.assertEqual(code, 5)
        self.assertEqual(out, "")
        self.assertEqual(err, PANEL_CLEANED)

    def test_forwards_snow_exit_code_and_stderr(self):
        self.enter(self.make_project())
        code, out, err = self.run_execute(
            {"sql": Outcome(1, "", "some snow error\n")}, "SELECT 1"
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
            {"sql": Outcome(1, "", panel),
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
            {"sql": Outcome(1, "", "syntax error\n")}, "SELECT 1"
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
            ("garbage output", Outcome(0, "not json", "")),
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
            "SELECT 1", connection_override=None, env=None, fmt="json", max_rows=5, max_cell=10
        )

    def test_main_output_flag_defaults(self):
        with mock.patch.object(snowman, "execute", return_value=0) as execute:
            self.assertEqual(snowman.main(["snowman.py", "SELECT 1"]), 0)
        execute.assert_called_once_with(
            "SELECT 1", connection_override=None, env=None, fmt="csv", max_rows=50, max_cell=200
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

    def test_main_routes_to_stage(self):
        root = self.enter(self.make_project())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(
                snowman.main(["snowman.py", "--stage", "--name", "noop", "DROP TABLE t"]),
                0,
            )
        self.assertTrue(list((root / ".snowman" / "staged").glob("*.sql")))


if __name__ == "__main__":
    unittest.main()
