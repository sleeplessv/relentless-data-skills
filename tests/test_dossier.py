"""Tests for skills/dossier/scripts/check_render.py.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

The browser half of the check needs Playwright and Chromium, which CI does not
install, so these tests cover the pure parts: reading the report, locating
Mermaid blocks and their lines, classifying rendered-DOM facts and failed
requests, and turning them into a verdict. The verdict codes are an
interface: SKILL.md tells the agent what PASS, FAIL, and BLOCKED mean.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "dossier" / "scripts"))

import check_render  # noqa: E402
import dag_svg  # noqa: E402

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
        self.assertEqual(self.kind("https://fastly.jsdelivr.net/npm/x.js", status=503), "blocked")

    def test_server_error_off_the_house_cdn_is_a_defect(self):
        # The house library block loads only from jsdelivr; any other host is
        # the page's own choice, so its outage is the page's problem.
        self.assertEqual(self.kind("https://cdn.tailwindcss.com/", status=503), "defect")

    def test_unknown_host_is_a_typo_only_when_the_network_works(self):
        url = "https://cdn.jsdelivr.nett/npm/mermaid.mjs"
        self.assertEqual(self.kind(url, "net::ERR_NAME_NOT_RESOLVED"), "defect")
        self.assertEqual(self.kind(url, "net::ERR_NAME_NOT_RESOLVED", network_ok=False),
                         "blocked")


class FakeResponse:
    """The parts of a Playwright response that Net reads."""

    def __init__(self, url, status=200, resource_type="fetch"):
        self.url, self.status = url, status
        self.request = types.SimpleNamespace(url=url, resource_type=resource_type)


class TestNet(unittest.TestCase):
    def test_a_response_from_another_host_is_a_defect(self):
        net = check_render.Net()
        for url in ("https://cdn.jsdelivr.net/npm/vega@6.4.0/build/vega.min.js",
                    "https://fastly.jsdelivr.net/npm/x@1.0.0/x.js",
                    "https://data.example.com/rows.json", "http://api.example.org/x?y=1",
                    "file:///tmp/report.html", "data:text/plain,hi"):
            net._response(FakeResponse(url))
        self.assertEqual([r["url"] for r in net.offhost],
                         ["https://data.example.com/rows.json", "http://api.example.org/x?y=1"])
        self.assertEqual(check_render.verdict(result(requests=net.offhost)), FAIL)

    def test_a_url_fetched_twice_is_one_defect(self):
        net = check_render.Net()
        for _ in range(3):
            net._response(FakeResponse("https://data.example.com/rows.json"))
        self.assertEqual(len(net.offhost), 1)

    def test_the_checkers_own_requests_do_not_count(self):
        net = check_render.Net()
        net.frozen = True
        net._response(FakeResponse("https://data.example.com/rows.json"))
        self.assertEqual(net.offhost, [])


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


class TestStaleShots(unittest.TestCase):
    def test_only_the_scripts_own_shot_names_are_removed(self):
        mine = ["page-1.png", "page-12.png", "diagram-3.png", "chart-1.png", "dag-2.png"]
        theirs = ["page-header.png", "diagram-foo.png", "chart-1.jpg", "pages.png", "dag-.png"]
        with tempfile.TemporaryDirectory() as d:
            for name in mine + theirs:
                (Path(d) / name).write_bytes(b"")
            stale = sorted(p.name for p in check_render.stale_shots(Path(d)))
        self.assertEqual(stale, sorted(mine))


class TestCounted(unittest.TestCase):
    def test_repeats_collapse(self):
        self.assertEqual(check_render.counted(["a", "b", "a"]), ["a (x2)", "b"])


LOCKED = ("<style>\n/* dossier:locked:begin v1 */\n:root { --ink: #102542; }\n"
          ".fig { display: grid; }\n/* dossier:locked:end */\n"
          "/* dossier:report:begin */\n#table-1 td { width: 4rem; }\n/* dossier:report:end */\n"
          "</style>")


class TestLockedBlock(unittest.TestCase):
    def test_extracts_the_text_between_the_markers(self):
        self.assertEqual(check_render.locked_version_and_text(LOCKED)[1],
                         ":root { --ink: #102542; }\n.fig { display: grid; }")

    def test_identical_block_passes(self):
        report = LOCKED.replace("width: 4rem", "width: 9rem")   # report geometry may change
        self.assertIsNone(check_render.locked_problem(report, LOCKED))

    def test_line_endings_and_trailing_spaces_do_not_count(self):
        report = LOCKED.replace("\n", "  \r\n")
        self.assertIsNone(check_render.locked_problem(report, LOCKED))

    def test_one_changed_byte_fails(self):
        report = LOCKED.replace("#102542", "#102543")
        self.assertIn("differs from the scaffold", check_render.locked_problem(report, LOCKED))

    def test_missing_markers_fail(self):
        problem = check_render.locked_problem("<style>:root{}</style>", LOCKED)
        self.assertIn("no locked block", problem)

    def test_marker_version_must_match_the_scaffold(self):
        report = LOCKED.replace("begin v1", "begin v0")
        self.assertIn("v0", check_render.locked_problem(report, LOCKED))


MERMAID_PIN = "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs"


class TestResourceUrls(unittest.TestCase):
    def test_collects_every_resource_the_page_loads(self):
        html = (
            '<link rel="stylesheet" href="https://fonts.example/a.css">\n'
            '<script src="https://cdn.jsdelivr.net/npm/vega@6.4.0/build/vega.min.js"></script>\n'
            '<img src="https://img.example/x.png">\n'
            '<a href="https://elsewhere.example/">a link is not a resource</a>\n'
            '<script type="module">\n'
            '  // import x from "https://old.example/x.mjs";\n'
            f'  import mermaid from "{MERMAID_PIN}";\n'
            '  const m = await import("https://esm.sh/thing@1");\n'
            '</script>\n'
            '<img src="local.png"><img src="data:image/gif;base64,R0lG">\n'
        )
        self.assertEqual(check_render.resource_urls(html), [
            "https://fonts.example/a.css",
            "https://cdn.jsdelivr.net/npm/vega@6.4.0/build/vega.min.js",
            "https://img.example/x.png",
            MERMAID_PIN,
            "https://esm.sh/thing@1",
        ])

    def test_hints_that_load_nothing_are_not_resources(self):
        html = ('<link rel="preconnect" href="https://cdn.jsdelivr.net">'
                '<link rel="dns-prefetch" href="https://cdn.jsdelivr.net">'
                '<link rel="Preconnect stylesheet" href="https://fonts.example/a.css">'
                '<link href="https://fonts.example/b.css">')
        self.assertEqual(check_render.resource_urls(html),
                         ["https://fonts.example/a.css", "https://fonts.example/b.css"])


class TestUrlProblem(unittest.TestCase):
    def test_pinned_jsdelivr_package_passes(self):
        self.assertIsNone(check_render.url_problem(MERMAID_PIN))
        self.assertIsNone(check_render.url_problem(
            "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/x.mjs"))

    def test_unpinned_versions_fail(self):
        for url in ("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs",
                    "https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.esm.min.mjs",
                    "https://cdn.jsdelivr.net/npm/vega@latest",
                    "https://cdn.jsdelivr.net/npm/@scope/pkg/x.js"):
            self.assertIn("not pinned", check_render.url_problem(url), url)

    def test_other_hosts_fail(self):
        for url in ("https://cdn.tailwindcss.com/", "https://unpkg.com/vega@6.4.0",
                    "http://cdn.jsdelivr.net.evil.example/npm/x@1.0.0/x.js"):
            self.assertIn("not an allowed host", check_render.url_problem(url), url)

    def test_local_and_inline_urls_are_ignored(self):
        for url in ("chart.png", "./x.js", "data:image/gif;base64,R0lG", "#top"):
            self.assertIsNone(check_render.url_problem(url), url)


class TestLibraryWarnings(unittest.TestCase):
    def test_house_libraries_at_their_pins_are_quiet(self):
        self.assertEqual(check_render.library_warnings([
            MERMAID_PIN, "https://cdn.jsdelivr.net/npm/vega-lite@6.5.0/build/vega-lite.min.js"]), [])

    def test_a_package_outside_the_library_block_warns(self):
        found = check_render.library_warnings([
            "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/x.mjs"])
        self.assertEqual(len(found), 1)
        self.assertIn("@mermaid-js/layout-elk", found[0])

    def test_a_house_library_at_another_version_warns(self):
        found = check_render.library_warnings([
            "https://cdn.jsdelivr.net/npm/mermaid@11.16.0/dist/mermaid.esm.min.mjs"])
        self.assertIn("11.17.2", found[0])


SOWHAT = ('<div class="sowhat"><p class="lbl">So what</p><p class="claim">It costs '
          '<em>4 times</em> more.</p><p class="rest">Detail.</p></div>')


def figure(n, kind="fig", body='<div class="figframe">x</div>', caption=None, sowhat=SOWHAT,
           after=False):
    fid = f"fig-{n}" if kind == "fig" else f"table-{n}-fig"
    label = caption if caption is not None else (
        f"Figure {n}." if kind == "fig" else f"Table {n}.")
    so = sowhat or ""
    cap = (f'<p class="caption"><span class="figno">{label}</span> What it shows. '
           f'<span class="how">How to read it.</span></p>')
    margin = cap + so if after else so + cap
    return (f'<div class="fig" id="{fid}"><div class="visual">{body}</div>'
            f'<div class="margin">{margin}</div></div>')


def section(n, title, body):
    return (f'<section class="sec" id="s{n}"><h2 class="sec-head"><span class="n">0{n}</span>'
            f'<span>{title}</span><span class="count">Figure {n}</span></h2>{body}</section>\n')


LIMITS = section(9, "Limits", '<ol class="limits"><li>None.</li></ol>')


def findings(*targets):
    items = "".join(f'<li><a href="#{t}">Finding {t} costs 3 hours.</a></li>'
                    for t in targets)
    return (f'<section class="findings" aria-label="Key findings"><p class="label eyebrow">'
            f'Key findings</p><ol>{items}</ol></section>')


FINDINGS = findings("s1", "s1", "s9")   # s1 and Limits are in every test dossier


def dossier(*sections, toc=True, answer='<section class="answer"><p class="claim">The check '
            'fails bad pages.</p></section>', findings=FINDINGS, limits=LIMITS):
    side = ('<aside class="side"><ol class="toc" id="toc"></ol></aside>'
            '<nav class="toc-inline"></nav>') if toc else ""
    if not sections:
        sections = (section(1, "How the check runs", "<p>Short prose.</p>" + figure(1)),
                    section(2, "What the table holds", figure(1, "table")))
    return (f"<html><body>{side}<main>{answer}{findings}\n{''.join(sections)}{limits}"
            "</main></body></html>")


def dag(nodes):
    gs = "".join(f'<g class="dn" transform="translate({i},0)"><rect class="box"/></g>'
                 for i in range(nodes))
    return (f'<div class="dag-frame"><svg class="dag dag-lr">{gs}</svg>'
            f'<svg class="dag dag-tb">{gs}</svg></div>')


class TestStructure(unittest.TestCase):
    def check(self, html):
        return check_render.structure(html)

    def problems(self, html):
        return " | ".join(self.check(html)[0])

    def warnings(self, html):
        return " | ".join(self.check(html)[1])

    def test_a_complete_dossier_is_clean(self):
        self.assertEqual(self.check(dossier()), ([], []))

    def test_no_answer_box_fails(self):
        self.assertIn("answer box", self.problems(dossier(answer="")))
        no_claim = '<section class="answer"><p>Hello.</p></section>'
        self.assertIn("claim", self.problems(dossier(answer=no_claim)))

    def test_an_empty_answer_claim_fails(self):
        empty = '<section class="answer"><p class="claim">  </p></section>'
        self.assertIn("no .claim", self.problems(dossier(answer=empty)))

    def test_an_unfilled_scaffold_fails(self):
        found = self.problems(check_render.read_source(check_render.SCAFFOLD))
        self.assertIn('"[Report title]"', found)

    def test_a_placeholder_left_in_the_text_fails(self):
        html = dossier(section(1, "How the check runs", "<p>[Two to four short sentences.]</p>"
                               + figure(1)))
        self.assertIn("placeholder", self.problems(html))
        short = dossier(section(1, "How the check runs", "<p>See [1] and [Note].</p>" + figure(1)))
        self.assertEqual(self.problems(short), "")

    def test_the_gallery_has_no_structure_problems(self):
        gallery = REPO_ROOT / "skills" / "dossier" / "assets" / "gallery.html"
        self.assertEqual(self.check(check_render.read_source(gallery))[0], [])

    def test_a_placeholder_left_in_the_title_fails(self):
        gallery = REPO_ROOT / "skills" / "dossier" / "assets" / "gallery.html"
        html = re.sub(r"<title>[^<]*</title>", "<title>[Report title]</title>",
                      check_render.read_source(gallery), count=1)
        self.assertIn('"[Report title]"', self.problems(html))

    def test_no_key_findings_fails(self):
        self.assertIn("key findings", self.problems(dossier(findings="")))

    def test_key_findings_need_three_to_five_items(self):
        for n in (3, 5):
            self.assertEqual(self.problems(dossier(findings=findings(*["s1"] * n))), "", n)
        for n in (2, 6):
            self.assertIn(f"{n} findings", self.problems(dossier(findings=findings(*["s1"] * n))), n)

    def test_a_finding_must_link_to_a_section(self):
        found = self.problems(dossier(findings=findings("s1", "s2", "s7")))
        self.assertIn('"#s7"', found)
        found = self.problems(dossier(findings=findings("s1", "s2", "fig-1")))
        self.assertIn('"#fig-1"', found)
        unlinked = FINDINGS.replace('<a href="#s9">', "").replace("</a></li></ol>", "</li></ol>")
        self.assertIn("link", self.problems(dossier(findings=unlinked)))

    def test_key_findings_must_follow_the_answer_box(self):
        stats = '<div class="stats"><div class="stat">1</div></div>'
        ok = dossier(findings=FINDINGS + stats)
        self.assertEqual(self.problems(ok), "")
        late = dossier(findings=stats + FINDINGS)
        self.assertIn("right after the answer box", self.problems(late))

    def test_a_nested_list_in_a_finding_is_not_another_finding(self):
        nested = FINDINGS.replace("</a></li></ol>",
                                  "</a><ul><li>a</li><li>b</li><li>c</li></ul></li></ol>")
        self.assertEqual(self.problems(dossier(findings=nested)), "")

    def test_no_limits_section_fails(self):
        self.assertIn("Limits", self.problems(dossier(limits="")))

    def test_limits_must_be_the_last_section(self):
        html = dossier(LIMITS, section(1, "How the check runs", figure(1)), limits="")
        self.assertIn("last section", self.problems(html))

    def test_figure_without_a_numbered_caption_fails(self):
        html = dossier(section(1, "How the check runs", figure(1, caption="")))
        self.assertIn("Figure 1", self.problems(html))
        html = dossier(section(1, "How the check runs", figure(1, caption="Figure 2.")))
        self.assertIn('"Figure 1."', self.problems(html))

    def test_visual_outside_a_figure_fails(self):
        for body in ('<table><tr><td>1</td></tr></table>', '<div class="chart"></div>',
                     '<pre class="mermaid">sequenceDiagram</pre>', dag(3)):
            html = dossier(section(1, "How the check runs", body + figure(1)))
            self.assertIn("no numbered caption", self.problems(html), body)

    def test_template_and_noscript_content_is_ignored_like_mermaid_blocks(self):
        for tag in ("template", "noscript"):
            loose = f'<{tag}><table><tr><td>1</td></tr></table><div class="chart"></div></{tag}>'
            html = dossier(section(1, "How the check runs", loose + figure(1)))
            self.assertEqual(self.problems(html), "", tag)
            boxed = dossier(answer=f'<{tag}><section class="answer"><p class="claim">x</p>'
                            f"</section></{tag}>")
            self.assertIn("no answer box", self.problems(boxed), tag)

    def test_figures_out_of_numeric_order_fail(self):
        html = dossier(section(1, "How the check runs", figure(2) + figure(1)))
        self.assertIn("Figure 2 comes where Figure 1 should", self.problems(html))

    def test_tables_count_on_their_own_counter(self):
        html = dossier(section(1, "How the check runs", figure(1) + figure(1, "table") + figure(2)))
        self.assertEqual(self.problems(html), "")

    def test_four_sections_without_a_toc_warn(self):
        secs = [section(i, f"Part {i} of it", figure(i)) for i in range(1, 3)]   # + Limits = 3
        self.assertNotIn("table of contents", self.warnings(dossier(*secs, toc=False)))
        secs.append(section(3, "Part three", figure(3)))
        self.assertIn("table of contents", self.warnings(dossier(*secs, toc=False)))

    def test_long_paragraph_warns(self):
        words = lambda n: " ".join(["word"] * n)  # noqa: E731
        ok = dossier(section(1, "How the check runs", f"<p>{words(60)}</p>" + figure(1)))
        self.assertEqual(self.warnings(ok), "")
        long = dossier(section(1, "How the check runs", f"<p>{words(61)}</p>" + figure(1)))
        self.assertIn("61 words", self.warnings(long))

    def test_a_list_after_an_unclosed_paragraph_is_not_part_of_it(self):
        items = "".join(f"<li>{' '.join(['word'] * 10)}</li>" for _ in range(7))
        html = dossier(section(1, "How the check runs", f"<p>Intro<ul>{items}</ul>" + figure(1)))
        self.assertEqual(self.warnings(html), "")

    def test_any_block_start_closes_an_unclosed_paragraph(self):
        words = " ".join(["word"] * 40)
        for tag in ("aside", "h4", "blockquote", "header"):
            html = dossier(section(1, "How the check runs",
                                   f"<p>{words}<{tag}>{words}</{tag}>" + figure(1)))
            self.assertEqual(self.warnings(html), "", tag)

    def test_section_without_a_figure_warns(self):
        html = dossier(section(1, "How the check runs", "<p>Prose only.</p>"))
        self.assertIn("How the check runs", self.warnings(html))

    def test_figure_without_a_so_what_warns(self):
        html = dossier(section(1, "How the check runs", figure(1, sowhat=False)))
        self.assertIn("So what", self.warnings(html))

    def test_a_so_what_without_a_claim_fails(self):
        old = '<p class="sowhat"><span class="lbl">So what</span>It matters.</p>'
        html = dossier(section(1, "How the check runs", figure(1, sowhat=old)))
        self.assertIn("no .claim", self.problems(html))

    def test_an_empty_so_what_claim_fails(self):
        empty = SOWHAT.replace("It costs <em>4 times</em> more.", "  ")
        html = dossier(section(1, "How the check runs", figure(1, sowhat=empty)))
        self.assertIn("no .claim", self.problems(html))

    def test_a_so_what_with_two_claims_fails(self):
        two = SOWHAT.replace('<p class="rest">', '<p class="claim">Again.</p><p class="rest">')
        html = dossier(section(1, "How the check runs", figure(1, sowhat=two)))
        self.assertIn("2 .claim", self.problems(html))

    def test_a_so_what_without_its_label_warns(self):
        bare = SOWHAT.replace('<p class="lbl">So what</p>', "")
        html = dossier(section(1, "How the check runs", figure(1, sowhat=bare)))
        self.assertEqual(self.problems(html), "")
        self.assertIn("no .lbl", self.warnings(html))

    def test_a_wrapped_so_what_after_its_caption_fails(self):
        html = dossier(section(1, "How the check runs",
                               figure(1, sowhat=f"<div>{SOWHAT}</div>", after=True)))
        self.assertIn("after its caption", self.problems(html))

    def test_a_so_what_after_its_caption_fails(self):
        html = dossier(section(1, "How the check runs", figure(1, after=True)))
        self.assertIn("after its caption", self.problems(html))

    def test_a_so_what_claim_with_two_key_figures_fails(self):
        two = SOWHAT.replace("more.", "more, <em>2</em> times.")
        html = dossier(section(1, "How the check runs", figure(1, sowhat=two)))
        self.assertIn("2 <em>", self.problems(html))

    def test_a_long_so_what_claim_warns(self):
        claim = lambda n: SOWHAT.replace("It costs <em>4 times</em> more.", " ".join(["w"] * n))  # noqa: E731
        ok = dossier(section(1, "How the check runs", figure(1, sowhat=claim(20))))
        self.assertEqual(self.check(ok), ([], []))
        long = dossier(section(1, "How the check runs", figure(1, sowhat=claim(21))))
        self.assertIn("21 words", self.warnings(long))

    def test_dag_notes_with_a_so_what_heading_count_as_the_so_what(self):
        notes = ('<div class="dag-notes"><div><h3>So what</h3><ul><li>It matters.</li></ul>'
                 '</div></div>')
        html = dossier(section(1, "Graph", figure(1, body=dag(3) + notes, sowhat=False)))
        self.assertEqual(self.warnings(html), "")
        other = notes.replace("So what", "How to read")
        html = dossier(section(1, "Graph", figure(1, body=dag(3) + other, sowhat=False)))
        self.assertIn("So what", self.warnings(html))

    def test_table_over_twenty_visible_rows_warns(self):
        rows = lambda n: "<tr><td>1</td></tr>" * n  # noqa: E731
        ok = f"<table><tbody>{rows(20)}</tbody><tbody hidden>{rows(30)}</tbody></table>"
        self.assertEqual(self.warnings(dossier(section(1, "Rows", figure(1, "table", ok)))), "")
        big = f"<table><thead><tr><th>h</th></tr></thead><tbody>{rows(21)}</tbody></table>"
        self.assertIn("21 visible rows", self.warnings(dossier(section(1, "Rows", figure(1, "table", big)))))

    def test_heading_not_in_sentence_case_warns(self):
        for title in ("HOW THE CHECK RUNS", "How The Render Check Runs"):
            self.assertIn("sentence case", self.warnings(dossier(section(1, title, figure(1)))), title)
        for title in ("How CI runs the DAG check", "How Mermaid draws the Snowflake graph",
                      "Limits of dbt-runner"):
            self.assertEqual(self.warnings(dossier(section(1, title, figure(1)))), "", title)

    def test_slop_words_in_prose_warn_but_not_in_code(self):
        prose = dossier(section(1, "How the check runs", "<p>A pivotal step.</p>" + figure(1)))
        self.assertIn('"pivotal"', self.warnings(prose))
        # SLOP covers more than the common AI-vocabulary words.
        for word in ("leverages", "robust", "seamlessly", "utilize"):
            html = dossier(section(1, "How the check runs", f"<p>It {word} it.</p>" + figure(1)))
            self.assertIn(word, self.warnings(html), word)
        code = dossier(section(1, "How the check runs", "<p><code>pivotal</code></p>" + figure(1)))
        self.assertEqual(self.warnings(code), "")

    def test_mermaid_is_for_sequence_diagrams_only(self):
        seq = '<pre class="mermaid">---\ntitle: x\n---\n%% note\nsequenceDiagram\n  A->>B: hi</pre>'
        self.assertEqual(self.problems(dossier(section(1, "Calls", figure(1, body=seq)))), "")
        flow = '<pre class="mermaid">\nflowchart LR\n  A --&gt; B</pre>'
        found = self.problems(dossier(section(1, "Calls", figure(1, body=flow))))
        self.assertIn("flowchart", found)
        self.assertIn("dag_svg.py", found)

    def test_dag_node_count(self):
        def run(n):
            return self.check(dossier(section(1, "Graph", figure(1, body=dag(n)))))
        self.assertEqual(run(11), ([], []))
        self.assertIn("12 nodes", " ".join(run(12)[1]))
        self.assertEqual(run(12)[0], [])
        self.assertIn("16 nodes", " ".join(run(16)[0]))


def chart(**overrides):
    """Facts for a drawn, visible Vega chart; override to break it."""
    fact = {"label": "Figure 1", "visible": True, "svg": True, "marks": 12,
            "width": 640, "height": 280, "error": None}
    fact.update(overrides)
    return fact


class TestChartStatus(unittest.TestCase):
    def status(self, **overrides):
        return check_render.chart_status(chart(**overrides))

    def test_drawn_chart_is_ok(self):
        self.assertEqual(self.status(), ("ok", None))

    def test_no_svg_is_unrendered(self):
        status, problem = self.status(svg=False, marks=0)
        self.assertEqual(status, "unrendered")
        self.assertIn("Vega", problem)

    def test_embed_error_is_reported(self):
        status, problem = self.status(svg=False, marks=0, error="Invalid specification")
        self.assertEqual(status, "error")
        self.assertIn("Invalid specification", problem)

    def test_axes_without_marks_or_a_speck_is_empty(self):
        self.assertEqual(self.status(marks=0)[0], "empty")
        self.assertEqual(self.status(width=10)[0], "empty")

    def test_hidden_chart_is_not_judged(self):
        self.assertEqual(self.status(visible=False, svg=False)[0], "hidden")


def dag_fact(**overrides):
    fact = {"label": "Figure 3", "visible": True, "width": 900, "height": 220,
            "natural_width": 1120, "font_px": 13, "spills": [],
            "visible_width": 900, "visible_height": 220}
    fact.update(overrides)
    return fact


class TestDagStatus(unittest.TestCase):
    def test_legible_dag_is_ok(self):
        self.assertEqual(check_render.dag_status(dag_fact()), ("ok", None, None))

    def test_the_hidden_orientation_is_skipped(self):
        self.assertEqual(check_render.dag_status(dag_fact(visible=False))[0], "hidden")

    def test_label_spilling_its_box_fails(self):
        status, problem, _ = check_render.dag_status(dag_fact(spills=["lint_skill.py"]))
        self.assertEqual(status, "spill")
        self.assertIn("lint_skill.py", problem)

    def test_clipped_dag_fails(self):
        self.assertEqual(check_render.dag_status(dag_fact(visible_width=400))[0], "clipped")

    def test_scaled_text_below_nine_px_warns(self):
        # 13px names at 600/1120 scale: about 7px.
        status, problem, warning = check_render.dag_status(dag_fact(width=600))
        self.assertEqual((status, problem), ("ok", None))
        self.assertIn("7px", warning)


class TestViewportFindings(unittest.TestCase):
    def test_sideways_scroll_and_wide_frames_fail(self):
        problems, warnings = check_render.viewport_findings([
            {"viewport": 1200, "kind": "frame", "label": "Table 1", "excess": 16},
            {"viewport": 768, "kind": "page", "label": "the page", "excess": 40},
        ])
        self.assertEqual(len(problems), 2)
        self.assertIn("Table 1 is 16px wider than its frame at 1200px", problems[0])
        self.assertEqual(warnings, [])

    def test_scrolling_code_and_small_text_warn(self):
        problems, warnings = check_render.viewport_findings([
            {"viewport": 768, "kind": "code", "label": "Figure 5", "excess": 120},
            {"viewport": 768, "kind": "text", "label": "diagram 1", "px": 9.3},
            {"viewport": 1440, "kind": "text", "label": "diagram 1", "px": 11},
        ])
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 2)
        # The prototype's sequence diagram at 768: 16px labels scaled to 58%.
        self.assertIn("about 9.3px at 768px", warnings[1])

    def test_slack_of_two_px_is_allowed(self):
        self.assertEqual(check_render.viewport_findings(
            [{"viewport": 1200, "kind": "frame", "label": "Table 1", "excess": 2}]), ([], []))


class TestColourWarnings(unittest.TestCase):
    ALARMS = {"--red": "#a3123a", "--amber": "#b7791f"}

    def test_red_or_amber_category_fill_warns(self):
        found = check_render.colour_warnings(
            [{"label": "Figure 3 node", "colour": "rgb(163, 18, 58)"},
             {"label": "Figure 9 bar", "colour": "rgb(183, 121, 31)"}], self.ALARMS)
        self.assertEqual(len(found), 2)
        self.assertIn("--red", found[0])

    def test_coral_and_navy_fills_are_fine(self):
        self.assertEqual(check_render.colour_warnings(
            [{"label": "bar", "colour": "rgb(248, 112, 96)"},
             {"label": "node", "colour": "#102542"}], self.ALARMS), [])

    def test_no_tokens_means_no_check(self):
        self.assertEqual(check_render.colour_warnings(
            [{"label": "bar", "colour": "rgb(163, 18, 58)"}], {}), [])


class TestStripWarnings(unittest.TestCase):
    def test_thick_left_border_alone_is_a_side_strip(self):
        found = check_render.strip_warnings(
            [{"label": "div.note", "left": 4, "right": 0, "top": 0, "bottom": 0}])
        self.assertIn("div.note", found[0])

    def test_even_borders_are_fine(self):
        self.assertEqual(check_render.strip_warnings(
            [{"label": "div.figframe", "left": 1, "right": 1, "top": 1, "bottom": 1},
             {"label": "div.box", "left": 3, "right": 3, "top": 3, "bottom": 3}]), [])


class TestReadDossier(unittest.TestCase):
    def read(self, html):
        return check_render.read_dossier(html)

    def test_an_empty_or_broken_page_gives_an_empty_model(self):
        for html in ("", "</p></div></section></body>", '<html><body><div class="x"><sp'):
            d = self.read(html)
            for f in dataclasses.fields(d):
                self.assertIn(getattr(d, f.name), (None, (), "", False), (html, f.name))

    def test_inert_content_and_comments_never_reach_the_model(self):
        d = self.read('<template><section class="answer"><p class="claim">T</p></section></template>'
                      '<noscript><table><tr><td>x</td></tr></table></noscript>'
                      '<!-- <p>comment</p> --><p>live</p>')
        self.assertIsNone(d.answer)
        self.assertEqual((d.uncaptioned, d.tables), ((), ()))
        self.assertEqual([p.text for p in d.paragraphs], ["live"])

    def test_the_answer_box_claims(self):
        d = self.read('<section class="answer"><p class="claim">The check\n  fails.</p>'
                      '<p class="claim"><em>Two</em> claims</p></section>'
                      '<section class="answer"><p class="claim">A second box</p></section>')
        self.assertEqual(d.answer.claims, ("The check fails.", "Two claims"))

    def test_a_key_finding_href_is_none_without_a_link_and_empty_without_an_href(self):
        d = self.read('<section class="answer"></section><section class="findings"><ol>'
                      '<li>No link</li><li><a>No href</a></li>'
                      '<li><a href="#s1">Linked</a><ul><li>nested</li></ul></li></ol></section>')
        self.assertEqual([f.href for f in d.key_findings.items], [None, "", "#s1"])
        self.assertTrue(d.key_findings.follows_answer)
        d = self.read('<section class="findings"><ol></ol></section><section class="answer"></section>')
        self.assertFalse(d.key_findings.follows_answer)

    def test_section_titles_skip_the_number_and_the_count(self):
        d = self.read(section(1, "How the  check runs", "<p>x</p>") + section(2, "Costs", figure(1))
                      + '<section class="sec"><h2>Bare</h2></section>')
        self.assertEqual([(s.id, s.title, s.has_figure) for s in d.sections],
                         [("s1", "How the check runs", False), ("s2", "Costs", True), (None, "Bare", False)])

    def test_figno_is_the_first_caption_figno_normalised(self):
        d = self.read(figure(1, caption=" Figure\n 1. ") + figure(2, "table")
                      + '<div class="fig" id="fig-3"><span class="figno">Figure 9.</span>'
                      '<p class="caption"><span class="figno">Figure 3.</span></p></div>'
                      '<div class="fig" id="fig-4"><div class="figframe">x</div></div>')
        self.assertEqual([(f.kind, f.number, f.id, f.figno) for f in d.figures], [
            ("Figure", 1, "fig-1", "Figure 1."), ("Table", 2, "table-2-fig", "Table 2."),
            ("Figure", 3, "fig-3", "Figure 3."), ("Figure", 4, "fig-4", "")])

    def test_after_caption_sees_a_wrapped_sowhat(self):
        wrapped = f'<div class="wrap">{SOWHAT}</div>'
        d = self.read(figure(1, sowhat=wrapped, after=True) + figure(2, sowhat=wrapped))
        self.assertEqual([so.after_caption for f in d.figures for so in f.so_whats], [True, False])
        so = d.figures[1].so_whats[0]
        self.assertTrue(so.has_label)
        self.assertEqual([(c.text, c.key_figures) for c in so.claims], [("It costs 4 times more.", 1)])

    def test_dag_so_what_is_an_h3_so_what_in_dag_notes(self):
        notes = '<div class="dag-notes"><h3> So  what </h3><p>It is slow.</p></div>'
        d = self.read(figure(1, body=dag(3), sowhat=notes) + figure(2, body=dag(3), sowhat=""))
        self.assertEqual([(f.dag_so_what, f.so_whats) for f in d.figures], [(True, ()), (False, ())])

    def test_a_dag_knows_its_figure_and_its_largest_orientation(self):
        uneven = ('<div class="dag-frame"><svg class="dag dag-lr"><g class="dn"></g></svg>'
                  '<svg class="dag dag-tb">' + '<g class="dn"></g>' * 5 + '</svg></div>')
        d = self.read('<svg class="dag"><g class="dn"></g><g class="dn"></g></svg>\n'
                      + figure(1, body=dag(4)) + "\n" + uneven)
        self.assertEqual([(g.figure, g.line, g.nodes) for g in d.dags],
                         [(None, 1, 2), (("Figure", 1), 2, 4), (None, 3, 5)])

    def test_visible_rows_skip_hidden_rows_and_closed_details(self):
        d = self.read('<table><tr><th>h</th></tr><tr><td>1</td></tr><tr hidden><td>2</td></tr>'
                      '<tr style="display: none"><td>3</td></tr>'
                      '<tbody style="display:none"><tr><td>4</td></tr></tbody></table>\n'
                      '<details><summary>more</summary><table><tr><td>5</td></tr></table></details>\n'
                      '<details open><table><tr><td>6</td></tr></table></details>')
        self.assertEqual([(t.line, t.visible_rows) for t in d.tables], [(1, 1), (2, 0), (3, 1)])

    def test_the_title_is_the_documents_not_an_svgs(self):
        d = self.read('<html><head><svg><title>Chart</title></svg><title>Report [Title here]</title>'
                      '</head><body><p>x</p></body></html>')
        self.assertEqual(d.title, "Report [Title here]")
        self.assertNotIn("Chart", d.prose)

    def test_prose_skips_code_scripts_and_svg(self):
        d = self.read('<html><body><p>Plain <code>code</code> words</p><script>var s</script>'
                      '<svg><text>label</text></svg><pre>pre</pre><style>.x{}</style></body></html>')
        self.assertEqual(check_render.norm(d.prose), "Plain words")

    def test_vega_data_urls_skip_data_uris_and_inline_values(self):
        d = self.read('<script src="https://cdn.jsdelivr.net/npm/vega@6.4.0/build/vega.min.js"></script>'
                      '<script>vegaEmbed("#a", {"data": {"url": "rows.csv"}});'
                      'vegaEmbed("#b", {"data": {"url": "data:text/csv,a%0A1"}});'
                      'vegaEmbed("#c", {"data": {"values": [{"url": "x.csv"}]}});</script>')
        self.assertEqual(d.vega_data_urls, ("rows.csv",))

    # Carried over from TestMermaidBlocks and TestResourceUrls, which go in the contract phase.

    def test_mermaid_blocks_with_lines_and_decoded_source(self):
        html = (
            "<html><body>\n"
            '<pre class="mermaid">flowchart LR\n  A --&gt; B</pre>\n'
            '<div class="card mermaid">sequenceDiagram</div>\n'
            "</body></html>"
        )
        self.assertEqual([(b.line, b.source) for b in self.read(html).mermaid],
                         [(2, "flowchart LR\n  A --> B"), (4, "sequenceDiagram")])

    def test_mermaid_needs_the_mermaid_class(self):
        html = '<pre class="mermaid-ish">x</pre><pre class="code">flowchart</pre>'
        self.assertEqual(self.read(html).mermaid, ())

    def test_a_nested_same_tag_does_not_end_a_mermaid_block_early(self):
        html = '<div class="mermaid">a<div>b</div>c</div><div>outside</div>'
        self.assertEqual(self.read(html).mermaid[0].source, "abc")

    def test_mermaid_skips_blocks_the_browser_never_renders(self):
        html = (
            '<template><pre class="mermaid">T</pre></template>\n'
            '<noscript><pre class="mermaid">N</pre></noscript>\n'
            '<textarea><pre class="mermaid">X</pre></textarea>\n'
            "<!-- <pre class=\"mermaid\">C</pre> -->\n"
            '<pre class="mermaid">real</pre>\n'
        )
        self.assertEqual([(b.line, b.source) for b in self.read(html).mermaid], [(5, "real")])

    def test_resources_are_every_http_url_the_page_loads(self):
        html = (
            '<link rel="stylesheet" href="https://fonts.example/a.css">\n'
            '<script src="https://cdn.jsdelivr.net/npm/vega@6.4.0/build/vega.min.js"></script>\n'
            '<img src="https://img.example/x.png">\n'
            '<a href="https://elsewhere.example/">a link is not a resource</a>\n'
            '<script type="module">\n'
            '  // import x from "https://old.example/x.mjs";\n'
            f'  import mermaid from "{MERMAID_PIN}";\n'
            '  const m = await import("https://esm.sh/thing@1");\n'
            '</script>\n'
            '<img src="local.png"><img src="data:image/gif;base64,R0lG">\n'
        )
        self.assertEqual(self.read(html).resources, (
            "https://fonts.example/a.css",
            "https://cdn.jsdelivr.net/npm/vega@6.4.0/build/vega.min.js",
            "https://img.example/x.png",
            MERMAID_PIN,
            "https://esm.sh/thing@1",
        ))

    def test_resources_skip_preconnect_hints(self):
        html = ('<link rel="preconnect" href="https://cdn.jsdelivr.net">'
                '<link rel="dns-prefetch" href="https://cdn.jsdelivr.net">'
                '<link rel="Preconnect stylesheet" href="https://fonts.example/a.css">'
                '<link href="https://fonts.example/b.css">')
        self.assertEqual(self.read(html).resources,
                         ("https://fonts.example/a.css", "https://fonts.example/b.css"))


class TestSourceChecks(unittest.TestCase):
    def test_a_vega_data_url_fails(self):
        for spec in ('{"data": {"url": "rows.csv"}}', "{data: {format: {type: 'csv'}, url: 'x/rows.csv'}}",
                     '{"data": {"url": "https://vega.github.io/data/cars.json"}}'):
            page = dossier().replace("</main>", f"</main><script>vegaEmbed('#c', {spec});</script>")
            self.assertIn("data URL", " | ".join(check_render.source_checks(page, None, "s")[0]), spec)

    def test_inline_vega_data_passes(self):
        for spec in ('{"data": {"values": [{"url": "rows.csv"}]}}',
                     '{"data": {"url": "data:text/csv,a%0A1"}}'):
            page = dossier().replace("</main>", f"</main><script>vegaEmbed('#c', {spec});</script>")
            self.assertEqual(check_render.source_checks(page, None, "s")[0], [], spec)

    def test_combines_structure_hosts_libraries_and_the_locked_block(self):
        page = dossier().replace("<main>", LOCKED + '<script src="https://unpkg.com/x@1.0.0"></script>'
                                 '<script src="https://cdn.jsdelivr.net/npm/@mermaid-js/'
                                 'layout-elk@0.2.3/dist/x.mjs"></script><main>')
        problems, warnings, unverified = check_render.source_checks(page, LOCKED, "s.html")
        self.assertEqual(len(problems), 1)
        self.assertIn("unpkg.com", problems[0])
        self.assertIn("layout-elk", " ".join(warnings))
        self.assertEqual(unverified, [])
        tampered = LOCKED.replace("grid", "flex")
        self.assertIn("differs", " ".join(check_render.source_checks(page, tampered, "s.html")[0]))

    def test_a_missing_scaffold_leaves_the_locked_block_unverified(self):
        problems, _, unverified = check_render.source_checks(dossier(), None, "/x/scaffold.html")
        self.assertEqual(problems, [])
        self.assertIn("/x/scaffold.html", unverified[0])

    def test_the_skill_ships_a_scaffold_with_a_locked_block(self):
        if not check_render.SCAFFOLD.exists():
            self.skipTest("assets/scaffold.html not written yet")
        self.assertIsNotNone(
            check_render.locked_version_and_text(check_render.read_source(check_render.SCAFFOLD)))


class TestPinsMatchTheScaffold(unittest.TestCase):
    """check_render's LIBRARIES is a copy of the scaffold's library block; they must not drift."""

    URL = re.compile(r"""(?:<script[^>]*\bsrc|\bimport\b[^"'\n]*\bfrom)\s*=?\s*["']([^"']+)["']""")
    NPM = re.compile(r"/npm/((?:@[^/@]+/)?[^/@]+)@([^/]+)/")

    def test_scaffold_urls_are_exactly_the_libraries(self):
        if not check_render.SCAFFOLD.exists():
            self.skipTest("assets/scaffold.html not written yet")
        html = check_render.SCAFFOLD.read_text(encoding="utf-8")
        urls = self.URL.findall(html)
        self.assertTrue(urls, "no <script src> or import URL found in the scaffold")
        pins = {}
        for url in urls:
            m = self.NPM.search(url)
            self.assertIsNotNone(m, url)
            pins[m.group(1)] = m.group(2)
        self.assertEqual(pins, check_render.LIBRARIES)

    def test_network_probe_uses_the_mermaid_pin(self):
        self.assertIn("mermaid@" + check_render.LIBRARIES["mermaid"] + "/",
                      check_render.NETWORK_PROBE_URL)


class TestCommandLine(unittest.TestCase):
    """The script end to end; a structure fault fails with or without a browser."""

    def test_a_page_without_an_answer_box_fails(self):
        script = REPO_ROOT / "skills" / "dossier" / "scripts" / "check_render.py"
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "report.html"
            page.write_text(dossier(answer=""), encoding="utf-8")
            run = subprocess.run([sys.executable, str(script), str(page),
                                  "--shots", str(Path(tmp) / "shots")],
                                 capture_output=True, text=True, timeout=400)
        report, _, last = run.stdout.rstrip().rpartition("\n")
        self.assertEqual(last, "FAIL", run.stdout[-3000:] + run.stderr[-3000:])
        self.assertEqual(run.returncode, 1)
        self.assertIn("no answer box", " | ".join(json.loads(report)["problems"]))


@unittest.skipUnless(importlib.util.find_spec("playwright"), "needs Playwright and Chromium")
class TestGalleryRenders(unittest.TestCase):
    """The shipped gallery is the render fixture: it must PASS the full check."""

    def test_gallery_passes(self):
        gallery = REPO_ROOT / "skills" / "dossier" / "assets" / "gallery.html"
        if not gallery.exists():
            self.skipTest("assets/gallery.html not written yet")
        script = REPO_ROOT / "skills" / "dossier" / "scripts" / "check_render.py"
        with tempfile.TemporaryDirectory() as shots:
            run = subprocess.run([sys.executable, str(script), str(gallery), "--shots", shots],
                                 capture_output=True, text=True, timeout=400)
        if run.returncode == 2:
            self.skipTest("BLOCKED (no browser or no network): " + run.stdout[-300:])
        report, _, last = run.stdout.rstrip().rpartition("\n")
        self.assertEqual(last, "PASS", run.stdout[-3000:])
        self.assertEqual(run.returncode, 0, run.stdout[-3000:])
        result = json.loads(report)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["warnings"], [])


@unittest.skipUnless(importlib.util.find_spec("playwright"), "needs Playwright and Chromium")
class TestInCellBarColour(unittest.TestCase):
    """td.bar is a category mark: a red or amber in-cell bar warns like .bar-fill."""

    PAGE = """<html><head><style>:root { --red: #a3123a; --amber: #b7791f; }
      td.bar .cbar { position: relative; display: block; }
      td.bar .cbar::before { content: ""; position: absolute; inset: 0; background: var(--bar); }
      </style></head><body><table class="data"><tr>
      <td class="bar" style="background: var(--amber)">1</td>
      <td class="bar"><span class="cbar" style="--bar: var(--red)">2</span></td>
      <td class="bar"><span class="cbar" style="--bar: #f87060">3</span></td>
      </tr></table></body></html>"""

    def test_alarm_coloured_td_bar_warns(self):
        from playwright.sync_api import Error, sync_playwright
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Error as exc:
                self.skipTest(f"no browser: {exc}")
            page = browser.new_page()
            page.set_content(self.PAGE)
            page.add_script_tag(content=check_render.INIT_JS)
            found = page.evaluate("(t) => window.__vrCheck.colours(t)",
                                  list(check_render.ALARM_TOKENS))
            browser.close()
        warnings = check_render.colour_warnings(found["facts"], found["alarms"])
        self.assertEqual(len(warnings), 2, warnings)
        self.assertIn("--amber", warnings[0])
        self.assertIn("--red", warnings[1])


class TestVerdictExtensions(unittest.TestCase):
    blocked_cdn = TestVerdict.blocked_cdn

    def test_structure_and_layout_problems_fail_even_offline(self):
        for case in (result(structure=["no answer box"]), result(layout=["page scrolls"]),
                     result(structure=["no Limits"], requests=[self.blocked_cdn]),
                     result(blocked="no browser", structure=["no answer box"])):
            self.assertEqual(check_render.verdict(case), FAIL, case)

    def test_drawn_but_bad_charts_and_dags_fail(self):
        for case in (result(charts=[{"status": "empty"}]), result(charts=[{"status": "error"}]),
                     result(dags=[{"status": "spill"}]), result(dags=[{"status": "clipped"}])):
            self.assertEqual(check_render.verdict(case), FAIL, case)

    def test_unrendered_chart_is_blocked_when_the_cdn_is_down(self):
        case = result(charts=[{"status": "unrendered"}], requests=[self.blocked_cdn])
        self.assertEqual(check_render.verdict(case), BLOCKED)
        self.assertEqual(check_render.verdict(result(charts=[{"status": "unrendered"}])), FAIL)

    def test_problems_lists_every_new_reason(self):
        case = result(structure=["no answer box"], layout=["Table 1 overflows"],
                      charts=[{"n": 1, "label": "Figure 1", "status": "empty", "problem": "no marks"}],
                      dags=[{"n": 1, "label": "Figure 3", "status": "spill", "problem": "x spills"}])
        text = " | ".join(check_render.problems(case))
        for want in ("no answer box", "Table 1 overflows", "Figure 1", "no marks", "x spills"):
            self.assertIn(want, text)


if __name__ == "__main__":
    unittest.main()
