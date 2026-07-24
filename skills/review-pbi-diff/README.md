# review-pbi-diff

The **`review-pbi-diff`** agent skill: turn a Power BI (PBIP) git diff —
hundreds of hash-named `visual.json` files and TMDL model files nobody can
read — into a single manager-ready review artifact: an executive summary,
to-scale page wireframes showing what changed where, every added/modified
measure spec-checked against the repo's metric definitions, and a ranked
red-flags list. Built for a Power BI expert reviewing a developer's branch.

## What it does

- **Deterministic extraction first.** A bundled stdlib-only script
  (`scripts/extract_changes.py`) walks the git range and builds a structured
  `change_model.json`: per-page visual inventories with absolute geometry
  (visual-group offsets resolved), field bindings and filters, per-table
  measure/column/calculation-item diffs with full before/after DAX,
  relationship and function diffs, plus raw before/after dumps of every
  changed file for drill-down. The agent analyzes this model, never the raw
  diff. Supports `A...B`, `A..B`, single-commit, and base-vs-working-tree
  ranges (untracked files included).
- **Scratch-page exclusion.** Power BI default-named pages (`Page N`), plus
  any pages the user names at invocation, are treated as developer scratch
  work: excluded from wireframes, tables, and checks, summarized in one muted
  exclusion line — with one guard: a scratch page left visible in view mode
  is flagged, because it ships to end users.
- **Spec-checked DAX.** Every added/modified measure gets a verdict badge —
  ✅ matches the documented definition, ⚠️ deviates (with exactly how), or
  ❓ no definition found — checked against logic (grain, filter context,
  exclusions), not just names.
- **Eleven red-flag checks**, run as a surface-everything detection pass, then
  filtered and ranked against evidence before they reach the artifact: bare
  `/` division, missing format strings, deleted/renamed measures still
  referenced, modified-measure ripple, `USERELATIONSHIP` targets, unrelated
  fact tables on one visual, untitled visuals, hidden filters that change
  data, overlapping data visuals, hardcoded literals / convention violations,
  and visible scratch pages.
- **Hosted HTML artifact.** One self-contained file — wireframes are
  color-coded to-scale layouts (added/modified/deleted/unchanged), DAX in
  collapsible before/after blocks, findings ranked 🔴/🟡/🔵. Published via
  the Artifact tool when available, saved to disk otherwise.

## Requirements

- A repo using the **PBIP format** (`*.Report` / `*.SemanticModel` folders
  with `definition/` JSON + TMDL) — the extractor matches these paths at any
  depth. `.pbix` binaries are out of scope.
- `python3` and `git` on PATH.
- Optional but rewarded: repo docs for metric definitions, requirements, and
  naming/DAX standards — the spec check and convention checks use them when
  present and degrade gracefully when absent.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/review-pbi-diff
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install review-pbi-diff@relentless-data-skills
```

It activates when you ask to review a Power BI branch/diff/PR or to summarize
Power BI work; it takes an optional git ref range (default `main...HEAD`).

## Files

- `SKILL.md` — core workflow: extract → analyze (spec check + red flags) →
  build the artifact.
- `references/artifact.md` — artifact structure and wireframe rules; loaded
  only at build time.
- `scripts/extract_changes.py` — the deterministic extractor (stdlib only):
  git range → `change_model.json` + raw `objects/` before/after dumps.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
