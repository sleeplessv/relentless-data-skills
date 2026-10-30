"""Tests for skills/dossier/scripts/dag_svg.py.

Standard library only. Run from the repo root:

    python3 -m unittest tests/test_dossier_dag.py -v

dag_svg.py draws a dependency graph as two static SVGs (left-to-right and
top-to-bottom) for the dossier's locked stylesheet. The tests cover its
public seams: load() validation, layout() geometry, render() markup and the
CLI's exit codes.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "dossier" / "scripts"))

import dag_svg  # noqa: E402


def node(i, tag="SKL", **kw):
    return dict({"id": i, "name": i, "tag": tag, "caption": f"{i} caption"}, **kw)


def graph(ids, edges, **kw):
    return dict({"nodes": [node(i) for i in ids], "edges": [list(e) for e in edges]}, **kw)


# a -> b -> c -> d, plus a -> d (a long edge spanning three ranks) and e -> c
CHAIN = graph("abcde", [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d"), ("e", "c")])


class TestLoad(unittest.TestCase):
    def test_edge_to_an_unknown_node_is_an_error(self):
        with self.assertRaises(dag_svg.GraphError) as cm:
            dag_svg.load(graph("ab", [("a", "zz")]))
        self.assertIn("zz", str(cm.exception))

    def test_cycle_is_an_error_that_names_its_nodes(self):
        with self.assertRaises(dag_svg.GraphError) as cm:
            dag_svg.load(graph("abc", [("a", "b"), ("b", "c"), ("c", "a")]))
        self.assertIn("cycle", str(cm.exception))

    def test_duplicate_node_id_is_an_error(self):
        with self.assertRaises(dag_svg.GraphError):
            dag_svg.load(graph("aa", []))

    def test_node_without_a_name_or_tag_is_an_error(self):
        with self.assertRaises(dag_svg.GraphError):
            dag_svg.load({"nodes": [{"id": "a", "tag": "SKL"}], "edges": []})
        with self.assertRaises(dag_svg.GraphError):
            dag_svg.load({"nodes": [{"id": "a", "name": "a"}], "edges": []})


class TestRanks(unittest.TestCase):
    def test_rank_is_the_longest_path_from_a_source(self):
        ranks = dag_svg.layout(dag_svg.load(CHAIN), "lr")["ranks"]
        self.assertEqual(ranks, {"a": 0, "b": 1, "c": 2, "d": 3, "e": 0})

    def test_a_given_rank_is_a_lower_bound(self):
        g = graph("abc", [("a", "b")])
        g["nodes"][2]["rank"] = 2
        ranks = dag_svg.layout(dag_svg.load(g), "lr")["ranks"]
        self.assertEqual(ranks, {"a": 0, "b": 1, "c": 2})


# Eleven nodes in five ranks with fan-in, fan-out and long edges: the shape of
# the approved prototype figure.
ELEVEN = graph(
    ["s1", "s2", "s3", "t1", "t2", "hub", "grp", "subj", "r1", "r2", "r3"],
    [("s3", "t1"), ("s3", "t2"), ("s1", "hub"), ("s2", "hub"), ("t1", "hub"), ("hub", "grp"),
     ("hub", "subj"), ("subj", "r1"), ("subj", "r2"), ("subj", "r3"), ("t2", "r3")],
    focus="subj", total_nodes=56)
ELEVEN["nodes"][6]["group_count"] = 17


def overlaps(b1, b2, gap=0):
    (x1, y1), (x2, y2) = b1, b2
    return x1 < x2 + dag_svg.W + gap and x2 < x1 + dag_svg.W + gap and \
        y1 < y2 + dag_svg.H + gap and y2 < y1 + dag_svg.H + gap


def lane_runs(d):
    """The straight segments (x0, y0, x1, y1) of a path: an edge's lanes through other ranks."""
    nums = [tuple(map(float, p.split(","))) for p in re.findall(r"-?[\d.]+,-?[\d.]+", d)]
    runs, pos, cur = [], 0, None
    for tok in re.findall(r"[MLC]", d):
        take = 3 if tok == "C" else 1
        pts = nums[pos:pos + take]
        pos += take
        if tok == "L":
            runs.append(cur + pts[0])
        cur = pts[-1]
    return runs


class TestLayout(unittest.TestCase):
    def setUp(self):
        self.g = dag_svg.load(ELEVEN)

    def test_no_two_nodes_overlap_in_either_direction(self):
        for mode in ("lr", "tb"):
            boxes = list(dag_svg.layout(self.g, mode)["boxes"].values())
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    self.assertFalse(overlaps(boxes[i], boxes[j], gap=8), (mode, boxes[i], boxes[j]))

    def test_viewbox_contains_every_node_with_a_margin(self):
        for mode in ("lr", "tb"):
            lay = dag_svg.layout(self.g, mode)
            vx, vy, vw, vh = lay["viewbox"]
            for x, y in lay["boxes"].values():
                self.assertGreaterEqual(x, vx + 4)
                self.assertGreaterEqual(y, vy + 4)
                self.assertLessEqual(x + dag_svg.W, vx + vw - 4)
                self.assertLessEqual(y + dag_svg.H, vy + vh - 4)

    def test_lr_puts_each_rank_in_its_own_column_and_tb_in_its_own_row(self):
        lr, tb = dag_svg.layout(self.g, "lr"), dag_svg.layout(self.g, "tb")
        for i, r in lr["ranks"].items():
            self.assertEqual(lr["boxes"][i][0], r * (dag_svg.W + 26))
            self.assertEqual(tb["boxes"][i][1], r * (dag_svg.H + 44))

    def test_a_long_edge_runs_in_a_lane_that_misses_every_node(self):
        for mode in ("lr", "tb"):
            lay = dag_svg.layout(self.g, mode)
            long_edges = [d for a, b, d in lay["paths"] if lay["ranks"][b] - lay["ranks"][a] > 1]
            self.assertEqual(len(long_edges), 3)  # s1->hub, s2->hub, t2->r3
            for d in long_edges:
                runs = lane_runs(d)
                self.assertTrue(runs, d)
                for x0, y0, x1, y1 in runs:
                    for bx, by in lay["boxes"].values():
                        inside = (bx - 2 < max(x0, x1) and min(x0, x1) < bx + dag_svg.W + 2 and
                                  by - 2 < max(y0, y1) and min(y0, y1) < by + dag_svg.H + 2)
                        self.assertFalse(inside, (mode, d, (bx, by)))

    def test_edges_run_from_the_reader_side_to_just_short_of_the_target(self):
        lay = dag_svg.layout(self.g, "lr")
        a, b, d = next(p for p in lay["paths"] if p[:2] == ("hub", "subj"))
        start = tuple(map(float, re.match(r"M(-?[\d.]+),(-?[\d.]+)", d).groups()))
        end = tuple(map(float, re.findall(r"(-?[\d.]+),(-?[\d.]+)", d)[-1]))
        hx, hy = lay["boxes"]["hub"]
        sx, sy = lay["boxes"]["subj"]
        self.assertEqual(start, (hx + dag_svg.W, hy + dag_svg.H / 2))
        self.assertEqual(end, (sx - 2, sy + dag_svg.H / 2))

    def test_layout_is_deterministic(self):
        self.assertEqual(dag_svg.layout(dag_svg.load(ELEVEN), "lr"), dag_svg.layout(self.g, "lr"))


def svgs(fragment):
    return re.findall(r"<svg\b.*?</svg>", fragment, re.S)


class TestRender(unittest.TestCase):
    def setUp(self):
        data = json.loads(json.dumps(ELEVEN))
        data["nodes"][0]["tag"] = "CI"
        data["nodes"][3]["tag"] = "TST"
        data["legend"] = {"TST": "test", "SKL": "skill"}
        self.data = data
        self.out = dag_svg.render(dag_svg.load(data))

    def test_fragment_is_a_dag_frame_with_lr_then_tb_drawing_then_a_legend(self):
        self.assertTrue(self.out.startswith('<div class="figframe dag-frame">'))
        two = svgs(self.out)
        self.assertEqual(len(two), 2)
        self.assertIn('class="dag dag-lr"', two[0])
        self.assertIn('class="dag dag-tb"', two[1])
        self.assertRegex(self.out, r'</svg>\s*</div>\s*<p class="legend">.*</p>\s*$')

    def test_drawings_carry_no_colours_of_their_own(self):
        for svg in svgs(self.out):
            self.assertNotRegex(svg, r'\b(fill|stroke|color)\s*=|#[0-9a-fA-F]{3,8}\b|rgb\(|style="[^"]*(fill|stroke|color)')

    def test_each_node_gets_its_tag_slot_and_the_legend_order_sets_the_slots(self):
        lr = svgs(self.out)[0]
        self.assertEqual(len(re.findall(r'<g class="dn tag-1\b', lr)), 1)       # TST, first in legend
        self.assertEqual(len(re.findall(r'<g class="dn tag-2\b', lr)), 9)       # SKL
        self.assertEqual(len(re.findall(r'<g class="dn tag-3\b', lr)), 1)       # CI, first seen after
        self.assertIn('<text class="tg"', lr)

    def test_subject_is_the_only_focus_node_and_the_group_shows_its_count(self):
        for svg in svgs(self.out):
            self.assertEqual(len(re.findall(r'<g class="dn [^"]*\bfocus\b', svg)), 1)
            group = re.search(r'<g class="dn [^"]*\bgroup\b.*?</g>', svg, re.S).group(0)
            self.assertIn('<rect class="cnt"', group)
            self.assertRegex(group, r'<text class="cn"[^>]*>17</text>')

    def test_arrowhead_markers_are_unique_per_drawing_and_used_by_every_edge(self):
        ids = re.findall(r'<marker id="([^"]+)"', self.out)
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        for svg, mid in zip(svgs(self.out), ids):
            self.assertIn('<path class="arrow"', svg)
            paths = re.findall(r'<path d="[^"]+" marker-end="url\(#([^)]+)\)"/>', svg)
            self.assertEqual(paths, [mid] * 11)
        other = dict(self.data, label="another figure")
        self.assertNotEqual(re.findall(r'<marker id="([^"]+)"', dag_svg.render(dag_svg.load(other))), ids)

    def test_aria_label_states_drawn_of_total(self):
        self.assertIn('role="img" aria-label="Dependency graph: 11 of 56 nodes drawn"', self.out)

    def test_legend_lists_slots_in_order_then_subject_then_group(self):
        legend = re.search(r'<p class="legend">(.*)</p>', self.out, re.S).group(1)
        keys = re.findall(r'<span class="(tgk [^"]+|grpk)">([^<]*)</span>([^<]*)</span>', legend)
        self.assertEqual(keys, [("tgk tag-1", "TST", "test"), ("tgk tag-2", "SKL", "skill"),
                                ("tgk tag-3", "CI", "CI"), ("tgk focus", "SKL", "subject"),
                                ("grpk", "", "merged group, count at right")])

    def test_text_is_escaped(self):
        data = graph(["a", "b"], [("a", "b")])
        data["nodes"][0]["name"] = "<b>&co</b>"
        out = dag_svg.render(dag_svg.load(data))
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;b&gt;&amp;co&lt;/b&gt;", out)

    def test_render_is_byte_for_byte_deterministic(self):
        self.assertEqual(dag_svg.render(dag_svg.load(self.data)), self.out)


class TestTextFit(unittest.TestCase):
    def test_a_name_that_fits_is_left_whole(self):
        # widest name in the approved figure, beside a three-letter badge
        self.assertEqual(dag_svg.fit("VISUAL-LANGUAGE.md", 148, 12.5), "VISUAL-LANGUAGE.md")

    def test_a_long_name_is_cut_with_an_ellipsis_and_kept_whole_in_the_title(self):
        long = "fct_customer_lifetime_value_by_acquisition_channel"
        data = graph(["a"], [])
        data["nodes"][0]["name"] = long
        out = dag_svg.render(dag_svg.load(data))
        shown = re.findall(r'<text class="nm"[^>]*>([^<]*)</text>', out)
        self.assertEqual(len(shown), 2)
        self.assertTrue(shown[0].endswith("…"), shown[0])
        self.assertLessEqual(dag_svg.text_width(shown[0], 12.5), dag_svg.W - 8 - 44.2)  # name starts after a 3-letter badge
        self.assertIn(f"<title>{long} · a caption</title>", out)

    def test_a_group_node_keeps_its_text_clear_of_the_count_chip(self):
        data = graph(["a"], [])
        data["nodes"][0].update(name="many many many other things", group_count=123,
                                caption=["skills/", "a very long folder caption"])
        out = dag_svg.render(dag_svg.load(data))
        chip_x = float(re.search(r'<rect class="cnt" x="([\d.]+)"', out).group(1))
        name = re.search(r'<text class="nm" x="([\d.]+)"[^>]*>([^<]*)</text>', out)
        cap = re.search(r'<text class="cp" x="([\d.]+)"[^>]*>([^<]*)</text>', out)
        self.assertLessEqual(float(name.group(1)) + dag_svg.text_width(name.group(2), 12.5), chip_x - 4)
        self.assertLessEqual(float(cap.group(1)) + dag_svg.text_width(cap.group(2), 10.5, mono=True), chip_x - 4)
        self.assertTrue(cap.group(2).startswith("skills/ · a very"))


class TestSize(unittest.TestCase):
    def test_eleven_nodes_draw_without_a_warning(self):
        self.assertEqual(dag_svg.load(ELEVEN)["warnings"], [])

    def test_twelve_nodes_warn_and_name_siblings_to_merge(self):
        g = graph(["root"] + [f"leaf{i}" for i in range(11)], [("root", f"leaf{i}") for i in range(11)])
        warnings = dag_svg.load(g)["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("12 nodes", warnings[0])
        self.assertIn("leaf0, leaf1", warnings[0])

    def test_sixteen_nodes_are_refused(self):
        g = graph([f"n{i}" for i in range(16)], [])
        with self.assertRaises(dag_svg.GraphError) as cm:
            dag_svg.load(g)
        self.assertIn("16 nodes", str(cm.exception))

    def test_more_node_types_than_badge_colours_is_an_error(self):
        g = graph([f"n{i}" for i in range(7)], [])
        for i, n in enumerate(g["nodes"]):
            n["tag"] = f"T{i}"
        with self.assertRaises(dag_svg.GraphError):
            dag_svg.load(g)


class TestGroups(unittest.TestCase):
    def test_members_collapse_into_one_counted_node_that_takes_their_edges(self):
        g = graph(["lint", "x", "y", "z", "ref"], [("lint", "x"), ("lint", "y"), ("lint", "z"),
                                                  ("x", "ref"), ("y", "ref"), ("x", "y")])
        g["groups"] = [{"id": "skills", "name": "other skills", "tag": "SKL", "caption": "skills/",
                        "members": ["x", "y", "z"]}]
        loaded = dag_svg.load(g)
        self.assertEqual([n["id"] for n in loaded["nodes"]], ["lint", "skills", "ref"])
        self.assertEqual(loaded["nodes"][1]["count"], 3)
        self.assertEqual(loaded["edges"], [("lint", "skills"), ("skills", "ref")])

    def test_a_member_of_two_groups_is_an_error(self):
        g = graph(["a", "b", "c"], [])
        g["groups"] = [{"id": "g1", "name": "g1", "tag": "SKL", "members": ["a", "b"]},
                       {"id": "g2", "name": "g2", "tag": "SKL", "members": ["b", "c"]}]
        with self.assertRaises(dag_svg.GraphError):
            dag_svg.load(g)


def run_cli(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = dag_svg.main(argv)
            except SystemExit as e:  # argparse usage errors
                code = e.code
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def test_reads_a_file_and_prints_the_fragment(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(ELEVEN, f)
        code, out, err = run_cli([f.name])
        Path(f.name).unlink()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), dag_svg.render(dag_svg.load(ELEVEN)))

    def test_writes_to_out_and_warns_on_stderr(self):
        g = graph(["root"] + [f"leaf{i}" for i in range(11)], [("root", f"leaf{i}") for i in range(11)])
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "dag.html"
            code, out, err = run_cli(["-", "--out", str(target)], stdin=json.dumps(g))
            self.assertEqual(code, 0)
            self.assertEqual(out, "")
            self.assertIn("warning: 12 nodes", err)
            self.assertTrue(target.read_text().startswith('<div class="figframe dag-frame">'))

    def test_invalid_graph_or_json_exits_1(self):
        code, out, err = run_cli(["-"], stdin=json.dumps(graph("ab", [("a", "b"), ("b", "a")])))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("cycle", err)
        self.assertEqual(run_cli(["-"], stdin="{not json")[0], 1)

    def test_missing_argument_exits_2(self):
        self.assertEqual(run_cli([])[0], 2)


if __name__ == "__main__":
    unittest.main()
