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
from collections.abc import Callable
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
BUCKETS = ("0-50", "51-300", "301-1500")
REPO = "example-org/alpha"  # what project-labels.json maps label A to; the report must never print it
TITLE = "Print the total of example-org/alpha"


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

    def draw(self, per_bucket: int = 10, labels: tuple[str, ...] = ("A",)) -> list[dict]:
        """A new set of per_bucket tickets in each bucket, from the projects labelled in turn, written at once, as
        the draw writes it: each project numbers its own tickets, so A-1 and B-1 can both be in a set."""
        start = sum(map(len, self.sets))
        drawn = [ticket for tickets in self.sets for ticket in tickets]
        tickets = []
        for at in range(3 * per_bucket):
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

    def scan(self, name: str, tokens: int | None, minutes: float | None, helpers: list[dict] | None = None) -> None:
        self.rows.append({"session": name, "input_tokens": None if tokens is None else 1,
                          "output_tokens": None if tokens is None else 1, "cache_write_tokens": None,
                          "cache_read_tokens": None, "total_tokens": tokens, "active_minutes": minutes,
                          "auto_compactions": 0, "typed_compactions": 0, "model": "claude-test-model",
                          "skills": [], "helpers": [] if helpers is None else helpers})

    def run(self, version: str, ticket: dict, right: bool | None, tokens: int | None = 100,
            minutes: float | None = 10.0, helpers: list[dict] | None = None) -> None:
        """A version of a ticket replayed where it is not generation one's, judged and scanned."""
        name = ticket["session"] if version == "generation-one" else self.replay(ticket, version)["session"]
        self.judge(ticket, version, right)
        self.scan(name, tokens, minutes, helpers)

    def baseline(self, first: int, second: int, sets: int = 1) -> None:
        """Sets of 30 with both versions judged on every ticket: generation one right on `first` tickets, the
        direct replays on `second`."""
        tickets = [ticket for _ in range(sets) for ticket in self.draw()]
        for at, ticket in enumerate(tickets):
            self.run("generation-one", ticket, at < first)
            self.run("direct", ticket, at < second)

    def save(self) -> None:
        for name, lines in (("versions", self.versions), ("verdicts", self.verdicts), ("scan-rows", self.rows)):
            (self.state / f"{name}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    def report(self, *args: str, save: bool = True) -> subprocess.CompletedProcess[str]:
        if save:
            self.save()
        env = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
        env.update({"HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(self.state)})
        return subprocess.run([sys.executable, str(self.source / "report.py"), *args], cwd=self.root, env=env,
                              text=True, capture_output=True)


def tree(folder: Path) -> dict[str, tuple]:
    """Every path under the folder with its kind, mode, modification time and bytes."""
    return {str(path.relative_to(folder)): (path.is_dir(), path.stat().st_mode, path.stat().st_mtime_ns,
                                            None if path.is_dir() else path.read_bytes())
            for path in sorted(folder.rglob("*"))}


# One helper of each of generation one's steps, with tokens of 2**n each so that every step's sum tells which
# helpers it took, then helpers sorted by the head of the brief, one sorted into no step, and one with no tokens of
# its own. Each re-check, fix and review names a step that comes later in the sort.
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


def no_helpers(spent: int) -> list[str]:
    """Warning sign 2's lines between its first line and its verdicts, for sessions with no helpers."""
    return ["  Left out of both sides: 0 with a blank token count, 0 with no list of generation-one's helpers.",
            "  generation-one's helpers by step: re-check 0, closing verification 0, fix 0, review 0, implement 0, "
            "publish 0, explore 0. 0 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 0 tokens, 0.0% of generation-one's.",
            "  Not sorted into a step: 0 tokens, 0.0% of generation-one's.",
            f"  The sessions' own, in no helper: {spent} tokens, 100.0% of generation-one's.",
            "  A helper resumed for a fix round counts under the step it started as."]


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

    def sign(self, first: int, second: int, sets: int = 1) -> list[str]:
        self.world.baseline(first, second, sets)
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
            "",
            "direct",
            "  0-50: 2 judged, 1 of 2 right first time, median total tokens 250, median active minutes 3.125.",
            "  51-300: 2 judged, 0 of 2 right first time, median total tokens 350, median active minutes 4.375.",
            "  301-1500: 2 judged, 1 of 2 right first time, median total tokens 450, median active minutes 5.625.",
            "  All: 6 judged, 2 of 6 right first time, median total tokens 350, median active minutes 4.375.",
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank.",
            "",
            "Warning sign 1: generation-one was right first time on 5 of 6 tickets, direct on 2 of 6, a difference "
            "of 3.",
            "No verdict: the table of warning sign 1 has lines for 30 and 60 tickets, not 6.",
            "",
            "Warning sign 2: on 6 of 6 tickets, generation-one spent 21000 tokens and direct 2100, an extra cost of "
            "18900.",
            *no_helpers(21000),
            "Without the spend not sorted, the cut is 0 tokens against half the extra cost, 9450. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 0 tokens. The sign does not appear."])

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
            "  Left out of both sides: 0 with a blank token count, 0 with no list of generation-one's helpers.",
            "  generation-one's helpers by step: re-check 300, closing verification 630, fix 1200, review 2400, "
            "implement 4860, publish 9600, explore 19200. 30 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 2130 tokens, 3.1% of generation-one's.",
            "  Not sorted into a step: 120 tokens, 0.2% of generation-one's.",
            "  The sessions' own, in no helper: 30000 tokens, 43.9% of generation-one's.",
            "  A helper resumed for a fix round counts under the step it started as.",
            "Without the spend not sorted, the cut is 2130 tokens against half the extra cost, 19155. The sign does "
            "not appear.",
            "With it counted as cut, the cut is 2250 tokens. The sign does not appear."])

    def test_sign_two_appears_when_the_cut_is_more_than_half_the_extra_cost(self) -> None:
        # 30 tickets: an extra cost of 6000 tokens, half of it 3000.
        for verification, verdict in ((101, "The sign appears."), (100, "The sign does not appear."),
                                      (99, "The sign does not appear.")):
            with self.subTest(cut=30 * verification):
                self.setUp()
                lines = self.two([helper("Closing verification", None, verification)], 1000, 800)
                self.assertEqual(lines[0], "Warning sign 2: on 30 of 30 tickets, generation-one spent 30000 tokens "
                                           "and direct 24000, an extra cost of 6000.")
                self.assertEqual(lines[-2:], [
                    f"Without the spend not sorted, the cut is {30 * verification} tokens against half the extra "
                    f"cost, 3000. {verdict}",
                    f"With it counted as cut, the cut is {30 * verification} tokens. {verdict}"])

    def test_sign_two_says_when_the_spend_not_sorted_decides_it(self) -> None:
        lines = self.two([helper("Fix round 1", None, 90), helper("Tidy the notes", None, 20)], 1000, 800)
        self.assertEqual(lines[-3:], [
            "Without the spend not sorted, the cut is 2700 tokens against half the extra cost, 3000. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 3300 tokens. The sign appears.",
            "The two verdicts differ: the spend not sorted decides the sign."])

    def test_sign_two_gives_no_verdict_with_no_extra_cost(self) -> None:
        for direct, extra in ((1000, 0), (1001, -30)):
            with self.subTest(extra=extra):
                self.setUp()
                lines = self.two([helper("Re-check", None, 400)], 1000, direct)
                self.assertEqual(lines[0], f"Warning sign 2: on 30 of 30 tickets, generation-one spent 30000 tokens "
                                           f"and direct {30 * direct}, an extra cost of {extra}.")
                self.assertEqual(lines[-1], "No verdict: generation-one cost no more than direct, so there is no "
                                            "extra cost to cut.")

    def test_a_ticket_left_out_of_the_token_figures_is_left_out_of_both_sides(self) -> None:
        cut = [helper("Closing verification", None, 100)]
        for at, ticket in enumerate(self.world.draw()):  # the other side of each ticket left out spends 99999
            self.world.run("generation-one", ticket, True, tokens=None if at == 1 else 99999 if at in (0, 2) else 1000,
                           helpers=None if at == 1 else cut)
            self.world.run("direct", ticket, True, tokens=None if at == 0 else 99999 if at in (1, 2) else 800)
            if at == 2:
                self.world.rows[-2]["helpers"] = None  # generation one's row, with a total and no list of helpers
        self.assertEqual(section(self.lines(), 2), [
            "Warning sign 2: on 27 of 30 tickets, generation-one spent 27000 tokens and direct 21600, an extra cost of "
            "5400.",
            "  Left out of both sides: 2 with a blank token count, 1 with no list of generation-one's helpers.",
            "  generation-one's helpers by step: re-check 0, closing verification 2700, fix 0, review 0, implement 0, "
            "publish 0, explore 0. 0 helpers have no tokens of their own.",
            "  The cut, closing verification, fix and re-check: 2700 tokens, 10.0% of generation-one's.",
            "  Not sorted into a step: 0 tokens, 0.0% of generation-one's.",
            "  The sessions' own, in no helper: 24300 tokens, 90.0% of generation-one's.",
            "  A helper resumed for a fix round counts under the step it started as.",
            "Without the spend not sorted, the cut is 2700 tokens against half the extra cost, 2700. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 2700 tokens. The sign does not appear."])

    def test_sign_two_gives_no_verdict_when_no_ticket_is_left(self) -> None:
        for ticket in self.world.draw():
            self.world.run("generation-one", ticket, True, tokens=1000)
            self.world.run("direct", ticket, True, tokens=None)
        self.assertEqual(section(self.lines(), 2), [
            "Warning sign 2: no verdict. No ticket has both token counts and generation-one's helpers.",
            "  Left out of both sides: 30 with a blank token count, 0 with no list of generation-one's helpers."])

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
            self.world.judge(ticket, "fan-out", at != 1, at=commit(70 + at))
        lines = self.lines()
        start = lines.index("fan-out")
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
            "",
            "direct",
            "  0-50: 20 judged, 20 of 20 (100%) right first time, median total tokens 63.5, median active minutes "
            "14.",
            "  51-300: 20 judged, 0 of 20 (0%) right first time, median total tokens 64.5, median active minutes 15.",
            "  301-1500: 20 judged, 0 of 20 (0%) right first time, median total tokens 65.5, median active minutes "
            "16.",
            "  All: 60 judged, 20 of 60 (33%) right first time, median total tokens 64.5, median active minutes 15.",
            *tail,
            "",
            "Warning sign 1: generation-one was right first time on 30 of 60 (50%) tickets, direct on 20 of 60 "
            "(33%), a difference of 10.",
            "The sign appears.",
            "",
            "Warning sign 2: on 60 of 60 tickets, generation-one spent 6870 tokens and direct 3870, an extra cost of "
            "3000.",
            *no_helpers(6870),
            "Without the spend not sorted, the cut is 0 tokens against half the extra cost, 1500. The sign does not "
            "appear.",
            "With it counted as cut, the cut is 0 tokens. The sign does not appear."])

    def test_a_third_version_is_printed_beside_the_other_two(self) -> None:
        tickets = self.world.draw(per_bucket=1)
        for ticket in tickets:
            self.world.run("generation-one", ticket, True)
            self.world.run("direct", ticket, False)
            self.world.run("fan-out", ticket, ticket is tickets[0], tokens=40, minutes=4.0)
        lines = self.lines()
        self.assertEqual([line for line in lines if line and not line.startswith(" ")][1:4],
                         ["generation-one", "direct", "fan-out"])
        start = lines.index("fan-out")
        self.assertEqual(lines[start + 4], "  All: 3 judged, 1 of 3 right first time, median total tokens 40, "
                                           "median active minutes 4.")

    def test_on_30_tickets_5_or_more_the_sign_appears(self) -> None:
        self.assertEqual(self.sign(20, 15), [
            "Warning sign 1: generation-one was right first time on 20 of 30 (67%) tickets, direct on 15 of 30 (50%), "
            "a difference of 5.",
            "The sign appears."])

    def test_on_30_tickets_4_or_3_a_second_set_is_needed(self) -> None:
        for first, second in ((20, 16), (20, 17)):
            with self.subTest(difference=first - second):
                self.setUp()
                self.assertEqual(self.sign(first, second)[1],
                                 "Not decided: a second set of 30 is needed, and 60 tickets decide.")

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
                lines = self.sign(40, second, sets=2)
                self.assertEqual(lines[1], verdict)
                self.assertEqual(self.world.report().stdout.splitlines()[0],
                                 "Replay sets 1 and 2: 60 tickets, of project A.")

    def test_the_verdict_waits_for_both_versions_on_every_ticket(self) -> None:
        self.world.baseline(20, 10)
        self.world.verdicts = [line for line in self.world.verdicts
                               if (line["version"], line["ticket"]) not in (("direct", 1), ("generation-one", 2))]
        self.world.verdicts[-1]["right_first_time"] = None
        lines = self.lines()
        for sign in (1, 2):
            self.assertEqual(section(lines, sign), [f"Warning sign {sign}: no verdict. Tickets without both "
                                                    "generation-one and direct judged: 3 of 30."])

    def test_a_second_set_not_yet_judged_holds_back_the_verdict(self) -> None:
        self.world.baseline(20, 10)
        self.world.draw()
        self.assertEqual(section(self.lines(), 1),
                         ["Warning sign 1: no verdict. Tickets without both generation-one and direct judged: 30 of 60."])

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
            ("scan-rows.jsonl", field("total_tokens", -100), "scan-rows.jsonl:2: total_tokens is not a count of tokens."),
            ("scan-rows.jsonl", field("total_tokens", float("nan")),
             "scan-rows.jsonl:2: total_tokens is not a count of tokens."),
            ("scan-rows.jsonl", field("helpers", [helper(None, None, 60), helper(None, None, 41)]),
             "scan-rows.jsonl:2: its helpers hold more tokens than its total_tokens."),
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
            self.assertIn("  30 tickets: appears at 5 or more, not decided at 3 to 4, not at 2 or fewer.",
                          result.stdout.splitlines())
            self.assertIn("  60 tickets: appears at 8 or more, not at 7 or fewer.", result.stdout.splitlines())
        for args in (["--set", "1"], ["extra"], ["--help", "extra"]):
            with self.subTest(args=args):
                result = self.world.report(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertEqual(result.stderr.splitlines()[0], "Print the comparison between versions on the "
                                                                "replay set and the verdicts on")


if __name__ == "__main__":
    unittest.main()
