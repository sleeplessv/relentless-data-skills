# candidate-to-spec

Turn the deepening candidates in an `improve-codebase-architecture` review report into approved
specs and `ready-for-agent` tickets, ready for `implement-feature`. That skill's grilling step
asks the human seam, interface, and test questions; this skill has agents answer them instead
and leaves the human one checkpoint: approving a spec whose first section is written in plain
English.

Per candidate, a designer worker records the test suite's baseline, walks the design tree, and
answers every node with evidence (a code citation, a design-it-twice comparison run as a flat
wave of three alternative workers, a throwaway prototype under the run directory, a decision of
a spec it builds on, or a quoted user answer), reading a per-project
`docs/architecture-policy.md` for taste questions and raising open questions only for behaviour
changes, ADR conflicts, dependency changes, and scope widening beyond the module, its callers,
and their tests. When the evidence says the deepening does not repay, the designer returns a
verdict and the user chooses a smaller change, the full deepening, or dropping the candidate. A
separate reviewer worker, briefed as the maintainer and carrying `ponytail-review`'s lean
checklist, reviews the log once. The designer revises or rejects with evidence; rejections
become "Contested decisions" in the spec. The spec is published at `needs-triage`, the user
approves it, and the reviewer answers `to-tickets`' quiz before the tickets publish as
sub-issues with native blocking edges.

A planning worker orders several candidates by dependency and holds any that contradict an ADR or
sit in a policy's off-limits area until the user says reopen, park, or drop. Every other pick
gets a spec in the same run: a candidate that depends on another is stacked, designed against
its predecessor's approved spec, and its tickets are blocked by the predecessor's. A candidate
is deferred only behind a held candidate or an earlier run's spec that is still unapproved. It
is posted as a comment on the spec that blocks it, so `candidate-to-spec <spec#>` picks the
deferred set up again without the review report. A parked candidate is re-run from the review
report with its slug as a pick, so the run report tells the user to keep that file.

Arguments come in any order: a review report path (without one, the report the conversation
produced or the newest one in the temp directories), picks by position, slug, or title
(`Candidate 2`, `1-3`), a lone spec number for a re-run, and a free-text instruction that is
quoted to the workers. The skill is user-only under
[SE1 and SE5](../../CODING_STANDARDS.md#side-effects): it publishes issues and runs many
workers. A handed-off or background session therefore cannot start it from a relayed message;
type `/candidate-to-spec` in the session that should run it.

[SKILL.md](SKILL.md) holds the workflow; [references/workers.md](references/workers.md) the
briefs, argument rules, candidate file, planning, designer, reviewer, and revision contracts;
[references/spec-and-tickets.md](references/spec-and-tickets.md) the label check, spec template,
checkpoint, and ticket commands; [references/policy.md](references/policy.md) the first-run
policy interview.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/candidate-to-spec
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install candidate-to-spec@relentless-data-skills
```

Install `orchestrator-mode` from this repository. Required companions from
[Matt Pocock's engineering skills](../../README.md#matt-pococks-engineering-skills):
`codebase-design`, `to-spec`, `to-tickets`, and `improve-codebase-architecture` to produce the
review report. `gh` 2.102 or later: setup checks that `gh issue create` has `--parent`.
Optional: `prototype` and `domain-modeling` from the same set,
[`ponytail-review`](../../README.md#others), and the
[Cursor pstack](../../README.md#cursors-pstack) writing skills `technical-writing` and `unslop`.
Setup records a missing optional skill, and the step that uses it applies the stated fallback.

## Compatibility

The skill reads these companions by path and depends on the named parts of each. A change
upstream to any of them is a change to this skill:

- `orchestrator-mode`: standing mode, the handoff elements, the worker cap with the root counted.
- `codebase-design`: the vocabulary in `SKILL.md`; `DESIGN-IT-TWICE.md` step 1 (framing), the
  four briefs and five outputs of step 2, and the comparison axes of step 3.
- `improve-codebase-architecture`: the report's file name
  (`architecture-review-<timestamp>.html`), the card fields in `HTML-REPORT.md`, the order of
  the cards (a pick by position counts them), the anchor from the Top recommendation to its
  card, and the ADR callout, which upstream writes for a contradiction and which the planner
  reads against the ADR because reports also use it to note agreement.
- `to-spec`: the section names of its template and its rule on paths in Implementation Decisions.
- `to-tickets`: steps 1 to 3 (drafting), the three quiz questions of step 4, and step 5 (publish).
- `ponytail-review`: the six items under "Lean".
- `implement-feature` and the tracker: sub-issues and blocked-by edges set after the create with
  `gh issue edit --parent` and `--add-blocked-by` (`gh` 2.102 or later), and the `## Parent` and
  `## Blocked by` body sections of `to-tickets`' ticket template as the fallback it reads. Three
  of its behaviours are relied on: one feature PR per spec (so a per-change file such as a
  version file changes once per spec), an open blocker in another spec stopping for a
  dependency decision (a stacked spec's cross-spec blockers), and a `needs-triage` ticket
  stopping for the user (a human-only ticket).

Writes to the target repository are limited by prose rather than a hook: the skill is user-only,
workers receive no branch to push, and the only files written are the two the workflow names.
The limit exists so the user commits only files the run report named and they have read.

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
registry consistency with `scripts/sync_registry.py --check`, and runs the fenced `gh` blocks
of both reference files against a recording stand-in in
`tests/test_candidate_to_spec_commands.py`, each as a bash script and the two publish blocks
also from zsh through the quoted heredoc the briefs prescribe.
