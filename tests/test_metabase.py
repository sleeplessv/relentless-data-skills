"""Tests for skills/metabase/scripts/mb.py.

Standard library only, like the script itself. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here ever talks to a Metabase instance: every test targets the pure
functions — the read-only SQL check, config/env parsing, the JSON walkers, and
the mutable/restorable field-set invariant. `api()` is never called.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "metabase" / "scripts"))

import mb  # noqa: E402


def blocked(fn, *args, **kwargs) -> str:
    """Run fn expecting a BLOCKED exit; return the stderr message."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            if exc.code != 2:
                raise AssertionError(f"expected exit 2, got {exc.code}")
            return err.getvalue()
    raise AssertionError(f"expected a BLOCKED exit, got none. stderr: {err.getvalue()!r}")


class StripSql(unittest.TestCase):
    """Comments and literals must be blanked so nothing hides inside them."""

    def test_line_and_block_comments_go(self):
        self.assertNotIn("DELETE", mb.strip_sql("SELECT 1 -- DELETE FROM t"))
        self.assertNotIn("DROP", mb.strip_sql("SELECT /* DROP TABLE t */ 1"))

    def test_nested_block_comments(self):
        self.assertNotIn("DROP", mb.strip_sql("SELECT /* a /* DROP */ b */ 1"))

    def test_string_literals_go(self):
        self.assertNotIn("DELETE", mb.strip_sql("SELECT 'DELETE FROM t'"))
        self.assertNotIn("DELETE", mb.strip_sql('SELECT "DELETE"'))

    def test_doubled_quote_escape_does_not_end_the_literal(self):
        # 'it''s DELETE' is ONE literal — a naive scanner reopens at ''.
        self.assertNotIn("DELETE", mb.strip_sql("SELECT 'it''s DELETE'"))

    def test_dollar_quoting(self):
        self.assertNotIn("DROP", mb.strip_sql("SELECT $$ DROP TABLE t $$"))
        self.assertNotIn("DROP", mb.strip_sql("SELECT $tag$ DROP TABLE t $tag$"))

    def test_e_string_backslash_escape(self):
        # E'\'' keeps the literal open past the escaped quote.
        self.assertNotIn("DELETE", mb.strip_sql(r"SELECT E'\' DELETE'"))

    def test_lowercase_e_string(self):
        self.assertNotIn("DELETE", mb.strip_sql(r"SELECT e'\' DELETE'"))

    def test_identifier_ending_in_e_is_not_an_e_string(self):
        # `some_e'x'` — the quote opens a plain literal, not an E-string.
        self.assertNotIn("DELETE", mb.strip_sql("SELECT some_e'DELETE'"))

    def test_unterminated_literal_raises(self):
        for sql in ("SELECT 'oops", "SELECT /* oops", "SELECT $$ oops"):
            with self.assertRaises(mb.Unterminated):
                mb.strip_sql(sql)

    def test_code_outside_literals_survives(self):
        self.assertIn("FROM t", mb.strip_sql("SELECT a FROM t -- x"))


class AssertReadonly(unittest.TestCase):
    def test_allows_read_only_leaders(self):
        for sql in (
            "SELECT 1",
            "select 1",
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "(SELECT 1)",
            "SHOW TABLES",
            "EXPLAIN SELECT 1",
            "DESCRIBE t",
            "VALUES (1)",
            "SELECT 1;",
        ):
            with self.subTest(sql=sql):
                mb.assert_readonly(sql)  # must not raise

    def test_write_leaders_blocked(self):
        for sql in ("DELETE FROM t", "UPDATE t SET a=1", "INSERT INTO t VALUES (1)",
                    "DROP TABLE t", "CREATE TABLE t (a int)", "GRANT ALL ON t TO x"):
            with self.subTest(sql=sql):
                blocked(mb.assert_readonly, sql)

    def test_data_modifying_cte_blocked(self):
        msg = blocked(mb.assert_readonly,
                      "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x")
        self.assertIn("DELETE", msg)

    def test_multiple_statements_blocked(self):
        msg = blocked(mb.assert_readonly, "SELECT 1; SELECT 2")
        self.assertIn("one statement", msg)

    def test_trailing_semicolon_is_not_a_second_statement(self):
        mb.assert_readonly("SELECT 1 ;  ")

    def test_semicolon_inside_a_literal_is_not_a_second_statement(self):
        mb.assert_readonly("SELECT 'a;b'")

    def test_unterminated_literal_blocked_not_swallowed(self):
        # Failing loudly is the point: a swallowed tail hides a second statement.
        msg = blocked(mb.assert_readonly, "SELECT 'oops; DROP TABLE t")
        self.assertIn("unterminated", msg)

    def test_empty_query_blocked(self):
        blocked(mb.assert_readonly, "   -- nothing here")

    def test_select_into_blocked(self):
        msg = blocked(mb.assert_readonly, "SELECT a INTO newtbl FROM t")
        self.assertIn("INTO", msg)

    def test_side_effecting_functions_blocked(self):
        for sql in ("SELECT nextval('s')", "SELECT pg_sleep(10)",
                    "SELECT pg_read_file('/etc/passwd')",
                    "SELECT dblink_exec('…','…')"):
            with self.subTest(sql=sql):
                blocked(mb.assert_readonly, sql)

    def test_write_keyword_inside_a_literal_is_allowed(self):
        # The keyword scan runs on stripped SQL, so data can mention DELETE.
        mb.assert_readonly("SELECT * FROM t WHERE action = 'DELETE'")

    def test_column_named_like_a_leading_only_keyword_is_allowed(self):
        # `comment`/`set` are only dangerous as a first token — see ALWAYS_BLOCKED.
        mb.assert_readonly("SELECT comment, set_id FROM t")

    def test_blocked_message_prefix(self):
        self.assertTrue(blocked(mb.assert_readonly, "DELETE FROM t")
                        .startswith("BLOCKED: "))


class EnvParsing(unittest.TestCase):
    def test_plain_and_export(self):
        self.assertEqual(mb.parse_env_line("A=1"), ("A", "1"))
        self.assertEqual(mb.parse_env_line("export A=1"), ("A", "1"))

    def test_matched_quotes_are_stripped(self):
        self.assertEqual(mb.parse_env_line("A='v'"), ("A", "v"))
        self.assertEqual(mb.parse_env_line('A="v"'), ("A", "v"))

    def test_unquoted_trailing_comment_is_dropped(self):
        self.assertEqual(mb.parse_env_line("A=v  # note"), ("A", "v"))

    def test_hash_inside_quotes_is_kept(self):
        # A key with a # in it must survive verbatim.
        self.assertEqual(mb.parse_env_line("A='v#1'"), ("A", "v#1"))

    def test_value_may_contain_equals(self):
        self.assertEqual(mb.parse_env_line("A=b=c"), ("A", "b=c"))

    def test_non_assignments_ignored(self):
        for line in ("", "   ", "# comment", "no equals here", "1BAD=x"):
            with self.subTest(line=line):
                self.assertIsNone(mb.parse_env_line(line))


class WalkFieldIds(unittest.TestCase):
    """Both argument orders, or half the ids get rewritten silently."""

    def test_pmbql_order_opts_second_id_third(self):
        node = ["field", {"base-type": "type/DateTime"}, 18607]
        self.assertEqual(sorted(mb.walk_field_ids(node)), [18607])

    def test_legacy_order_id_second_opts_third(self):
        node = ["field", 18607, {"base-type": "type/DateTime"}]
        self.assertEqual(sorted(mb.walk_field_ids(node)), [18607])

    def test_name_based_reference_yields_nothing(self):
        node = ["field", "backup_type", {"stage-number": 0}]
        self.assertEqual(sorted(mb.walk_field_ids(node)), [])

    def test_source_field_and_source_table_are_values_under_a_key(self):
        node = {"source-table": 1003, "filter": {"source-field": 4242}}
        self.assertEqual(sorted(mb.walk_field_ids(node)), [1003, 4242])

    def test_nested_mixed_orders(self):
        node = {"target": ["dimension", ["field", 1, {}], {"stage-number": 0}],
                "query": {"fields": [["field", {}, 2]], "source-field": 3}}
        self.assertEqual(sorted(mb.walk_field_ids(node)), [1, 2, 3])


class SourceCards(unittest.TestCase):
    def test_finds_nested_source_card_and_card_string(self):
        q = {"stages": [{"source-card": 12},
                        {"joins": [{"source-table": "card__34"}]}]}
        self.assertEqual(sorted(mb._find_source_cards(q, set())), [12, 34])

    def test_ignores_plain_table_ids(self):
        self.assertEqual(mb._find_source_cards({"source-table": 1003}, set()), set())


class NativeOf(unittest.TestCase):
    def test_stages_shape(self):
        card = {"dataset_query": {"stages": [{"native": "SELECT 1",
                                              "template-tags": {"a": {}}}]}}
        sql, tags = mb._native_of(card)
        self.assertEqual(sql, "SELECT 1")
        self.assertEqual(list(tags), ["a"])

    def test_legacy_shape(self):
        card = {"dataset_query": {"native": {"query": "SELECT 1"}}}
        self.assertEqual(mb._native_of(card)[0], "SELECT 1")

    def test_mbql_card_has_no_native_sql(self):
        card = {"dataset_query": {"stages": [{"source-card": 5}]}}
        self.assertEqual(mb._native_of(card), (None, {}))

    def test_multi_stage_native_is_not_treated_as_the_whole_query(self):
        # native stage 0 + MBQL stage 1: reading stage 0 alone would be wrong,
        # so _native_of declines and the caller compiles instead.
        card = {"dataset_query": {"stages": [{"native": "SELECT 1"},
                                             {"aggregation": [["count"]]}]}}
        self.assertEqual(mb._native_of(card), (None, {}))


class RowsFromDataset(unittest.TestCase):
    def test_keys_off_col_name_not_display_name(self):
        res = {"data": {"cols": [{"name": "id", "display_name": "ID"},
                                 {"name": "id_2", "display_name": "ID"}],
                        "rows": [[1, 2]]}}
        self.assertEqual(mb.rows_from_dataset(res), [{"id": 1, "id_2": 2}])

    def test_failed_status_exits_even_though_http_was_2xx(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                mb.rows_from_dataset({"status": "failed", "error": "boom"})
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("boom", err.getvalue())


class FieldSetInvariants(unittest.TestCase):
    """Anything the wrapper can change, it must also be able to undo."""

    def _restorable(self, source: str, const: str) -> bool:
        return f"for k in {const} if k in saved" in source

    def test_restore_uses_the_same_sets_update_accepts(self):
        source = (REPO_ROOT / "skills" / "metabase" / "scripts" / "mb.py").read_text()
        self.assertTrue(self._restorable(source, "MUTABLE"))
        self.assertTrue(self._restorable(source, "DASH_MUTABLE"))

    def test_archived_and_collection_id_are_recoverable(self):
        for field in ("archived", "collection_id"):
            self.assertIn(field, mb.MUTABLE)
            self.assertIn(field, mb.DASH_MUTABLE)

    def test_dashcards_is_dashboard_only(self):
        self.assertIn("dashcards", mb.DASH_MUTABLE)
        self.assertNotIn("dashcards", mb.MUTABLE)


class ContextUrl(unittest.TestCase):
    def test_reads_url_from_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Path(tmp) / "context.md"
            ctx.write_text("---\nurl: https://mb.example.com\nsuperuser: False\n---\n")
            original = mb.CTX_FILE
            mb.CTX_FILE = ctx
            try:
                self.assertEqual(mb.context_url(), "https://mb.example.com")
            finally:
                mb.CTX_FILE = original

    def test_missing_file_is_none(self):
        original = mb.CTX_FILE
        mb.CTX_FILE = Path("/nonexistent/context.md")
        try:
            self.assertIsNone(mb.context_url())
        finally:
            mb.CTX_FILE = original


class LoadBody(unittest.TestCase):
    def _write(self, tmp: str, text: str) -> str:
        p = Path(tmp) / "body.json"
        p.write_text(text)
        return str(p)

    def test_rejects_non_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked(mb._load_body, self._write(tmp, "[1, 2]"))

    def test_rejects_empty_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked(mb._load_body, self._write(tmp, "{}"))

    def test_accepts_an_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mb._load_body(self._write(tmp, '{"name": "x"}')),
                             {"name": "x"})


if __name__ == "__main__":
    unittest.main()
