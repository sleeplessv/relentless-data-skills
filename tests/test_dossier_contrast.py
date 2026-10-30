"""Tests for skills/dossier/scripts/check_contrast.py.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_dossier_contrast -v

The check reads the colour tokens and the declared colour pairs from a
dossier scaffold and fails any pair below WCAG AA. Expected ratios come from
the WCAG 2 formula worked by hand or from published reference values, not
from the code under test.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "dossier" / "scripts"))

import check_contrast  # noqa: E402


class TestRatio(unittest.TestCase):
    def test_black_on_white_is_twenty_one(self):
        self.assertAlmostEqual(check_contrast.ratio("#000000", "#ffffff"), 21.0, places=2)

    def test_order_does_not_matter(self):
        self.assertAlmostEqual(check_contrast.ratio("#ffffff", "#777777"),
                               check_contrast.ratio("#777777", "#ffffff"))

    def test_grey_777_on_white_just_misses_aa(self):
        self.assertAlmostEqual(check_contrast.ratio("#777777", "#ffffff"), 4.48, places=2)

    def test_house_pairs(self):
        self.assertAlmostEqual(check_contrast.ratio("#102542", "#f87060"), 5.48, places=2)
        self.assertAlmostEqual(check_contrast.ratio("#5f5348", "#ffffff"), 7.45, places=2)


class TestComposite(unittest.TestCase):
    def test_github_deleted_word_tint_over_deleted_line(self):
        # #ff8182 at alpha 0x66 (0.4) over #ffebe9: 129*.4+235*.6 = 192.6, 130*.4+233*.6 = 191.8
        self.assertEqual(check_contrast.composite("#ff818266", "#ffebe9"), "#ffc1c0")

    def test_opaque_colour_is_returned_unchanged(self):
        self.assertEqual(check_contrast.composite("#102542", "#ffffff"), "#102542")

    def test_zero_alpha_shows_the_background(self):
        self.assertEqual(check_contrast.composite("#00000000", "#abcdef"), "#abcdef")

    def test_uppercase_and_short_hex_are_normalised(self):
        self.assertEqual(check_contrast.composite("#FFF", "#000000"), "#ffffff")


ROOT_CSS = """<style>
/* dossier:locked:begin v1 */
:root {
  --paper: #ffffff;
  --ink: #102542;            /* text and structure */
  --muted: #5F5348;
  --gh-del-word: #ff818266;
  --tag-skl: var(--ink);
  --display: "Helvetica Neue", Arial, sans-serif;
  --shadow: 0 1px 2px rgba(16, 37, 66, 0.05);
}
/* dossier:locked:end */
:root { --paper: #000000; }
</style>"""


class TestParseTokens(unittest.TestCase):
    def setUp(self):
        self.tokens = check_contrast.parse_tokens(ROOT_CSS)

    def test_hex_tokens_are_read_lowercased(self):
        self.assertEqual(self.tokens["ink"], "#102542")
        self.assertEqual(self.tokens["muted"], "#5f5348")
        self.assertEqual(self.tokens["gh-del-word"], "#ff818266")

    def test_var_reference_resolves_to_its_target(self):
        self.assertEqual(self.tokens["tag-skl"], "#102542")

    def test_non_colour_tokens_are_skipped(self):
        self.assertNotIn("display", self.tokens)
        self.assertNotIn("shadow", self.tokens)

    def test_root_inside_the_locked_block_wins(self):
        self.assertEqual(self.tokens["paper"], "#ffffff")

    def test_no_root_block_is_an_error(self):
        with self.assertRaises(ValueError):
            check_contrast.parse_tokens("<style>body { color: red; }</style>")

    def test_rgb_tokens_are_read_as_hex(self):
        tokens = check_contrast.parse_tokens(
            "<style>:root { --a: rgb(16, 37, 66); --b: rgba(255 129 130 / 0.4); "
            "--c: rgb(0,0,0,40%); }</style>")
        self.assertEqual(tokens, {"a": "#102542", "b": "#ff818266", "c": "#00000066"})

    def test_an_unsupported_colour_function_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "--a"):
            check_contrast.parse_tokens("<style>:root { --a: oklch(0.5 0.1 200); }</style>")


PAIRS_CSS = """<style>
/* dossier:pairs
   text     ink      paper               body text
   graphic  rule     surface             DAG edge on canvas
   text     gh-fg    gh-del-word/gh-del  diff removed word
*/
</style>"""


class TestParsePairs(unittest.TestCase):
    def test_each_line_is_kind_fg_bg_label(self):
        pairs = check_contrast.parse_pairs(PAIRS_CSS)
        self.assertEqual(pairs[0], ("text", "ink", "paper", "body text"))
        self.assertEqual(pairs[1], ("graphic", "rule", "surface", "DAG edge on canvas"))
        self.assertEqual(len(pairs), 3)

    def test_layered_background_is_kept_as_written(self):
        self.assertEqual(check_contrast.parse_pairs(PAIRS_CSS)[2][2], "gh-del-word/gh-del")

    def test_unknown_kind_is_an_error(self):
        with self.assertRaises(ValueError):
            check_contrast.parse_pairs("/* dossier:pairs\n  bold ink paper x\n*/")

    def test_missing_block_is_an_error(self):
        with self.assertRaises(ValueError):
            check_contrast.parse_pairs("<style>:root { --ink: #000; }</style>")


TOKENS = {"black": "#000000", "white": "#ffffff", "grey": "#777777",
          "gh-fg": "#1f2328", "gh-del": "#ffebe9", "gh-del-word": "#ff818266",
          "veil": "#00000000", "spare": "#123456"}


def one(kind, fg, bg):
    [row] = check_contrast.check(TOKENS, [(kind, fg, bg, "label")])
    return row


class TestCheck(unittest.TestCase):
    def test_passing_pair_reports_its_ratio(self):
        row = one("text", "black", "white")
        self.assertTrue(row["ok"])
        self.assertAlmostEqual(row["ratio"], 21.0, places=2)
        self.assertEqual((row["fg"], row["bg"]), ("#000000", "#ffffff"))

    def test_text_needs_four_and_a_half(self):
        self.assertFalse(one("text", "grey", "white")["ok"])

    def test_graphics_and_large_text_need_three(self):
        self.assertTrue(one("graphic", "grey", "white")["ok"])
        self.assertTrue(one("large", "grey", "white")["ok"])

    def test_decor_never_fails(self):
        self.assertTrue(one("decor", "white", "white")["ok"])

    def test_missing_token_fails_rather_than_passes(self):
        row = one("text", "black", "nope")
        self.assertFalse(row["ok"])
        self.assertIn("nope", row["error"])

    def test_layered_background_is_composited_first(self):
        self.assertEqual(one("text", "gh-fg", "gh-del-word/gh-del")["bg"], "#ffc1c0")

    def test_translucent_foreground_is_composited_over_background(self):
        row = one("decor", "veil", "white")
        self.assertEqual(row["fg"], "#ffffff")

    def test_translucent_background_without_a_base_is_an_error(self):
        self.assertFalse(one("text", "black", "gh-del-word")["ok"])


class TestUnpaired(unittest.TestCase):
    def test_lists_colour_tokens_no_pair_mentions(self):
        pairs = [("text", "black", "white", "a"), ("text", "gh-fg", "gh-del-word/gh-del", "b"),
                 ("text", "grey", "white", "c"), ("decor", "veil", "white", "d")]
        self.assertEqual(check_contrast.unpaired(TOKENS, pairs), ["spare"])


def page(root, pairs):
    return f"<style>:root {{ {root} }}\n/* dossier:pairs\n{pairs}\n*/</style>"


class TestMain(unittest.TestCase):
    def run_on(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.html"
            path.write_text(text, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = check_contrast.main([str(path)])
        return code, out.getvalue()

    def test_all_pairs_pass_exits_zero(self):
        code, out = self.run_on(page("--ink: #000; --paper: #fff;", "text ink paper body"))
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_a_failing_pair_exits_one_and_names_it(self):
        code, out = self.run_on(page("--ink: #777; --paper: #fff;", "text ink paper body text"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("body text", out)

    def test_an_unpaired_colour_token_exits_one(self):
        code, out = self.run_on(page("--ink: #000; --paper: #fff; --spare: #f00;", "text ink paper body"))
        self.assertEqual(code, 1)
        self.assertIn("--spare", out)

    def test_unreadable_file_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check_contrast.main(["/no/such/file.html"]), 2)

    def test_page_without_pairs_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_on("<style>:root { --ink: #000; }</style>")[0], 2)


class TestShippedScaffold(unittest.TestCase):
    """Guard: a palette change that breaks AA fails here, in CI."""

    def test_scaffold_passes_every_declared_pair(self):
        html = (REPO_ROOT / "skills" / "dossier" / "assets" / "scaffold.html").read_text(encoding="utf-8")
        tokens = check_contrast.parse_tokens(html)
        pairs = check_contrast.parse_pairs(html)
        failed = [r["label"] for r in check_contrast.check(tokens, pairs) if not r["ok"]]
        self.assertEqual(failed, [])
        self.assertEqual(check_contrast.unpaired(tokens, pairs), [])
        self.assertGreater(len(pairs), 40)


if __name__ == "__main__":
    unittest.main()
