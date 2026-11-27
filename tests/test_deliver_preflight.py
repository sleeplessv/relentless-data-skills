"""The preflight runner and its stack settings check.

The runner's order is tested on stand-in checks in this process; everything else runs
`deliver.py preflight` at its command line in a throwaway world with a run mark.

    python3 -m unittest tests.test_deliver_preflight
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

preflight = deliver_kit.load("preflight")
MISSING = "no docs/agents/stack.toml: every stack setting has its default"
NO_CHECK = ("check_command is empty in docs/agents/stack.toml, so ready relies on the check plan's commands: "
            "set check_command there to the command that runs this repo's checks")


def without_at(lines: list[dict]) -> list[dict]:
    return [{k: v for k, v in line.items() if k != "at"} for line in lines]


class Runner(unittest.TestCase):
    def test_checks_run_in_list_order_and_end_at_the_first_stop(self):
        called = []

        def check(name, result):
            def run(ctx):
                called.append(name)
                return result
            return run

        stop = preflight.Stop("preflight.bad-settings", "fix it", {"error": "x"})
        checks = [check("a", preflight.Warn("a warns")), check("b", None), check("c", preflight.Warn("c warns")),
                  check("d", stop), check("e", preflight.Warn("e warns"))]
        self.assertEqual(preflight.run_checks(preflight.Context(run=None), checks), (stop, ["a warns", "c warns"]))
        self.assertEqual(called, ["a", "b", "c", "d"])

    def test_all_passing_checks_give_no_stop(self):
        checks = [lambda ctx: None, lambda ctx: preflight.Warn("w")]
        self.assertEqual(preflight.run_checks(preflight.Context(run=None), checks), (None, ["w"]))

    def test_settings_is_the_first_check(self):
        self.assertIs(preflight.CHECKS[0], preflight.check_settings)


class Preflight(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark(run="run-3")
        self.world.probe()
        deliver_kit.github_ok(self.world)

    def stack(self, text: str) -> None:
        (self.world.work / "docs" / "agents").mkdir(parents=True)
        (self.world.work / "docs" / "agents" / "stack.toml").write_text(text, encoding="utf-8")

    def record(self, result, stops=(), warnings=(), guard_probe="seen", permission_mode="default"):
        return {"event": "preflight", "run": "run-3", "result": result, "stops": list(stops),
                "warnings": list(warnings), "guard_probe": guard_probe, "permission_mode": permission_mode,
                "harness": "claude-code"}

    def test_clean_run_prints_one_line_and_saves_a_pass(self):
        self.stack('check_command = "make check"\n')
        result = self.world.deliver("preflight")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "Preflight passed.\n", ""))
        records = self.world.records()
        self.assertRegex(records[0]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(without_at(records), [self.record("pass")])
        self.assertEqual(self.world.state_lines("preflight-stops.jsonl"), [])

    def test_missing_stack_settings_warns(self):
        result = self.world.deliver("preflight")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f"warning: {MISSING}\nwarning: {NO_CHECK}\nPreflight passed.\n", ""))
        self.assertEqual(without_at(self.world.records()), [self.record("pass", warnings=[MISSING, NO_CHECK])])

    def test_preflight_bad_settings(self):
        self.stack("check_slots = 'two'\n")
        result = self.world.deliver("preflight")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            10,
            "REFUSED preflight.bad-settings: the stack settings cannot be read: "
            "docs/agents/stack.toml: check_slots must be int\n"
            "Next: fix docs/agents/stack.toml, then run deliver.py preflight\n",
            "",
        ))
        self.assertEqual(without_at(self.world.records()), [self.record("stop", stops=["preflight.bad-settings"], guard_probe="missing", permission_mode=None)])
        stops = self.world.state_lines("preflight-stops.jsonl")
        self.assertRegex(stops[0]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(without_at(stops), [{"run": "run-3", "code": "preflight.bad-settings", "harness": "claude-code"}])

    def test_each_run_appends_one_record(self):
        self.world.deliver("preflight")
        self.stack("[small_edit\n")
        self.world.deliver("preflight")
        self.assertEqual([r["result"] for r in self.world.records()], ["pass", "stop"])
        self.assertEqual(len(self.world.state_lines("preflight-stops.jsonl")), 1)

    def test_arguments_exit_2_with_usage(self):
        result = self.world.deliver("preflight", "--now")
        usage = deliver_kit.load("deliver").USAGE
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, "", f"deliver.py: preflight takes no arguments, got: --now\n\n{usage}\n"))
        self.assertEqual(self.world.records(), [])


if __name__ == "__main__":
    unittest.main()
