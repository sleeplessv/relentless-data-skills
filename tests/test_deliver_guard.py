"""The guard hook, its registration, its refusal log, and preflight's guard probe check.

The guard runs as Claude Code runs it: a subprocess with a hook input on standard input. The
inputs in `deliver_guard_inputs/` were recorded from Claude Code 2.1.330 (the harness-guards
research, #213): `session.json` is the session's own call, `agent.json` an agent's call, which
carries `agent_id`, and `session-bypass.json` a session call in bypass mode. Ids and paths are
replaced; each test sets `cwd` and the command. `one-way-commands.json` holds the commands
#409's reviewers probed the one-way list with, each with the verdict of the 31ea0e2 list.

    python3 -m unittest tests.test_deliver_guard
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

INPUTS = Path(__file__).resolve().parent / "deliver_guard_inputs"

# Commands the 31ea0e2 list caught that the list now lets through on purpose, settled in #409
# (PR #432): text inside closed quotes is not a command, a mention of production is not a target,
# and a command wrapped in `bash -c`, `sh -c` or `ssh` passes, as the hook stops habit only.
SETTLED = {
    "git commit -m 'fix prod bug'": "a mention of production",
    "echo production": "a mention of production",
    'echo "git push --force"': "quoted text",
    "echo 'gh release create' ": "quoted text",
    'bash -c "git push --force"': "a wrapped command",
    "sh -c 'npm publish'": "a wrapped command",
    'ssh host "docker push x"': "a wrapped command",
}


def one_way(command: str) -> bool:
    patterns = deliver_kit.load("settings").read_lists()["one_way_commands"]
    return any(re.search(p, command) for p in patterns)


class OneWayList(unittest.TestCase):
    """The measure fixed for #412: the list fails safe against the 31ea0e2 list."""

    def test_nothing_the_31ea0e2_list_caught_is_missed(self):
        rows = json.loads((INPUTS / "one-way-commands.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 101)
        missed = [r["command"] for r in rows if r["old"] and r["command"] not in SETTLED and not one_way(r["command"])]
        self.assertEqual(missed, [])
        self.assertEqual(sorted(c for c in SETTLED if not one_way(c)), sorted(SETTLED))

    def test_a_one_way_command_in_a_substitution_inside_double_quotes_is_caught(self):
        commands = ['url="$(gh release create v1.2)"', 'out="$(git push --force origin main 2>&1)"',
                    'echo "`git push -f origin "main"`"', 'log="$(npm publish --tag "next" 2>&1)"']
        self.assertEqual({c: one_way(c) for c in commands}, dict.fromkeys(commands, True))


if __name__ == "__main__":
    unittest.main()
