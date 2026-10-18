"""Execute the `gh` blocks documented in candidate-to-spec against a recording stand-in.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

The git-sequence tests drop `gh` lines because they cannot run offline. The
candidate-to-spec commands are all `gh`, so this file puts a fake `gh` first on
PATH that logs every argument, hands out issue URLs, and fails on request. Each
documented block is run whole, as one `bash` call, exactly as the reference tells
the worker to run it, so the tests see the block's own stop-on-failure behaviour
rather than a guard the harness adds. The tests check that a block derives the
issue number from the create URL, passes it to every later call, stops at the
first failure, handles zero-or-many items, and names every variable it uses.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from test_skill_git_sequences import BASH, GIT, Sandbox, doc_block, fenced_blocks

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "candidate-to-spec"
SPEC_TICKETS = SKILL_DIR / "references" / "spec-and-tickets.md"
WORKERS = SKILL_DIR / "references" / "workers.md"

# Every argument is logged %q-quoted, one call per line, so argument boundaries
# survive spaces. GH_FAIL="issue create" fails that subcommand; GH_CREATE_URL
# (set, even empty) replaces the URL `issue create` prints; GH_COMMENT_BODIES is what
# `issue view --json comments --jq .comments[].body` prints. --body-file must name a
# non-empty file.
GH_SHIM = r"""#!/bin/bash
{ printf '%q ' "$@"; printf '\n'; } >> "$GH_LOG"
if [ -n "${GH_FAIL:-}" ] && [ "$1 $2" = "$GH_FAIL" ]; then
  echo "gh: $GH_FAIL failed on request" >&2
  exit 1
fi
prev=""
for a in "$@"; do
  if [ "$prev" = "--body-file" ]; then
    [ -f "$a" ] || { echo "open $a: no such file or directory" >&2; exit 1; }
    [ -s "$a" ] || { echo "GraphQL: Body cannot be blank" >&2; exit 1; }
  fi
  prev="$a"
done
case "$1 $2" in
  "issue create")
    n=$(cat "$GH_COUNTER"); n=$((n + 1)); echo "$n" > "$GH_COUNTER"
    echo "${GH_CREATE_URL-https://github.com/o/r/issues/$n}" ;;
  "issue comment"|"issue edit"|"issue view"|"issue close")
    [[ "$3" =~ ^[0-9]+$ ]] || { echo "invalid issue: '$3'" >&2; exit 1; }
    case "$*" in
      *"--json url"*) echo "https://github.com/o/r/issues/$3" ;;
      *"--json labels,parent,blockedBy"*)
        echo '{"labels":[{"name":"ready-for-agent"}],"parent":{"number":42},"blockedBy":[]}' ;;
      *"--json labels,state"*) echo '{"labels":[],"state":"OPEN"}' ;;
      *"--json comments --jq .comments[].body"*) printf '%s\n' "${GH_COMMENT_BODIES-}" ;;
      *"--json state,stateReason,"*)
        echo '{"state":"OPEN","stateReason":"REOPENED","labels":[{"name":"needs-triage"}],"subIssues":[],"closedByPullRequestsReferences":[]}' ;;
    esac ;;
  "label list")
    printf 'spec\nready-for-agent\n' ;;
esac
exit 0
"""


@dataclass
class ScriptRun:
    rc: int
    out: str
    err: str
    calls: List[List[str]]

    def subcommands(self) -> List[str]:
        return [" ".join(c[:2]) for c in self.calls]


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

    def test_every_multi_line_block_stops_at_the_first_failure(self):
        """The preamble promises `set -euo pipefail`; each multi-line block opens with it."""
        for path in (SPEC_TICKETS, WORKERS):
            for block in fenced_blocks(path.read_text(encoding="utf-8")):
                lines = [line for line in block.splitlines() if line.strip()]
                if len(lines) > 1:
                    self.assertEqual(lines[0], "set -euo pipefail", f"{path.name}: {block}")


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
        self.run_dir = self.sb.root / "run"
        self.work = self.run_dir / "order-intake"
        self.deferred_dir = self.work / "deferred"
        self.deferred_dir.mkdir(parents=True)
        self.files: Dict[str, str] = {}
        for name in ("BODY", "LOG", "REASON", "BREAKDOWN", "TICKET_BODY"):
            path = self.work / f"{name.lower()}.md"
            path.write_text(f"{name} text\n", encoding="utf-8")
            self.files[name] = str(path)
        self.env = {
            "PATH": f"{shim_dir}{os.pathsep}{self.sb.env['PATH']}",
            "GH_LOG": str(self.log),
            "GH_COUNTER": str(self.counter),
            "RUN": str(self.run_dir),
            "DEFERRED_DIR": str(self.deferred_dir),
            "TITLE": "Deepen X: y",
            "TICKET_TITLE": "Expand",
            "EDGES": "native",
            "BLOCKED_BY": "",
            **self.files,
        }

    def deferred_file(self, slug: str) -> str:
        path = self.deferred_dir / f"{slug}.md"
        path.write_text(f"## Deferred candidate: {slug}\n\nbody\n", encoding="utf-8")
        return str(path)

    def run_script(self, block: str, extra: Optional[Dict[str, str]] = None,
                   unset: Optional[List[str]] = None) -> ScriptRun:
        """Run `block` whole, as one bash call with the variables in the environment."""
        script = self.sb.root / "block.sh"
        script.write_text(block + "\n", encoding="utf-8")
        env = dict(self.sb.env)
        env.update(self.env)
        env.update(extra or {})
        for name in unset or []:
            env.pop(name, None)
        proc = subprocess.run([BASH, "--noprofile", "--norc", str(script)], cwd=str(self.work),
                              env=env, capture_output=True, text=True)
        calls = []
        if self.log.exists():
            calls = [shlex.split(line) for line in
                     self.log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return ScriptRun(proc.returncode, proc.stdout, proc.stderr, calls)

    def run_block(self, heading: str, marker: str, extra: Optional[Dict[str, str]] = None,
                  unset: Optional[List[str]] = None) -> ScriptRun:
        return self.run_script(doc_block(SPEC_TICKETS, heading, marker), extra, unset)

    # Spec publish

    def test_spec_publish_derives_issue_number_from_create_url(self):
        run = self.run_block("Spec", "gh issue create")
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [
            ["issue", "create", "--title", "Deepen X: y", "--label", "spec",
             "--label", "needs-triage", "--body-file", self.files["BODY"]],
            ["issue", "comment", "42", "--body-file", self.files["LOG"]],
        ], "no deferred file, so no deferred comment")

    def test_spec_publish_posts_each_deferred_file(self):
        first = self.deferred_file("a-billing")
        second = self.deferred_file("b-shipping")
        run = self.run_block("Spec", "gh issue create")
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls[2:], [
            ["issue", "comment", "42", "--body-file", first],
            ["issue", "comment", "42", "--body-file", second],
        ])

    def test_spec_publish_edits_a_reopened_spec_in_place(self):
        self.deferred_file("a-billing")
        run = self.run_block("Spec", "gh issue create", {"SPEC_N": "17"})
        self.assertEqual(run.rc, 0, run)
        self.assertNotIn("issue create", run.subcommands())
        self.assertEqual(run.calls[0], ["issue", "edit", "17", "--body-file", self.files["BODY"],
                                        "--add-label", "needs-triage"])
        self.assertEqual(run.calls[1], ["issue", "view", "17", "--json", "url", "--jq", ".url"])
        self.assertEqual(run.calls[2][:3], ["issue", "comment", "17"])
        self.assertEqual(len(run.calls), 4)

    def test_spec_publish_stops_when_create_fails(self):
        self.deferred_file("a-billing")
        run = self.run_block("Spec", "gh issue create", {"GH_FAIL": "issue create"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create"],
                         "no comment is posted to an empty issue number")

    def test_spec_publish_rejects_a_create_url_without_a_number(self):
        for bad in ("https://github.com/o/r/issues/42?foo=1", "https://github.com/o/r/issues/",
                    "", "https://github.com/o/r/issues/42#issue-1"):
            with self.subTest(url=bad):
                self.log.unlink(missing_ok=True)
                run = self.run_block("Spec", "gh issue create", {"GH_CREATE_URL": bad})
                self.assertNotEqual(run.rc, 0, run)
                self.assertIn("bad issue url", run.err)
                self.assertEqual(run.subcommands(), ["issue create"])

    def test_log_with_a_run_directory_path_stops_publish(self):
        Path(self.files["LOG"]).write_text(f"evidence: {self.run_dir}/x.md:3\n", encoding="utf-8")
        run = self.run_block("Spec", "gh issue create")
        self.assertNotEqual(run.rc, 0, run)
        self.assertIn("run directory path", run.err)
        self.assertEqual(run.calls, [])

    # User decision

    def test_approve_flips_labels_on_the_spec(self):
        run = self.run_block("User decision", "ready-for-agent", {"SPEC_N": "42"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [
            ["issue", "edit", "42", "--body-file", self.files["BODY"],
             "--remove-label", "needs-triage", "--add-label", "ready-for-agent"],
            ["issue", "view", "42", "--json", "labels,state"],
        ])

    def test_reject_with_reason_edits_the_body_and_reposts_the_log(self):
        run = self.run_block("User decision", "gh issue edit \"$SPEC_N\" --body-file \"$BODY\"\n",
                             {"SPEC_N": "42"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [
            ["issue", "edit", "42", "--body-file", self.files["BODY"]],
            ["issue", "comment", "42", "--body-file", self.files["LOG"]],
        ])

    def test_reject_closes_as_not_planned_with_the_reason(self):
        run = self.run_block("User decision", "gh issue close", {"SPEC_N": "42"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [
            ["issue", "comment", "42", "--body-file", self.files["REASON"]],
            ["issue", "close", "42", "--reason", "not planned"],
            ["issue", "view", "42", "--json", "labels,state"],
        ])

    def test_reject_with_an_empty_reason_stops_before_close(self):
        Path(self.files["REASON"]).write_text("", encoding="utf-8")
        run = self.run_block("User decision", "gh issue close", {"SPEC_N": "42"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertIn("empty reason", run.err)
        self.assertEqual(run.calls, [])

    # Labels

    def test_label_list_fetches_every_label(self):
        run = self.run_block("Labels", "gh label list")
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.out.split(), ["spec", "ready-for-agent"])
        (call,) = run.calls
        self.assertEqual(call[:2], ["label", "list"])
        self.assertEqual(call[call.index("--limit") + 1], "1000")

    def test_label_create_uses_the_description(self):
        run = self.run_block("Labels", "gh label create",
                             {"LABEL": "needs-triage", "DESCRIPTION": "Maintainer evaluates"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [["label", "create", "needs-triage",
                                      "--description", "Maintainer evaluates"]])

    # Tickets

    TICKET_BLOCK = ("Tickets", "--add-blocked-by")

    def ticket_create(self, run: ScriptRun) -> List[str]:
        self.assertEqual(run.subcommands().count("issue create"), 1, run)
        self.assertEqual(run.calls[0], ["issue", "create", "--title", "Expand", "--label",
                                        "ready-for-agent", "--body-file",
                                        self.files["TICKET_BODY"]],
                         "the create carries no edge flags")
        return run.calls[0]

    def test_ticket_publish_without_blockers_sets_only_the_parent(self):
        run = self.run_block(*self.TICKET_BLOCK, {"SPEC_N": "17"})
        self.assertEqual(run.rc, 0, run)
        self.ticket_create(run)
        self.assertEqual(run.calls[1:], [
            ["issue", "edit", "42", "--parent", "17"],
            ["issue", "view", "42", "--json", "labels,parent,blockedBy"],
        ])

    def test_ticket_publish_with_two_blockers_passes_them_once(self):
        run = self.run_block(*self.TICKET_BLOCK, {"SPEC_N": "17", "BLOCKED_BY": "40,41"})
        self.assertEqual(run.rc, 0, run)
        self.ticket_create(run)
        edit = run.calls[1]
        self.assertEqual(edit[:3], ["issue", "edit", "42"])
        self.assertEqual(edit.count("--add-blocked-by"), 1)
        self.assertEqual(edit[edit.index("--add-blocked-by") + 1], "40,41")
        self.assertEqual(edit[edit.index("--parent") + 1], "17")
        self.assertEqual(run.calls[2][:3], ["issue", "view", "42"])

    def test_ticket_publish_with_edges_in_the_body_skips_the_edit(self):
        run = self.run_block(*self.TICKET_BLOCK,
                             {"SPEC_N": "17", "BLOCKED_BY": "40,41", "EDGES": "body"})
        self.assertEqual(run.rc, 0, run)
        self.ticket_create(run)
        self.assertEqual(run.subcommands(), ["issue create", "issue view"])

    def test_ticket_publish_rejects_an_unknown_edges_value_before_creating(self):
        run = self.run_block(*self.TICKET_BLOCK, {"SPEC_N": "17", "EDGES": "api"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [])

    def test_ticket_publish_stops_when_create_fails(self):
        run = self.run_block(*self.TICKET_BLOCK, {"SPEC_N": "17", "GH_FAIL": "issue create"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create"], "no edit or view of a missing ticket")

    def test_ticket_publish_edge_failure_leaves_one_ticket(self):
        run = self.run_block(*self.TICKET_BLOCK, {"SPEC_N": "17", "GH_FAIL": "issue edit"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create", "issue edit"])
        self.assertEqual(self.counter.read_text().strip(), "42", "exactly one ticket exists")

    def test_breakdown_comment_lands_on_the_spec(self):
        run = self.run_block("Tickets", "BREAKDOWN", {"SPEC_N": "42"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [["issue", "comment", "42", "--body-file",
                                      self.files["BREAKDOWN"]]])

    # Planner and loader (workers.md)

    DEDUPE_BLOCK = ("Planning", "grep -qxF")

    def test_planner_reads_the_spec_state(self):
        run = self.run_script(doc_block(WORKERS, "Planning", "closedByPullRequestsReferences"),
                              {"SPEC_N": "42"})
        self.assertEqual(run.rc, 0, run)
        (call,) = run.calls
        self.assertEqual(call[:4], ["issue", "view", "42", "--json"])
        fields = set(call[4].split(","))
        self.assertTrue({"state", "stateReason", "labels", "subIssues",
                         "closedByPullRequestsReferences"} <= fields, call)
        self.assertIn('"stateReason":"REOPENED"', run.out)

    def test_loader_reads_the_comment_bodies(self):
        bodies = "## Deferred candidate: a-billing\n\nbody\n"
        run = self.run_script(doc_block(WORKERS, "Candidate file", "comments"),
                              {"SPEC_N": "42", "GH_COMMENT_BODIES": bodies})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [["issue", "view", "42", "--json", "comments",
                                      "--jq", ".comments[].body"]])
        self.assertEqual(run.out.splitlines()[0], "## Deferred candidate: a-billing")

    def test_planner_posts_a_deferred_file_whose_heading_is_absent(self):
        deferred = self.deferred_file("a-billing")
        run = self.run_script(doc_block(WORKERS, *self.DEDUPE_BLOCK),
                              {"SPEC_N": "42", "DEFERRED": deferred,
                               "GH_COMMENT_BODIES": "## Deferred candidate: other\n\nx\n"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue view", "issue comment"])
        self.assertEqual(run.calls[1], ["issue", "comment", "42", "--body-file", deferred])

    def test_planner_skips_a_deferred_file_already_posted(self):
        deferred = self.deferred_file("a-billing")
        run = self.run_script(doc_block(WORKERS, *self.DEDUPE_BLOCK),
                              {"SPEC_N": "42", "DEFERRED": deferred,
                               "GH_COMMENT_BODIES": "## Deferred candidate: a-billing\n\nx\n"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue view"])

    def test_planner_dedupe_fails_on_an_unset_deferred_file(self):
        run = self.run_script(doc_block(WORKERS, *self.DEDUPE_BLOCK), {"SPEC_N": "42"},
                              unset=["DEFERRED"])
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [])


    def test_planner_searches_prior_specs_by_slug_marker(self):
        run = self.run_script(doc_block(WORKERS, "Planning", "gh issue list"),
                              {"SLUG": "order-intake"})
        self.assertEqual(run.rc, 0, run)
        (call,) = run.calls
        self.assertEqual(call[:2], ["issue", "list"])
        self.assertIn("--label", call)
        self.assertEqual(call[call.index("--label") + 1], "spec")
        self.assertIn('"candidate: order-intake"', call[call.index("--search") + 1])


if __name__ == "__main__":
    unittest.main()
