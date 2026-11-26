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
Workers often sit in zsh, so the publish blocks also run from zsh through the
quoted heredoc that workers.md prescribes.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
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
ZSH = shutil.which("zsh")

# Every argument is logged %q-quoted, one call per line, so argument boundaries
# survive spaces. GH_FAIL="issue create" fails that subcommand; GH_CREATE_URL
# (set, even empty) replaces the URL `issue create` prints; GH_COMMENT_BODIES is what
# `issue view --json comments --jq .comments[].body` prints. --body-file must name a
# non-empty file.
GH_SHIM = r"""#!/bin/bash
{ printf '%q ' "$@"; printf '\n'; } >> "$GH_LOG"
default_host=${GH_HOST:-github.com}
repo=${GH_REPO:-Acme/Work}
case "$repo" in */*/*) ;; *) repo="$default_host/$repo" ;; esac
if [[ "$1 $2" == "repo view" && -z "${GH_REPO:-}" ]]; then repo="$GH_CHECKOUT_REPO"; fi
if [[ "$1 $2" == "api graphql" ]]; then
  host=$default_host
  name_with_owner=${repo#*/}
  owner="" name=""
  for arg in "$@"; do
    if [[ "${prev:-}" == "--hostname" ]]; then host=$arg; fi
    case "$arg" in
      'owner={owner}') owner=${name_with_owner%/*} ;;
      'name={repo}') name=${name_with_owner#*/} ;;
      owner=*) owner=${arg#owner=} ;;
      name=*) name=${arg#name=} ;;
    esac
    prev=$arg
  done
  repo="$host/$owner/$name"
fi
echo "$repo" >> "$GH_LOG.targets"
counter="$GH_TRACKERS/$repo/counter"
[[ -f "$counter" ]] || { echo "unknown tracker: $repo" >&2; exit 1; }
if [ -n "${GH_FAIL:-}" ] && [ "$1 $2" = "$GH_FAIL" ]; then
  echo "gh: $GH_FAIL failed on request" >&2
  exit 1
fi
if [ "$1 $2" = "issue view" ] && [ -n "${GH_MISSING_FIELDS:-}" ]; then
  for field in ${GH_MISSING_FIELDS//,/ }; do
    if [[ ",$5," == *",$field,"* ]]; then
      echo "GraphQL: Field '$field' doesn't exist on type 'Issue'" >&2
      exit 1
    fi
  done
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
  "repo view")
    [[ "$3 $4 $5 $6" == '--json url,nameWithOwner --jq [.url, .nameWithOwner] | @tsv' ]] || exit 1
    printf 'https://%s\t%s\n' "$repo" "${repo#*/}" ;;
  "api graphql")
    if [[ ",${GH_MISSING_FIELDS:-}," == *,blockedBy,* ]]; then
      echo "GraphQL: Field 'blockedBy' doesn't exist on type 'Issue'" >&2; exit 1
    fi
    for arg in "$@"; do
      if [[ "$arg" == n=* ]]; then
        edges="$counter.${arg#n=}.blockers"
        if [ -f "$edges" ]; then cat "$edges"; fi
      fi
    done ;;
  "issue create")
    n=$(cat "$counter"); n=$((n + 1)); echo "$n" > "$counter"
    echo "${GH_CREATE_URL-https://$repo/issues/$n}" ;;
  "issue comment"|"issue edit"|"issue view"|"issue close")
    [[ "$3" =~ ^[0-9]+$ ]] || { echo "invalid issue: '$3'" >&2; exit 1; }
    case "$*" in
      *"--add-blocked-by "*)
        IFS=, read -ra blockers <<< "$5"
        rc=0
        for n in "${blockers[@]}"; do
          if [ "$n" = "${GH_FAIL_BLOCKER:-}" ]; then
            echo "gh: addBlockedBy failed for #$n" >&2; rc=1
          else
            echo "https://$repo/issues/$n" >> "$counter.$3.blockers"
            if [ "$n" = "${GH_LOST_REPLY:-}" ]; then exit 1; fi
          fi
        done
        exit "$rc" ;;
      *"--parent "*) echo "$5" > "$counter.$3.parent" ;;
      *"--json url"*) echo "${GH_VIEW_URL-https://$repo/issues/$3}" ;;
      *"--json labels,parent,blockedBy"*)
        python3 - "$counter.$3.blockers" "$counter.$3.parent" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
nodes = [{"number": int(url.rsplit("/", 1)[1]), "url": url}
         for url in (path.read_text().splitlines() if path.exists() else [])]
parent = Path(sys.argv[2])
print(json.dumps({"labels": [{"name": "ready-for-agent"}],
                  "parent": {"number": int(parent.read_text())} if parent.exists() else None,
                  "blockedBy": {"nodes": nodes, "totalCount": len(nodes)}}))
PY
        ;;
      *"--json labels,parent,body"*)
        echo '{"labels":[{"name":"ready-for-agent"}],"parent":{"number":17},"body":"## Blocked by\n#40\n#41"}' ;;
      *"--json labels,body"*)
        echo '{"labels":[{"name":"ready-for-agent"}],"body":"## Parent\n#17\n## Blocked by\n#40\n#41"}' ;;
      *"--json labels,state"*) echo '{"labels":[],"state":"OPEN"}' ;;
      *"--json comments --jq .comments[].body"*) printf '%s\n' "${GH_COMMENT_BODIES-}" ;;
      *"--json state,stateReason,labels")
        echo '{"state":"OPEN","stateReason":"REOPENED","labels":[{"name":"needs-triage"}]}' ;;
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

    def test_no_block_relies_on_word_splitting(self):
        """zsh keeps an unquoted `${VAR:+flag "$VAR"}` as one word, so a flag and its value fuse."""
        for path in (SPEC_TICKETS, WORKERS):
            for block in fenced_blocks(path.read_text(encoding="utf-8")):
                self.assertIsNone(re.search(r"\$\{[A-Z_]+:\+[^}]*\s", block),
                                  f"{path.name}: {block}")

    def test_workers_prescribes_the_quoted_heredoc(self):
        self.assertIn("bash <<'EOF'", WORKERS.read_text(encoding="utf-8"))


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
        self.repo = "git.example.test/Acme/Work"
        self.default_repo = "github.com/Acme/Work"
        self.issue_prefix = f"https://{self.repo}/issues"
        trackers = self.sb.root / "trackers"
        for repo in (self.repo, self.default_repo):
            directory = trackers / repo
            directory.mkdir(parents=True)
            (directory / "counter").write_text("41\n", encoding="utf-8")
        self.counter = trackers / self.repo / "counter"
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
            "GH_HOST": "github.com",
            "GH_TRACKERS": str(trackers),
            "GH_CHECKOUT_REPO": self.repo,
            "RUN": str(self.run_dir),
            "DEFERRED_DIR": str(self.deferred_dir),
            "TITLE": "Deepen X: y",
            "TICKET_TITLE": "Expand",
            "TICKET_LABEL": "ready-for-agent",
            "EDGES": "native",
            "BLOCKED_BY": "",
            **self.files,
        }

    def deferred_file(self, slug: str) -> str:
        path = self.deferred_dir / f"{slug}.md"
        path.write_text(f"## Deferred candidate: {slug}\n\nbody\n", encoding="utf-8")
        return str(path)

    def worker_script(self, block, variables, repo):
        template, = (b for b in fenced_blocks(WORKERS.read_text(), langs=("text",))
                     if b.startswith("bash <<'EOF'"))
        return (template.replace("<repository root>", str(self.work))
                .replace("<host/owner/repo>", repo)
                .replace("<candidate-to-spec root>", str(SKILL_DIR))
                .replace("<variable assignments>", "\n".join(
                    f"{name}={shlex.quote(value)}" for name, value in variables.items()))
                .replace("<the block>", block))

    def run_script(self, block: str, extra: Optional[Dict[str, str]] = None,
                   unset: Optional[List[str]] = None, *, shell=BASH, variables=None,
                   repo=None, setup=False, args=()) -> ScriptRun:
        """Execute the actual setup block or worker heredoc with an isolated CLI."""
        script = self.sb.root / "block.sh"
        if not setup:
            block = self.worker_script(block, variables or {}, self.repo if repo is None else repo)
        script.write_text(block + "\n", encoding="utf-8")
        env = dict(self.sb.env)
        env.update(self.env)
        env.update(extra or {})
        for name in unset or []:
            env.pop(name, None)
        proc = subprocess.run([shell, str(script), *args], cwd=str(self.work),
                              env=env, capture_output=True, text=True)
        calls = []
        if self.log.exists():
            calls = [shlex.split(line) for line in
                     self.log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return ScriptRun(proc.returncode, proc.stdout, proc.stderr, calls)

    def run_block(self, heading: str, marker: str, extra: Optional[Dict[str, str]] = None,
                  unset: Optional[List[str]] = None) -> ScriptRun:
        return self.run_script(doc_block(SPEC_TICKETS, heading, marker), extra, unset)

    def run_from_zsh(self, block: str, variables: Dict[str, str]) -> ScriptRun:
        return self.run_script(block, shell=ZSH, unset=list(variables), variables=variables)

    def setup_tracker(self, saved="", *records, override=None):
        context = {"GH_REPO": override} if override else {}
        return self.run_script(doc_block(WORKERS, "Tracker setup", "resolve_tracker"),
                               {**context, "SAVED_REPO": saved,
                                "TRACKER_SH": str(SKILL_DIR / "scripts" / "tracker.sh")},
                               setup=True, args=records)

    def targets(self):
        return self.log.with_suffix(".log.targets").read_text().splitlines()

    def test_setup_and_legacy_resume_select_the_checkout_tracker(self):
        for saved, records in [("", ()), ("acme/work", (f"{self.issue_prefix}/17", "17",
                                                       f"{self.issue_prefix}/42", "42"))]:
            with self.subTest(saved=saved):
                run = self.setup_tracker(saved, *records)
                self.assertEqual(run.rc, 0, run)
                self.assertEqual(run.out.strip(), self.repo)
        self.assertEqual(self.targets(), [self.repo, self.repo])

    def test_setup_honors_the_callers_explicit_tracker(self):
        for saved in ("", "Acme/Work"):
            records = (f"https://{self.default_repo}/issues/17", "17") if saved else ()
            setup = self.setup_tracker(saved, *records, override=self.default_repo)
            self.assertEqual(setup.rc, 0, setup)
            self.assertEqual(setup.out.strip(), self.default_repo)
            run = self.run_script(self.ticket_blocks(), {"SPEC_N": "17"}, repo=setup.out.strip())
            self.assertEqual(run.rc, 0, run)
        self.assertEqual(set(self.targets()), {self.default_repo})

    def test_legacy_resume_stops_on_conflicting_or_incomplete_evidence(self):
        spec = (f"{self.issue_prefix}/17", "17")
        for saved, records in [
            ("Acme/Other", spec),
            ("Acme/Work", (*spec, f"https://{self.default_repo}/issues/42", "42")),
            ("Acme/Work", (*spec, f"{self.issue_prefix}/42", "41")),
            ("Acme/Work", (*spec, f"{self.issue_prefix}/42")),
        ]:
            with self.subTest(saved=saved, records=records):
                run = self.setup_tracker(saved, *records)
                self.assertNotEqual(run.rc, 0, run)
                self.assertEqual(run.out, "")
                self.assertEqual(set(run.subcommands()), {"repo view"})

    def test_spec_decision_checks_saved_target_before_edit(self):
        run = self.run_block("User decision", "ready-for-agent", {
            "SPEC_URL": f"https://{self.default_repo}/issues/17", "SPEC_N": "17"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [])

    def test_hostless_worker_stops_before_create(self):
        run = self.run_script(self.ticket_blocks(), {"SPEC_N": "17"}, repo="Acme/Work")
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [])

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
        self.assertEqual(run.calls[1], ["issue", "edit", "17", "--body-file", self.files["BODY"],
                                        "--add-label", "needs-triage"])
        self.assertEqual(run.calls[0], ["issue", "view", "17", "--json", "url", "--jq", ".url"])
        self.assertEqual(run.calls[2][:3], ["issue", "comment", "17"])
        self.assertEqual(len(run.calls), 4)

    def test_reopened_spec_rejects_foreign_view_result_before_edit(self):
        run = self.run_block("Spec", "gh issue create", {
            "SPEC_N": "17", "SPEC_URL": f"{self.issue_prefix}/17",
            "GH_VIEW_URL": f"https://{self.default_repo}/issues/17"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue view"])

    def test_spec_publish_stops_when_create_fails(self):
        self.deferred_file("a-billing")
        run = self.run_block("Spec", "gh issue create", {"GH_FAIL": "issue create"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create"],
                         "no comment is posted to an empty issue number")

    def test_spec_publish_rejects_a_create_url_without_a_number(self):
        for bad in (f"{self.issue_prefix}/42?foo=1", f"{self.issue_prefix}/",
                    "", f"{self.issue_prefix}/42#issue-1", f"https://{self.default_repo}/issues/42"):
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

    @staticmethod
    def ticket_blocks():
        return "\n".join(doc_block(SPEC_TICKETS, "Tickets", marker) for marker in
                         ("gh issue create", "--parent", "--add-blocked-by",
                          'gh issue view "$TICKET_N"'))

    def publish_ticket(self, extra, unset=None):
        return self.run_script(self.ticket_blocks(), extra, unset)

    def ticket_create(self, run: ScriptRun) -> List[str]:
        self.assertEqual(run.subcommands().count("issue create"), 1, run)
        self.assertEqual(run.calls[0], ["issue", "create", "--title", "Expand", "--label",
                                        "ready-for-agent", "--body-file",
                                        self.files["TICKET_BODY"]],
                         "the create carries no edge flags")
        return run.calls[0]

    def test_ticket_publish_without_blockers_sets_only_the_parent(self):
        run = self.publish_ticket({"SPEC_N": "17"})
        self.assertEqual(run.rc, 0, run)
        self.ticket_create(run)
        self.assertEqual(run.calls[1:], [
            ["issue", "edit", "42", "--parent", "17"],
            ["issue", "view", "42", "--json", "labels,parent,blockedBy"],
        ])

    def test_ticket_publish_with_two_blockers_passes_them_once(self):
        run = self.publish_ticket({"SPEC_N": "17", "BLOCKED_BY": "40,41"})
        self.assertEqual(run.rc, 0, run)
        self.ticket_create(run)
        self.assertEqual(run.calls[1], ["issue", "edit", "42", "--parent", "17"])
        self.assertEqual(run.calls[2][:3], ["api", "graphql", "--paginate"])
        self.assertIn("n=42", run.calls[2])
        self.assertEqual(run.calls[3:], [
            ["issue", "edit", "42", "--add-blocked-by", "40"],
            ["issue", "edit", "42", "--add-blocked-by", "41"],
            ["issue", "view", "42", "--json", "labels,parent,blockedBy"],
        ])
        observed = json.loads(run.out.splitlines()[-1])["blockedBy"]
        self.assertEqual(observed["totalCount"], 2)
        self.assertEqual([node["number"] for node in observed["nodes"]], [40, 41])

    def test_ticket_publish_carries_the_human_label(self):
        run = self.publish_ticket({"SPEC_N": "17", "TICKET_LABEL": "needs-triage"})
        self.assertEqual(run.rc, 0, run)
        create = run.calls[0]
        self.assertEqual(create[create.index("--label") + 1], "needs-triage")
        self.assertEqual(create.count("--label"), 1)

    def test_ticket_publish_fails_on_an_unset_label(self):
        run = self.publish_ticket({"SPEC_N": "17"}, unset=["TICKET_LABEL"])
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [])

    @unittest.skipUnless(ZSH, "zsh is required")
    def test_ticket_publish_from_zsh_keeps_blockers_a_separate_argument(self):
        run = self.run_from_zsh(self.ticket_blocks(), {
            "EDGES": "native", "TICKET_TITLE": "Expand", "TICKET_LABEL": "ready-for-agent",
            "TICKET_BODY": self.files["TICKET_BODY"], "SPEC_N": "17", "BLOCKED_BY": "40,41"})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls[3:5], [
            ["issue", "edit", "42", "--add-blocked-by", "40"],
            ["issue", "edit", "42", "--add-blocked-by", "41"]])

    @unittest.skipUnless(ZSH, "zsh is required")
    def test_spec_publish_from_zsh_survives_an_empty_deferred_directory(self):
        run = self.run_from_zsh(doc_block(SPEC_TICKETS, "Spec", "gh issue create"), {
            "RUN": str(self.run_dir), "LOG": self.files["LOG"], "BODY": self.files["BODY"],
            "TITLE": "Deepen X: y", "DEFERRED_DIR": str(self.deferred_dir)})
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create", "issue comment"])

    def test_ticket_publish_with_edges_in_the_body_skips_the_edit(self):
        run = self.publish_ticket({"SPEC_N": "17", "BLOCKED_BY": "40,41", "EDGES": "body",
                                   "GH_MISSING_FIELDS": "parent,blockedBy"})
        self.assertEqual(run.rc, 0, run)
        self.ticket_create(run)
        self.assertEqual(run.subcommands(), ["issue create", "issue view"])
        self.assertIn("## Blocked by", run.out)

    def test_parent_only_schema_verifies_blockers_in_body(self):
        run = self.publish_ticket({"SPEC_N": "17", "BLOCKED_BY": "40,41", "EDGES": "parent",
                                   "GH_MISSING_FIELDS": "blockedBy"})
        self.assertEqual(run.rc, 0, run)
        self.ticket_create(run)
        self.assertEqual(run.calls[1:], [
            ["issue", "edit", "42", "--parent", "17"],
            ["issue", "view", "42", "--json", "labels,parent,body"],
        ])
        self.assertIn("## Blocked by", run.out)

    def test_missing_blocked_by_read_resumes_at_verification_on_the_same_ticket(self):
        missing = {"GH_MISSING_FIELDS": "blockedBy"}
        run = self.publish_ticket({"SPEC_N": "17", **missing})
        self.assertNotEqual(run.rc, 0)
        self.assertIn("Field 'blockedBy'", run.err)
        self.assertIn(f"{self.issue_prefix}/42", run.out)
        prior_calls = run.calls
        resumed = self.run_block("Tickets", 'gh issue view "$TICKET_N"',
                                 {"TICKET_N": "42", "TICKET_URL": run.out.strip(),
                                  "EDGES": "parent", **missing})
        self.assertEqual(resumed.rc, 0, resumed)
        self.assertEqual(resumed.calls, prior_calls + [
            ["issue", "view", "42", "--json", "labels,parent,body"]])

    def test_unavailable_native_blocker_query_stops_before_the_blocker_edit(self):
        run = self.publish_ticket({"SPEC_N": "17", "BLOCKED_BY": "40,41",
                                   "GH_MISSING_FIELDS": "blockedBy"})
        self.assertNotEqual(run.rc, 0)
        self.assertIn("Field 'blockedBy'", run.err)
        self.assertEqual(run.out.strip(), f"{self.issue_prefix}/42")
        self.assertEqual(run.subcommands(), ["issue create", "issue edit", "api graphql"])

    def test_ticket_publish_rejects_an_unknown_edges_value_before_creating(self):
        run = self.publish_ticket({"SPEC_N": "17", "EDGES": "api"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.calls, [])

    def test_ticket_publish_stops_when_create_fails(self):
        run = self.publish_ticket({"SPEC_N": "17", "GH_FAIL": "issue create"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create"], "no edit or view of a missing ticket")

    def test_ticket_publish_edge_failure_leaves_one_ticket(self):
        run = self.publish_ticket({"SPEC_N": "17", "GH_FAIL": "issue edit"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create", "issue edit"])
        self.assertEqual(self.counter.read_text().strip(), "42", "exactly one ticket exists")
        self.assertIn(f"{self.issue_prefix}/42", run.out)
        self.assertIn("gh: issue edit failed on request", run.err)

    def test_partial_blocker_edit_retries_only_the_missing_edge_on_the_created_ticket(self):
        block = doc_block(SPEC_TICKETS, "Tickets", "--add-blocked-by")
        env = {"SPEC_N": "17", "BLOCKED_BY": "40,41"}
        failed = self.publish_ticket({**env, "GH_FAIL_BLOCKER": "41"})
        self.assertNotEqual(failed.rc, 0)
        self.assertIn("addBlockedBy failed for #41", failed.err)
        ticket = failed.out.strip()
        self.assertEqual(ticket, f"{self.issue_prefix}/42")
        applied = self.counter.with_suffix(".42.blockers")
        self.assertEqual(applied.read_text().splitlines(), [f"{self.issue_prefix}/40"])
        resumed = self.run_script(block, {**env, "TICKET_N": "42", "TICKET_URL": ticket})
        self.assertEqual(resumed.rc, 0, resumed)
        self.assertEqual(resumed.calls[len(failed.calls):], [
            failed.calls[2], ["issue", "edit", "42", "--add-blocked-by", "41"]])
        self.assertEqual(applied.read_text().splitlines(),
                         [f"{self.issue_prefix}/40", f"{self.issue_prefix}/41"])

    def test_lost_blocker_reply_replays_on_setup_host_and_verifies_once_complete(self):
        other = Path(self.env["GH_TRACKERS"]) / self.default_repo
        (other / "counter").write_text("42\n")
        (other / "counter.42.parent").write_text("99\n")
        (other / "counter.42.blockers").write_text(f"https://{self.default_repo}/issues/41\n")
        setup = self.setup_tracker("Acme/Work", f"{self.issue_prefix}/17", "17")
        self.assertEqual(setup.rc, 0, setup)
        repo = setup.out.strip()
        env = {"SPEC_N": "17", "SPEC_URL": f"{self.issue_prefix}/17", "BLOCKED_BY": "40,41"}
        lost = self.run_script(self.ticket_blocks(), {**env, "GH_LOST_REPLY": "40"}, repo=repo)
        self.assertNotEqual(lost.rc, 0, lost)
        self.assertEqual(lost.out.strip(), f"{self.issue_prefix}/42")
        recorded = {**env, "TICKET_URL": lost.out.strip(), "TICKET_N": "42"}
        blockers = doc_block(SPEC_TICKETS, "Tickets", "--add-blocked-by")
        verify = doc_block(SPEC_TICKETS, "Tickets", 'gh issue view "$TICKET_N"')
        run = self.run_script(blockers + "\n" + verify, recorded, repo=repo)
        self.assertEqual(run.rc, 0, run)
        self.assertEqual(run.calls[len(lost.calls):], [
            lost.calls[-2], ["issue", "edit", "42", "--add-blocked-by", "41"],
            ["issue", "view", "42", "--json", "labels,parent,blockedBy"]])
        observed = json.loads(run.out)
        self.assertEqual(observed["parent"], {"number": 17})
        nodes = observed["blockedBy"]["nodes"]
        self.assertEqual([node["url"] for node in nodes],
                         [f"{self.issue_prefix}/40", f"{self.issue_prefix}/41"])
        self.assertEqual(self.targets(), [self.repo] * len(run.calls))
        self.assertEqual(self.counter.read_text(), "42\n")
        self.assertEqual((other / "counter").read_text(), "42\n")
        self.assertEqual((other / "counter.42.parent").read_text(), "99\n")
        self.assertEqual((other / "counter.42.blockers").read_text(),
                         f"https://{self.default_repo}/issues/41\n")

    def test_ticket_rejects_foreign_create_result_before_parent_edit(self):
        run = self.publish_ticket({"SPEC_N": "17", "GH_CREATE_URL": f"https://{self.default_repo}/issues/42"})
        self.assertNotEqual(run.rc, 0, run)
        self.assertEqual(run.subcommands(), ["issue create"])

    def test_resumed_ticket_checks_saved_issue_before_each_operation(self):
        for marker in ("--parent", "--add-blocked-by", 'gh issue view "$TICKET_N"'):
            for url in (f"https://{self.default_repo}/issues/42",
                        "https://git.example.test/Acme/Other/issues/42", f"{self.issue_prefix}/41"):
                with self.subTest(marker=marker, url=url):
                    run = self.run_block("Tickets", marker, {
                        "TICKET_URL": url, "TICKET_N": "42", "SPEC_N": "17", "BLOCKED_BY": "40"})
                    self.assertNotEqual(run.rc, 0, run)
                    self.assertEqual(run.calls, [])

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

    def test_planner_can_read_an_existing_spec_on_an_older_schema(self):
        block = doc_block(WORKERS, "Planning", "closedByPullRequestsReferences")
        env = {"SPEC_N": "42", "GH_MISSING_FIELDS": "subIssues,closedByPullRequestsReferences"}
        self.assertNotEqual(self.run_script(block, env).rc, 0)
        run = self.run_script(block, {**env, "SPEC_FIELDS": "state,stateReason,labels"})
        self.assertEqual(run.rc, 0, run)
        self.assertIn('"stateReason":"REOPENED"', run.out)
        self.assertEqual(run.calls[-1], ["issue", "view", "42", "--json", "state,stateReason,labels"])

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
