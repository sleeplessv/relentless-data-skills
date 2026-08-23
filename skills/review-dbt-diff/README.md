# review-dbt-diff

The **`review-dbt-diff`** agent skill: a read-only, diff-scoped reviewer for
dbt model changes. Built for a repo where the review problem is coverage, not
rigor. Most PRs merge with zero comments, so the bar is "useful enough to
read on a PR nobody else was going to look at", and the worst failure mode is
crying wolf.

## What it does

- **Twelve checks from real fix history.** The checklist was derived from
  35+ actual fix diffs in the target repo, ordered by how many fixes each
  class maps to: grain declaration, join cardinality (SCD2 qualification),
  incremental strategy coherence, determinism, timezone handling, reporting
  contract, row-count delta, NULL semantics, CDC ordering, literal filters,
  contract drift, and test accompaniment. Mechanically-enforceable checks
  carry retirement markers pointing at the companion CI issue.
- **Two passes.** A 2–4 minute default pass reads the diff and runs one
  query (a row-count delta of compiled SQL against the deployed production
  relation). An escalated pass adds lineage, fan-out, and distinct-value
  queries at evidence rung 4; it announces itself when the diff touches
  reporting models, incremental config, or a hardcoded high-risk file list.
- **Evidence-graded findings, capped.** Every finding is graded on the
  blast-radius evidence ladder and takes a three-part form: named invariant,
  dated data check, proposed dbt test. At most five findings in "Act On";
  the rest land in a visible Dismissed section. An empty review is a valid
  outcome.
- **A dismissal log that learns.** First use seeds a committed
  `.review-dbt-diff/dismissals.md` in the target repo; upheld dismissals
  become skip patterns with a candidate/recurring/strong confidence ladder.
  Five categories are never auto-skipped: grain, tenant scoping, PII
  surface, reporting contract, incremental strategy / unique_key changes.
- **Hosted HTML artifact.** One self-contained file, published via the
  Artifact tool when available, saved to disk otherwise. Review and report
  only: no edits, no PR posting, not a CI gate.

## Requirements

- The target dbt repo (currently specific to
  `xplor/xde-xpl-fit-mte-analytics-dbt`) with its `.dbt-runner/` and
  `.snowman/` context files bootstrapped.
- The `dbt-runner`, `snowman`, and `blast-radius` skills installed. This
  skill invokes them rather than reimplementing dbt invocation, Snowflake
  queries, or evidence discipline.
- Read access to the production Snowflake environment via snowman's `prod`
  env for row-count and fan-out checks.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/review-dbt-diff
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install review-dbt-diff@relentless-data-skills
```

It is user-invoked only (`disable-model-invocation: true`); ask to review a
dbt branch, diff, or PR, optionally passing a git ref range (default
`main...HEAD`).

## Files

- `SKILL.md` — core workflow: bootstrap → scope → per-model × per-check
  review → grade and filter → artifact.
- `references/examples.md` — the worked finding example and real
  before/after SQL per defect class; loaded when a check fires.
- `references/gotchas.md` — Snowflake/dbt semantics the checks depend on
  (MERGE NULL behavior, CDC timestamp stamping, timezone traps, dev data
  artifacts); loaded before the semantics-heavy checks.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
