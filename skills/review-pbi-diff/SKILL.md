---
name: review-pbi-diff
description: Turn a Power BI (PBIP) git diff into a manager-ready review artifact — page wireframes, spec-checked DAX, ranked red flags. Use when asked to review a Power BI branch, diff, or PR, or to summarize Power BI work in a PBIP-format repo (*.Report / *.SemanticModel folders). Takes an optional git ref range.
disable-model-invocation: true
---

# Review Power BI Diff

Turn a large, unreadable PBIP diff (hash-named `visual.json` files, TMDL model
files) into a single review artifact: an executive summary of what was built,
page wireframes showing what changed where, spec-checked measures with full
DAX, and a ranked red-flags list. The reviewer is a Power BI expert — show raw
DAX and exact bindings.

**Input:** an optional git ref range as the argument (`A...B`, `A..B`, or a
single base ref meaning "vs working tree"). Default: `main...HEAD`. The user
may also name pages to treat as scratch, beyond the automatic rule below.

**Scope:** review and report — findings go in the artifact, not into edits to
the PBIP files, the DAX, or an issue tracker.

## Step 1 — Extract the change model (deterministic)

Run the bundled extractor, outputting to the scratchpad:

```bash
python3 <skill-dir>/scripts/extract_changes.py "<range>" \
  --out <scratchpad>/pbi-review --repo <repo-root>
```

`<skill-dir>` is this skill's directory. It produces:

- `<out>/change_model.json` — the structured change model. Everything below
  works from this file, **not** from the raw git diff.
- `<out>/objects/<repo-path>.before|.after` — raw before/after of every
  changed file, for drill-down when something in the model looks suspicious.

Change-model shape: `reports.<name>.pages.<id>` has `display_name`, `status`
(added / modified / visuals-changed / deleted), `width`/`height`,
`visibility` (present when not default-visible), `scratch` (see below), page
`filters`, and `visuals.<id>` — every visual on each touched page (including
unchanged ones, so wireframes are complete) with `visual_type`, `title`,
`abs_x`/`abs_y`/`width`/`height`/`z`, `status`, `fields` (role → bound
fields), `filters`, and for modified visuals `changed_sections` plus
`*_before` values. `models.<name>` has per-table
`measures_added/modified/deleted` (with full DAX, `dax_before`/`dax_after`
for modified), same for `columns` and `calculation_items`, plus
`relationships` and `functions` diffs. `commits` and `authors` identify whose
work this is. Calculation-group internals and partition/refresh-policy
changes are not member-diffed — the change model flags the table with a
note; drill into `objects/` for those.

If `change_model.json` is large, query it with python one-liners rather than
reading it whole; read pages/tables one at a time.

### Scratch pages

Pages marked `scratch: true` (Power BI default names, `Page N`), plus any
pages the user named at invocation, are developer scratch work. Review the
model in full and the curated pages only: scratch pages get no wireframe, no
visual tables, and no red-flag checks except #11. References from their
visuals (checks 3–4) aren't findings — they go in the exclusion line. They
surface in the artifact exactly twice: the exclusion line (see
[references/artifact.md](references/artifact.md)) and, when visible, check #11.

## Step 2 — Analyze

### Spec check (every added/modified measure)

For each measure in `measures_added` / `measures_modified`, look for a
matching definition in the repo's metric-definition docs — try
`docs/metric-definitions/` first, else search the repo for definition-style
docs, else ask the user where definitions live (match by name, then by
concept). Verdicts, each rendered as a badge in the artifact:

- ✅ **Matches definition** — DAX implements the documented logic (check the
  numerator/denominator, grain, filter context, exclusions, business-hours
  flags — not just the name).
- ⚠️ **Deviates** — state exactly how the DAX differs from the definition.
- ❓ **No definition found** — itself a useful finding; list these so docs can
  catch up. If the repo has no metric-definition docs at all, say so once and
  mark every measure ❓ without repeating it per measure.

Done when every added/modified measure carries a verdict. Spec-check inline:
~15 measures is a ceiling, not a trigger. Past it, use as few parallel
subagents as cover the measures in batches (each gets its batch + the
definitions docs) and merge. Never spawn an agent to review the review.

If the repo documents requirements (e.g. `docs/requirements/`), also map the
overall work against them: which requirements does this branch address, and
what claimed scope is missing.

### Red-flag checks

**Detection pass — surface everything.** Run every check below and record
every candidate it raises; don't drop one for being minor, uncertain, or
probably fine. Each check either yields candidates or comes back confirmed
clean.

**Filter pass — evidence, then rank.** Before building the artifact, revisit
the candidates: pull each one's evidence from the change model, reading the
`objects/…before|.after` files whenever the model doesn't carry enough;
discard only what the evidence disproves; and rank — 🔴 wrong results /
broken, 🟡 should fix before merge, 🔵 minor/hygiene. Every finding in the
artifact cites what you checked; one you can neither confirm nor disprove
ships as 🔵 stating what you checked and what is still unknown.

1. **Bare `/` division** in new/changed DAX where the denominator can be
   zero/blank (`DIVIDE` is the safe idiom).
2. **Missing `formatString`** on added measures that return numbers.
3. **Deleted or renamed measures still referenced** — grep the repo at head
   for each deleted measure name (visuals reference them as
   `<Table>.<Name>` in `queryRef`, other measures as `[<Name>]`). A rename
   shows up as one added + one deleted measure; check the deleted name. Flag
   equally any visual binding to a measure that doesn't exist in the model at
   head (e.g. a missing name prefix).
4. **Modified measure ripple** — for measures whose DAX changed, grep which
   other measures/visuals reference them and note affected downstream logic.
5. **`USERELATIONSHIP` targets** — confirm the named relationship exists
   (check `relationships` in the change model and
   `definition/relationships.tmdl` at head) and is inactive as expected.
6. **Visuals bound to unrelated tables** — fields from two fact tables with
   no relationship path on the same visual.
7. **Placeholder names** — visuals left untitled where siblings are titled.
8. **Hidden filters that change data** — visual/page filters with
   `hidden_in_view: true` (field emitted only when true).
9. **Overlapping data visuals** on the same page — pairs covering >15% of the
   smaller visual's area (use `abs_x/abs_y/width/height`; ignore
   shapes/textboxes layered as backgrounds).
10. **Hardcoded literals** in DAX (magic dates, hardcoded brand/region
    values) and, when the repo documents naming/DAX standards (e.g. under
    `docs/standards/`), convention violations against them.
11. **Visible scratch pages** — a scratch page without
    `visibility: HiddenInViewMode` ships to end users: 🟡 hide (or delete)
    before publishing. Hidden scratch pages are tolerated.

## Step 3 — Build the artifact

Follow [references/artifact.md](references/artifact.md) for the artifact
structure and wireframe rules. Length follows substance — within that
structure, wireframes and tables over prose, no filler padding, no restating
a table in prose beneath it. Load the `artifact-design` skill if available,
write a single self-contained HTML file to the scratchpad, and publish it with
the Artifact tool (favicon 📊, stable title `PBI Review: <branch or range>`).
If the Artifact tool is unavailable, save the HTML and give the user its path.
Close out with the outcome first — artifact URL (or path) and 🔴/🟡/🔵 counts
— then any detail.
