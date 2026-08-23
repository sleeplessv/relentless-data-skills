# Render: UX spec, performance rules, design tokens, verification

One dispatch after validation passes. The agent works in `scripts/render/` (see its README for the commands), builds `lineage.html`, runs `test.js`, and returns the test JSON plus screenshot paths. Load the `dataviz` skill before touching colours and `artifact-design` before publishing.

## Performance rules

Never lay out the whole graph. Two views, both laid out with dagre (`rankdir: LR`, `tight-tree` ranker above 250 nodes):

- **Overview** = live, non-fork, table-level nodes only. Source databases group per database, Bronze groups per schema + country, reports form one group per model; triggers fold into pipeline details; notebooks and pipelines hidden behind a toggle; `unresolved.*` excluded but counted in a notice. Target ~300 nodes, dagre under 100 ms. Group nodes expand in place (`+`), with Collapse groups to reset.
- **Focus** = directional closure of one node (dbt `+node+`: upstream follows in-edges only, downstream follows out-edges only), depth selector (1 / 2 / 3 / 5 / ∞), hard cap of 400 nodes with a notice, nothing collapsed, notebooks and pipelines shown automatically. Enter with double-click, `F`, the details button, or search; `Esc` returns.
- Nodes with no edges under the current filters sit in a grid below the DAG with a caption, rather than vanishing.

## Page anatomy

- Top bar: title + subtitle, search (`/` focuses; ranks exact name > prefix > substring > id > path, live non-fork first; Enter selects, expanding a collapsed group when the hit is inside one), breadcrumbs (Overview › Focus: X), theme toggle.
- Filter row: layer chips (fixed order, each with swatch + text tag), country chips, partner multi-select, toggles (show forks / show non-live / show notebooks & pipelines), edge-kind chips (`partof` and `relationship` off by default).
- Explainer panel (optional, `--explainer`): a hand-drawn SVG of the macro flow (sources → Bronze → Silver → Gold → model → reports) plus the main scheduled chain with its time and timezone. Write it from the validation report numbers; uses `currentColor` so it survives the theme switch.
- Coverage & gaps panel: stat row (nodes, edges, live, forks, unresolved), Parsed list from the coverage text, Gaps list from `meta.gaps` with the first 8 names of each.
- Canvas: Fit / Zoom to selection / stats (`N nodes · M edges · layout ms`), legend, notice strip, tooltip on edge hover (kind, ×count, via list).
- Details panel: tag + type + fork / not-live flags, Focus lineage and Zoom to buttons, definition list (id, layer, repo path, partner, country, load type, schema, lakehouse, config path, keys, partition, columns, engine, orchestration, notebook, wrapper, semantic fields, note), **Schedule** ("Run by pipeline X, Daily 06:00 GMT" resolved by walking `runs` / `invokes` upward to an enabled schedule; "No pipeline runs this hop" otherwise), Pipelines, Notebooks, Activities, Upstream / Downstream link lists (first 120), model relationships.
- Hover or select tints the upstream closure blue and the downstream closure orange and dims the rest; identity is never colour-alone: every node carries a layer text tag (`SRC BRZ SLV GLD SEM RPT NB PL OTH`) and group nodes use a dashed border.

## Design tokens

Light palette on bare `:root`; dark redefined under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` and again under `:root[data-theme="dark"]` so the toggle wins both ways; `body` paints `var(--bg)` explicitly. Layer colours in fixed order (`--c-source --c-bronze --c-silver --c-gold --c-semantic --c-report --c-notebook --c-pipeline --c-other`), the gold tag uses dark text for contrast, `other` is hatched. Validate the palette with the `dataviz` validator before changing it. Fonts: Bricolage Grotesque (display), Source Sans 3 (body), JetBrains Mono (ids), each with a real fallback stack; Google Fonts is the only external host allowed under the artifact CSP. Reduced motion disables the zoom transitions.

## Data contract for the page

`data.json` = `{ meta: { counts, coverage, gaps }, nodes: [{ id, name, layer, type, path, partner, country, loadType, isFork, isLive, details }], edges: [{ f, t, k, v }] }`. `build-data.js` picks which `graph.json` details reach the page per layer; add a key to its `pick()` list and to the `dd()` calls in `app.js` to surface a new field.

## Verification (test.js)

`node test.js lineage.html <focus-id> <search-term> <shot-dir>` prints JSON and PASS / FAIL. PASS requires all of:

- zero console errors / warnings / page errors;
- zero requests to hosts other than `fonts.googleapis.com` / `fonts.gstatic.com`;
- `document.documentElement.scrollWidth <= clientWidth` (no horizontal body scroll);
- overview layout timing recorded (report it: nodes, edges, ms);
- the key fact table exists and Focus on it renders with its details text;
- search for the term returns results and Enter selects a node;
- dark theme body background and text colour computed (eyeball `lineage-dark.png` for legibility).

Screenshots: `lineage-overview.png`, `lineage-focus.png`, `lineage-dark.png`, `lineage-panels.png`. Read them before declaring done.

The page is wrapped in a document skeleton at publish time, so the template starts at `<title>`.
