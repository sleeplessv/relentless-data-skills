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
        (self.state / "project-labels.json").write_text(json.dumps({"A": REPO}))
        self.sets: list[list[dict]] = []
        self.versions: list[dict] = []
        self.verdicts: list[dict] = []
        self.rows: list[dict] = []

    def draw(self, per_bucket: int = 10) -> list[dict]:
        """A new set of per_bucket tickets in each bucket, written at once, as the draw writes it."""
        start = 1 + sum(map(len, self.sets))
        tickets = [{"label": "A", "ticket": start + at, "bucket": BUCKETS[at % 3], "size": 10, "title": TITLE,
                    "body": "## Acceptance criteria\n\n- [ ] The total.", "base_commit": commit(1),
                    "ready_commit": commit(1000 + start + at), "model": "claude-test-model", "pr": 500 + start + at,
                    "session": session(start + at), "log": f"logs/{session(start + at)}.jsonl",
                    "check_output": f"checks/A-{start + at}.txt"} for at in range(3 * per_bucket)]
        self.sets.append(tickets)
        number = len(self.sets)
        (self.state / f"replay-set-{number}.json").write_text(json.dumps(
            {"set": number, "seed": 7, "drawn_at": "2026-11-26T10:00:00+00:00", "tickets": tickets,
             "set_aside": []}, indent=2) + "\n")
        return tickets

    def replay(self, ticket: dict, version: str = "direct", not_direct: bool = False) -> dict:
        found = {"label": ticket["label"], "ticket": ticket["ticket"], "version": version,
                 "commit": commit(5000 + ticket["ticket"] + 100000 * len(version)),
                 "repo": f"replays/A-{ticket['ticket']}-{version}.git", "base_commit": ticket["base_commit"],
                 "clone": f"replays/A-{ticket['ticket']}-{version}", "exit_status": 0,
                 "session": session(9000 + ticket["ticket"] + 100000 * len(version)), "skills": [],
                 "not_direct": not_direct}
        self.versions.append(found)
        return found

    def judge(self, ticket: dict, version: str, right: bool | None, at: str | None = None) -> None:
        if at is None:
            at = ticket["ready_commit"] if version == "generation-one" else next(
                line["commit"] for line in self.versions
                if (line["ticket"], line["version"]) == (ticket["ticket"], version))
        self.verdicts.append({"label": ticket["label"], "ticket": ticket["ticket"], "version": version, "commit": at,
                              "base_commit": ticket["base_commit"], "judged_at": "2026-11-26T11:00:00+00:00",
                              "check": {"passed": True, "reason": None, "output": "judged/x/check.txt"},
                              "review": {"passed": right, "reason": None},
                              "right_first_time": right})

    def scan(self, name: str, tokens: int | None, minutes: float | None) -> None:
        self.rows.append({"session": name, "input_tokens": None if tokens is None else 1,
                          "output_tokens": None if tokens is None else 1, "cache_write_tokens": None,
                          "cache_read_tokens": None, "total_tokens": tokens, "active_minutes": minutes,
                          "auto_compactions": 0, "typed_compactions": 0, "model": "claude-test-model",
                          "skills": [], "helpers": []})

    def run(self, version: str, ticket: dict, right: bool | None, tokens: int | None = 100,
            minutes: float | None = 10.0) -> None:
        """A version of a ticket replayed where it is not generation one's, judged and scanned."""
        name = ticket["session"] if version == "generation-one" else self.replay(ticket, version)["session"]
        self.judge(ticket, version, right)
        self.scan(name, tokens, minutes)

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
        return self.lines()[-2:]

    def test_it_prints_each_version_per_bucket_and_over_the_set(self) -> None:
        tickets = self.world.draw(per_bucket=2)  # buckets in turn: 0-50, 51-300, 301-1500, 0-50, 51-300, 301-1500
        for at, ticket in enumerate(tickets):
            self.world.run("generation-one", ticket, at != 1, tokens=1000 * (at + 1), minutes=10.0 * (at + 1))
            self.world.run("direct", ticket, at in (0, 2), tokens=100 * (at + 1), minutes=1.25 * (at + 1))
        self.assertEqual(self.lines(), [
            "Replay set 1: 6 tickets.",
            "",
            "generation-one",
            "  0-50: 2 of 2 judged, 2 of 2 right first time, median total tokens 2500, median active minutes 25.0.",
            "  51-300: 2 of 2 judged, 1 of 2 right first time, median total tokens 3500, median active minutes 35.0.",
            "  301-1500: 2 of 2 judged, 2 of 2 right first time, median total tokens 4500, median active minutes "
            "45.0.",
            "  All: 6 of 6 judged, 5 of 6 right first time, median total tokens 3500, median active minutes 35.0.",
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank.",
            "",
            "direct",
            "  0-50: 2 of 2 judged, 1 of 2 right first time, median total tokens 250, median active minutes 3.1.",
            "  51-300: 2 of 2 judged, 0 of 2 right first time, median total tokens 350, median active minutes 4.4.",
            "  301-1500: 2 of 2 judged, 1 of 2 right first time, median total tokens 450, median active minutes 5.6.",
            "  All: 6 of 6 judged, 2 of 6 right first time, median total tokens 350, median active minutes 4.4.",
            "  Left out of every figure: 0 not direct, 0 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank.",
            "",
            "Warning sign 1: generation-one was right first time on 5 of 6 tickets, direct on 2 of 6, a difference "
            "of 3.",
            "No verdict: the table of warning sign 1 has lines for 30 and 60 tickets, not 6."])

    def test_a_count_out_of_fewer_than_20_is_never_a_rate(self) -> None:
        self.world.baseline(17, 14)
        lines = self.lines()
        self.assertIn("  0-50: 10 of 10 judged, 6 of 10 right first time, median total tokens 100, median active "
                      "minutes 10.0.", lines)
        self.assertIn("  All: 30 of 30 (100%) judged, 17 of 30 (57%) right first time, median total tokens 100, "
                      "median active minutes 10.0.", lines)

    def test_a_rate_starts_at_20_tickets(self) -> None:
        tickets = self.world.draw(per_bucket=7)[:20]  # 20 tickets judged of 21, then 19 of 21
        for ticket in tickets:
            self.world.run("generation-one", ticket, True)
        for ticket in tickets[:19]:
            self.world.run("direct", ticket, True)
        lines = self.lines()
        self.assertIn("  All: 20 of 21 (95%) judged, 20 of 20 (100%) right first time, median total tokens 100, "
                      "median active minutes 10.0.", lines)
        self.assertIn("  All: 19 of 21 (90%) judged, 19 of 19 right first time, median total tokens 100, "
                      "median active minutes 10.0.", lines)

    def test_a_blank_token_count_is_left_out_of_the_token_figures_and_counted(self) -> None:
        tickets = self.world.draw(per_bucket=1)
        self.world.run("generation-one", tickets[0], True, tokens=None, minutes=None)
        self.world.run("generation-one", tickets[1], True, tokens=300, minutes=None)
        self.world.judge(tickets[2], "generation-one", False)  # judged, but its session has no scan row
        lines = self.lines()
        self.assertEqual(lines[2:9], [
            "generation-one",
            "  0-50: 1 of 1 judged, 1 of 1 right first time, median total tokens none, median active minutes none.",
            "  51-300: 1 of 1 judged, 1 of 1 right first time, median total tokens 300, median active minutes none.",
            "  301-1500: 1 of 1 judged, 0 of 1 right first time, median total tokens none, median active minutes "
            "none.",
            "  All: 3 of 3 judged, 2 of 3 right first time, median total tokens 300, median active minutes none.",
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
            "  All: 2 of 6 judged, 1 of 2 right first time, median total tokens 200, median active minutes 10.0.",
            "  Left out of every figure: 1 not direct, 3 with no verdict, 0 judged at a commit the version does not "
            "record.",
            "  Left out of the token figures: 0 with a blank token count. Left out of the active minutes: 0 blank."])

    def test_a_verdict_on_another_commit_is_left_out_of_every_figure(self) -> None:
        tickets = self.world.draw(per_bucket=1)
        self.world.judge(tickets[0], "generation-one", True, at=commit(77))  # not the ready commit
        self.world.run("generation-one", tickets[1], True)
        self.world.replay(tickets[0])
        self.world.judge(tickets[0], "direct", True, at=commit(78))  # not the replay's commit
        self.world.judge(tickets[1], "direct", True, at=commit(79))  # no replay recorded
        lines = self.lines()  # tickets[2] has neither version judged
        for version, judged in (("generation-one", 1), ("direct", 0)):
            start = lines.index(version)
            self.assertEqual(lines[start + 4:start + 6], [
                f"  All: {judged} of 3 judged, {judged} of {judged} right first time, median total tokens "
                f"{100 if judged else 'none'}, median active minutes {'10.0' if judged else 'none'}.",
                f"  Left out of every figure: 0 not direct, 1 with no verdict, {2 - judged} judged at a commit the "
                "version does not record."])

    def test_projects_appear_as_labels_only(self) -> None:
        self.world.baseline(20, 20)
        output = self.world.report().stdout
        for secret in (REPO, "alpha", TITLE, session(1), commit(1001)):
            self.assertNotIn(secret, output)

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
        self.assertEqual(lines[start + 4], "  All: 3 of 3 judged, 1 of 3 right first time, median total tokens 40, "
                                           "median active minutes 4.0.")

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
                self.assertEqual(self.world.report().stdout.splitlines()[0], "Replay sets 1 and 2: 60 tickets.")

    def test_the_verdict_waits_for_both_versions_on_every_ticket(self) -> None:
        self.world.baseline(20, 10)
        self.world.verdicts = [line for line in self.world.verdicts
                               if (line["version"], line["ticket"]) not in (("direct", 1), ("generation-one", 2))]
        self.world.verdicts[-1]["right_first_time"] = None
        self.assertEqual(self.lines()[-1],
                         "Warning sign 1: no verdict. Tickets without both generation-one and direct judged: 3 of 30.")

    def test_a_second_set_not_yet_judged_holds_back_the_verdict(self) -> None:
        self.world.baseline(20, 10)
        self.world.draw()
        self.assertEqual(self.lines()[-1],
                         "Warning sign 1: no verdict. Tickets without both generation-one and direct judged: 30 of 60.")

    def test_lines_for_a_ticket_in_no_set_are_left_out_and_counted(self) -> None:
        self.world.baseline(20, 15)
        stray = {**self.world.sets[0][0], "ticket": 99, "ready_commit": commit(99), "session": session(99)}
        self.world.run("generation-one", stray, False)
        self.world.run("direct", stray, True)
        lines = self.lines()
        self.assertEqual(lines[:2], ["Replay set 1: 30 tickets.",
                                     "Left out: 3 lines of versions.jsonl and verdicts.jsonl name a ticket in no set."])
        self.assertEqual(lines[-1], "The sign appears.")

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

    def test_missing_versions_verdicts_and_rows_are_nothing_judged_yet(self) -> None:
        self.world.draw()
        result = self.world.report(save=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines()[-1],
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
            ("replay-set-2.json", "copy", "replay-set-2.json: ticket entry 1: a second line for the same label, "
                                          "ticket."),
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
                                                            "and the verdict on")
        for args in (["--set", "1"], ["extra"], ["--help", "extra"]):
            with self.subTest(args=args):
                result = self.world.report(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertEqual(result.stderr.splitlines()[0], "Print the comparison between versions on the "
                                                                "replay set and the verdict on")


if __name__ == "__main__":
    unittest.main()
