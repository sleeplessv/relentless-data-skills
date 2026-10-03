# Artifact structure and wireframe rules

The artifact is a single self-contained HTML file. Style per the
`artifact-design` skill; must work in light and dark themes.

## Structure, top to bottom

1. **Header.** Repo, range, commit count, authors, date; stat chips (pages
   added, visuals added/modified/deleted, measures added/modified,
   relationships added); page and visual counts cover curated pages only.
2. **Executive summary.** The progress-report layer, in business terms: what
   was built (model and curated pages) and why it matters, mapped to
   requirements where the repo documents them. A manager reading only this
   section should know what the developer accomplished.
3. **Red flags.** Ranked 🔴/🟡/🔵 cards; each with location (page/visual or
   table/measure), evidence (DAX snippet or binding), and why it matters.
   If none: say so explicitly.
4. **Report changes.** One section per report, opening with one muted
   exclusion line when scratch pages were touched: their names, changed-visual
   count, and any references from their visuals to deleted or modified
   measures ("Page 2 references 2 deleted measures"). Then one subsection per
   touched curated page (added pages first). Each page gets:
   - A **wireframe** (rules below).
   - A table of added/modified/deleted visuals: type, title, bound fields by
     role, filters.
   - For modified visuals, a `<details>` with what changed
     (`changed_sections`, `*_before` vs current values).
5. **Model changes.** Measures grouped by `displayFolder`: each a card with
   name, format string, spec-check badge, and DAX in a collapsible
   `<details>` (side-by-side or stacked before/after for modified). Then
   compact tables for deleted measures, new columns, relationships (from →
   to, active?, cross-filter), and functions.
6. **Appendix.** Full changed-file list and the exact range/command used.

## Wireframe rules

For each touched curated page, draw the canvas to scale:

- Container: `position: relative`, full width (max ~860px),
  `aspect-ratio: <width>/<height>` from the page entry.
- Each visual: absolutely positioned div at percentage coordinates,
  `left: abs_x/page_width*100%`, `top: abs_y/page_height*100%`, same for
  width/height. Use `abs_x`/`abs_y` (group offsets already resolved), and
  `z-index` from `z` so stacking is faithful.
- Color code by `status`: green = added, amber = modified, red dashed +
  reduced opacity = deleted, muted grey = unchanged. Hidden visuals get 50%
  opacity and a "hidden" tag. Include a legend once, above the first
  wireframe.
- Label each box with `title`, else `visual_type`; small font, clipped
  overflow, full details in the `title=` attribute (hover). Render shapes and
  textboxes as unobtrusive background boxes so data visuals stand out.
- Wireframes carry no data, theme colors, or conditional formatting. Say so
  in the artifact so nobody expects screenshots.

## Check markers

`scripts/check_artifact.py` proves the artifact against `change_model.json`.
It parses the page as a browser does and counts only static text a reader
sees, so write every marker, badge, and number as plain, visible HTML text.
It skips anything a script adds, CSS `content`, images, and hidden markup:
`hidden`, `aria-hidden="true"` (even on a decorative emoji), inline
`display:none`, `visibility:hidden` or `opacity:0`, and the content of
`<template>`, `<noscript>`, or `<title>`.

A card or chip marker goes on the element that wraps the whole card or chip.
Inside each card, `data-badge` marks the one element that shows its badge.

| Element | Markers and rules |
| --- | --- |
| Stat chip | `data-stat`: one of `pages_added`, `visuals_added`, `visuals_modified`, `visuals_deleted`, `measures_added`, `measures_modified`, `relationships_added`. All seven chips, once each, even at 0. The chip's first number is its value, and its text names the stat: `6 visuals added`. Visual counts skip group containers. |
| Red-flag list | `data-flags` on the element that holds the red-flag cards, present even with no findings. Inside it, 🔴/🟡/🔵 appear only within cards. |
| Red-flag card | One `<article>` per finding inside the list, with `data-severity`: `red`, `yellow`, or `blue`. |
| Measure card | One per added or modified measure: `data-model`, `data-table`, and `data-measure` as the change model names them, plus `data-verdict`: `match`, `deviates`, or `none`. The card's text shows the measure's name. Deleted measures go in the deleted-measures table, unmarked. |
| Badge | `data-badge` on the element showing the card's 🔴/🟡/🔵 or ✅/⚠️/❓. It holds that one badge and no other from its set; explanations and DAX sit outside it. |
| Wireframe | `data-report` (the report's key in the change model) and `data-wireframe` (the page id). The last heading (`h1`–`h6`) before it shows the page's `display_name`. Only touched curated pages get one. |
| Visual box | `data-visual` (the visual id) and `data-status` (its `status` in the change model), inside its page's wireframe. Only wireframe boxes carry `data-visual`; drawing group containers is optional. Color each box from `data-status` (`[data-status=added]`) so color and marker agree. |
| Exclusion line | `data-excluded` on each report's exclusion line. Together they name every excluded page by `display_name`. |
