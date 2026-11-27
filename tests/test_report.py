"""Exercise scripts/report.py at its command line against a machine directory the tests build.

Each test writes its own replay sets, versions, verdicts and scan rows into a
machine directory in a temporary folder, in the shapes scripts/draw.py,
scripts/replay.py, scripts/judge.py and scripts/scan.py write them, and runs
the report from a copy of scripts/. No test reads the real machine directory
or a session log, starts a session or touches the network.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
BUCKETS = ("0-50", "51-300", "301-1500")
REPO = "example-org/alpha"  # what project-labels.json maps label A to; the report must never print it
TITLE = "Print the total of example-org/alpha"
OLD = object()  # a copied_tokens for a row written before scripts/scan.py had the column: the row has no such field
SCANNED = object()  # a figure as the scan gives it: blank beside a blank total_tokens, else the test's usual one


def commit(number: int) -> str:
    return f"{number:040x}"


def session(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def helper(description: str | None, brief: str | None, tokens: int | float | None) -> dict:
    """One helper of a session's scan row, as scripts/scan.py lists it: blank counts when it has no tokens of its
    own."""
    counts = [None] * 4 if tokens is None else [tokens, 0, 0, 0]
    return {"id": f"a{len(str(description)):04x}{len(str(brief)):012x}", "description": description,
            "brief_head": brief, **dict(zip(("input_tokens", "output_tokens", "cache_write_tokens",
                                             "cache_read_tokens"), counts)), "total_tokens": tokens}


class World:
    """A machine directory holding replay sets and what was replayed, judged and scanned for them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.state.mkdir()
        (root / "home").mkdir()
        # The report runs from a copy of scripts/, so a test sees anything a run writes beside it.
        self.source = root / "source"
        shutil.copytree(SCRIPTS, self.source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.sets: list[list[dict]] = []
        self.versions: list[dict] = []
        self.verdicts: list[dict] = []
        self.rows: list[dict] = []
        self.ids: dict[tuple[str, int, str], int] = {}  # each replay's own number, for its commit and session

    def draw(self, per_bucket: int = 10, labels: tuple[str, ...] = ("A",), count: int | None = None) -> list[dict]:
        """A new set of per_bucket tickets in each bucket, or of count tickets over the buckets in turn, from the
        projects labelled in turn, written at once, as the draw writes it: each project numbers its own tickets, so
        A-1 and B-1 can both be in a set."""
        start = sum(map(len, self.sets))
        drawn = [ticket for tickets in self.sets for ticket in tickets]
        tickets = []
        for at in range(3 * per_bucket if count is None else count):
            label, number = labels[at % len(labels)], start + at + 1  # number: unique over every set, for commits
            ticket = 1 + sum(earlier["label"] == label for earlier in drawn + tickets)
            tickets.append({"label": label, "ticket": ticket, "bucket": BUCKETS[at % 3], "size": 10, "title": TITLE,
                            "body": "## Acceptance criteria\n\n- [ ] The total.", "base_commit": commit(1),
                            "ready_commit": commit(1000 + number), "model": "claude-test-model", "pr": 500 + ticket,
                            "session": session(number), "log": f"logs/{session(number)}.jsonl",
                            "check_output": f"checks/{label}-{ticket}.txt"})
        self.sets.append(tickets)
        number = len(self.sets)
        (self.state / f"replay-set-{number}.json").write_text(json.dumps(
            {"set": number, "seed": 7, "drawn_at": "2026-11-26T10:00:00+00:00", "tickets": tickets,
             "set_aside": []}, indent=2) + "\n")
        known = {label: f"example-org/{label.lower()}-project" for tickets in self.sets for label in
                 {ticket["label"] for ticket in tickets}}
        (self.state / "project-labels.json").write_text(json.dumps({**known, "A": REPO}))
        return tickets

    def replay(self, ticket: dict, version: str = "direct", not_direct: bool = False) -> dict:
        key = (ticket["label"], ticket["ticket"], version)
        number = 5000 + self.ids.setdefault(key, len(self.ids) + 1)
        name = f"{ticket['label']}-{ticket['ticket']}-{version}"
        found = {"label": ticket["label"], "ticket": ticket["ticket"], "version": version, "commit": commit(number),
                 "repo": f"replays/{name}.git", "base_commit": ticket["base_commit"], "clone": f"replays/{name}",
                 "exit_status": 0, "session": session(number), "skills": [], "not_direct": not_direct}
        self.versions.append(found)
        return found

    def judge(self, ticket: dict, version: str, right: bool | None, at: str | None = None) -> None:
        if at is None:
            at = ticket["ready_commit"] if version == "generation-one" else next(
                line["commit"] for line in self.versions
                if (line["label"], line["ticket"], line["version"]) == (ticket["label"], ticket["ticket"], version))
        self.verdicts.append({"label": ticket["label"], "ticket": ticket["ticket"], "version": version, "commit": at,
                              "base_commit": ticket["base_commit"], "judged_at": "2026-11-26T11:00:00+00:00",
                              "check": {"passed": True, "reason": None, "output": "judged/x/check.txt"},
                              "review": {"passed": right, "reason": None},
                              "right_first_time": right})

    def scan(self, name: str, tokens: int | float | None, minutes: object = SCANNED, helpers: object = SCANNED,
             copied: object = 0) -> None:
        """A row as scan() in scripts/scan.py writes it. With a total, the token columns add up to it and the other
        figures are given. With a blank total, as for a log that is gone, every figure is blank. A blank minutes or
        helpers beside a total, a figure beside a blank total, or a copied of OLD (no such field) is a row a test
        builds on purpose."""
        blank = tokens is None
        row = {"session": name, "input_tokens": None if blank else tokens,
               **dict.fromkeys(("output_tokens", "cache_write_tokens", "cache_read_tokens"), None if blank else 0),
               "total_tokens": tokens, "copied_tokens": None if blank else copied,
               "active_minutes": (None if blank else 10.0) if minutes is SCANNED else minutes,
               "auto_compactions": None if blank else 0, "typed_compactions": None if blank else 0,
               "model": None if blank else "claude-test-model", "skills": None if blank else [],
               "helpers": (None if blank else []) if helpers is SCANNED else None if helpers is None else list(helpers)}
        if copied is OLD:
            del row["copied_tokens"]
        self.rows.append(row)

    def run(self, version: str, ticket: dict, right: bool | None, tokens: int | float | None = 100,
            minutes: object = SCANNED, helpers: object = SCANNED, copied: object = 0) -> None:
        """A version of a ticket replayed where it is not generation one's, judged and scanned."""
        name = ticket["session"] if version == "generation-one" else self.replay(ticket, version)["session"]
        self.judge(ticket, version, right)
        self.scan(name, tokens, minutes, helpers, copied)

    def baseline(self, first: int, second: int, *sizes: int) -> None:
        """Sets of the sizes given, one set of 30 when none is, with both versions judged on every ticket: generation
        one right on `first` tickets, the direct replays on `second`."""
        tickets = [ticket for size in sizes or (30,) for ticket in self.draw(count=size)]
        for at, ticket in enumerate(tickets):
            self.run("generation-one", ticket, at < first)
            self.run("direct", ticket, at < second)

    def save(self) -> None:
        for name, lines in (("versions", self.versions), ("verdicts", self.verdicts), ("scan-rows", self.rows)):
            (self.state / f"{name}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    def report(self, *args: str, save: bool = True, text: bool = True) -> subprocess.CompletedProcess:
        if save:
            self.save()
        env = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
        env.update({"HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(self.state)})
        return subprocess.run([sys.executable, str(self.source / "report.py"), *args], cwd=self.root, env=env,
                              text=text, capture_output=True)


def tree(folder: Path) -> dict[str, tuple]:
    """Every path under the folder with its kind, mode, modification time and bytes."""
    return {str(path.relative_to(folder)): (path.is_dir(), path.stat().st_mode, path.stat().st_mtime_ns,
                                            None if path.is_dir() else path.read_bytes())
            for path in sorted(folder.rglob("*"))}


# One helper of each of generation one's steps, with tokens of 10 times a power of two (10 to 640) so that every
# step's sum tells which helpers it took, then helpers sorted by the head of the brief, one sorted into no step, and
# one with no tokens of its own. The re-check and the fix also name a step later in their text.
EVERY_STEP = [
    helper("Re-check fix round 1", "This is a re-check after one fix round. Read the review skill.", 10),
    helper("Closing verification on the final head", "You are the closing verifier for ticket #12.", 20),
    helper("Fix round 2: the review findings", "# Fix round 2 for ticket #12", 40),
    helper("Standards review", "You are a Standards reviewer. Review one change, read-only.", 80),
    helper("Implement ticket #12", '# Implementing brief: ticket #12, "Fix the total and verify it"', 160),
    helper("Publish the PR body", "# Publish brief for ticket #12", 320),
    helper("Explore the scan's helpers", "Find where scan.py lists each helper.", 640),
    helper(None, "You are the closing verifier for ticket #12.", 1),
    helper("Ticket #12 worker", '# Implementing brief: ticket #12, "Print the total"', 2),
    helper("Tidy the notes", "Tidy the notes folder.", 4),
    helper("Fix round 3", "# Fix round 3 for ticket #12", None),
]
# The 26 texts of ticket #339, the reviews' probes of the sort: id, description, head of the brief, the step the
# helper took, and the step the sorter gives it (None: not sorted).
PROBES = [
    ("W1", "Follow-up review of the fix head", None, "re-check", "re-check"),
    ("W2", "Standards review", "Re-check the fix diff against accepted findings.", "re-check", "re-check"),
    ("W3", "Implement ticket: verify CSV headers", "Implement the parser.", "implement", "implement"),
    ("W4", "Ticket worker", '# Implementing brief: ticket #12, "Fix the total and verify it"', "implement",
     "implement"),
    ("R1", "Fix header parsing", "Implement the parser change for ticket #12.", "implement", "implement"),
    ("R2", "Follow-up check on required CI", "Poll the PR checks and mark the PR ready when green.", "publish",
     "publish"),
    ("R3", "Ticket worker", "Read the closing verification brief and run its checks on the final commit.",
     "closing verification", "closing verification"),
    ("R4", "Review the fix round 1 diff", "Confirm that each accepted finding is closed.", "re-check", "re-check"),
    ("R5", "Standards review", "Ticket #12: Re-check cached credentials. Review the implementation against the "
                               "coding standards.", "review", "review"),
    ("R6", "Standards review: follow-up on the fix head", "Confirm the accepted findings are closed.", "re-check",
     "re-check"),
    ("R7", "Standards review", "You are the Standards reviewer. Re-check the accepted findings on the fixed commit.",
     "re-check", "re-check"),
    ("R8", "Ticket #12: Verify CSV headers", "# Implementing brief. Implement CSV header validation.", "implement",
     "implement"),
    ("R9", "Standards review, round 2", None, "re-check", "re-check"),
    ("R10", "Apply the late fix", None, "fix", "fix"),
    ("R11", "Address the two discrepancies in the cached-token accounting the final reviewer identified", None,
     "fix", "fix"),
    ("Q4", "Ticket worker", "For ticket #12: run closing verification on the final commit.", "closing verification",
     None),
    ("Q5a", "Standards review", "Review the implementation against the coding standards. List follow-up work "
                                "separately.", "review", "review"),
    ("Q5b", "Standards review", "Review the implementation on this first pass. The coordinator will re-check any "
                                "fixes.", "review", "review"),
    ("Q5c", "Standards review of round 2 scheduling", "Review the tournament scheduler change against the coding "
                                                      "standards.", "review", None),
    ("Q5d", "Ticket worker", "Fix CSV header parsing in the importer and implement the normalization needed by the "
                             "review screen.", "implement", "implement"),
    ("Q6a", "Follow-up check", "Confirm that the accepted findings are closed on the fixed commit.", "re-check", None),
    ("Q6b", "Read the schema", "Summarize which columns are nullable. Return the source paths without editing any "
                               "files.", "explore", None),
    ("Q7a", "Verify CSV headers", "Implement CSV header validation.", "implement", None),
    ("Q7b", "Ticket #12: Parse config.json and verify headers", "Implement CSV header validation.", "implement",
     None),
    ("Q7c", "Apply the lint fixes", "Correct the two lint errors flagged by the reviewer on the previous commit.",
     "fix", None),
    ("Q1", "Ticket worker", "Compare with the first review. Your assignment is to re-check the accepted findings.",
     "re-check", "re-check"),
]


Copied = tuple[int | float, int | float, str | None, int]  # copied, total, share as printed or None, blank count


def shown(share: str | None) -> str:
    return "" if share is None else f", {share}"


def copied_tokens(copied: int | float, total: int | float, share: str | None, blank: int) -> str:
    """A version's line on its copied tokens; a share of None is one the report does not print."""
    return (f"  Copied tokens: {copied} of the {total} total tokens of the tickets with a copied count{shown(share)}. "
            f"Left out of the copied tokens: {blank} with a blank copied count.")


def sign_two_copied(first: Copied, second: Copied) -> str:
    """Warning sign 2's line on the copied tokens inside each side's sum: each side as (copied, total, share, blank),
    the share as copied_tokens takes it."""
    (first_copied, first_total, first_share, first_blank), (second_copied, second_total, second_share, second_blank) = (
        first, second)
    return (f"  Copied tokens in these sums: {first_copied} of the {first_total} total tokens of generation-one's "
            f"tickets with a copied count{shown(first_share)}, and {second_copied} of the {second_total} total tokens "
            f"of direct's tickets with a copied count{shown(second_share)}. Left out of the copied tokens: "
            f"{first_blank} of generation-one's tickets and {second_blank} of direct's, with a blank copied count.")


def no_helpers(spent: int, copied: str, unjudged: int = 0) -> list[str]:
    """Warning sign 2's lines between its first line and its verdicts, for sessions with no helpers."""
    return [f"  Left out of both sides: {unjudged} without both versions judged, 0 with a blank token count.",
            "  generation-one's helpers by step: re-check 0, closing verification 0, fix 0, review 0, implement 0, "
            "publish 0, explore 0. 0 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 0 tokens, 0.0% of generation-one's.",
            f"  Not sorted into a step: {spent} tokens, 100.0% of generation-one's: 0 in helpers that name no step, "
            f"{spent} the sessions' own, in no helper.",
            "  A helper resumed for a fix round counts under the step it started as.", copied]


# The rule over the sets together, as both the not-decided line and --help state it.
SETS_TOGETHER = ("the sign appears at a difference of at least 2/15 of the tickets judged, rounded up, and does not "
                 "appear below that.")
NOT_DECIDED = ("Not decided: a second set is needed, the rest of the pool: every remaining pool ticket whose check "
               f"passes, with no limit per bucket. Over both sets together, {SETS_TOGETHER}")


def section(lines: list[str], sign: int) -> list[str]:
    """The report's lines on one warning sign, up to the blank line after them."""
    start = next(at for at, line in enumerate(lines) if line.startswith(f"Warning sign {sign}"))
    return lines[start:next((at for at in range(start, len(lines)) if not lines[at]), len(lines))]


class TestReport(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name).resolve())

    def lines(self, *args: str) -> list[str]:
        result = self.world.report(*args)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result.stdout.splitlines()

    def error(self, message: str) -> None:
        result = self.world.report(save=False)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, "", f"report: {message}\n"))

    def sign(self, first: int, second: int, *sizes: int) -> list[str]:
        self.world.baseline(first, second, *sizes)
        return section(self.lines(), 1)

    def test_it_prints_each_version_per_bucket_and_over_the_set(self) -> None:
        tickets = self.world.draw(per_bucket=2)  # buckets in turn: 0-50, 51-300, 301-1500, 0-50, 51-300, 301-1500
        for at, ticket in enumerate(tickets):
            self.world.run("generation-one", ticket, at != 1, tokens=1000 * (at + 1), minutes=10.0 * (at + 1))
            self.world.run("direct", ticket, at in (0, 2), tokens=100 * (at + 1), minutes=1.25 * (at + 1))
        self.assertEqual(self.lines(), [
            "Replay set 1: 6 tickets, of project A.",
            "",
            "generation-one",
            "  0-50: 2 judged, 2 of 2 right first time, median total tokens 2500, median active minutes 25.",
            "  51-300: 2 judged, 1 of 2 right first time, median total tokens 3500, median active minutes 35.",
            "  301-1500: 2 judged, 2 of 2 right first time, median total tokens 4500, median active minutes 45.",
            "  All: 6 judged, 5 of 6 right first time, median total tokens 3500, median active minutes 35.",
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank.",
            copied_tokens(0, 21000, "0.0%", 0),
            "",
            "direct",
            "  0-50: 2 judged, 1 of 2 right first time, median total tokens 250, median active minutes 3.125.",
            "  51-300: 2 judged, 0 of 2 right first time, median total tokens 350, median active minutes 4.375.",
            "  301-1500: 2 judged, 1 of 2 right first time, median total tokens 450, median active minutes 5.625.",
            "  All: 6 judged, 2 of 6 right first time, median total tokens 350, median active minutes 4.375.",
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank.",
            copied_tokens(0, 2100, "0.0%", 0),
            "",
            "Warning sign 1: generation-one was right first time on 5 of 6 tickets, direct on 2 of 6, a difference "
            "of 3.",
            "The sign appears.",
            "",
            "Warning sign 2: on 6 of 6 tickets, generation-one spent 21000 tokens and direct 2100, an extra cost of "
            "18900.",
            *no_helpers(21000, sign_two_copied((0, 21000, "0.0%", 0), (0, 2100, "0.0%", 0))),
            "Without the spend not sorted, the cut is 0 tokens against half the extra cost, 9450. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 21000 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def two(self, helpers: list[dict], spent: int, direct: int) -> list[str]:
        """Warning sign 2 on a set of 30 tickets with both versions judged on each: generation one spends `spent`
        tokens on each ticket, with these helpers, and the direct replay `direct`."""
        for ticket in self.world.draw():
            self.world.run("generation-one", ticket, True, tokens=spent, helpers=helpers)
            self.world.run("direct", ticket, True, tokens=direct)
        return section(self.lines(), 2)

    def test_sign_two_sorts_each_helper_into_its_step(self) -> None:
        self.assertEqual(self.two(EVERY_STEP, 2277, 1000), [
            "Warning sign 2: on 30 of 30 tickets, generation-one spent 68310 tokens and direct 30000, an extra cost of "
            "38310.",
            "  Left out of both sides: 0 without both versions judged, 0 with a blank token count.",
            "  generation-one's helpers by step: re-check 300, closing verification 630, fix 1200, review 2400, "
            "implement 4860, publish 9600, explore 19200. 30 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 2130 tokens, 3.1% of generation-one's.",
            "  Not sorted into a step: 30120 tokens, 44.1% of generation-one's: 120 in helpers that name no step, "
            "30000 the sessions' own, in no helper.",
            "  A helper resumed for a fix round counts under the step it started as.",
            sign_two_copied((0, 68310, "0.0%", 0), (0, 30000, "0.0%", 0)),
            "Without the spend not sorted, the cut is 2130 tokens against half the extra cost, 19155. The sign does "
            "not appear.",
            "With it counted as cut, the cut is 32250 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def test_a_helper_is_sorted_by_its_description_then_by_its_brief(self) -> None:
        # The shapes fix round 1 closed, sorted by the rules of step() and named(). Each sits beside a helper whose step
        # its words name, but for "Re-verify the fixed head", which has none.
        lines = self.two([
            helper("Follow-up review of the fix head", "Confirm the accepted findings are closed.", 1),
            helper("Standards review of the change", "You are a Standards reviewer.", 2),
            helper("Standards review", "Re-check the fix diff against the accepted findings.", 4),
            helper("Standards review", "Review the change against the standards.", 8),
            helper("Implement ticket #12: verify CSV headers", None, 16),
            helper("Ticket worker", '# Implementing brief: ticket #12, "Fix the total and verify it"', 32),
            helper("Ticket worker", "# Publish brief. The closing verifier has passed; fix nothing.", 64),
            helper("Closing verification of ticket #12: Implement the parser", None, 128),
            helper("Ticket worker", '# Fix round 1 brief: ticket #12, "Publish the total"', 256),
            helper("Ticket worker", "# Closing verification brief. The publish brief follows.", 512),
            helper("Re-verify the fixed head", None, 1024)], 3000, 1000)
        self.assertEqual(lines[2], "  generation-one's helpers by step: re-check 30870, closing verification 19200, "
                                   "fix 7680, review 300, implement 1440, publish 1920, explore 0. 0 helpers have no "
                                   "tokens of their own.")

    def alone(self, description: str | None, brief: str | None) -> list[str]:
        """Warning sign 2's lines on helpers by step, the cut and the spend not sorted, in a fresh machine directory
        where one helper of 800 tokens is the only one in each of 30 sessions of 1000."""
        self.setUp()
        return self.two([helper(description, brief, 800)], 1000, 200)[2:5]

    @staticmethod
    def sorted_alone(its_step: str | None) -> list[str]:
        """alone()'s lines when the sorter puts the helper in its_step, or leaves it not sorted (None)."""
        return ["  generation-one's helpers by step: " + ", ".join(
                    f"{name} {24000 if name == its_step else 0}" for name in (
                        "re-check", "closing verification", "fix", "review", "implement", "publish", "explore"))
                + ". 0 helpers have no tokens of their own.",
                f"  Not sorted into a step: {30000 if its_step is None else 6000} tokens, "
                f"{100 if its_step is None else 20}.0% of generation-one's: {24000 if its_step is None else 0} in "
                f"helpers that name no step, 6000 the sessions' own, in no helper."]

    def test_no_probe_text_is_sorted_across_the_cut_and_each_lands_where_it_is_pinned(self) -> None:
        for at, description, brief, its_step, sorted_as in PROBES:
            with self.subTest(at):
                by_step, cut, not_sorted = self.alone(description, brief)
                cut = cut.split(":")[0].removeprefix("  The cut, ").replace(" and ", ", ").split(", ")
                given = next((part.rsplit(" ", 1)[0] for part in by_step.split("by step: ")[1].split(". ")[0]
                              .split(", ") if not part.endswith(" 0")), None)
                self.assertTrue(given is None or (given in cut) == (its_step in cut),
                                f"{at}: a helper of {its_step} sorted as {given}, across the cut")
                self.assertEqual([by_step, not_sorted], self.sorted_alone(sorted_as), at)

    def test_each_contrast_case_lands_on_its_own_step(self) -> None:
        # Each shares its words with one of the probe texts R1 to R11 in PROBES but is a helper of another step or,
        # beside R10 "Apply the late fix", one not sorted (its_step None).
        for description, brief, its_step in [
            ("Review the fix head", "Confirm the accepted findings are closed.", "re-check"),
            ("Follow-up review on required CI", "Confirm the accepted findings are closed.", "re-check"),
            ("Ticket worker", "Read the issue and find where the parser lives.", "explore"),
            ("Fix round 1 worker", "Address each accepted review finding.", "fix"),
            ("Standards review", "Ticket #12: Cache credentials. Re-check the accepted findings.", "re-check"),
            ("Standards review: the header fix", "Review the diff against the standards.", "review"),
            ("Standards review", "You are the Standards reviewer. Review the implementation on the final commit.",
             "review"),
            ("Ticket #12: Verify CSV headers", "Run the closing verification on the final commit.",
             "closing verification"),
            ("Fix round 2", None, "fix"),
            ("Apply the lint fixes", None, None),
            ("Final review: address the cached-token accounting", None, "review"),
        ]:
            with self.subTest(description=description, brief=brief):
                lines = self.alone(description, brief)
                self.assertEqual([lines[0], lines[2]], self.sorted_alone(its_step))

    def test_a_text_naming_both_sides_of_the_cut_says_nothing_and_texts_that_disagree_sort_nothing(self) -> None:
        # Two helpers for each rule of step(), one it sorts and one it leaves not sorted.
        lines = self.two([
            helper("Verify the build", None, 1),  # the description names both sides, and no brief: not sorted
            helper("Verify the build", "Implement the importer.", 2),  # the brief alone is read: implement
            helper("Survey the open issues", "Publish the PR body.", 4),  # one side: the description, explore
            helper("Publish the PR body", "Run the closing verification.", 8),  # two sides: not sorted
            helper(None, "# Publish brief. Verify the CI first.", 16),  # the heading alone is read: publish
            helper(None, "# Notes. Publish the PR body, then verify it.", 32),  # the heading names none: not sorted
            helper("Standards review", "Re-verify the closed findings.", 64),  # a review and a re-check: re-check
            helper("Implement the parser", "Re-verify the closed findings.", 128),  # two sides: not sorted
        ], 1000, 900)
        self.assertEqual(lines[2:5], [
            "  generation-one's helpers by step: re-check 1920, closing verification 0, fix 0, review 0, implement 60, "
            "publish 480, explore 120. 0 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 1920 tokens, 6.4% of generation-one's.",
            "  Not sorted into a step: 27420 tokens, 91.4% of generation-one's: 5070 in helpers that name no step, "
            "22350 the sessions' own, in no helper."])

    def test_a_text_that_names_a_re_check_and_a_review_names_a_re_check(self) -> None:
        # A re-check is a review of a fix, so a brief that names one and says "review" later names one role.
        lines = self.two([
            helper("Review the parser", "Re-check the accepted findings. The review covers only the fixed diff.", 1),
            helper("Standards review", "You are a re-check reviewer. Review one fix commit range, read-only, and "
                                       "write one report file.", 2),
            helper("Spec review", "Re-check: confirm each accepted finding of the Spec review is closed.", 4),
            helper("Ticket worker", "Re-check the accepted findings of the first review on the fixed commit.", 8),
        ], 1000, 900)
        self.assertEqual(lines[2:5], [
            "  generation-one's helpers by step: re-check 450, closing verification 0, fix 0, review 0, implement 0, "
            "publish 0, explore 0. 0 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 450 tokens, 1.5% of generation-one's.",
            "  Not sorted into a step: 29550 tokens, 98.5% of generation-one's: 0 in helpers that name no step, "
            "29550 the sessions' own, in no helper."])

    def test_a_fix_names_its_finding_and_a_skill_name_names_no_step(self) -> None:
        lines = self.two([helper("Fix the Standards finding on the total", None, 1),
                          helper("Address the spec review's one comment", None, 2),
                          helper("implement-ticket owner for #12", "Use the implement-ticket skill on #12.", 4),
                          helper("Run the backlog", "Run plugin:implement-backlog, then orchestrator-mode.", 8),
                          helper("Implement ticket #12 with implement-ticket", None, 16),
                          helper("Fix the total", "# Ticket #12: Fix the total. Review it once it is done.", 32),
                          helper("Fix the total. Then review it", None, 64)], 1000, 900)
        self.assertEqual(lines[2], "  generation-one's helpers by step: re-check 0, closing verification 0, fix 90, "
                                   "review 2880, implement 480, publish 0, explore 0. 0 helpers have no tokens of "
                                   "their own.")
        self.assertEqual(lines[4], "  Not sorted into a step: 26550 tokens, 88.5% of generation-one's: 360 in "
                                   "helpers that name no step, 26190 the sessions' own, in no helper.")

    def test_sign_two_appears_when_the_cut_is_more_than_half_the_extra_cost(self) -> None:
        # 30 tickets: an extra cost of 6000 tokens, half of it 3000.
        for verification, verdict in ((101, "The sign appears."), (100, "The sign does not appear."),
                                      (99, "The sign does not appear.")):
            with self.subTest(cut=30 * verification):
                self.setUp()
                lines = self.two([helper("Closing verification", None, verification),
                                  helper("Implement", None, 1000 - verification)], 1000, 800)
                self.assertEqual(lines[0], "Warning sign 2: on 30 of 30 tickets, generation-one spent 30000 tokens "
                                           "and direct 24000, an extra cost of 6000.")
                self.assertEqual(lines[-2:], [
                    f"Without the spend not sorted, the cut is {30 * verification} tokens against half the extra "
                    f"cost, 3000. {verdict}",
                    f"With it counted as cut, the cut is {30 * verification} tokens. {verdict}"])

    def test_sign_two_says_when_the_spend_not_sorted_decides_it(self) -> None:
        lines = self.two([helper("Fix round 1", None, 90), helper("Tidy the notes", None, 20),
                          helper("Implement", None, 890)], 1000, 800)
        self.assertEqual(lines[-3:], [
            "Without the spend not sorted, the cut is 2700 tokens against half the extra cost, 3000. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 3300 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def test_the_sessions_own_spend_is_spend_not_sorted(self) -> None:
        lines = self.two([helper("Fix round 1", None, 90), helper("Implement", None, 10)], 1000, 800)
        self.assertEqual(lines[4:], [
            "  Not sorted into a step: 27000 tokens, 90.0% of generation-one's: 0 in helpers that name no step, 27000 "
            "the sessions' own, in no helper.",
            "  A helper resumed for a fix round counts under the step it started as.",
            sign_two_copied((0, 30000, "0.0%", 0), (0, 24000, "0.0%", 0)),
            "Without the spend not sorted, the cut is 2700 tokens against half the extra cost, 3000. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 29700 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def test_sign_two_gives_no_verdict_with_no_extra_cost(self) -> None:
        for direct, extra in ((1000, 0), (1001, -30)):
            with self.subTest(extra=extra):
                self.setUp()
                lines = self.two([helper("Re-check", None, 400)], 1000, direct)
                self.assertEqual(lines[0], f"Warning sign 2: on 30 of 30 tickets, generation-one spent 30000 tokens "
                                           f"and direct {30 * direct}, an extra cost of {extra}.")
                self.assertEqual(lines[-2:], [
                    sign_two_copied((0, 30000, "0.0%", 0), (0, 30 * direct, "0.0%", 0)),
                    "No verdict: generation-one cost no more than direct, so there is no extra cost to cut."])

    def test_a_ticket_left_out_of_the_token_figures_is_left_out_of_both_sides(self) -> None:
        cut = [helper("Closing verification", None, 100)]
        for at, ticket in enumerate(self.world.draw()):  # the other side of each ticket left out spends 99999
            self.world.run("generation-one", ticket, True, tokens=None if at == 1 else 99999 if at == 0 else 1000,
                           helpers=None if at in (1, 2) else cut)  # at 2: a total and no list of helpers
            self.world.run("direct", ticket, True, tokens=None if at == 0 else 99999 if at == 1 else 800)
        self.assertEqual(section(self.lines(), 2), [
            "Warning sign 2: on 28 of 30 tickets, generation-one spent 28000 tokens and direct 22400, an extra cost of "
            "5600.",
            "  Left out of both sides: 0 without both versions judged, 2 with a blank token count.",
            "  generation-one's helpers by step: re-check 0, closing verification 2700, fix 0, review 0, implement 0, "
            "publish 0, explore 0. 0 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 2700 tokens, 9.6% of generation-one's.",
            "  Not sorted into a step: 25300 tokens, 90.4% of generation-one's: 0 in helpers that name no step, 25300 "
            "the sessions' own, in no helper.",
            "  A helper resumed for a fix round counts under the step it started as.",
            sign_two_copied((0, 28000, "0.0%", 0), (0, 22400, "0.0%", 0)),
            "Without the spend not sorted, the cut is 2700 tokens against half the extra cost, 2800. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 28000 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def test_sign_two_gives_the_copied_tokens_inside_each_side(self) -> None:
        for at, ticket in enumerate(self.world.draw()):
            # By draw position: at 0, generation one's row is from before the column. At 1 and 3, direct's copied
            # count is null. At 2, generation one's blank total leaves the ticket out of both sides of sign 2, and
            # direct's 70 copied with it, which direct's own block still counts.
            self.world.run("generation-one", ticket, True, tokens=None if at == 2 else 1000,
                           copied=OLD if at == 0 else 100)
            self.world.run("direct", ticket, True, tokens=800, copied=None if at in (1, 3) else 70 if at == 2 else 40)
        lines = self.lines()
        self.assertEqual([line for line in lines if line.startswith("  Copied tokens: ")], [
            copied_tokens(2800, 28000, "10.0%", 1),  # generation-one: 28 tickets say, of the 29 with a total
            copied_tokens(1150, 22400, "5.1%", 2)])  # direct: 27 times 40 and the 70, of the 28 of 30 that say
        self.assertEqual(section(lines, 2), [
            "Warning sign 2: on 29 of 30 tickets, generation-one spent 29000 tokens and direct 23200, an extra cost of "
            "5800.",
            "  Left out of both sides: 0 without both versions judged, 1 with a blank token count.",
            *no_helpers(29000, sign_two_copied((2800, 28000, "10.0%", 1), (1080, 21600, "5.0%", 2)))[1:],
            "Without the spend not sorted, the cut is 0 tokens against half the extra cost, 2900. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 29000 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def test_sign_two_prints_no_share_of_no_tokens(self) -> None:
        # Generation one: at draw position 0 a row of 0 tokens, 0 copied; every other row from before the column.
        # Direct: every row from before the column.
        for at, ticket in enumerate(self.world.draw()):
            self.world.run("generation-one", ticket, True, tokens=0 if at == 0 else 1000, copied=0 if at == 0 else OLD)
            self.world.run("direct", ticket, True, tokens=800, copied=OLD)
        self.assertEqual(section(self.lines(), 2)[6],
                         sign_two_copied((0, 0, None, 29), (0, 0, None, 30)))

    def test_sign_two_prints_a_share_for_one_side_without_the_other(self) -> None:
        # One side's rows are all from before the column, so it has no share; the other's say 40 copied of 800.
        for old_side in ("generation-one", "direct"):
            with self.subTest(old_side=old_side):
                self.setUp()
                for ticket in self.world.draw():
                    for version in ("generation-one", "direct"):
                        self.world.run(version, ticket, True, tokens=800, copied=OLD if version == old_side else 40)
                said, old = (1200, 24000, "5.0%", 0), (0, 0, None, 30)
                self.assertEqual(section(self.lines(), 2)[6], sign_two_copied(
                    *((old, said) if old_side == "generation-one" else (said, old))))

    def verdict_lines(self, copied: int, cut: int, direct_copied: int) -> tuple[list[str], list[str]]:
        """Warning sign 2's lines from its copied line on, with the column and without it, on 30 tickets where
        generation one spends 100 tokens with `cut` in a closing verification and direct spends 50."""
        for ticket in self.world.draw():
            self.world.run("generation-one", ticket, True, tokens=100, copied=copied,
                           helpers=[helper("Closing verification", None, cut)])
            self.world.run("direct", ticket, True, tokens=50, copied=direct_copied)
        with_column = section(self.lines(), 2)[6:]
        for row in self.world.rows:
            row.pop("copied_tokens")
        return with_column, section(self.lines(), 2)[6:]

    def test_copied_tokens_change_no_verdict_of_sign_two(self) -> None:
        # Each fixture sits where taking the copied tokens out of a figure the verdict is built from would change a
        # verdict line: out of the extra cost or generation one's sum (the first), or out of the cut or direct's
        # sum (the second).
        for (copied, cut, direct_copied), verdicts in [
            ((60, 20, 0), [
                "Without the spend not sorted, the cut is 600 tokens against half the extra cost, 750. The sign does "
                "not appear.",
                "With it counted as cut, the cut is 3000 tokens. The sign appears.",
                "The two verdicts differ: the spend not sorted decides the sign."]),
            ((10, 30, 10), [
                "Without the spend not sorted, the cut is 900 tokens against half the extra cost, 750. The sign "
                "appears.",
                "With it counted as cut, the cut is 3000 tokens. The sign appears."]),
        ]:
            with self.subTest(copied=copied, cut=cut, direct_copied=direct_copied):
                self.setUp()
                with_column, without = self.verdict_lines(copied, cut, direct_copied)
                self.assertEqual(with_column, [sign_two_copied((30 * copied, 3000, f"{copied / 100:.1%}", 0),
                                                               (30 * direct_copied, 1500, f"{direct_copied / 50:.1%}",
                                                                0)), *verdicts])
                self.assertEqual(without, [sign_two_copied((0, 0, None, 30), (0, 0, None, 30)), *verdicts])

    def test_the_column_changes_no_other_line_and_no_verdict(self) -> None:
        # Copied tokens on both sides, a row without the column, and helpers of every step.
        for at, ticket in enumerate(self.world.draw()):
            self.world.run("generation-one", ticket, at % 2 == 0, tokens=2277 + at, minutes=1.5 + at,
                           helpers=EVERY_STEP, copied=OLD if at == 3 else 300 + at)
            self.world.run("direct", ticket, at % 3 == 0, tokens=1000 + at, minutes=0.5 + at, copied=40.5 * (at % 4))
        with_column = self.world.report(text=False)
        for row in self.world.rows:
            row.pop("copied_tokens", None)
        without = self.world.report(text=False)
        self.assertEqual((with_column.returncode, with_column.stderr, without.returncode, without.stderr),
                         (0, b"", 0, b""))
        blank = copied_tokens(0, 0, None, 30)
        self.assertEqual([line for line in without.stdout.decode().split("\n") if line.startswith("  Copied tokens")],
                         [blank, blank, sign_two_copied((0, 0, None, 30), (0, 0, None, 30))])
        self.assertEqual(*([line for line in result.stdout.split(b"\n") if not line.startswith(b"  Copied tokens")]
                           for result in (with_column, without)))

    def test_sign_two_gives_no_verdict_when_no_ticket_is_left(self) -> None:
        for ticket in self.world.draw():
            self.world.run("generation-one", ticket, True, tokens=1000)
            self.world.run("direct", ticket, True, tokens=None)
        self.assertEqual(section(self.lines(), 2), [
            "Warning sign 2: no verdict. No ticket has both versions judged and both token counts.",
            "  Left out of both sides: 0 without both versions judged, 30 with a blank token count."])

    def test_a_count_out_of_fewer_than_20_is_never_a_rate(self) -> None:
        self.world.baseline(17, 14)
        lines = self.lines()
        self.assertIn("  0-50: 10 judged, 6 of 10 right first time, median total tokens 100, median active "
                      "minutes 10.", lines)
        self.assertIn("  All: 30 judged, 17 of 30 (57%) right first time, median total tokens 100, "
                      "median active minutes 10.", lines)

    def test_a_rate_starts_at_20_tickets(self) -> None:
        tickets = self.world.draw(per_bucket=7)[:20]  # 20 tickets judged of 21, then 19 of 21
        for ticket in tickets:
            self.world.run("generation-one", ticket, True)
        for ticket in tickets[:19]:
            self.world.run("direct", ticket, True)
        lines = self.lines()
        self.assertIn("  All: 20 judged, 20 of 20 (100%) right first time, median total tokens 100, "
                      "median active minutes 10.", lines)
        self.assertIn("  All: 19 judged, 19 of 19 right first time, median total tokens 100, "
                      "median active minutes 10.", lines)

    def test_a_blank_token_count_is_left_out_of_the_token_figures_and_counted(self) -> None:
        tickets = self.world.draw(per_bucket=1)
        self.world.run("generation-one", tickets[0], True, tokens=None, minutes=None)
        self.world.run("generation-one", tickets[1], True, tokens=300, minutes=None)
        self.world.judge(tickets[2], "generation-one", False)  # judged, but its session has no scan row
        lines = self.lines()
        self.assertEqual(lines[2:9], [
            "generation-one",
            "  0-50: 1 judged, 1 of 1 right first time, median total tokens none, median active minutes none.",
            "  51-300: 1 judged, 1 of 1 right first time, median total tokens 300, median active minutes none.",
            "  301-1500: 1 judged, 0 of 1 right first time, median total tokens none, median active minutes "
            "none.",
            "  All: 3 judged, 2 of 3 right first time, median total tokens 300, median active minutes none.",
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 2 with a blank token count. Left out of the active minutes: 3 blank."])

    def test_a_replay_not_direct_and_a_version_with_no_verdict_are_left_out_of_every_figure(self) -> None:
        tickets = self.world.draw(per_bucket=2)
        self.world.run("direct", tickets[0], True, tokens=100)
        marked = self.world.replay(tickets[1], not_direct=True)  # judged and scanned, but not direct
        self.world.judge(tickets[1], "direct", True)
        self.world.scan(marked["session"], 900, 90.0)
        self.world.replay(tickets[2])  # replayed, never judged
        self.world.scan(self.world.versions[-1]["session"], 900, 90.0)
        self.world.run("direct", tickets[3], None, tokens=900)  # judged with no verdict
        self.world.run("direct", tickets[4], False, tokens=300)
        lines = self.lines()  # tickets[5] has no replay at all
        start = lines.index("direct")
        self.assertEqual(lines[start + 4:start + 7], [
            "  All: 2 judged, 1 of 2 right first time, median total tokens 200, median active minutes 10.",
            "  Left out of every figure: 1 not direct, 3 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank."])

    def test_a_verdict_on_another_commit_than_the_one_recorded_is_left_out_of_every_figure(self) -> None:
        tickets = self.world.draw(per_bucket=1)  # tickets[2] has neither version judged
        self.world.judge(tickets[0], "generation-one", True, at=commit(77))  # not the ready commit
        self.world.run("generation-one", tickets[1], True)
        self.world.replay(tickets[0])
        self.world.judge(tickets[0], "direct", True, at=commit(78))  # not the replay's commit
        # The replay script records every direct replay, so one with no record may yet be marked not direct.
        self.world.judge(tickets[1], "direct", True, at=commit(79))
        lines = self.lines()
        for version, judged, tokens, minutes in (("generation-one", 1, 100, 10), ("direct", 0, "none", "none")):
            start = lines.index(version)
            self.assertEqual(lines[start + 4:start + 7], [
                f"  All: {judged} judged, {judged} of {judged} right first time, median total tokens {tokens}, "
                f"median active minutes {minutes}.",
                f"  Left out of every figure: 0 not direct, 1 with no verdict, {2 - judged} judged at a commit the "
                "version does not record.",
                "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 "
                "blank."])

    def test_a_version_judged_with_no_replay_record_counts_with_blank_figures(self) -> None:
        tickets = self.world.draw(per_bucket=1)
        for at, ticket in enumerate(tickets):  # judged at a commit the judge was given, with no versions.jsonl line
            self.world.judge(ticket, "squad", at != 1, at=commit(70 + at))
        lines = self.lines()
        start = lines.index("squad")
        self.assertEqual(lines[start + 4:start + 7], [
            "  All: 3 judged, 2 of 3 right first time, median total tokens none, median active minutes none.",
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 3 with a blank token count. Left out of the active minutes: 3 blank."])

    def test_the_medians_keep_their_fractions(self) -> None:
        tickets = self.world.draw(per_bucket=2)  # tickets 0 and 3 are both in 0-50
        self.world.run("generation-one", tickets[0], True, tokens=100, minutes=1.01)
        self.world.run("generation-one", tickets[3], False, tokens=101, minutes=1.02)
        lines = self.lines()
        self.assertEqual(lines[3], "  0-50: 2 judged, 1 of 2 right first time, median total tokens 100.5, median "
                                   "active minutes 1.015.")
        self.assertEqual(lines[6], "  All: 2 judged, 1 of 2 right first time, median total tokens 100.5, median "
                                   "active minutes 1.015.")

    def copied_line(self, *rows: tuple[int | float | None, object]) -> str:
        """generation-one's copied-tokens line, for a set of one ticket per row of (total_tokens, copied_tokens)."""
        tickets = self.world.draw(per_bucket=(len(rows) + 2) // 3)
        for ticket, (tokens, copied) in zip(tickets, rows):
            self.world.run("generation-one", ticket, True, tokens=tokens, copied=copied)
        lines = self.lines()
        return lines[lines.index("direct") - 2]

    def test_each_version_gives_the_copied_tokens_of_the_tickets_whose_row_says(self) -> None:
        self.assertEqual(self.copied_line((1000, 0), (2000, 500), (3000, OLD)), copied_tokens(500, 3000, "16.7%", 1))

    def test_the_copied_tokens_line_for_each_shape_of_rows(self) -> None:
        for rows, figures in [
            (((1000, 0), (2000, 0), (3000, 0)), (0, 6000, "0.0%", 0)),  # every row says 0
            (((1000, 1000),), (1000, 1000, "100.0%", 0)),  # every token copied
            (((100.5, 0.25), (200, 50.5)), (50.75, 300.5, "16.9%", 0)),  # figures with fractions
            (((1000, None), (500, 100)), (100, 500, "20.0%", 1)),  # a null beside a total
            (((1000, OLD), (2000, None)), (0, 0, None, 2)),  # no row says: no share
            (((0, 0),), (0, 0, None, 0)),  # a total of 0: no share
            (((None, None),), (0, 0, None, 0)),  # no ticket in the token figures
        ]:
            with self.subTest(rows=rows):
                self.setUp()
                self.assertEqual(self.copied_line(*rows), copied_tokens(*figures))

    def test_projects_appear_as_labels_only(self) -> None:
        for labels in (("A", "AB"), ("C",)):  # A-1 and AB-1 both, replayed as direct
            for at, ticket in enumerate(self.world.draw(labels=labels)):
                self.world.run("generation-one", ticket, at % 2 == 0, tokens=100 + at, minutes=1.0 + at)
                self.world.run("direct", ticket, at % 3 == 0, tokens=50 + at, minutes=0.5 + at)
        tail = [
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank."]
        self.assertEqual(self.lines(), [  # the whole report: no line beyond these may name or count a project
            "Replay sets 1 and 2: 60 tickets, of projects A, C and AB.",
            "",
            "generation-one",
            "  0-50: 20 judged, 10 of 20 (50%) right first time, median total tokens 113.5, median active minutes "
            "14.5.",
            "  51-300: 20 judged, 10 of 20 (50%) right first time, median total tokens 114.5, median active minutes "
            "15.5.",
            "  301-1500: 20 judged, 10 of 20 (50%) right first time, median total tokens 115.5, median active "
            "minutes 16.5.",
            "  All: 60 judged, 30 of 60 (50%) right first time, median total tokens 114.5, median active minutes "
            "15.5.",
            *tail,
            copied_tokens(0, 6870, "0.0%", 0),
            "",
            "direct",
            "  0-50: 20 judged, 20 of 20 (100%) right first time, median total tokens 63.5, median active minutes "
            "14.",
            "  51-300: 20 judged, 0 of 20 (0%) right first time, median total tokens 64.5, median active minutes 15.",
            "  301-1500: 20 judged, 0 of 20 (0%) right first time, median total tokens 65.5, median active minutes "
            "16.",
            "  All: 60 judged, 20 of 60 (33%) right first time, median total tokens 64.5, median active minutes 15.",
            *tail,
            copied_tokens(0, 3870, "0.0%", 0),
            "",
            "Warning sign 1: generation-one was right first time on 30 of 60 (50%) tickets, direct on 20 of 60 "
            "(33%), a difference of 10.",
            "The sign appears.",
            "",
            "Warning sign 2: on 60 of 60 tickets, generation-one spent 6870 tokens and direct 3870, an extra cost of "
            "3000.",
            *no_helpers(6870, sign_two_copied((0, 6870, "0.0%", 0), (0, 3870, "0.0%", 0))),
            "Without the spend not sorted, the cut is 0 tokens against half the extra cost, 1500. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 6870 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def test_a_third_version_is_printed_beside_the_other_two(self) -> None:
        tickets = self.world.draw(per_bucket=1)
        for ticket in tickets:
            self.world.run("generation-one", ticket, True)
            self.world.run("direct", ticket, False)
            self.world.run("squad", ticket, ticket is tickets[0], tokens=40, minutes=4.0,
                           copied=OLD if ticket is tickets[1] else 8)
        lines = self.lines()
        self.assertEqual([line for line in lines if line and not line.startswith(" ")][1:4],
                         ["generation-one", "direct", "squad"])
        start = lines.index("squad")
        self.assertEqual(lines[start + 4], "  All: 3 judged, 1 of 3 right first time, median total tokens 40, "
                                           "median active minutes 4.")
        self.assertEqual(lines[start + 7], copied_tokens(16, 80, "20.0%", 1))

    def test_on_30_tickets_5_or_more_the_sign_appears(self) -> None:
        self.assertEqual(self.sign(20, 15), [
            "Warning sign 1: generation-one was right first time on 20 of 30 (67%) tickets, direct on 15 of 30 (50%), "
            "a difference of 5.",
            "The sign appears."])

    def test_on_30_tickets_4_or_3_a_second_set_is_needed(self) -> None:
        for first, second in ((20, 16), (20, 17)):
            with self.subTest(difference=first - second):
                self.setUp()
                self.assertEqual(self.sign(first, second), [
                    f"Warning sign 1: generation-one was right first time on {first} of 30 ({first / 30:.0%}) "
                    f"tickets, direct on {second} of 30 ({second / 30:.0%}), a difference of {first - second}.",
                    NOT_DECIDED])

    def test_on_30_tickets_2_or_fewer_the_sign_does_not_appear(self) -> None:
        for first, second in ((20, 18), (15, 20)):
            with self.subTest(difference=first - second):
                self.setUp()
                self.assertEqual(self.sign(first, second), [
                    f"Warning sign 1: generation-one was right first time on {first} of 30 ({first / 30:.0%}) "
                    f"tickets, direct on {second} of 30 ({second / 30:.0%}), a difference of {first - second}.",
                    "The sign does not appear."])

    def test_on_60_tickets_8_or_more_the_sign_appears_and_7_or_fewer_it_does_not(self) -> None:
        for second, verdict in ((32, "The sign appears."), (33, "The sign does not appear.")):
            with self.subTest(difference=40 - second):
                self.setUp()
                lines = self.sign(40, second, 30, 30)
                self.assertEqual(lines[1], verdict)
                self.assertEqual(self.world.report().stdout.splitlines()[0],
                                 "Replay sets 1 and 2: 60 tickets, of project A.")

    def test_on_one_set_of_14_tickets_3_or_more_appears_2_is_not_decided_and_1_or_fewer_does_not(self) -> None:
        for second, verdict in ((7, "The sign appears."), (8, NOT_DECIDED), (9, "The sign does not appear.")):
            with self.subTest(difference=10 - second):
                self.setUp()
                self.assertEqual(self.sign(10, second, 14), [
                    f"Warning sign 1: generation-one was right first time on 10 of 14 tickets, direct on {second} of "
                    f"14, a difference of {10 - second}.", verdict])

    def verdicts(self, first: int, *sizes: int) -> Callable[[int], str]:
        """The verdict line of warning sign 1 at each difference, over the sets of the sizes given, with generation
        one right on `first` tickets; the section holds the counts' line and that line only."""
        def verdict(difference: int) -> str:
            self.setUp()
            lines = self.sign(first, first - difference, *sizes)
            self.assertEqual(len(lines), 2)
            return lines[1]
        return verdict

    def test_on_one_set_of_29_tickets_5_or_more_appears_3_to_4_is_not_decided_and_2_or_fewer_does_not(self) -> None:
        verdict = self.verdicts(10, 29)
        for difference, expected in ((5, "The sign appears."), (4, NOT_DECIDED), (3, NOT_DECIDED),
                                     (2, "The sign does not appear.")):
            with self.subTest(difference=difference):
                self.assertEqual(verdict(difference), expected)

    def test_on_one_set_of_5_tickets_1_or_more_appears_and_0_or_fewer_does_not(self) -> None:
        verdict = self.verdicts(3, 5)  # 1/6 and 1/10 of 5 both round up to 1, so no difference is not decided
        for difference, expected in ((1, "The sign appears."), (0, "The sign does not appear."),
                                     (-1, "The sign does not appear.")):
            with self.subTest(difference=difference):
                self.assertEqual(verdict(difference), expected)

    def test_over_two_sets_of_29_tickets_4_or_more_appears_and_3_or_fewer_does_not(self) -> None:
        verdict = self.verdicts(20, 14, 15)
        for difference, expected in ((4, "The sign appears."), (3, "The sign does not appear.")):
            with self.subTest(difference=difference):
                self.assertEqual(verdict(difference), expected)
                self.assertEqual(self.world.report().stdout.splitlines()[0],
                                 "Replay sets 1 and 2: 29 tickets, of project A.")

    def test_three_sets_take_the_line_of_the_sets_together(self) -> None:
        # 30 tickets: 2/15 of them is 4, where one set of 30 is not decided at 3 and 4. 31 tickets: 2/15 of them is
        # 62/15, about 4.13, so 5 rounded up, where rounding to the nearest or down gives 4; one set of 31 would leave
        # 4 and 5 not decided.
        for sizes, appears in (((10, 10, 10), 4), ((10, 10, 11), 5)):
            verdict = self.verdicts(20, *sizes)
            for difference, expected in ((appears, "The sign appears."), (appears - 1, "The sign does not appear.")):
                with self.subTest(sizes=sizes, difference=difference):
                    self.assertEqual(verdict(difference), expected)

    def test_a_set_with_no_ticket_gives_no_verdict(self) -> None:
        self.world.draw(count=0)
        self.assertEqual(section(self.lines(), 1), ["Warning sign 1: no verdict. The sets hold no ticket."])

    def test_the_verdict_waits_for_both_versions_on_every_ticket(self) -> None:
        self.world.baseline(20, 10)
        for at, row in enumerate(self.world.rows):  # ticket n: generation one spends 990 + 10n, direct 99 + n
            row["total_tokens"] = row["input_tokens"] = 1000 + 10 * (at // 2) if at % 2 == 0 else 100 + at // 2
        self.world.verdicts = [line for line in self.world.verdicts
                               if (line["version"], line["ticket"]) not in (("direct", 1), ("generation-one", 2))]
        self.world.verdicts[-1]["right_first_time"] = None
        self.world.versions.reverse()  # the replays' ledger in another order than the draw's
        lines = self.lines()
        self.assertEqual(section(lines, 1), ["Warning sign 1: no verdict. Tickets without both generation-one and "
                                             "direct judged: 3 of 30."])
        self.assertEqual(section(lines, 2), [  # tickets 3 to 29
            "Warning sign 2: on 27 of 30 tickets, generation-one spent 31050 tokens and direct 3105, an extra cost of "
            "27945.",
            *no_helpers(31050, sign_two_copied((0, 31050, "0.0%", 0), (0, 3105, "0.0%", 0)), unjudged=3),
            "No verdict: tickets without both generation-one and direct judged: 3 of 30."])

    def test_a_second_set_not_yet_judged_holds_back_the_verdict(self) -> None:
        self.world.baseline(20, 10)
        self.world.draw()
        self.assertEqual(section(self.lines(), 1),
                         ["Warning sign 1: no verdict. Tickets without both generation-one and direct judged: 30 of "
                          "60."])

    def test_lines_for_a_ticket_in_no_set_are_left_out_and_counted(self) -> None:
        self.world.baseline(20, 15)
        stray = {**self.world.sets[0][0], "ticket": 99, "ready_commit": commit(99), "session": session(99)}
        self.world.run("generation-one", stray, False)
        self.world.run("direct", stray, True)
        lines = self.lines()
        self.assertEqual(lines[:2], ["Replay set 1: 30 tickets, of project A.",
                                     "Left out: 3 lines of versions.jsonl and verdicts.jsonl name a ticket in no set."])
        self.assertEqual(section(lines, 1)[-1], "The sign appears.")

    def test_it_writes_nothing(self) -> None:
        self.world.baseline(20, 15)
        self.world.save()
        before = tree(self.world.root)  # the machine directory, the copy of scripts/, HOME and the working folder
        self.assertEqual(self.world.report(save=False).returncode, 0)
        self.assertEqual(tree(self.world.root), before)

    def test_a_machine_directory_that_does_not_exist_is_an_error_and_stays_absent(self) -> None:
        shutil.rmtree(self.world.state)
        self.error(f"no replay set in {self.world.state}.")
        self.assertFalse(self.world.state.exists())
        self.assertFalse((self.world.source / "__pycache__").exists())

    def test_a_machine_directory_it_cannot_list_is_an_error(self) -> None:
        self.world.baseline(20, 15)
        self.world.save()
        self.world.state.chmod(0o100)  # searchable, not readable
        self.addCleanup(self.world.state.chmod, 0o700)
        listing = subprocess.run([sys.executable, "-c", "import os, sys; os.listdir(sys.argv[1])",
                                  str(self.world.state)], capture_output=True)
        if listing.returncode == 0:
            self.skipTest("the mode does not bind this user (root, or an access list)")
        self.error(f"{self.world.state} cannot be read (PermissionError).")

    def test_a_folder_or_ledger_it_cannot_reach_is_an_error_not_absent(self) -> None:
        # A link to itself: exists() and is_dir() answer false, and reading it fails with ELOOP, for any user.
        self.world.baseline(20, 15)
        self.world.save()
        for name in ("versions.jsonl", "verdicts.jsonl", "scan-rows.jsonl"):
            with self.subTest(name=name):
                path = self.world.state / name
                saved = path.read_bytes()
                path.unlink()
                path.symlink_to(name)
                self.error(f"{path} cannot be read (OSError).")
                path.unlink()
                path.write_bytes(saved)
        shutil.rmtree(self.world.state)
        self.world.state.symlink_to(self.world.state.name)
        self.error(f"{self.world.state} cannot be read (OSError).")

    def test_missing_versions_verdicts_and_rows_are_nothing_judged_yet(self) -> None:
        self.world.draw()
        result = self.world.report(save=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(section(result.stdout.splitlines(), 1)[-1],
                         "Warning sign 1: no verdict. Tickets without both generation-one and direct judged: 30 of 30.")

    def test_input_it_cannot_read_with_certainty_stops_it_with_nothing_printed(self) -> None:
        def field(name: str, value: object) -> Callable[[list[str]], None]:
            def change(lines: list[str]) -> None:
                line = json.loads(lines[1])
                line.pop(name) if value is None else line.update({name: value})
                lines[1] = json.dumps(line)
            return change

        def entry(name: str, value: object) -> Callable[[dict], None]:
            return lambda saved: saved["tickets"][1].update({name: value})

        cases = [
            ("versions.jsonl", lambda lines: lines.__setitem__(0, "{not json"), "versions.jsonl:1: not a JSON line."),
            ("verdicts.jsonl", lambda lines: lines.__setitem__(0, "[1, 2]"), "verdicts.jsonl:1: not a JSON object."),
            ("verdicts.jsonl", field("right_first_time", None),
             "verdicts.jsonl:2: right_first_time is missing or of the wrong type."),
            ("verdicts.jsonl", field("ticket", True), "verdicts.jsonl:2: ticket is missing or of the wrong type."),
            ("verdicts.jsonl", lambda lines: lines.append(lines[0]),
             "verdicts.jsonl:61: a second line for the same label, ticket, version."),
            ("versions.jsonl", field("not_direct", "no"),
             "versions.jsonl:2: not_direct is missing or of the wrong type."),
            ("scan-rows.jsonl", field("total_tokens", "100"),
             "scan-rows.jsonl:2: total_tokens is missing or of the wrong type."),
            ("scan-rows.jsonl", lambda lines: lines.append(lines[0]),
             "scan-rows.jsonl:61: a second line for the same session."),
            ("replay-set-1.json", entry("bucket", "0-49"), "replay-set-1.json: ticket entry 2: bucket is not one the "
                                                           "draw uses."),
            ("replay-set-1.json", entry("session", None), "replay-set-1.json: ticket entry 2: session is missing or of "
                                                          "the wrong type."),
            ("replay-set-1.json", "{", "replay-set-1.json cannot be read as JSON (JSONDecodeError)."),
            ("replay-set-1.json", entry("label", REPO), "replay-set-1.json: ticket entry 2: label is not a label the "
                                                        "draw gives."),
            ("verdicts.jsonl", field("version", REPO), "verdicts.jsonl:2: version is not a version name."),
            ("versions.jsonl", field("version", REPO), "versions.jsonl:2: version is not a version name."),
            ("replay-set-2.json", "copy", "replay-set-2.json: ticket entry 1: a second line for the same label, "
                                          "ticket."),
            ("scan-rows.jsonl", field("helpers", None), "scan-rows.jsonl:2: helpers is missing or of the wrong type."),
            ("scan-rows.jsonl", field("helpers", {"a": 1}),
             "scan-rows.jsonl:2: helpers is missing or of the wrong type."),
            ("scan-rows.jsonl", field("helpers", [helper("Fix round 1", None, 1), 1]),
             "scan-rows.jsonl:2: helper 2: not a JSON object."),
            ("scan-rows.jsonl", field("helpers", [{**helper(None, None, 1), "description": 5}]),
             "scan-rows.jsonl:2: helper 1: description is missing or of the wrong type."),
            ("scan-rows.jsonl", field("helpers", [{**helper(None, None, 1), "brief_head": ["x"]}]),
             "scan-rows.jsonl:2: helper 1: brief_head is missing or of the wrong type."),
            ("scan-rows.jsonl", field("helpers", [helper(None, None, "7")]),
             "scan-rows.jsonl:2: helper 1: total_tokens is missing or of the wrong type."),
            ("scan-rows.jsonl", field("helpers", [helper(None, None, -1)]),
             "scan-rows.jsonl:2: helper 1: total_tokens is not a count of tokens."),
            ("scan-rows.jsonl", field("helpers", [helper(None, None, float("inf"))]),
             "scan-rows.jsonl:2: helper 1: total_tokens is not a count of tokens."),
            ("scan-rows.jsonl", field("total_tokens", -100),
             "scan-rows.jsonl:2: total_tokens is not a count of tokens."),
            ("scan-rows.jsonl", field("total_tokens", float("nan")),
             "scan-rows.jsonl:2: total_tokens is not a count of tokens."),
            ("scan-rows.jsonl", field("helpers", [helper(None, None, 60), helper(None, None, 41)]),
             "scan-rows.jsonl:2: its helpers hold more tokens than its total_tokens."),
            *(("scan-rows.jsonl", field("copied_tokens", value),
               "scan-rows.jsonl:2: copied_tokens is of the wrong type.") for value in ("5", True, [1], {"a": 1})),
            *(("scan-rows.jsonl", field("copied_tokens", value),
               "scan-rows.jsonl:2: copied_tokens is not a count of tokens.")
              for value in (-1, float("nan"), float("inf"))),
            ("scan-rows.jsonl", field("copied_tokens", 100.5),  # the row's total_tokens is 100
             "scan-rows.jsonl:2: copied_tokens is more than its total_tokens or beside a blank one."),
            ("scan-rows.jsonl", lambda lines: lines.__setitem__(1, json.dumps({**json.loads(lines[1]),
                                                                            "total_tokens": None, "copied_tokens": 5})),
             "scan-rows.jsonl:2: copied_tokens is more than its total_tokens or beside a blank one."),
            ("scan-rows.jsonl", lambda lines: lines.append(json.dumps({**json.loads(lines[0]), "session": session(999),
                                                                       "copied_tokens": -1})),  # a session in no set
             "scan-rows.jsonl:61: copied_tokens is not a count of tokens."),
        ]
        for name, change, message in cases:
            with self.subTest(message=message):
                self.setUp()
                self.world.baseline(20, 15)
                self.world.save()
                path = self.world.state / name
                if name.endswith(".jsonl"):
                    lines = path.read_text().splitlines()
                    change(lines)
                    path.write_text("\n".join(lines) + "\n")
                elif change == "copy":
                    shutil.copyfile(self.world.state / "replay-set-1.json", path)
                elif change == "{":
                    path.write_text(change)
                else:
                    saved = json.loads(path.read_text())
                    change(saved)
                    path.write_text(json.dumps(saved))
                self.error(f"{self.world.state}/{message}")

    def write_rows(self, *lines: bytes) -> None:
        """The scan-rows.jsonl the other files of this world leave, with these lines of bytes in place of its rows."""
        self.world.save()
        (self.world.state / "scan-rows.jsonl").write_bytes(b"".join(line + b"\n" for line in lines))

    def scan_writes(self, session_name: str) -> None:
        """Run scripts/scan.py's row writer, the code that keeps a line it cannot read, over the rows file."""
        code = "import json, sys; sys.path.insert(0, sys.argv[1]); import scan; scan.write_row(json.loads(sys.argv[2]))"
        self.world.scan(session_name, 1, 1.0)
        env = {**os.environ, "HOME": str(self.world.root / "home"), "DELIVER_STATE_DIR": str(self.world.state)}
        written = subprocess.run([sys.executable, "-c", code, str(self.world.source), json.dumps(self.world.rows.pop())],
                                 env=env, text=True, capture_output=True)
        self.assertEqual(written.returncode, 0, written.stderr)

    def test_a_line_the_scan_keeps_that_is_no_row_is_left_out_named_and_counted(self) -> None:
        self.world.baseline(20, 15)
        self.world.save()
        good = (self.world.state / "scan-rows.jsonl").read_bytes().split(b"\n")[:-1]
        clean = self.lines()
        damaged = [b"{broken", b"[]", b'{"total_tokens": 5}', b'{"session": 5}', b"\xff\xfe not UTF-8"]
        # Each damaged line is at its own line number: after good row 1, 2, 3, 4 and 5 (so lines 2, 4, 6, 8 and 10).
        mixed = [line for pair in zip(good[:5], damaged) for line in pair] + good[5:]
        self.write_rows(*mixed)
        self.scan_writes(session(999))  # the writer reads the file, keeps these lines and adds its own row
        kept = (self.world.state / "scan-rows.jsonl").read_bytes().split(b"\n")
        self.assertEqual([line for line in kept if line in damaged], damaged)
        result = self.world.report(save=False)
        rows = self.world.state / "scan-rows.jsonl"
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, [
            clean[0], "Left out: scan-rows.jsonl lines that are no scan row: 5.", *clean[1:]]))
        self.assertEqual(result.stderr.splitlines(), [
            f"report: {rows}:2: not a JSON object, left out.",
            f"report: {rows}:4: not a JSON object, left out.",
            f"report: {rows}:6: session is missing or of the wrong type, left out.",
            f"report: {rows}:8: session is missing or of the wrong type, left out.",
            f"report: {rows}:10: not a JSON object, left out."])

    def test_a_session_whose_row_is_such_a_line_is_counted_as_one_with_no_row(self) -> None:
        self.world.baseline(20, 15)
        self.world.save()
        good = (self.world.state / "scan-rows.jsonl").read_bytes().split(b"\n")[:-1]
        self.write_rows(*good[1:])  # generation one's session of the first ticket has no row
        without = self.world.report(save=False).stdout.splitlines()
        self.assertIn("  Left out of the token figures: 1 with a blank token count. Left out of the active minutes: 1 "
                      "blank.", without)
        self.write_rows(b"{broken", *good[1:])  # the same row, damaged: a line that names no session
        result = self.world.report(save=False)
        rows = self.world.state / "scan-rows.jsonl"
        self.assertEqual((result.returncode, result.stdout.splitlines(), result.stderr), (0, [
            without[0], "Left out: scan-rows.jsonl lines that are no scan row: 1.", *without[1:]],
            f"report: {rows}:1: not a JSON object, left out.\n"))

    def test_a_bad_total_tokens_stops_the_report_and_the_line_left_out_before_it_is_still_named(self) -> None:
        self.world.baseline(20, 15)
        self.world.save()
        good = (self.world.state / "scan-rows.jsonl").read_bytes().split(b"\n")[:-1]
        wrong = json.dumps({**json.loads(good[2]), "total_tokens": "100"}).encode()
        self.write_rows(good[0], b"[]", b"", wrong, *good[3:])
        # The wrong figure is on line 4: the damaged line 2 and the blank line 3 count as lines.
        result = self.world.report(save=False)
        rows = self.world.state / "scan-rows.jsonl"
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, "", f"report: {rows}:2: not a JSON object, left out.\n"
                   f"report: {rows}:4: total_tokens is missing or of the wrong type.\n"))

    def test_blank_lines_of_the_rows_file_are_passed_over_and_not_counted(self) -> None:
        self.world.baseline(20, 15)
        clean = self.world.report(text=False)  # bytes, so that a changed line ending shows
        self.assertEqual((clean.returncode, clean.stderr), (0, b""))
        good = (self.world.state / "scan-rows.jsonl").read_bytes().split(b"\n")[:-1]
        self.write_rows(b"", b"  ", *good, b"\t", "\u00a0\u2003".encode())
        result = self.world.report(save=False, text=False)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, clean.stdout, b""))

    def test_a_damaged_line_of_versions_or_verdicts_still_stops_it_whatever_the_rows_file_holds(self) -> None:
        for name, damage in (("versions.jsonl", b"{broken"), ("verdicts.jsonl", b"[]"), ("versions.jsonl", b"\xff"),
                             ("verdicts.jsonl", b"\xff")):
            with self.subTest(name=name, damage=damage):
                self.setUp()
                self.world.baseline(20, 15)
                self.write_rows(b"{broken", b"[]")
                path = self.world.state / name
                path.write_bytes(damage + b"\n" + path.read_bytes())
                result = self.world.report(save=False)
                message = (f"{path}:1: not a JSON line." if damage == b"{broken" else
                           f"{path}:1: not a JSON object." if damage == b"[]" else
                           f"{path} cannot be read (UnicodeDecodeError).")
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (1, "", f"report: {message}\n"))

    def test_help_states_which_lines_of_the_rows_file_are_left_out(self) -> None:
        text = self.world.report("--help").stdout
        self.assertIn(
            "A nonblank line of scan-rows.jsonl is no row when the scan would not read it as a\n"
            "JSON object (json_object in scripts/scan.py says which) or when it is an object\n"
            "whose session is not text. The scan keeps such a line, and the report leaves it\n"
            "out: it names the line once on standard error, with the file, the line number and\n"
            "the reason, as it reads the file, and prints on standard output how many lines it\n"
            "left out when it prints the report. A line of nothing but whitespace is blank,\n"
            "and is passed over and not counted. A session whose row was such a line is left\n"
            "out of the token figures and counted, like one with no row.\n", text + "\n")
        self.assertIn("one ticket of the sets stops the report. The error goes on standard error and\n"
                      "names the folder or file, and the ledger line, helper or set ticket entry that\n"
                      "fails a check. A set file that is not JSON, or not an object holding a list of\n"
                      "tickets, and a versions.jsonl or verdicts.jsonl that is not UTF-8 are named by\n"
                      "file alone. It never prints a refused label or version name, and prints nothing\n"
                      "on standard output.\n", text + "\n")

    def test_help_states_once_that_every_token_figure_includes_copied_tokens(self) -> None:
        text = self.world.report("--help").stdout + "\n"
        rule = ("Every token figure includes the tokens a resumed session copied: the report\n"
                "takes none out of a figure or a verdict. python3 scripts/scan.py --help says\n"
                "which lines are copied and what copied_tokens holds. A copied response counts\n"
                "in total_tokens and, wherever the scan puts it, in a helper's tokens or in the\n"
                "session's own. Each version's block ends with the copied_tokens of the tickets\n"
                "in its token figures, summed, out of the total_tokens of those of them with a\n"
                "copied_tokens, and that share as a percent. Warning sign 2 gives the same for\n"
                "each side, over the tickets it counts. Where those total_tokens sum to 0, no\n"
                "share is printed. A copied_tokens that is null, or absent from a row the scan\n"
                "wrote before it had that column, is blank: its ticket is left out of the copied\n"
                "tokens and counted.\n")
        self.assertIn("\n\n" + rule + "\n", text)
        sentence = " ".join(rule[:rule.index("verdict.") + len("verdict.")].split())  # the rule's first sentence
        self.assertEqual(" ".join(text.split()).count(sentence), 1)
        # Every share the report prints is a percent, and each sentence names the right whole.
        self.assertIn("A share of tokens is not a count of\ntickets, so the report gives every share as a percent at "
                      "any number of\ntickets. The cut and the tokens not sorted are percents of generation-one's\n"
                      "tokens. Each copied share is of the total printed beside it.\n", text)
        self.assertIn("  scan-rows.jsonl       session, total_tokens, copied_tokens, active_minutes\n"
                      "                        and helpers of each row, and description, brief_head\n"
                      "                        and total_tokens of each helper (scripts/scan.py).\n", text)
        self.assertIn("A missing versions.jsonl, verdicts.jsonl or scan-rows.jsonl holds nothing\n"
                      "yet. A folder or file that cannot be read, a line of versions.jsonl or\n"
                      "verdicts.jsonl that is not a JSON object, a field missing or of the wrong type\n"
                      "(but not the session of a line of scan-rows.jsonl, above, or a missing\n"
                      "copied_tokens), a set entry's label the draw would not give or bucket it does\n"
                      "not use, a version name in versions.jsonl or verdicts.jsonl the judge would\n"
                      "not take, a total_tokens or copied_tokens that is negative, infinite or not a\n"
                      "number, helpers that hold more tokens than their row's total_tokens, a\n"
                      "copied_tokens more than its row's total_tokens or beside a blank one, or a\n"
                      "second line for one ticket and version, one session or\n"
                      "one ticket of the sets stops the report.", text)

    def test_help_names_every_place_that_holds_the_words_the_sorter_reads(self) -> None:
        self.assertIn(
            "The report reads each helper's description and the head of its brief, and\n"
            "puts the helper in a step of generation one or leaves it not sorted. How it\n"
            "chooses, and where it can sort wrong, are in step() and named() in\n"
            "scripts/report.py, with each step's words in STEPS, the words read past in\n"
            "NO_ROLE and those that make a review a re-check in AGAIN. A helper sorted\n"
            "into the wrong step can move the cut either way. The steps:\n",
            self.world.report("--help").stdout)

    def test_help_states_the_rule_of_warning_sign_1(self) -> None:
        text = " ".join(self.world.report("--help").stdout.split())  # the help is wrapped at any word
        for fact in ("a share of the tickets judged, rounded up.",
                     "Over one set, the sign appears at a difference of at least 1/6 of the tickets",
                     "does not appear below 1/10 of them.",
                     "Between the two it is not decided, and a second set is needed, the rest of the pool: every "
                     "remaining pool ticket whose check passes, with no limit per bucket.",
                     f"Over two sets or more, taken together, {SETS_TOGETHER}",
                     "One set of 30 tickets gives 5 and 3; 60 tickets over two sets give 8.",
                     "Sets that hold no ticket give no verdict."):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        self.assertNotIn("Any other number of tickets", text)

    def test_help_exits_0_and_bad_usage_exits_2(self) -> None:
        self.world.draw()
        for args in (["--help"], ["-h"]):
            result = self.world.report(*args)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.splitlines()[0], "Print the comparison between versions on the replay set "
                                                            "and the verdicts on")
            self.assertIn("  re-check, closing verification, fix, review, implement, publish and explore.",
                          result.stdout.splitlines())
            self.assertIn("The cut is the helpers' tokens in closing verification, fix and re-check.",
                          result.stdout.splitlines())
        for args in (["--set", "1"], ["extra"], ["--help", "extra"]):
            with self.subTest(args=args):
                result = self.world.report(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertEqual(result.stderr.splitlines()[0], "Print the comparison between versions on the "
                                                                "replay set and the verdicts on")


if __name__ == "__main__":
    unittest.main()
