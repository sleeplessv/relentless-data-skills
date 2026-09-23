"""Tests for skills/review-pbi-diff/scripts/extract_changes.py.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here talks to git: the overlap computation works on the per-page
visual summaries the extractor builds, so the tests feed it those dicts
directly. The `overlaps` shape ({a, b, pct_of_smaller}) is asserted
deliberately: SKILL.md check 9 reads it, so it is an interface.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "review-pbi-diff" / "scripts"))

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


if __name__ == "__main__":
    unittest.main()
