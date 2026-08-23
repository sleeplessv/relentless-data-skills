---
name: review-dbt-diff
description: "Read-only review of a dbt model diff in the MTE analytics repo — 12 defect checks derived from the repo's own fix history, row-count deltas against PRD, findings ranked in an evidence-graded HTML artifact. Use when asked to review a dbt branch, diff, or PR in xde-xpl-fit-mte-analytics-dbt, or to check dbt model changes before pushing. Takes an optional git ref range."
disable-model-invocation: true
---

# Review dbt Diff

Read-only, diff-scoped review of dbt model changes. The review problem in this
repo is coverage, not rigor: most PRs merge with zero review comments, so the
bar is "useful enough to read on a PR nobody else was going to look at", not
"exhaustive". The worst failure mode is crying wolf.

**Input:** an optional git ref range (default `main...HEAD`).

**Scope:** review and report. Findings go in the artifact, never into edits,
PR comments, or CI. `gh` in this repo needs
`GH_CONFIG_DIR="$HOME/.config/gh-xplor"` on every call; a 404 means wrong
identity (expected login `vadims-xplor`), never run `gh auth login`/`switch`.

**Dependencies:** invoke these skills rather than reimplementing them. `dbt-runner`
for every dbt command, `snowman` for every query (its workflows reference
carries the fan-out and duplicate playbooks), `cortex lineage
<DB.SCHEMA.NAME>` for consumer sets, `blast-radius` on escalation only.

## Step 0 — Bootstrap (once per repo)

If `.review-dbt-diff/dismissals.md` is missing at the target-repo root, create
and commit it with this seed, then continue:

```markdown
# review-dbt-diff dismissal log
Ask by default, never auto-skip, even if previously dismissed: grain, tenant
scoping, PII surface, reporting contract, incremental strategy / unique_key.
<!-- One pattern per dismissal the user upholds. Confidence: candidate (1-2
examples) | recurring (several) | strong (narrow, verified, low-risk). -->
### <pattern name>
- Confidence: candidate
- Skip when: <conditions> / Do not skip when: <risk boundary>
- Example signal: <phrase or code shape> / Source: <PR or finding>
```

## Step 1 — Scope

1. List changed models: `git diff --name-only <range> -- 'dbt_project/models'`
   (`.sql` and `.yml`). Fetch `main` first if stale. No state manifest needed.
2. Read the dismissal log. A `strong` pattern may pre-filter a finding;
   `candidate`/`recurring` patterns only annotate it.
3. Pick the pass, announcing escalation in one line ("escalated: touches
   `int_memberships__status_history` [9 fixes]"). **Escalate** when the diff
   touches REPORTING or SEMANTIC models, incremental/`unique_key` config, or
   the high-risk list; otherwise run the default pass.

High-risk files (bracketed fix counts; sampled 2026-08, regenerate with
`git log --grep '^fix' --name-only --pretty= | sort | uniq -c | sort -rn`):
`int_memberships__status_history` [9], `int_memberships__active_status` [9],
`int_memberships__daily_listing` [7], `dim_class_session_type_scd2` [7],
`int_memberships__instance_history` [6], `int_memberships__orders` [6],
`fct_memberships_by_type` [6], `fct_sales_by_product` [6],
`rpt_msd_frozen_memberships` [6], `fact_reservations` [5],
`fct_intro_offers` [5], `fct_first_visits` [3].

## Step 2 — Review every model against every check

Work model by model. **Done when every changed model carries a pass / finding
/ not-applicable mark for each check in its pass.** Record every candidate
finding here; the cap applies at write-up, not during detection. Load
[references/examples.md](references/examples.md) when a check fires (the real
before/after SQL for that defect class) and
[references/gotchas.md](references/gotchas.md) before working checks 3, 5, 8,
9, or 11 (the Snowflake and dbt semantics they depend on).

Default pass (2–4 minutes): checks 1–8 and 12. Check 7 is the only one that
queries. Escalated pass adds 9–11. Checks marked *CI* retire once
xplor/xde-xpl-fit-mte-analytics-dbt#505 lands; skip any part CI enforces.

1. **Grain declaration.** What is this model's grain, and is it asserted
   (`unique_combination_of_columns` or equivalent)? The single best question
   per PR: fan-out, double-counting, and SCD2 overlap all reduce to it.
2. **Join cardinality.** For each added/modified join: is the right side 1:1
   at the join key? SCD2 right side ⇒ temporal qualification present. Confirm
   with `count(*) vs count(distinct key)` when in doubt, not by eye.
3. **Incremental coherence.** Watermark and filter on the same clock; no
   filter on lookup CTEs; predicate windows vs late CDC updates. **Ask,
   don't assert** on the predicate/CDC interaction.
4. **Determinism** (*CI*). Every `row_number()`/`qualify` order-by carries a
   partition-unique tiebreaker.
5. **Timezone handling.** Two-arg `CONVERT_TIMEZONE` on `TIMESTAMP_TZ`; raw
   calls routed through `to_local_date()`/`safe_timezone()`; flag silent UTC
   fallback dating.
6. **Reporting contract** (partial *CI*). REPORTING/SEMANTIC is the external
   boundary: no `DBT_*` or `_scd2` names, both `TENANT_ID` and tenant-name
   columns present, no silently dropped columns, no new inner join that
   deletes rows a consumer sees today.
7. **Row-count delta.** Compile the model via `dbt-runner`, wrap the compiled
   SELECT in `count(*)` via `snowman --env prod`, compare against the
   deployed PRD relation. Read-only; never stage anything against prod. If
   the model is not in prod yet, compare in dev and apply
   `colliding_tenant_exclusion()` (see gotchas) before trusting counts.
8. **NULL semantics** (partial *CI*). Nullable `unique_key` columns, `NOT IN`
   over nullable subqueries, anti-join traps, sentinel coalescing on grain
   columns.
9. **CDC ordering** (escalated). Dedup ranked by source `updated_at`, never
   `_dms_ingestion_ts` alone, plus a record-level tiebreaker.
10. **Literal filters** (escalated). String literals in new predicates
    checked against `select distinct` on the source column.
11. **Contract drift** (escalated). Renames/type changes vs downstream
    consumers: `dbt ls --select <model>+` via `dbt-runner`, `cortex lineage`
    for warehouse consumers; MERGE cannot alter a deployed column's type.
12. **Test accompaniment** (partial *CI*). Does the change encode its own
    invariant as a test or YAML change? Half of historical fixes shipped
    without one; propose the missing test in the finding.

## Step 3 — Escalated additions

Run checks 9–11, then invoke the `blast-radius` skill for the writeup
discipline and push each load-bearing fact to rung 4 with the snowman fan-out
and duplicate playbooks. Escalation adds queries, never a local build.

## Grade, then filter

Grade every finding by evidence rung (source: `blast-radius`): 1 you said so
(worthless alone) · 2 you pointed at the line · 3 you showed the bad case
can't happen · 4 you ran it · 5 reproduced in the running app. Lead with
rung-4 findings; a rung-1 finding may ship only labelled unproven.

Triage each finding `fix` / `dismiss` / `ask`. The five ask-by-default
categories are in the dismissal log seed; when in doubt, ask. **Act On caps
at five findings**; everything else goes to a visible Dismissed section with
a one-line reason, the trust mechanism that lets the user override you. An
empty review is a valid outcome; if all findings are nits, the code is
probably fine; say so. When the user upholds a dismissal, append or promote
a pattern in `.review-dbt-diff/dismissals.md`.

## Step 4 — Build the artifact

Every finding takes the three-part form (worked example at the top of
[references/examples.md](references/examples.md)): **named invariant** the
code relies on, **dated data check** that tested it, **proposed dbt test**
that would enforce it. Load the `artifact-design` skill if available, write
one self-contained HTML file to the scratchpad, publish with the Artifact
tool (favicon 🧱, stable title `dbt Review: <branch or range>`); if
unavailable, save the HTML and give the path. Close out outcome-first:
artifact URL, Act On / Dismissed counts, escalation state.

**Non-goals:** splice and history-assembly defects (the
`int_memberships__instance_history` class) are not catchable from a diff;
say so rather than pretending. Compilation and existing tests on modified
models and descendants are CI's job (`dbt_pr_check.yml`); never repeat them.
