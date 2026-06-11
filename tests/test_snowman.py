"""Tests for skills/snowman/scripts/snowman.py.

Standard library only, like the script itself. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here ever talks to Snowflake: execute() tests mock subprocess.run,
and stage mode never executes by design.
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


def fake_completed(
    returncode: int = 0, stderr: bytes = b"", stdout: bytes = b""
) -> types.SimpleNamespace:
    return types.SimpleNamespace(returncode=returncode, stderr=stderr, stdout=stdout)


def fake_connection_list(connection: str, parameters: dict) -> types.SimpleNamespace:
    """A successful `snow connection list --format JSON` result."""
    listing = [{"connection_name": connection, "parameters": parameters}]
    return fake_completed(stdout=json.dumps(listing).encode())


class SnowmanTestCase(unittest.TestCase):
    """Shared helpers: BLOCKED assertions and a temp project to chdir into."""

    def setUp(self) -> None:
        self._original_cwd = os.getcwd()
        self.addCleanup(os.chdir, self._original_cwd)

    def assert_blocked(self, fn, *args, match: str = "", **kwargs) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as cm:
            fn(*args, **kwargs)
        self.assertEqual(cm.exception.code, snowman.BLOCK)
        message = stderr.getvalue()
        self.assertIn("BLOCKED:", message)
        if match:
            self.assertIn(match, message)
        return message

    def make_project(self, frontmatter: str = SINGLE_CONN_FRONTMATTER) -> Path:
        """Create a temp project with .snowman/context.md and chdir into it."""
        root = Path(tempfile.mkdtemp(prefix="snowman-test-")).resolve()
        self.addCleanup(self._rmtree, root)
        snowman_dir = root / ".snowman"
        snowman_dir.mkdir()
        (snowman_dir / "context.md").write_text(frontmatter, encoding="utf-8")
        os.chdir(root)
        return root

    def make_bare_dir(self) -> Path:
        """Create a temp dir with no context file and chdir into it."""
        root = Path(tempfile.mkdtemp(prefix="snowman-test-")).resolve()
        self.addCleanup(self._rmtree, root)
        os.chdir(root)
        return root

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


class TestResolveConnection(SnowmanTestCase):
    def context_with(self, text: str) -> Path:
        root = self.make_bare_dir()
        context = root / "context.md"
        context.write_text(text, encoding="utf-8")
        return context

    def test_legacy_single_connection(self):
        context = self.context_with(SINGLE_CONN_FRONTMATTER)
        self.assertEqual(snowman.resolve_connection(context, None), ("analytics", None))

    def test_legacy_rejects_env_flag(self):
        context = self.context_with(SINGLE_CONN_FRONTMATTER)
        self.assert_blocked(
            snowman.resolve_connection, context, "dev", match="--env was given"
        )

    def test_legacy_missing_connection_blocks(self):
        context = self.context_with("---\nowner: someone\n---\n")
        self.assert_blocked(
            snowman.resolve_connection, context, None, match="no `connection:`"
        )

    def test_multi_env_explicit(self):
        context = self.context_with(MULTI_ENV_FRONTMATTER)
        self.assertEqual(
            snowman.resolve_connection(context, "prod"), ("acme_prod", "prod")
        )

    def test_multi_env_falls_back_to_default(self):
        context = self.context_with(MULTI_ENV_FRONTMATTER)
        self.assertEqual(snowman.resolve_connection(context, None), ("acme_dev", "dev"))

    def test_multi_env_unknown_env_blocks(self):
        context = self.context_with(MULTI_ENV_FRONTMATTER)
        self.assert_blocked(
            snowman.resolve_connection, context, "staging", match="unknown environment"
        )

    def test_multi_env_no_default_and_no_flag_blocks(self):
        context = self.context_with(
            "---\nenvironments:\n  dev:\n    connection: acme_dev\n---\n"
        )
        self.assert_blocked(
            snowman.resolve_connection, context, None, match="default_env"
        )

    def test_both_forms_blocks(self):
        context = self.context_with(
            "---\n"
            "connection: legacy\n"
            "environments:\n"
            "  dev:\n"
            "    connection: acme_dev\n"
            "default_env: dev\n"
            "---\n"
        )
        self.assert_blocked(
            snowman.resolve_connection, context, None, match="exactly one form"
        )

    def test_stage_requires_explicit_env(self):
        context = self.context_with(MULTI_ENV_FRONTMATTER)
        self.assert_blocked(
            snowman.resolve_connection,
            context,
            None,
            for_stage=True,
            match="requires --env",
        )

    def test_env_without_connection_value_blocks(self):
        context = self.context_with(
            "---\nenvironments:\n  dev:\n    role: analyst\ndefault_env: dev\n---\n"
        )
        self.assert_blocked(
            snowman.resolve_connection, context, None, match="no `connection:` value"
        )


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


class TestDiscovery(SnowmanTestCase):
    def test_find_context_walks_up(self):
        root = self.make_project()
        nested = root / "models" / "marts"
        nested.mkdir(parents=True)
        os.chdir(nested)
        self.assertEqual(snowman.find_context(), root / ".snowman" / "context.md")

    def test_find_context_blocks_without_bootstrap(self):
        self.make_bare_dir()
        self.assert_blocked(snowman.find_context, match="bootstrap")

    def test_find_env_file_walks_up(self):
        root = self.make_bare_dir()
        (root / ".env").write_text("X=1\n", encoding="utf-8")
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(snowman.find_env_file(nested), root / ".env")

    def test_find_env_file_none_when_absent(self):
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
        root = self.make_project()
        output = self.run_stage("CREATE TABLE t (id INT)", "create-t", None)
        self.assertIn("STAGED (not executed)", output)
        files = self.staged_files(root)
        self.assertEqual(len(files), 1)
        body = files[0].read_text(encoding="utf-8")
        self.assertIn("-- staged by snowman — NOT executed", body)
        self.assertIn("-- purpose: create-t", body)
        self.assertIn("snow sql -f", body)
        self.assertIn("--connection analytics", body)
        self.assertIn("CREATE TABLE t (id INT)", body)

    def test_accepts_multi_statement_dml(self):
        root = self.make_project()
        self.run_stage("INSERT INTO t VALUES (1); UPDATE t SET x = 2;", "backfill", None)
        self.assertEqual(len(self.staged_files(root)), 1)

    def test_destructive_keywords_warn_but_never_block(self):
        root = self.make_project()
        self.run_stage("DROP TABLE old; TRUNCATE TABLE older;", "teardown", None)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        self.assertIn("WARNING", body)
        self.assertIn("DROP", body)
        self.assertIn("TRUNCATE", body)

    def test_non_destructive_script_has_no_warning(self):
        root = self.make_project()
        self.run_stage("INSERT INTO t VALUES (1)", "insert-row", None)
        body = self.staged_files(root)[0].read_text(encoding="utf-8")
        self.assertNotIn("WARNING", body)

    def test_maintains_gitignore(self):
        root = self.make_project()
        self.run_stage("SELECT 1", "noop", None)
        gitignore = root / ".snowman" / "staged" / ".gitignore"
        self.assertEqual(gitignore.read_text(encoding="utf-8"), "*\n")

    def test_empty_script_blocks(self):
        self.make_project()
        self.assert_blocked(snowman.stage, "   ", "noop", None, match="empty")

    def test_name_normalised_to_slug(self):
        root = self.make_project()
        self.run_stage("SELECT 1", "Add  User--Table!", None)
        self.assertIn("add-user-table", self.staged_files(root)[0].name)

    def test_unusable_name_blocks(self):
        self.make_project()
        self.assert_blocked(snowman.stage, "SELECT 1", "!!!", None, match="empty slug")

    def test_multi_env_requires_env_flag(self):
        self.make_project(MULTI_ENV_FRONTMATTER)
        self.assert_blocked(
            snowman.stage, "SELECT 1", "noop", None, match="requires --env"
        )

    def test_multi_env_stamps_env_in_filename_and_header(self):
        root = self.make_project(MULTI_ENV_FRONTMATTER)
        self.run_stage("SELECT 1", "noop", "prod")
        staged = self.staged_files(root)[0]
        self.assertIn("prod__noop", staged.name)
        body = staged.read_text(encoding="utf-8")
        self.assertIn("-- target environment: prod (connection: acme_prod)", body)

    def test_filename_collision_bumps_suffix(self):
        root = self.make_project()
        fixed = datetime(2026, 1, 2, 3, 4, 5)
        fake_datetime = mock.Mock(now=mock.Mock(return_value=fixed))
        with mock.patch.object(snowman, "datetime", fake_datetime):
            self.run_stage("SELECT 1", "noop", None)
            self.run_stage("SELECT 2", "noop", None)
        names = [f.name for f in self.staged_files(root)]
        self.assertEqual(
            names,
            ["20260102-030405__noop-1.sql", "20260102-030405__noop.sql"],
        )

    def test_stage_blocks_without_context(self):
        self.make_bare_dir()
        self.assert_blocked(snowman.stage, "SELECT 1", "noop", None, match="bootstrap")


class TestExecute(SnowmanTestCase):
    def test_blocked_sql_never_reaches_snow(self):
        self.make_project()
        with mock.patch.object(snowman.subprocess, "run") as run:
            self.assert_blocked(snowman.execute, "DROP TABLE t")
        run.assert_not_called()

    def test_runs_snow_with_resolved_connection(self):
        self.make_project()
        with mock.patch.object(
            snowman.subprocess, "run", return_value=fake_completed()
        ) as run:
            self.assertEqual(snowman.execute("SELECT 1"), 0)
        cmd = run.call_args[0][0]
        self.assertEqual(
            cmd,
            ["snow", "sql", "-q", "SELECT 1", "--connection", "analytics",
             "--format", "JSON"],
        )

    def test_forwards_snow_exit_code_and_stderr(self):
        self.make_project()
        stderr = io.StringIO()
        with mock.patch.object(
            snowman.subprocess, "run",
            return_value=fake_completed(returncode=1, stderr=b"some snow error\n"),
        ), contextlib.redirect_stderr(stderr):
            self.assertEqual(snowman.execute("SELECT 1"), 1)
        self.assertIn("some snow error", stderr.getvalue())

    def test_multi_env_picks_connection(self):
        self.make_project(MULTI_ENV_FRONTMATTER)
        with mock.patch.object(
            snowman.subprocess, "run", return_value=fake_completed()
        ) as run:
            snowman.execute("SELECT 1", env="prod")
        self.assertIn("acme_prod", run.call_args[0][0])

    def test_multi_env_default_fallback(self):
        self.make_project(MULTI_ENV_FRONTMATTER)
        with mock.patch.object(
            snowman.subprocess, "run", return_value=fake_completed()
        ) as run:
            snowman.execute("SELECT 1")
        self.assertIn("acme_dev", run.call_args[0][0])

    def test_connection_override_skips_context(self):
        self.make_bare_dir()  # no context file at all
        with mock.patch.object(
            snowman.subprocess, "run", return_value=fake_completed()
        ) as run:
            self.assertEqual(
                snowman.execute("SELECT 1", connection_override="bootstrap_conn"), 0
            )
        self.assertIn("bootstrap_conn", run.call_args[0][0])

    def test_blocks_without_context_and_without_override(self):
        self.make_bare_dir()
        with mock.patch.object(snowman.subprocess, "run") as run:
            self.assert_blocked(snowman.execute, "SELECT 1", match="bootstrap")
        run.assert_not_called()

    def test_dotenv_relayed_to_snow_process_env_wins(self):
        root = self.make_project()
        (root / ".env").write_text(
            "RELAYED_ONLY=from_dotenv\nALREADY_SET=from_dotenv\n", encoding="utf-8"
        )
        with mock.patch.dict(os.environ, {"ALREADY_SET": "from_process"}), \
                mock.patch.object(
                    snowman.subprocess, "run", return_value=fake_completed()
                ) as run:
            snowman.execute("SELECT 1")
        env = run.call_args[1]["env"]
        self.assertEqual(env["RELAYED_ONLY"], "from_dotenv")
        self.assertEqual(env["ALREADY_SET"], "from_process")

    def test_missing_snow_cli_blocks(self):
        self.make_project()
        stderr = io.StringIO()
        with mock.patch.object(
            snowman.subprocess, "run", side_effect=FileNotFoundError
        ), contextlib.redirect_stderr(stderr):
            self.assertEqual(snowman.execute("SELECT 1"), snowman.BLOCK)
        self.assertIn("`snow` CLI not found", stderr.getvalue())

    def run_failing_auth(self, sql_stderr: bytes, lookup) -> str:
        """Execute with a failing snow call followed by a connection lookup."""
        stderr = io.StringIO()
        with mock.patch.object(
            snowman.subprocess, "run",
            side_effect=[fake_completed(returncode=1, stderr=sql_stderr), lookup],
        ), contextlib.redirect_stderr(stderr):
            self.assertEqual(snowman.execute("SELECT 1"), 1)
        return stderr.getvalue()

    def test_auth_failure_keypair_hint(self):
        self.make_project()
        output = self.run_failing_auth(
            b"could not decrypt private key\n",
            fake_connection_list(
                "analytics",
                {"authenticator": "SNOWFLAKE_JWT", "private_key_file": "/k.pem"},
            ),
        )
        self.assertIn("key-pair auth failure", output)
        self.assertIn("no .env file was found", output)
        self.assertNotIn("snow connection test", output)

    def test_auth_failure_browser_hint(self):
        self.make_project()
        output = self.run_failing_auth(
            b"OAuth access token expired\n",
            fake_connection_list(
                "analytics", {"authenticator": "OAUTH_AUTHORIZATION_CODE"}
            ),
        )
        self.assertIn("authenticates in a browser", output)
        self.assertIn("snow connection test -c analytics", output)
        self.assertNotIn("PRIVATE_KEY_PASSPHRASE", output)

    def test_auth_failure_unknown_gets_combined_hint(self):
        self.make_project()
        output = self.run_failing_auth(
            b"JWT token is invalid\n",
            fake_completed(stdout=b"not json"),  # lookup fails -> generic hint
        )
        self.assertIn("PRIVATE_KEY_PASSPHRASE", output)
        self.assertIn("snow connection test -c analytics", output)

    def test_auth_hint_mentions_loaded_dotenv(self):
        root = self.make_project()
        (root / ".env").write_text("PRIVATE_KEY_PASSPHRASE=x\n", encoding="utf-8")
        output = self.run_failing_auth(
            b"bad passphrase\n",
            fake_connection_list("analytics", {"authenticator": "SNOWFLAKE_JWT"}),
        )
        self.assertIn("a .env was loaded from", output)

    def test_non_auth_failure_gets_no_hint(self):
        self.make_project()
        stderr = io.StringIO()
        with mock.patch.object(
            snowman.subprocess, "run",
            return_value=fake_completed(returncode=1, stderr=b"syntax error\n"),
        ), contextlib.redirect_stderr(stderr):
            self.assertEqual(snowman.execute("SELECT 1"), 1)
        self.assertNotIn("hint:", stderr.getvalue())


class TestAuthClassification(SnowmanTestCase):
    def test_browser_authenticators(self):
        for value in ("OAUTH_AUTHORIZATION_CODE", "EXTERNALBROWSER", "externalbrowser"):
            with self.subTest(authenticator=value):
                self.assertEqual(
                    snowman.classify_auth({"authenticator": value}), "browser"
                )

    def test_keypair_via_authenticator(self):
        self.assertEqual(
            snowman.classify_auth({"authenticator": "SNOWFLAKE_JWT"}), "keypair"
        )

    def test_keypair_via_private_key_file_without_authenticator(self):
        self.assertEqual(
            snowman.classify_auth({"private_key_file": "/k.pem"}), "keypair"
        )

    def test_unknown_for_missing_or_other(self):
        for params in (None, {}, {"authenticator": "OAUTH_CLIENT_CREDENTIALS"}):
            with self.subTest(params=params):
                self.assertEqual(snowman.classify_auth(params), "unknown")


class TestConnectionParams(SnowmanTestCase):
    def lookup(self, result) -> dict | None:
        with mock.patch.object(snowman.subprocess, "run", return_value=result):
            return snowman.connection_params("analytics", dict(os.environ))

    def test_returns_parameters_for_listed_connection(self):
        params = self.lookup(
            fake_connection_list("analytics", {"authenticator": "SNOWFLAKE_JWT"})
        )
        self.assertEqual(params, {"authenticator": "SNOWFLAKE_JWT"})

    def test_none_when_connection_not_listed(self):
        self.assertIsNone(
            self.lookup(fake_connection_list("other", {"authenticator": "X"}))
        )

    def test_none_on_garbage_output(self):
        self.assertIsNone(self.lookup(fake_completed(stdout=b"not json")))

    def test_none_when_snow_missing(self):
        with mock.patch.object(
            snowman.subprocess, "run", side_effect=FileNotFoundError
        ):
            self.assertIsNone(snowman.connection_params("analytics", {}))


class TestAuthErrorRe(SnowmanTestCase):
    def test_matches_auth_failures(self):
        for message in (
            "could not decrypt private key",
            "JWT token is invalid",
            "OAuth access token expired or invalid",
            "Failed to authenticate: 250001",
        ):
            with self.subTest(message=message):
                self.assertTrue(snowman.AUTH_ERROR_RE.search(message))

    def test_ignores_parser_token_errors(self):
        self.assertFalse(
            snowman.AUTH_ERROR_RE.search("syntax error: unexpected token 'FROM'")
        )


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

    def test_main_routes_to_execute(self):
        self.make_project()
        with mock.patch.object(
            snowman.subprocess, "run", return_value=fake_completed()
        ) as run:
            self.assertEqual(snowman.main(["snowman.py", "SELECT 1"]), 0)
        run.assert_called_once()

    def test_main_routes_to_stage(self):
        root = self.make_project()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(
                snowman.main(["snowman.py", "--stage", "--name", "noop", "DROP TABLE t"]),
                0,
            )
        self.assertTrue(list((root / ".snowman" / "staged").glob("*.sql")))


if __name__ == "__main__":
    unittest.main()
