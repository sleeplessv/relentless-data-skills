"""Tests for skills/dossier/scripts/diff_html.py.

Standard library only. Run from the repo root:

    python3 -m unittest tests/test_dossier_diff.py -v

diff_html.py turns unified diff text (from `git diff` or `git show`) into the
dossier's diff rows: `pre.code.diff` lines with old and new line numbers,
GitHub-style word highlights and optional numbered annotation markers.
"""
from __future__ import annotations

import io
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "dossier" / "scripts"))

import diff_html  # noqa: E402

ONE_HUNK = """\
diff --git a/notes.txt b/notes.txt
index 1111111..2222222 100644
--- a/notes.txt
+++ b/notes.txt
@@ -3,4 +3,4 @@ Heading
 alpha
-the quick brown fox
+the quick red fox
 omega
 end
"""


def row_texts(fragment):
    """(classes, old number, new number, sign, text without tags) per row."""
    rows = re.findall(r'<span class="l ([^"]*)"[^>]*><span class="o">([^<]*)</span>'
                      r'<span class="n">([^<]*)</span><span class="sg">([^<]*)</span>'
                      r'<span class="t">(.*?)</span></span>(?=<span class="l |</code>|$)',
                      fragment)
    return [(c, o, n, s, re.sub(r"<[^>]+>", "", t)) for c, o, n, s, t in rows]


class TestRows(unittest.TestCase):
    def test_one_hunk_gives_hunk_context_removed_and_added_rows_with_both_line_numbers(self):
        out = diff_html.render(ONE_HUNK)
        self.assertTrue(out.startswith('<pre class="code diff"><code>'))
        self.assertEqual(row_texts(out), [
            ("hunk", "", "", "", "@@ -3,4 +3,4 @@ Heading"),
            ("ctx", "3", "3", " ", "alpha"),
            ("del", "4", "", "-", "the quick brown fox"),
            ("add", "", "4", "+", "the quick red fox"),
            ("ctx", "5", "5", " ", "omega"),
            ("ctx", "6", "6", " ", "end"),
        ])

    def test_paired_lines_highlight_only_the_changed_words(self):
        out = diff_html.render(ONE_HUNK)
        self.assertEqual(re.findall(r'<span class="w">([^<]*)</span>', out), ["brown", "red"])
        self.assertIn('<span class="t">the quick <span class="w">brown</span> fox</span>', out)
        self.assertIn('<span class="t">the quick <span class="w">red</span> fox</span>', out)

    def test_changed_words_separated_only_by_spaces_form_one_highlight(self):
        old, new = diff_html.words("keep aa bb cc keep too", "keep xx yy zz keep too")
        self.assertEqual(old, 'keep <span class="w">aa bb cc</span> keep too')
        self.assertEqual(new, 'keep <span class="w">xx yy zz</span> keep too')

    def test_unlike_lines_get_no_word_highlight(self):
        diff = "@@ -1 +1 @@\n-completely different words here\n+nothing shared at all, really\n"
        self.assertNotIn('class="w"', diff_html.render(diff))

    def test_a_run_of_removals_pairs_with_the_following_additions_in_order(self):
        diff = "@@ -1,2 +1,3 @@\n-one two three\n-four five six\n+one 2 three\n+four five 6\n+brand new line\n"
        self.assertEqual(re.findall(r'<span class="w">([^<]*)</span>', diff_html.render(diff)),
                         ["two", "six", "2", "6"])

    def test_html_in_the_diff_is_escaped(self):
        diff = '@@ -1 +1 @@\n-<b class="x">a & b</b>\n+<i>a & c</i>\n'
        out = diff_html.render(diff)
        self.assertNotIn("<b ", out)
        self.assertNotIn("<i>", out)
        self.assertIn("&lt;b class=&quot;x&quot;&gt;", out)
        self.assertIn("&amp;", out)

    def test_each_hunk_restarts_its_line_numbers(self):
        diff = ("@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
                "@@ -40,2 +40,3 @@ def f():\n x\n+y\n z\n")
        self.assertEqual([(c, o, n) for c, o, n, _, _ in row_texts(diff_html.render(diff))], [
            ("hunk", "", ""), ("ctx", "1", "1"), ("del", "2", ""), ("add", "", "2"),
            ("hunk", "", ""), ("ctx", "40", "40"), ("add", "", "41"), ("ctx", "41", "42"),
        ])

    def test_no_newline_marker_is_a_numberless_note_row_not_a_line(self):
        diff = "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
        rows = row_texts(diff_html.render(diff))
        self.assertEqual([(c, o, n, t) for c, o, n, _, t in rows], [
            ("hunk", "", "", "@@ -1 +1 @@"),
            ("del", "1", "", "old"),
            ("ctx nonl", "", "", "No newline at end of file"),
            ("add", "", "1", "new"),
            ("ctx nonl", "", "", "No newline at end of file"),
        ])

    def test_only_a_newline_ends_a_line(self):
        # Form feed and the other separators str.splitlines() honours are text.
        diff = "@@ -1,2 +1,2 @@\r\n-a\x0cb\r\n+a\x0cc\r\n ctx\x1dend\u2028\r\n"
        rows = row_texts(diff_html.render(diff))
        self.assertEqual([(c, o, n, t) for c, o, n, _, t in rows], [
            ("hunk", "", "", "@@ -1,2 +1,2 @@"),
            ("del", "1", "", "a\x0cb"),
            ("add", "", "1", "a\x0cc"),
            ("ctx", "2", "2", "ctx\x1dend\u2028"),
        ])

TWO_FILES = """\
commit 0123456789abcdef
Author: Someone <someone@example.com>

    subject line
    -not a removal, part of the message

diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-a old
+a new
diff --git a/dir/b.txt b/dir/b.txt
--- a/dir/b.txt
+++ b/dir/b.txt
@@ -7 +7 @@
-b old
+b new
"""


class TestFiles(unittest.TestCase):
    def test_a_diff_of_several_files_needs_a_path(self):
        with self.assertRaises(diff_html.DiffError) as cm:
            diff_html.render(TWO_FILES)
        self.assertIn("a.txt", str(cm.exception))
        self.assertIn("dir/b.txt", str(cm.exception))

    def test_path_picks_one_file_and_ignores_the_commit_message(self):
        rows = row_texts(diff_html.render(TWO_FILES, path="dir/b.txt"))
        self.assertEqual([(c, o, n, t) for c, o, n, _, t in rows], [
            ("hunk", "", "", "@@ -7 +7 @@"), ("del", "7", "", "b old"), ("add", "", "7", "b new")])

    def test_unknown_path_is_an_error(self):
        with self.assertRaises(diff_html.DiffError):
            diff_html.render(TWO_FILES, path="c.txt")

    def test_a_removed_line_that_looks_like_a_file_header_stays_a_removal(self):
        diff = "--- a/x.sql\n+++ b/x.sql\n@@ -1,2 +1,2 @@\n--- a SQL comment\n+++ counter\n select 1\n"
        rows = row_texts(diff_html.render(diff))
        self.assertEqual([(c, t) for c, _, _, _, t in rows],
                         [("hunk", "@@ -1,2 +1,2 @@"), ("del", "-- a SQL comment"),
                          ("add", "++ counter"), ("ctx", "select 1")])

    def test_text_without_a_hunk_is_an_error(self):
        with self.assertRaises(diff_html.DiffError):
            diff_html.render("just some text\n")


BIG_HUNK = """\
@@ -10,8 +10,9 @@ section
 ten
 eleven
-twelve old
+twelve new
+twelve and a half
 thirteen
 fourteen
-fifteen old
+fifteen new
 sixteen
 seventeen
"""


class TestLineRange(unittest.TestCase):
    def test_range_keeps_new_side_lines_in_range_and_the_removals_between_them(self):
        rows = row_texts(diff_html.render(BIG_HUNK, line_range=(11, 14)))
        self.assertEqual([(c, o, n, t) for c, o, n, _, t in rows], [
            ("hunk", "", "", "@@ -11,3 +11,4 @@ section"),
            ("ctx", "11", "11", "eleven"),
            ("del", "12", "", "twelve old"),
            ("add", "", "12", "twelve new"),
            ("add", "", "13", "twelve and a half"),
            ("ctx", "13", "14", "thirteen"),
        ])

    def test_range_that_misses_every_line_is_an_error(self):
        with self.assertRaises(diff_html.DiffError):
            diff_html.render(BIG_HUNK, line_range=(100, 120))

    def test_range_across_two_hunks_keeps_both_headers(self):
        diff = "@@ -1,2 +1,2 @@\n a\n-b\n+B\n@@ -40,2 +40,2 @@\n x\n-y\n+Y\n"
        rows = row_texts(diff_html.render(diff, line_range=(2, 40)))
        self.assertEqual([(c, t) for c, _, _, _, t in rows], [
            ("hunk", "@@ -2 +2 @@"), ("del", "b"), ("add", "B"),
            ("hunk", "@@ -40 +40 @@"), ("ctx", "x")])


class TestNotes(unittest.TestCase):
    def test_markers_are_numbered_top_to_bottom_and_the_notes_follow_that_order(self):
        out = diff_html.render(BIG_HUNK, notes=[("new", 16, "Moved."), ("old", 12, "Was <old>.")])
        self.assertEqual(re.findall(r'<span class="l ([^"]*)" data-m="(\d)"><span class="o">(\d*)</span>'
                                    r'<span class="n">(\d*)</span>', out),
                         [("del mark", "1", "12", ""), ("add mark", "2", "", "16")])
        notes = out.split("</pre>", 1)[1]
        self.assertEqual(notes, '<ol class="markers">'
                         '<li><span class="k">1</span><span class="ln">-12</span> Was &lt;old&gt;.</li>'
                         '<li><span class="k">2</span><span class="ln">+16</span> Moved.</li></ol>')

    def test_a_context_line_can_be_named_by_either_side(self):
        out = diff_html.render(BIG_HUNK, notes=[("old", 14, "Unchanged.")])
        self.assertIn('<span class="l ctx mark" data-m="1"><span class="o">14</span><span class="n">15</span>', out)
        self.assertIn('<span class="ln">15</span> Unchanged.', out)

    def test_backticks_in_a_note_become_code(self):
        out = diff_html.render(BIG_HUNK, notes=[("new", 12, "Run `check.py <x>` now.")])
        self.assertIn("Run <code>check.py &lt;x&gt;</code> now.", out)

    def test_a_note_on_a_line_outside_the_figure_is_an_error(self):
        with self.assertRaises(diff_html.DiffError):
            diff_html.render(BIG_HUNK, line_range=(11, 14), notes=[("new", 16, "Gone.")])

    def test_two_notes_on_one_line_is_an_error(self):
        with self.assertRaises(diff_html.DiffError):
            diff_html.render(BIG_HUNK, notes=[("new", 12, "a"), ("new", 12, "b")])

    def test_no_notes_means_no_markers_and_no_list(self):
        out = diff_html.render(BIG_HUNK)
        self.assertNotIn("data-m", out)
        self.assertTrue(out.endswith("</pre>"))


def run_cli(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = diff_html.main(argv)
            except SystemExit as e:  # argparse usage errors
                code = e.code
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def test_reads_stdin_and_prints_the_fragment(self):
        code, out, _ = run_cli(["-"], stdin=ONE_HUNK)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), diff_html.render(ONE_HUNK))

    def test_reads_a_file_with_path_lines_and_notes(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
            f.write(TWO_FILES)
        code, out, _ = run_cli([f.name, "--path", "dir/b.txt", "--lines", "7-7",
                                "--note", "old:7=Was b.", "--note", "new:7=Now `b`."])
        Path(f.name).unlink()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), diff_html.render(
            TWO_FILES, path="dir/b.txt", line_range=(7, 7),
            notes=[("old", 7, "Was b."), ("new", 7, "Now `b`.")]))

    def test_bad_diff_exits_1_with_the_reason_on_stderr(self):
        code, out, err = run_cli(["-"], stdin=TWO_FILES)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("several files", err)

    def test_missing_file_exits_1_with_the_reason_on_stderr(self):
        code, out, err = run_cli(["no-such-file.diff"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("diff_html: "), err)
        self.assertNotIn("Traceback", err)

    def test_malformed_note_or_lines_exits_2(self):
        self.assertEqual(run_cli(["-", "--note", "36=no side"], stdin=ONE_HUNK)[0], 2)
        self.assertEqual(run_cli(["-", "--lines", "9"], stdin=ONE_HUNK)[0], 2)


if __name__ == "__main__":
    unittest.main()
