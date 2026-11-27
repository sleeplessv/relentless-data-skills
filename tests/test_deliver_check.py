"""deliver.py check: the saved check record, commit pinning, selected nothing and the slot.

Every test runs deliver.py at its command line in a throwaway world from tests/deliver_kit.py, except
the matcher's measure, which also calls `check.selected_nothing` directly. The slot tests order
their children with named pipes the commands write and read, and never sleep or poll.

    python3 -m unittest tests.test_deliver_check
"""
from __future__ import annotations

import errno
import os
import re
import shlex
import signal
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

AT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
WAITING = "Waiting for a check slot.\n"

# The measure the matcher is held to, from the ticket snapshot's author decision D1.
SELECTED_NOTHING = [
    "Ran 0 tests in 0.000s",
    "============================ no tests ran in 0.01s =============================",
    "no tests ran in 0.12s",
    "12:00:01  Nothing to do. Try checking your model configs and model specification args",
    "[WARNING]: Nothing to do. Try checking your model configs and model specification args",
    "WARNING: Nothing to do. Try checking your model configs and model specification args",
    "[warning] [NoNodesSelected (dbt1601)]: Nothing to do. Try checking your model configs and model specification args",
    "\x1b[33m=== \x1b[33mno tests ran\x1b[0m\x1b[33m in 0.00s\x1b[0m\x1b[33m ===\x1b[0m",
    "\x1b[0m12:00:01  \x1b[33mNothing to do.\x1b[0m Try checking your model configs",
]
SELECTED_SOMETHING = [
    "Ran 10 tests in 0.010s",
    "Ran 1 test in 0.001s",
    "Ran 100 tests in 2.5s",
    "test_ran_0_tests (tests.test_x.T.test_ran_0_tests) ... ok",
    "echo Ran 0 tests in a dry run",
    'assert "no tests ran" in out',
    "==== 3 passed in 0.10s ====",
    "1 deselected in 0.01s",
    "nothing to do",
    "make: Nothing to be done for 'all'.",
    "Nothing to do here",
    "assert out == 'Nothing to do.'",
    "{'msg': 'Nothing to do.'}",
    "12:00:01  Done. PASS=3 WARN=0 ERROR=0 SKIP=0 TOTAL=3",
]


class Saved(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark()
        self.head = self.world.git(self.world.work, "rev-parse", "HEAD")

    def check(self, *command: str):
        return self.world.deliver("check", "--", *command)

    def output_file(self, name: str) -> str:
        common = self.world.work / ".git" / "deliver" / "branches" / "main"
        return (common / name).read_text(encoding="utf-8")

    def assert_record(self, record: dict, **fields):
        self.assertEqual(list(record), ["event", "at", "command", "exit", "output", "commit", "selected_nothing",
                                        "slot_wait_s"])
        self.assertRegex(record["at"], AT)
        self.assertIsInstance(record["slot_wait_s"], float)
        self.assertEqual({k: v for k, v in record.items() if k not in ("at", "slot_wait_s")}, {"event": "check", **fields})

    def test_a_passing_check_is_saved_with_every_field(self):
        result = self.check("echo out; echo err >&2")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f"out\nerr\nSaved check checks/1.txt: exit 0, at {self.head[:7]}.\n", ""))
        [record] = self.world.records()
        self.assert_record(record, command="echo out; echo err >&2", exit=0, output="checks/1.txt", commit=self.head,
                           selected_nothing=False)
        self.assertEqual(self.output_file("checks/1.txt"), "out\nerr\n")

    def test_a_failing_check_is_saved_and_ends_in_exit_0(self):
        result = self.check("echo broken; exit 3")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f"broken\nSaved check checks/1.txt: exit 3, at {self.head[:7]}.\n", ""))
        [record] = self.world.records()
        self.assert_record(record, command="echo broken; exit 3", exit=3, output="checks/1.txt", commit=self.head,
                           selected_nothing=False)

    def test_every_run_is_saved_to_its_own_output_file(self):
        self.check("echo one")
        self.check("printf two")
        self.assertEqual([(r["command"], r["output"]) for r in self.world.records()],
                         [("echo one", "checks/1.txt"), ("printf two", "checks/2.txt")])
        self.assertEqual((self.output_file("checks/1.txt"), self.output_file("checks/2.txt")), ("one\n", "two"))

    def test_several_arguments_are_saved_as_one_quoted_command(self):
        args = ["python3", "-c", "print('a b')"]
        result = self.check(*args)
        self.assertEqual(result.stdout, f"a b\nSaved check checks/1.txt: exit 0, at {self.head[:7]}.\n")
        self.assertEqual(self.world.records()[0]["command"], shlex.join(args))
        self.check(shlex.join(args))
        self.assertEqual(self.world.records()[1]["command"], self.world.records()[0]["command"])

    def test_a_changed_tracked_file_ties_the_check_to_no_commit(self):
        (self.world.work / "README.md").write_text("changed\n", encoding="utf-8")
        result = self.check("true")
        self.assertEqual(result.stdout, "Saved check checks/1.txt: exit 0, tied to no commit.\n")
        self.assertIsNone(self.world.records()[0]["commit"])

    def test_a_command_that_changes_a_tracked_file_ties_the_check_to_no_commit(self):
        result = self.check("echo changed > README.md")
        self.assertEqual(result.stdout, "Saved check checks/1.txt: exit 0, tied to no commit.\n")
        self.assertIsNone(self.world.records()[0]["commit"])

    def test_an_untracked_file_keeps_the_commit(self):
        (self.world.work / ".deliver").mkdir()
        (self.world.work / ".deliver" / "plan.md").write_text("draft\n", encoding="utf-8")
        self.check("true")
        self.assertEqual(self.world.records()[0]["commit"], self.head)

    def test_each_sign_of_selected_nothing_is_saved_as_not_a_pass(self):
        for line in ("Ran 0 tests in 0.000s", "no tests ran in 0.01s",
                     "12:00:01  Nothing to do. Try checking your model configs and model specification args"):
            with self.subTest(line):
                before = len(self.world.records())
                result = self.check(shlex.join(["printf", "%s\n", line]))
                n = before + 1
                self.assertEqual(result.stdout, f"{line}\nSaved check checks/{n}.txt: exit 0, at {self.head[:7]}; "
                                                "it selected nothing, so it is not a pass.\n")
                self.assertTrue(self.world.records()[-1]["selected_nothing"])

    def test_a_real_unittest_run_of_no_test_selected_nothing(self):
        (self.world.root / "empty").mkdir()
        self.check(shlex.join([sys.executable, "-m", "unittest", "discover", "-s", str(self.world.root / "empty")]))
        [record] = self.world.records()
        self.assertEqual((record["exit"], record["selected_nothing"]), (5, True))
        self.assertIn("Ran 0 tests in ", self.output_file("checks/1.txt"))

    def test_a_check_with_no_command_is_a_usage_error(self):
        for args in ((), ("--",), ("echo", "x")):
            with self.subTest(args):
                result = self.world.deliver("check", *args)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.startswith(
                    "deliver.py: check takes a command after --: deliver.py check -- <command>\n\nusage:"))
        self.assertEqual(self.world.records(), [])


class Matcher(unittest.TestCase):
    def test_the_measure(self):
        check = deliver_kit.load("check")
        self.assertEqual([line for line in SELECTED_NOTHING if not check.selected_nothing(line)], [])
        self.assertEqual([line for line in SELECTED_SOMETHING if check.selected_nothing(line)], [])

    def test_a_sign_anywhere_in_the_output_counts(self):
        check = deliver_kit.load("check")
        self.assertTrue(check.selected_nothing("Ran 3 tests in 0.1s\n\nOK\n" + SELECTED_NOTHING[0] + "\n\nNO TESTS RAN\n"))

    def test_the_measure_through_the_command_line(self):
        world = deliver_kit.World(self.addCleanup)
        world.write_mark()
        lines = SELECTED_NOTHING + SELECTED_SOMETHING
        script = world.root / "lines.txt"
        for line in lines:
            script.write_text(line + "\n", encoding="utf-8")
            world.deliver("check", "--", f"cat {shlex.quote(str(script))}")
        self.assertEqual([r["selected_nothing"] for r in world.records()],
                         [True] * len(SELECTED_NOTHING) + [False] * len(SELECTED_SOMETHING))


class Slot(unittest.TestCase):
    """Two checks at once, ordered by named pipes: a holder's command writes `<name>-started`
    when it runs and then waits to read `<name>-go`."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark()
        self.order = self.world.root / "order.txt"

    def popen(self, name: str, command: str, stderr=None) -> subprocess.Popen:
        out = (self.world.root / f"{name}.out").open("w")
        self.addCleanup(out.close)
        proc = subprocess.Popen(
            [sys.executable, str(deliver_kit.DELIVER), "check", "--", command], cwd=self.world.work,
            env=self.world.env(), stdout=out, stderr=stderr or out, text=True,
        )
        self.addCleanup(self.stop, proc)
        return proc

    @staticmethod
    def stop(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.stderr:
            proc.stderr.close()

    def release(self, go: Path) -> None:
        """Let a holder's command finish, if its reader is still there."""
        try:
            fd = os.open(go, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno != errno.ENXIO:
                raise
            return
        os.write(fd, b"go\n")
        os.close(fd)

    def hold(self, name: str) -> tuple[subprocess.Popen, Path]:
        """Start a check whose command holds the slot until released; return once it runs."""
        started, go = self.world.root / f"{name}-started", self.world.root / f"{name}-go"
        os.mkfifo(started)
        os.mkfifo(go)
        self.addCleanup(self.release, go)
        command = (f"echo {name} >> {self.order}; echo up > {started}; cat {go} > /dev/null; "
                   f"echo {name}-end >> {self.order}")
        proc = self.popen(name, command)
        with started.open() as f:
            self.assertEqual(f.read(), "up\n")
        return proc, go

    def second(self) -> subprocess.Popen:
        """Start a check that cannot run until the slot is free; return once it waits."""
        proc = self.popen("b", f"echo b >> {self.order}", stderr=subprocess.PIPE)
        self.assertEqual(proc.stderr.readline(), WAITING)
        return proc

    def test_two_checks_at_once_with_one_slot_run_one_after_the_other(self):
        first, go = self.hold("a")
        second = self.second()
        self.release(go)
        self.assertEqual((first.wait(), second.wait()), (0, 0))
        self.assertEqual(self.order.read_text(encoding="utf-8"), "a\na-end\nb\n")
        self.assertEqual([r["command"].split(" ")[1] for r in self.world.records()], ["a", "b"])

    def test_a_killed_holder_frees_the_slot(self):
        first, _ = self.hold("a")
        second = self.second()
        first.send_signal(signal.SIGKILL)
        self.assertEqual(first.wait(), -signal.SIGKILL)
        self.assertEqual(second.wait(), 0)
        self.assertEqual(self.order.read_text(encoding="utf-8"), "a\nb\n")
        self.assertEqual([r["command"] for r in self.world.records()], [f"echo b >> {self.order}"])

    def test_check_slots_above_1_without_ports_command_is_one_slot(self):
        self.write_settings("check_slots = 2\n")
        first, go = self.hold("a")
        second = self.second()
        self.release(go)
        self.assertEqual((first.wait(), second.wait()), (0, 0))
        self.assertEqual(self.order.read_text(encoding="utf-8"), "a\na-end\nb\n")

    def test_check_slots_with_ports_command_runs_two_at_once(self):
        self.write_settings('check_slots = 2\nports_command = "echo 47970"\n')
        first, go = self.hold("a")
        second = self.world.deliver("check", "--", f"echo b >> {self.order}")
        self.release(go)
        self.assertEqual((second.returncode, second.stderr, first.wait()), (0, "", 0))
        self.assertEqual(self.order.read_text(encoding="utf-8"), "a\nb\na-end\n")

    def write_settings(self, text: str) -> None:
        path = self.world.work / "docs" / "agents" / "stack.toml"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
        self.world.git(self.world.work, "add", "docs")
        self.world.git(self.world.work, "commit", "-q", "-m", "settings")

    def test_the_slot_lock_is_in_the_machine_directory(self):
        self.world.deliver("check", "--", "true")
        self.assertEqual(sorted(p.name for p in self.world.state.iterdir()), ["check-slot-0.lock"])


if __name__ == "__main__":
    unittest.main()
