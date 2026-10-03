"""Tests for skills/visual-report/scripts/check_render.py.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

The browser half of the check needs Playwright and Chromium, which CI does not
install, so these tests cover the pure parts: reading the report, locating
Mermaid blocks and their lines, classifying rendered-DOM facts and failed
requests, and turning them into a verdict. The verdict codes are an
interface: SKILL.md tells the agent what PASS, FAIL, and BLOCKED mean.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "visual-report" / "scripts"))

import check_render  # noqa: E402

PASS, FAIL, BLOCKED = check_render.PASS, check_render.FAIL, check_render.BLOCKED


def result(**overrides):
    base = {"diagrams": [], "requests": [], "broken_images": [], "page_errors": [],
            "console_errors": [], "hung": None, "blocked": None, "incomplete": None}
    base.update(overrides)
    return base


def drawn(**overrides):
    """Facts for a healthy, visible, rendered diagram; override to break it."""
    fact = {"processed": True, "holds": "svg", "wrapper": False, "role": "flowchart-v2",
            "error_marks": False, "visible": True, "width": 870, "height": 70,
            "natural_width": 870, "natural_height": 70, "labels": 4, "shown_labels": 4,
            "font_px": 16}
    fact.update(overrides)
    fact.setdefault("visible_width", fact["width"])
    fact.setdefault("visible_height", fact["height"])
    return fact


class TestReadSource(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.html"
            path.write_bytes(data)
            return check_render.read_source(path)

    def test_utf8(self):
        self.assertIn("Café", self.read("<p>Café</p>".encode("utf-8")))

    def test_declared_latin1_does_not_crash(self):
        html = '<meta charset="iso-8859-1"><pre class="mermaid">A["Café"]</pre>'
        self.assertIn("Café", self.read(html.encode("latin-1")))

    def test_undeclared_non_utf8_falls_back(self):
        self.assertIn("Résumé", self.read("<p>Résumé</p>".encode("cp1252")))

    def test_bom(self):
        self.assertEqual(self.read(b"\xef\xbb\xbf<p>x</p>"), "<p>x</p>")


class TestMermaidBlocks(unittest.TestCase):
    def test_finds_blocks_with_lines_and_decoded_source(self):
        html = (
            "<html><body>\n"
            '<pre class="mermaid">flowchart LR\n  A --&gt; B</pre>\n'
            '<div class="card mermaid">sequenceDiagram</div>\n'
            "</body></html>"
        )
        blocks = check_render.mermaid_blocks(html)
        self.assertEqual([b["line"] for b in blocks], [2, 4])
        self.assertEqual(blocks[0]["source"], "flowchart LR\n  A --> B")
        self.assertEqual(blocks[1]["source"], "sequenceDiagram")

    def test_ignores_elements_without_the_mermaid_class(self):
        html = '<pre class="mermaid-ish">x</pre><pre class="code">flowchart</pre>'
        self.assertEqual(check_render.mermaid_blocks(html), [])

    def test_nested_same_tag_does_not_end_the_block_early(self):
        html = '<div class="mermaid">a<div>b</div>c</div><div>outside</div>'
        self.assertEqual(check_render.mermaid_blocks(html)[0]["source"], "abc")

    def test_skips_blocks_the_browser_never_renders(self):
        html = (
            '<template><pre class="mermaid">T</pre></template>\n'
            '<noscript><pre class="mermaid">N</pre></noscript>\n'
            '<textarea><pre class="mermaid">X</pre></textarea>\n'
            "<!-- <pre class=\"mermaid\">C</pre> -->\n"
            '<pre class="mermaid">real</pre>\n'
        )
        blocks = check_render.mermaid_blocks(html)
        self.assertEqual([(b["line"], b["source"]) for b in blocks], [(5, "real")])


class TestAssignLines(unittest.TestCase):
    def test_pairs_by_source_text_not_position(self):
        html = ('<div id="slot"></div>\n'
                '<pre class="mermaid">\nflowchart LR\n  A[Store (cache)]\n</pre>\n')
        # A script injected a diagram ahead of the static one.
        diagrams = [{"text": "flowchart LR\n  X --> Y"},
                    {"text": "\nflowchart LR\n  A[Store (cache)]\n"}]
        check_render.assign_lines(diagrams, html)
        self.assertEqual([d["line"] for d in diagrams], [None, 2])

    def test_template_block_does_not_shift_lines(self):
        html = ('<template><pre class="mermaid">flowchart LR\n T1</pre></template>\n'
                '<pre class="mermaid">flowchart LR\n A</pre>\n'
                '<pre class="mermaid">flowchart LR\n B(</pre>\n')
        diagrams = [{"text": "flowchart LR\n A"}, {"text": "flowchart LR\n B("}]
        check_render.assign_lines(diagrams, html)
        self.assertEqual([d["line"] for d in diagrams], [3, 5])

    def test_identical_sources_pair_in_order(self):
        html = '<pre class="mermaid">pie</pre>\n<pre class="mermaid">pie</pre>\n'
        diagrams = [{"text": "pie"}, {"text": "pie"}]
        check_render.assign_lines(diagrams, html)
        self.assertEqual([d["line"] for d in diagrams], [1, 2])

    def test_block_under_another_selector_is_found_as_text(self):
        html = '<pre class="diagram">\nflowchart LR\n  A[Store (cache)] --&gt; B\n</pre>\n'
        diagrams = [{"text": "\nflowchart LR\n  A[Store (cache)] --> B\n"}]
        check_render.assign_lines(diagrams, html)
        self.assertEqual(diagrams[0]["line"], 2)

    def test_diagram_without_source_text_gets_no_line(self):
        diagrams = [{"text": None}]
        check_render.assign_lines(diagrams, '<pre class="mermaid">pie</pre>')
        self.assertIsNone(diagrams[0]["line"])


class TestMermaidModule(unittest.TestCase):
    M11 = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"

    def test_commented_out_imports_are_ignored(self):
        script = ('// import mermaid from "https://unpkg.com/mermaid@9/dist/mermaid.esm.min.mjs";\n'
                  '/* import mermaid from "https://old.example/m.mjs"; */\n'
                  f'import mermaid from "{self.M11}";')
        self.assertEqual(check_render.import_urls([script]), [self.M11])

    def test_picks_the_import_the_page_actually_loaded(self):
        imports = ["https://dead.example/mermaid.esm.min.mjs", self.M11]
        loaded = ["https://cdn.tailwindcss.com/", self.M11]
        self.assertEqual(check_render.mermaid_module(imports, loaded), self.M11)

    def test_falls_back_to_a_loaded_entry_module_not_a_chunk(self):
        loaded = ["https://cdn.jsdelivr.net/npm/mermaid@11/dist/chunks/mermaid.esm.min/x.mjs",
                  self.M11]
        self.assertEqual(check_render.mermaid_module([], loaded), self.M11)
        self.assertIsNone(check_render.mermaid_module([], ["https://cdn.tailwindcss.com/"]))


class TestDiagramStatus(unittest.TestCase):
    def status(self, **overrides):
        return check_render.diagram_status(drawn(**overrides))[0]

    def test_rendered_diagram_is_ok(self):
        self.assertEqual(self.status(), "ok")

    def test_parse_error_diagram_is_an_error(self):
        self.assertEqual(self.status(role="error", error_marks=True), "error")

    def test_draw_time_error_without_a_role_is_an_error(self):
        # Parse passed, drawing threw: no aria-roledescription, wrapper left behind.
        self.assertEqual(self.status(role=None, wrapper=True, error_marks=True), "error")

    def test_mid_draw_placeholder_is_still_rendering(self):
        self.assertEqual(self.status(role=None, wrapper=True, labels=0, shown_labels=0),
                         "rendering")
        self.assertEqual(self.status(holds="nothing"), "rendering")

    def test_unprocessed_source_is_unrendered_when_visible(self):
        self.assertEqual(self.status(processed=False, holds="text"), "unrendered")

    def test_unprocessed_source_in_a_hidden_container_is_lazy(self):
        self.assertEqual(self.status(processed=False, holds="text", hidden_at_settle=True),
                         "lazy")

    def test_speck_and_labelless_diagrams_are_empty(self):
        speck = dict(width=16, height=16, natural_width=16, natural_height=16)
        self.assertEqual(self.status(**speck), "empty")
        self.assertEqual(self.status(width=0, height=150, natural_width=0), "empty")
        self.assertEqual(self.status(shown_labels=0), "empty")

    def test_shrunk_until_unreadable_is_illegible(self):
        # A 40-node chain at 7% of its natural width: labels about 1px tall.
        self.assertEqual(self.status(width=942, height=5, natural_width=12376), "illegible")

    def test_small_but_readable_is_ok(self):
        # 43% of natural size: labels about 7px tall.
        self.assertEqual(self.status(width=942, height=30, natural_width=2190,
                                     natural_height=70), "ok")

    def test_overflow_hidden_clipping_is_clipped(self):
        self.assertEqual(self.status(width=4758, natural_width=4758, visible_width=958),
                         "clipped")

    def test_still_hidden_after_reveal_is_not_judged(self):
        self.assertEqual(self.status(visible=False), "hidden")


class TestExplain(unittest.TestCase):
    def test_lazy_diagram_with_a_bad_source_fails(self):
        d = {"status": "lazy"}
        check_render.explain(d, {"parse_error": "Parse error on line 2"})
        self.assertEqual(d["status"], "error")
        self.assertEqual(d["error"], "Parse error on line 2")

    def test_lazy_diagram_with_a_good_source_is_unverified(self):
        d = {"status": "lazy"}
        check_render.explain(d, {"width": 800, "height": 70})
        self.assertEqual(d["status"], "lazy")
        self.assertIn("not exercised", d["unverified"])

    def test_draw_error_is_labelled(self):
        d = {"status": "error", "problem": "Mermaid drew its error diagram"}
        check_render.explain(d, {"draw_error": "Setting A as parent of A would create a cycle"})
        self.assertTrue(d["error"].startswith("while drawing: "))

    def test_broken_by_hiding_names_the_cause(self):
        d = {"status": "empty", "problem": "it renders as a 16x16 px speck",
             "hidden_when_drawn": True}
        check_render.explain(d, {"width": 800, "height": 70})
        self.assertIn("hidden", d["problem"])

    def test_chunk_download_failure_is_the_environment(self):
        d = {"status": "error", "problem": "Mermaid drew its error diagram"}
        check_render.explain(d, {"draw_error": "Failed to fetch dynamically imported module: x"})
        self.assertTrue(d["env"])

    def test_hidden_drawn_diagram_that_differs_from_a_visible_render_warns(self):
        probe = {"width": 450, "height": 263, "natural_width": 450, "natural_height": 263}
        d = {"status": "ok", "_natural": (450, 198)}
        check_render.explain(d, probe)
        self.assertIn("450x198", d["warning"])
        same = {"status": "ok", "_natural": (450, 260)}
        check_render.explain(same, probe)
        self.assertNotIn("warning", same)


class TestRequestProblem(unittest.TestCase):
    def kind(self, url, failure=None, status=None, network_ok=True):
        found = check_render.request_problem(url, failure, status, network_ok)
        return found[0] if found else None

    def test_404_and_orb_are_defects(self):
        self.assertEqual(self.kind("https://cdn.jsdelivr.net/npm/x.js", status=404), "defect")
        self.assertEqual(self.kind("https://cdn.jsdelivr.net/npm/x.png",
                                   "net::ERR_BLOCKED_BY_ORB"), "defect")

    def test_missing_local_file_is_a_defect(self):
        self.assertEqual(self.kind("file:///tmp/chart.png", "net::ERR_FILE_NOT_FOUND"), "defect")

    def test_cancelled_and_inline_requests_are_ignored(self):
        self.assertIsNone(self.kind("https://cdn.jsdelivr.net/x.json", "net::ERR_ABORTED"))
        self.assertIsNone(self.kind("data:image/gif;base64,R0lG", "net::ERR_FAILED"))

    def test_unreachable_cdn_is_the_environment(self):
        self.assertEqual(self.kind("https://cdn.jsdelivr.net/npm/mermaid.mjs",
                                   "net::ERR_NAME_NOT_RESOLVED"), "blocked")
        self.assertEqual(self.kind("https://cdn.tailwindcss.com/", status=503), "blocked")

    def test_unknown_host_is_a_typo_only_when_the_network_works(self):
        url = "https://cdn.jsdelivr.nett/npm/mermaid.mjs"
        self.assertEqual(self.kind(url, "net::ERR_NAME_NOT_RESOLVED"), "defect")
        self.assertEqual(self.kind(url, "net::ERR_NAME_NOT_RESOLVED", network_ok=False),
                         "blocked")


class TestVerdict(unittest.TestCase):
    blocked_cdn = {"url": "https://cdn.jsdelivr.net/m.mjs", "kind": "blocked", "why": "x"}
    defect = {"url": "https://cdn.jsdelivr.net/x.png", "kind": "defect", "why": "x"}

    def test_clean_page_passes(self):
        self.assertEqual(check_render.verdict(result(diagrams=[{"status": "ok"}])), PASS)

    def test_page_without_diagrams_passes(self):
        self.assertEqual(check_render.verdict(result()), PASS)

    def test_unverified_diagrams_do_not_fail(self):
        case = result(diagrams=[{"status": "lazy"}, {"status": "hidden"}])
        self.assertEqual(check_render.verdict(case), PASS)

    def test_any_defect_fails(self):
        for case in (
            result(diagrams=[{"status": "ok"}, {"status": "error"}]),
            result(diagrams=[{"status": "empty"}]),
            result(diagrams=[{"status": "illegible"}]),
            result(diagrams=[{"status": "clipped"}]),
            result(diagrams=[{"status": "unrendered"}]),
            result(diagrams=[{"status": "rendering"}]),
            result(requests=[self.defect]),
            result(broken_images=["missing.png"]),
            result(page_errors=["TypeError"]),
            result(console_errors=["boom"]),
            result(hung="frozen"),
        ):
            self.assertEqual(check_render.verdict(case), FAIL, case)

    def test_proven_defect_beats_an_unreachable_cdn(self):
        for case in (
            result(diagrams=[{"status": "error"}], requests=[self.blocked_cdn]),
            result(requests=[self.blocked_cdn, self.defect]),
            result(broken_images=["file:///tmp/missing.png"], requests=[self.blocked_cdn]),
        ):
            self.assertEqual(check_render.verdict(case), FAIL, case)

    def test_unreachable_cdn_explains_unrendered_diagrams(self):
        # Offline, every diagram is unrendered; that is no evidence of a defect.
        case = result(diagrams=[{"status": "unrendered"}], requests=[self.blocked_cdn],
                      page_errors=["mermaid is not defined"])
        self.assertEqual(check_render.verdict(case), BLOCKED)

    def test_error_from_a_failed_chunk_download_blocks(self):
        case = result(diagrams=[{"status": "error", "env": True}])
        self.assertEqual(check_render.verdict(case), BLOCKED)

    def test_setup_problem_or_timeout_blocks(self):
        self.assertEqual(check_render.verdict(result(blocked="no browser")), BLOCKED)
        self.assertEqual(check_render.verdict(result(incomplete="timed out")), BLOCKED)


class TestPageSlices(unittest.TestCase):
    def test_bands_cover_the_page(self):
        self.assertEqual(check_render.page_slices(2000, 900),
                         [(0, 900), (900, 900), (1800, 200)])
        self.assertEqual(check_render.page_slices(900, 900), [(0, 900)])
        self.assertEqual(check_render.page_slices(0, 900), [(0, 1)])

    def test_bands_are_capped(self):
        self.assertEqual(len(check_render.page_slices(10 ** 6, 900, limit=5)), 5)


class TestCounted(unittest.TestCase):
    def test_repeats_collapse(self):
        self.assertEqual(check_render.counted(["a", "b", "a"]), ["a (x2)", "b"])


if __name__ == "__main__":
    unittest.main()
