"""Tests for skills/review-pbi-diff/scripts/extract_changes.py and check_artifact.py.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here talks to git: the overlap computation works on the per-page
visual summaries the extractor builds, so the tests feed it those dicts
directly. The `overlaps` shape ({a, b, pct_of_smaller}) is asserted
deliberately: SKILL.md check 9 reads it, so it is an interface. The artifact
check reads the markers references/artifact.md defines, another interface.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "review-pbi-diff" / "scripts"))

import check_artifact  # noqa: E402
import extract_changes  # noqa: E402


def visual(name, x, y, w, h, **extra):
    v = {"name": name, "x": x, "y": y, "width": w, "height": h,
         "visual_type": "barChart", "status": "unchanged"}
    v.update(extra)
    return v


class TestComputeOverlaps(unittest.TestCase):
    """Pairs above 15% of the smaller visual's area, using abs_x/abs_y."""

    def overlaps(self, visuals):
        extract_changes.resolve_group_offsets(visuals)
        return extract_changes.compute_overlaps(visuals)

    def test_disjoint_visuals_report_nothing(self):
        visuals = {"a": visual("a", 0, 0, 100, 100), "b": visual("b", 200, 0, 100, 100)}
        self.assertEqual(self.overlaps(visuals), [])

    def test_edge_touching_visuals_do_not_overlap(self):
        visuals = {"a": visual("a", 0, 0, 100, 100), "b": visual("b", 100, 0, 100, 100)}
        self.assertEqual(self.overlaps(visuals), [])

    def test_pct_is_fraction_of_smaller_visual(self):
        # b (50x50) sits half inside a (200x200): 25x50 = 1250 of b's 2500.
        visuals = {"a": visual("a", 0, 0, 200, 200), "b": visual("b", 175, 0, 50, 50)}
        self.assertEqual(
            self.overlaps(visuals), [{"a": "a", "b": "b", "pct_of_smaller": 0.5}]
        )

    def test_below_threshold_is_dropped_and_above_is_kept(self):
        # 10x100 = 1000 of 10000 -> 0.10 dropped; 20x100 = 2000 -> 0.20 kept.
        visuals = {
            "a": visual("a", 0, 0, 100, 100),
            "b": visual("b", 90, 0, 100, 100),
            "c": visual("c", 0, 80, 100, 100),
        }
        self.assertEqual(
            self.overlaps(visuals), [{"a": "a", "b": "c", "pct_of_smaller": 0.2}]
        )

    def test_exact_threshold_is_not_reported(self):
        # 15x100 = 1500 of 10000 -> exactly 0.15, which is not "more than".
        visuals = {"a": visual("a", 0, 0, 100, 100), "b": visual("b", 85, 0, 100, 100)}
        self.assertEqual(self.overlaps(visuals), [])

    def test_pct_rounded_to_three_decimals(self):
        # 33x100 = 3300 of 9900 (b is 99x100) -> 0.3333...
        visuals = {"a": visual("a", 0, 0, 100, 100), "b": visual("b", 67, 0, 99, 100)}
        self.assertEqual(self.overlaps(visuals)[0]["pct_of_smaller"], 0.333)

    def test_uses_group_resolved_absolute_positions(self):
        # Inside a group at (500, 0), b's relative (0, 0) is absolute (500, 0),
        # so it overlaps a at (500, 0) fully, not the visual at the origin.
        visuals = {
            "g": visual("g", 500, 0, 300, 300, visual_type="visualGroup"),
            "o": visual("o", 0, 0, 100, 100),
            "a": visual("a", 500, 0, 100, 100),
            "b": visual("b", 0, 0, 100, 100, parent_group="g"),
        }
        self.assertEqual(
            self.overlaps(visuals), [{"a": "a", "b": "b", "pct_of_smaller": 1.0}]
        )

    def test_groups_hidden_and_deleted_visuals_are_skipped(self):
        visuals = {
            "g": visual("g", 0, 0, 500, 500, visual_type="visualGroup"),
            "a": visual("a", 0, 0, 100, 100),
            "h": visual("h", 0, 0, 100, 100, hidden=True),
            "d": visual("d", 0, 0, 100, 100, status="deleted"),
        }
        self.assertEqual(self.overlaps(visuals), [])

    def test_shapes_and_textboxes_are_included_for_reviewer_judgment(self):
        visuals = {
            "bg": visual("bg", 0, 0, 400, 400, visual_type="shape"),
            "a": visual("a", 10, 10, 100, 100),
        }
        self.assertEqual(
            self.overlaps(visuals), [{"a": "a", "b": "bg", "pct_of_smaller": 1.0}]
        )

    def test_identical_boxes_report_full_overlap(self):
        visuals = {"a": visual("a", 10, 10, 100, 50), "b": visual("b", 10, 10, 100, 50)}
        self.assertEqual(
            self.overlaps(visuals), [{"a": "a", "b": "b", "pct_of_smaller": 1.0}]
        )

    def test_visual_without_raw_position_is_skipped(self):
        # resolve_group_offsets turns a None x/y into abs 0/0; that visual
        # must not be reported as sitting at the origin.
        visuals = {
            "a": visual("a", 0, 0, 100, 100),
            "p": visual("p", None, None, 100, 100),
        }
        self.assertEqual(self.overlaps(visuals), [])

    def test_missing_or_zero_size_boxes_are_ignored(self):
        visuals = {
            "a": visual("a", 0, 0, 100, 100),
            "n": visual("n", 0, 0, None, 100),
            "z": visual("z", 0, 0, 0, 100),
        }
        self.assertEqual(self.overlaps(visuals), [])


def change_model():
    """One report (a curated added page with a group, a scratch page) and one
    model with an added, a modified, and a deleted measure."""
    return {
        "reports": {"Sales": {"pages": {
            "p_new": {"display_name": "Margin", "status": "added", "visuals": {
                "g1": {"visual_type": "visualGroup", "status": "added"},
                "v_a": {"visual_type": "barChart", "status": "added"},
                "v_b": {"visual_type": "card", "status": "modified"},
            }},
            "p_scr": {"display_name": "Page 1", "status": "added", "scratch": True,
                      "visuals": {"v_s": {"visual_type": "table", "status": "added"}}},
        }}},
        "models": {"Sales": {"tables": {"Sales": {
            "measures_added": [{"name": "Margin"}],
            "measures_modified": [{"name": "Revenue"}],
            "measures_deleted": [{"name": "Old"}],
        }}, "relationships": {"added": [{}], "modified": [], "deleted": []}}},
    }


STATS = {"pages_added": 1, "visuals_added": 1, "visuals_modified": 1, "visuals_deleted": 0,
         "measures_added": 1, "measures_modified": 1, "relationships_added": 1}

MARGIN_CARD = ('<div data-model="Sales" data-table="Sales" data-measure="Margin" '
               'data-verdict="none"><h4>Margin</h4><span data-badge>❓ No definition</span></div>')
REVENUE_CARD = ('<div data-model="Sales" data-table="Sales" data-measure="Revenue" '
                'data-verdict="deviates"><h4>Revenue</h4><span data-badge>⚠️ Deviates</span></div>')
WIREFRAME = ('<h3>Margin</h3><div data-report="Sales" data-wireframe="p_new">'
             '<div data-visual="v_a" data-status="added">bar</div>'
             '<div data-visual="v_b" data-status="modified"><br>card</div></div>')
EXCLUDED = '<p data-excluded>Scratch pages excluded: Page 1.</p>'


def card(name, verdict, inner):
    return (f'<div data-model="Sales" data-table="Sales" data-measure="{name}" '
            f'data-verdict="{verdict}">{inner}</div>')


def flag(severity, badge, title="Finding", extra=""):
    return (f'<article data-severity="{severity}"><span data-badge>{badge}</span> '
            f'{title}{extra}</article>')


def chip(stat, text):
    return f'<span data-stat="{stat}">{text}</span>'


def artifact(stats=None, measures=None, wireframes=None, findings="", excluded=EXCLUDED,
             flags_list=None):
    stats = STATS if stats is None else stats
    measures = MARGIN_CARD + REVENUE_CARD if measures is None else measures
    wireframes = WIREFRAME if wireframes is None else wireframes
    flags_list = f"<div data-flags>{findings}</div>" if flags_list is None else flags_list
    chips = "".join(chip(k, f"{v} {k.replace('_', ' ')}") for k, v in stats.items())
    return (f"<html><body><header>{chips}</header><h2>Red flags</h2>{flags_list}"
            f"{excluded}{wireframes}{measures}</body></html>")


class TestCheckArtifact(unittest.TestCase):
    """The artifact must agree with change_model.json, by what a reader sees."""

    def result(self, html, scratch=(), model=None):
        return check_artifact.check(model or change_model(), html, scratch)

    def problems(self, html, scratch=(), model=None):
        return self.result(html, scratch, model)["problems"]

    def assertProblem(self, html, fragment, scratch=(), model=None):
        problems = self.problems(html, scratch, model)
        self.assertTrue(any(fragment in p for p in problems),
                        f"no problem containing {fragment!r} in {problems}")

    # The faithful baseline and the original checks.

    def test_faithful_artifact_passes_and_reports_counts(self):
        findings = flag("red", "🔴", "Bare division") + flag("yellow", "🟡", "Visible scratch page")
        result = self.result(artifact(findings=findings))
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["findings"], {"red": 1, "yellow": 1, "blue": 0})
        self.assertEqual(result["verdicts"], {"match": 0, "deviates": 1, "none": 1})
        self.assertEqual(result["excluded_pages"], [{
            "report": "Sales", "page": "p_scr", "display_name": "Page 1",
            "reason": "marked scratch by the extractor"}])

    def test_measure_without_a_verdict_card_fails(self):
        self.assertEqual(self.problems(artifact(measures=REVENUE_CARD)),
                         ["measure Sales[Margin] (model Sales) has no verdict card"])

    def test_verdict_badge_must_match_the_attribute(self):
        html = artifact(measures=card("Margin", "match", "Margin <span data-badge>❓</span>")
                        + card("Revenue", "maybe", "Revenue <span data-badge>✅</span>"))
        problems = self.problems(html)
        self.assertEqual(len(problems), 2)
        self.assertIn("is match, so its data-badge must show ✅ alone; it shows ❓", problems[0])
        self.assertIn("data-verdict 'maybe'", problems[1])

    def test_card_for_a_measure_the_change_model_lacks_fails(self):
        extra = card("Ghost", "none", "Ghost <span data-badge>❓</span>")
        problems = self.problems(artifact().replace("</body>", extra + "</body>"))
        self.assertEqual(len(problems), 1)
        self.assertIn("Sales[Ghost]", problems[0])

    def test_wireframe_must_draw_every_non_group_visual(self):
        html = artifact(wireframes='<h3>Margin</h3><div data-report="Sales" data-wireframe="p_new">'
                                   '<div data-visual="v_a" data-status="added"></div>'
                                   '<div data-visual="v_zzz" data-status="added"></div></div>')
        self.assertEqual(self.problems(html), [
            "page p_new (report Sales) wireframe is missing visuals ['v_b']",
            "page p_new (report Sales) wireframe draws visuals not on the page ['v_zzz']",
        ])

    def test_group_containers_are_optional_in_wireframes(self):
        html = artifact(wireframes='<h3>Margin</h3><div data-report="Sales" data-wireframe="p_new">'
                                   '<div data-visual="g1" data-status="added">'
                                   '<div data-visual="v_a" data-status="added"></div>'
                                   '<div data-visual="v_b" data-status="modified"></div></div></div>')
        self.assertEqual(self.problems(html), [])

    def test_missing_wireframe_and_scratch_wireframe_both_fail(self):
        html = artifact(wireframes='<h3>Page 1</h3><div data-report="Sales" data-wireframe="p_scr">'
                                   '<div data-visual="v_s" data-status="added"></div></div>')
        self.assertEqual(self.problems(html), [
            "page p_new (report Sales) has no wireframe",
            "page p_scr (report Sales) is scratch work but has a wireframe",
        ])

    def test_visual_outside_a_wireframe_fails(self):
        # Also a visuals-table row carrying data-visual for hover-linking.
        html = artifact().replace("</body>", '<table><tr data-visual="v_a"><td>bar</td></tr></table></body>')
        self.assertProblem(html, "visual v_a sits outside any data-wireframe")

    def test_wireframe_of_an_untouched_page_fails(self):
        extra = '<h3>Details</h3><div data-report="Sales" data-wireframe="p_old"></div>'
        self.assertEqual(self.problems(artifact(wireframes=WIREFRAME + extra)), [
            "wireframe for page p_old (report Sales) matches no touched page; "
            "untouched pages get no wireframe"])

    def test_stat_chip_text_is_checked_and_groups_are_not_counted(self):
        # visuals_added is 1: the added group container does not count.
        html = artifact(stats=dict(STATS, visuals_added=2))
        self.assertEqual(self.problems(html),
                         ["stat chip visuals_added shows 2, change model gives 1"])

    def test_every_stat_chip_is_required_even_at_zero(self):
        stats = {k: v for k, v in STATS.items() if k != "visuals_deleted"}
        self.assertEqual(self.problems(artifact(stats=stats)),
                         ["no stat chip for visuals_deleted (expected 0)"])

    def test_user_named_scratch_page_is_excluded(self):
        html = artifact(wireframes="", stats=dict(STATS, pages_added=0, visuals_added=0,
                                                  visuals_modified=0),
                        excluded="<p data-excluded>Excluded: Page 1, Margin.</p>")
        result = self.result(html, scratch=["Margin"])
        self.assertEqual(result["problems"], [])
        self.assertEqual([(p["page"], p["reason"]) for p in result["excluded_pages"]],
                         [("p_new", "--scratch 'Margin'"), ("p_scr", "marked scratch by the extractor")])

    def test_deleted_measure_card_fails(self):
        extra = card("Old", "none", "Old <span data-badge>❓</span>")
        self.assertEqual(self.problems(artifact(measures=MARGIN_CARD + REVENUE_CARD + extra)), [
            "line 1: measure Sales[Old] (model Sales) is deleted; list deleted measures "
            "without data-measure"])

    # Badges are read from the one data-badge element, not the whole card.

    def test_badge_elsewhere_in_the_card_does_not_count(self):
        inner = ('Margin <span data-badge>⚠️ Deviates</span>'
                 '<p>Numerator ✅ matches; the denominator does not.</p>')
        self.assertProblem(artifact(measures=card("Margin", "match", inner) + REVENUE_CARD),
                           "is match, so its data-badge must show ✅ alone; it shows ⚠")

    def test_emoji_in_dax_or_evidence_neither_satisfies_nor_confuses_a_badge(self):
        dax = '<pre>SWITCH(TRUE(), [M] &lt; 0.2, "🔴", [M] &lt; 0.3, "⚠️", "❓")</pre>'
        measures = card("Margin", "match", "Margin <span data-badge>✅</span>" + dax) + REVENUE_CARD
        self.assertEqual(self.problems(artifact(measures=measures)), [])
        findings = flag("red", "🔵", "Hardcoded thresholds", dax)
        self.assertProblem(artifact(findings=findings),
                           "is red, so its data-badge must show 🔴 alone; it shows 🔵")

    def test_badge_must_hold_only_its_own_badge(self):
        inner = "Margin <span data-badge>✅ formula, ⚠️ format</span>"
        self.assertProblem(artifact(measures=card("Margin", "match", inner) + REVENUE_CARD),
                           "it shows ✅ ⚠")

    def test_each_card_needs_exactly_one_badge(self):
        none = card("Margin", "none", "Margin ❓")
        two = card("Margin", "none", "Margin <span data-badge>❓</span><span data-badge>❓</span>")
        self.assertProblem(artifact(measures=none + REVENUE_CARD), "has no data-badge element")
        self.assertProblem(artifact(measures=two + REVENUE_CARD), "has 2 data-badge elements")
        stray = artifact().replace("</body>", "<span data-badge>✅</span></body>")
        self.assertProblem(stray, "data-badge sits outside any measure or red-flag card")

    def test_badge_drawn_by_css_does_not_count(self):
        inner = 'Margin <span class="ok" data-badge></span>'
        html = artifact(measures=card("Margin", "none", inner) + REVENUE_CARD).replace(
            "<body>", '<body><style>.ok::before { content: "❓"; }</style>')
        self.assertProblem(html, "it shows none of ✅⚠❓")

    def test_severity_badge_must_match_and_script_text_is_ignored(self):
        # The 🔵 inside the badge's script is not something a reader sees.
        findings = ('<article data-severity="blue"><span data-badge>🔴 wrong badge'
                    '<script>const tally = "🔵";</script></span></article>')
        problems = self.problems(artifact(findings=findings))
        self.assertEqual(len(problems), 1)
        self.assertIn("is blue, so its data-badge must show 🔵 alone; it shows 🔴", problems[0])

    # Hidden and never-rendered markup counts for nothing.

    def test_hidden_or_unrendered_card_does_not_count(self):
        wrappers = {
            "hidden attribute": ("<div hidden>", "</div>"),
            'aria-hidden="true"': ('<div aria-hidden="true">', "</div>"),
            "display:none": ('<div style="color: red; display: none !important">', "</div>"),
            "visibility:hidden": ('<div style="visibility:hidden">', "</div>"),
            "opacity:0": ('<div style="opacity: 0">', "</div>"),
            "<template>": ("<template>", "</template>"),
            "closed <dialog>": ("<dialog>", "</dialog>"),
        }
        for reason, (before, after) in wrappers.items():
            with self.subTest(reason):
                problems = self.problems(artifact(measures=before + MARGIN_CARD + after + REVENUE_CARD))
                self.assertIn("measure Sales[Margin] (model Sales) has no verdict card", problems)
                self.assertTrue(any(f"is hidden from readers ({reason})" in p for p in problems), problems)

    def test_markup_inside_raw_text_elements_does_not_count(self):
        for tag in ("noscript", "title", "iframe", "noembed", "noframes", "textarea", "xmp"):
            with self.subTest(tag):
                html = artifact(measures=f"<{tag}>{MARGIN_CARD}</{tag}>{REVENUE_CARD}")
                self.assertIn("measure Sales[Margin] (model Sales) has no verdict card",
                              self.problems(html))

    def test_markers_in_comments_do_not_count(self):
        html = artifact(measures=f"<!--{MARGIN_CARD}-->{REVENUE_CARD}")
        self.assertEqual(self.problems(html),
                         ["measure Sales[Margin] (model Sales) has no verdict card"])

    def test_self_closing_script_swallows_what_follows(self):
        # Browsers ignore "/>" on <script>, so the card is script text.
        html = artifact(measures=f'<script src="app.js"/>{MARGIN_CARD}</script>{REVENUE_CARD}')
        self.assertEqual(self.problems(html),
                         ["measure Sales[Margin] (model Sales) has no verdict card"])

    def test_hidden_badge_or_number_text_does_not_count(self):
        inner = 'Margin <span data-badge><span aria-hidden="true">❓</span> No definition</span>'
        self.assertProblem(artifact(measures=card("Margin", "none", inner) + REVENUE_CARD),
                           "it shows none of")
        html = artifact().replace(chip("visuals_added", "1 visuals added"),
                                  chip("visuals_added", "<span hidden>1</span>7 visuals added"))
        self.assertIn("stat chip visuals_added shows 7, change model gives 1", self.problems(html))

    def test_visible_descendant_of_visibility_hidden_counts(self):
        html = artifact().replace(
            chip("relationships_added", "1 relationships added"),
            '<div style="visibility: hidden">ghost <span data-stat="relationships_added" '
            'style="visibility: visible">1 relationship added</span></div>')
        self.assertEqual(self.problems(html), [])

    # Stat chips: once each, labelled, separated at element boundaries.

    def test_duplicate_stat_chips_fail_in_either_order(self):
        right, wrong = chip("visuals_added", "1 visuals added"), chip("visuals_added", "7 visuals added")
        for html in (artifact().replace("</body>", wrong + "</body>"),
                     artifact().replace(right, wrong).replace("</body>", right + "</body>")):
            with self.subTest():
                self.assertProblem(html, "2 stat chips for visuals_added")

    def test_stat_chip_must_name_its_stat(self):
        html = artifact().replace(chip("visuals_added", "1 visuals added"),
                                  chip("visuals_added", "1 visuals modified"))
        self.assertProblem(html, "stat chip visuals_added reads '1 visuals modified'")
        html = artifact().replace(chip("visuals_added", "1 visuals added"),
                                  chip("visuals_added", "1 new visual"))
        self.assertEqual(self.problems(html), [])

    def test_adjacent_elements_do_not_run_together(self):
        for inner in ("<div>1</div><div>0 groups counted</div><div>visuals added</div>",
                      "1<sup>2</sup> visuals added", "<b>1</b> visuals added"):
            with self.subTest(inner):
                html = artifact().replace(chip("visuals_added", "1 visuals added"),
                                          chip("visuals_added", inner))
                self.assertEqual(self.problems(html), [])

    # Red flags: every finding is its own marked <article> in data-flags.

    def test_unmarked_red_flag_card_fails(self):
        findings = flag("red", "🔴") + "<article>🔴 Inactive relationship</article>"
        result = self.result(artifact(findings=findings))
        self.assertIn("line 1: <article> in the data-flags list has no data-severity",
                      result["problems"])
        loose = flag("red", "🔴") + '<div class="card">🟡 Visible scratch page</div>'
        self.assertProblem(artifact(findings=loose),
                           "the data-flags list shows 🟡 outside any red-flag card")

    def test_severity_marker_on_a_rank_group_fails(self):
        section = ('<section data-severity="red"><h3 data-badge>🔴 Wrong results</h3>'
                   '<article>Bare division</article><article>Inactive rel</article></section>')
        self.assertProblem(artifact(findings=section), "red-flag card is marked on <section>")
        self.assertProblem(artifact(findings=section), "<article> in the data-flags list has no data-severity")
        group = ('<article data-severity="red"><h3 data-badge>🔴 Wrong results</h3>'
                 + flag("red", "🔴", "Bare division") + "</article>")
        self.assertProblem(artifact(findings=group), "sits inside the card at line 1")

    def test_red_flag_list_is_required_and_holds_the_cards(self):
        self.assertProblem(artifact(flags_list=""), "no data-flags element")
        self.assertProblem(artifact(flags_list=flag("red", "🔴")), "sits outside the data-flags list")

    def test_severity_emoji_outside_the_list_and_page_wrappers_are_fine(self):
        html = artifact(findings=flag("red", "🔴")).replace(
            "<body>", "<body><article><p>Summary: 🔴 1, 🟡 0</p>").replace("</body>", "</article></body>")
        self.assertEqual(self.problems(html), [])

    # Markers are tied to visible text.

    def test_measure_card_must_show_its_name_outside_pre(self):
        titled_wrong = card("Margin", "none", "<h4>AOV</h4><span data-badge>❓</span>")
        in_dax_only = card("Margin", "none", "<h4>AOV</h4><span data-badge>❓</span><pre>[Margin]</pre>")
        for measures in (titled_wrong, in_dax_only):
            with self.subTest():
                self.assertProblem(artifact(measures=measures + REVENUE_CARD),
                                   "measure Sales[Margin] card doesn't show the measure's name")

    def test_wireframe_must_follow_a_heading_naming_its_page(self):
        self.assertProblem(artifact(wireframes=WIREFRAME.replace("<h3>Margin</h3>", "<h3>Overview</h3>")),
                           "follows the heading 'Overview'; the last heading before it must name the page 'Margin'")
        self.assertProblem(artifact(wireframes=WIREFRAME.replace("<h3>Margin</h3>", "")),
                           "follows the heading 'Red flags'")

    def test_visual_box_status_must_match_the_change_model(self):
        wrong = WIREFRAME.replace('data-status="added"', 'data-status="unchanged"')
        self.assertProblem(artifact(wireframes=wrong),
                           "visual v_a has data-status 'unchanged'; the change model says 'added'")
        missing = WIREFRAME.replace(' data-status="modified"', "")
        self.assertProblem(artifact(wireframes=missing), "visual v_b has no data-status")

    # Scratch pages: scoped, audited, and named in the artifact.

    def test_scratch_can_be_scoped_to_one_report_and_ignores_case(self):
        model = change_model()
        model["reports"]["Ops"] = {"pages": {"p_new": {"display_name": "Margin", "status": "added",
                                                       "visuals": {}}}}
        want = check_artifact.expected(model, ["sales/margin"])
        self.assertEqual([(p["report"], p["page"]) for p in want["excluded"]],
                         [("Sales", "p_new"), ("Sales", "p_scr")])
        want = check_artifact.expected(model, ["MARGIN"])
        self.assertEqual([(p["report"], p["page"]) for p in want["excluded"]],
                         [("Sales", "p_new"), ("Sales", "p_scr"), ("Ops", "p_new")])

    def test_scratch_value_matching_no_page_fails(self):
        self.assertProblem(artifact(), "--scratch 'Nope' matches no page in the change model",
                           scratch=["Nope"])

    def test_exclusion_line_must_name_every_excluded_page(self):
        self.assertProblem(artifact(excluded=""), "no data-excluded line names excluded page 'Page 1'")
        html = artifact(wireframes="", stats=dict(STATS, pages_added=0, visuals_added=0,
                                                  visuals_modified=0))
        self.assertEqual(self.problems(html, scratch=["Margin"]),
                         ["no data-excluded line names excluded page 'Margin' (report Sales)"])

    # Malformed input is a problem, not a crash.

    def test_valueless_markers_are_problems(self):
        extra = ('<div data-report="Sales" data-wireframe="p_new"><div data-visual></div></div>'
                 '<span data-stat></span><div data-measure></div>')
        problems = self.problems(artifact().replace("</body>", extra + "</body>"))
        self.assertIn("line 1: data-visual has no value", problems)
        self.assertProblem(artifact().replace("</body>", extra + "</body>"),
                           "needs values for data-model, data-table and data-measure")

    def test_unreadable_files_are_problems(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            model, html = Path(tmp) / "change_model.json", Path(tmp) / "a.html"
            model.write_text(json.dumps(change_model()), encoding="utf-8")
            html.write_bytes("<p>Caf\xe9</p>".encode("cp1252"))
            result = check_artifact.run(str(model), str(html))
            self.assertEqual(result["verdict"], "FAIL")
            self.assertIn("artifact is not UTF-8 (byte 0xe9 at offset 6)", result["problems"][0])
            model.write_text("{not json", encoding="utf-8")
            self.assertIn("cannot read change model", check_artifact.run(str(model), str(html))["problems"][0])

    # Parsing follows the browser's tree, not the literal tag sequence.

    def test_omitted_end_tags_are_implied(self):
        # Without implied </li>, Margin's item would hold Revenue's badge too.
        items = ('<ul><li data-model="Sales" data-table="Sales" data-measure="Margin" data-verdict="none">'
                 'Margin <span data-badge>❓</span>'
                 '<li data-model="Sales" data-table="Sales" data-measure="Revenue" data-verdict="deviates">'
                 'Revenue <span data-badge>⚠️</span></ul>')
        self.assertEqual(self.problems(artifact(measures=items)), [])
        # Without implied </p>, the chip would sit inside the hidden paragraph.
        html = artifact().replace(chip("visuals_added", "1 visuals added"),
                                  '<p hidden>draft<p data-stat="visuals_added">1 visual added</p>')
        self.assertEqual(self.problems(html), [])
        # Without implied </td>, the second cell's text would count for the first.
        cells = ('<table><tr><td data-stat="visuals_added">1 visual added'
                 '<td data-stat="visuals_modified">1 visual modified</table>')
        html = artifact().replace(chip("visuals_added", "1 visuals added"), "").replace(
            chip("visuals_modified", "1 visuals modified"), cells)
        self.assertEqual(self.problems(html), [])

    def test_misnested_inline_end_tag_keeps_the_block_open(self):
        html = artifact().replace(chip("visuals_added", "1 visuals added"),
                                  '<b><div data-stat="visuals_added"></b>1 visual added</div>')
        self.assertEqual(self.problems(html), [])

    def test_attribute_entities_compare_by_decoded_name(self):
        # Python versions decode a raw "&not" in an attribute differently.
        model = change_model()
        model["models"]["Sales"]["tables"]["Sales"]["measures_added"] = [{"name": "Units&notional"}]
        measures = ('<div data-model="Sales" data-table="Sales" data-measure="Units&notional" '
                    'data-verdict="none">Units&amp;notional <span data-badge>❓</span></div>' + REVENUE_CARD)
        self.assertEqual(self.problems(artifact(measures=measures), model=model), [])


if __name__ == "__main__":
    unittest.main()
