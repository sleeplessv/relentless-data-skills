"""Execute the `gh` sequences documented in candidate-to-spec against a recording stand-in.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

The git-sequence tests drop `gh` lines because they cannot run offline. The
candidate-to-spec commands are all `gh`, so this file puts a fake `gh` first on
PATH that logs every call, hands out issue URLs and database ids, and fails on
request. The tests then check that the documented sequence derives the issue
number from the create URL, passes it to every later call, stops at the first
failure, and names every variable it uses.
"""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from typing import Dict, List

from test_skill_git_sequences import (BASH, GIT, Sandbox, doc_block, fenced_blocks,
                                      split_commands)

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "candidate-to-spec"
SPEC_TICKETS = SKILL_DIR / "references" / "spec-and-tickets.md"
WORKERS = SKILL_DIR / "references" / "workers.md"

GH_SHIM = r"""#!/bin/bash
printf '%s\n' "$*" >> "$GH_LOG"
if [ -n "$GH_FAIL" ] && [ "$1 $2" = "issue create" ]; then
  echo "could not add label: 'needs-triage' not found" >&2
  exit 1
fi
case "$1 $2" in
  "issue create")
    n=$(cat "$GH_COUNTER"); n=$((n + 1)); echo "$n" > "$GH_COUNTER"
    echo "https://github.com/o/r/issues/$n" ;;
  "label list")
    printf 'spec\nready-for-agent\n' ;;
  api*)
    if [ "$3" = "--jq" ]; then n=${2##*/}; echo $((1000 + n)); fi ;;
esac
exit 0
"""


def variables_used(block: str) -> List[str]:
    return sorted(set(re.findall(r"\$\{?([A-Z][A-Z_]*)", block)))


def declared_variables(md_text: str) -> List[str]:
    return sorted(set(re.findall(r"`([A-Z][A-Z_]+)`", md_text)))


@unittest.skipUnless(GIT and BASH, "git and bash are required")
class VariableNamingTests(unittest.TestCase):
    """CS2: every shell command names the variables it uses."""

    def check(self, path: Path):
        text = path.read_text(encoding="utf-8")
        declared = set(declared_variables(text))
        for block in fenced_blocks(text):
            for var in variables_used(block):
                self.assertIn(var, declared, f"{path.name}: ${var} is used but never named")

    def test_spec_and_tickets_names_every_variable(self):
        self.check(SPEC_TICKETS)

    def test_workers_names_every_variable(self):
        self.check(WORKERS)


@unittest.skipUnless(GIT and BASH, "git and bash are required")
class GhSequenceTests(unittest.TestCase):

    def setUp(self):
        self.sb = Sandbox(self)
        shim_dir = self.sb.root / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "gh"
        shim.write_text(GH_SHIM, encoding="utf-8")
        shim.chmod(0o755)
        self.log = self.sb.root / "gh.log"
        self.counter = self.sb.root / "counter"
        self.counter.write_text("41\n", encoding="utf-8")
        self.work = self.sb.root / "work"
        self.work.mkdir()
        self.files: Dict[str, str] = {}
        for name in ("BODY", "LOG", "DEFERRED", "REASON", "BREAKDOWN", "TICKET_BODY"):
            path = self.work / f"{name.lower()}.md"
            path.write_text(f"{name} text\n", encoding="utf-8")
            self.files[name] = str(path)
        self.env = {
            "PATH": f"{shim_dir}{os.pathsep}{self.sb.env['PATH']}",
            "GH_LOG": str(self.log),
            "GH_COUNTER": str(self.counter),
            **self.files,
        }

    def calls(self) -> List[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def run_block(self, heading: str, marker: str, extra: Dict[str, str] = None):
        cmds = split_commands(doc_block(SPEC_TICKETS, heading, marker))
        env = dict(self.env)
        env.update(extra or {})
        return cmds, self.sb.run(self.work, cmds, env)

    def test_spec_publish_derives_issue_number_from_create_url(self):
        cmds, run = self.run_block("Spec", "gh issue create", {"TITLE": "Deepen X: y"})
        self.assertTrue(run.completed, run)
        calls = self.calls()
        self.assertEqual(calls[0], f"issue create --title Deepen X: y --label spec "
                                   f"--label needs-triage --body-file {self.files['BODY']}")
        self.assertEqual(calls[1], f"issue comment 42 --body-file {self.files['LOG']}")
        self.assertEqual(calls[2], f"issue comment 42 --body-file {self.files['DEFERRED']}")

    def test_spec_publish_stops_when_create_fails(self):
        cmds, run = self.run_block("Spec", "gh issue create",
                                   {"TITLE": "Deepen X: y", "GH_FAIL": "1"})
        self.assertFalse(run.completed, run)
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.steps[0].rc, 1)
        self.assertEqual(len(self.calls()), 1, "no comment is posted to an empty issue number")

    def test_approve_flips_labels_on_the_spec(self):
        cmds, run = self.run_block("User decision", "ready-for-agent", {"SPEC_N": "42"})
        self.assertTrue(run.completed, run)
        self.assertEqual(self.calls(), [f"issue edit 42 --body-file {self.files['BODY']} "
                                        "--remove-label needs-triage --add-label ready-for-agent",
                                        "issue view 42 --json labels,state"])

    def test_reject_closes_as_not_planned_with_the_reason(self):
        cmds, run = self.run_block("User decision", "gh issue close", {"SPEC_N": "42"})
        self.assertTrue(run.completed, run)
        self.assertEqual(self.calls(), ["issue close 42 --reason not planned --comment REASON text",
                                        "issue view 42 --json labels,state"])

    def test_label_check_and_create(self):
        cmds, run = self.run_block("Labels", "gh label", {"LABEL": "needs-triage",
                                                         "DESCRIPTION": "Maintainer evaluates"})
        self.assertTrue(run.completed, run)
        self.assertEqual(run.steps[0].out.split(), ["spec", "ready-for-agent"])
        self.assertEqual(self.calls()[1], "label create needs-triage --description Maintainer evaluates")

    def test_ticket_publish_uses_database_ids_for_edges(self):
        self.counter.write_text("42\n", encoding="utf-8")
        cmds, run = self.run_block("Tickets", "sub_issues",
                                   {"REPO": "o/r", "SPEC_N": "42", "TICKET_TITLE": "Expand",
                                    "BLOCKER_ID": "1042"})
        self.assertTrue(run.completed, run)
        calls = self.calls()
        self.assertEqual(calls[0], f"issue create --title Expand --label ready-for-agent "
                                   f"--body-file {self.files['TICKET_BODY']}")
        self.assertEqual(calls[1], "api repos/o/r/issues/43 --jq .id")
        self.assertEqual(calls[2], "api --method POST repos/o/r/issues/42/sub_issues -F sub_issue_id=1043")
        self.assertEqual(calls[3], "api --method POST repos/o/r/issues/43/dependencies/blocked_by -F issue_id=1042")
        self.assertEqual(calls[4], "issue view 43 --json labels")

    def test_planner_searches_prior_specs_by_slug_marker(self):
        cmds = split_commands(doc_block(WORKERS, "Planning", "gh issue list"))
        run = self.sb.run(self.work, cmds, {**self.env, "SLUG": "order-intake"})
        self.assertTrue(run.completed, run)
        self.assertEqual(self.calls(), ['issue list --state all --label spec --search '
                                        '"candidate: order-intake" in:body '
                                        '--json number,state,stateReason,url'])

    def test_breakdown_comment_lands_on_the_spec(self):
        cmds, run = self.run_block("Tickets", "BREAKDOWN", {"SPEC_N": "42"})
        self.assertTrue(run.completed, run)
        self.assertEqual(self.calls(), [f"issue comment 42 --body-file {self.files['BREAKDOWN']}"])


if __name__ == "__main__":
    unittest.main()
