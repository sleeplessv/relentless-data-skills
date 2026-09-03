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
   compact tables for new columns, relationships (from → to, active?,
   cross-filter), and functions.
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
