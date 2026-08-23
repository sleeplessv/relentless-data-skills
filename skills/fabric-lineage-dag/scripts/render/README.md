# render/

Builds the single-file lineage page from `graph.json` + `graph-compact.json` (output of `merge_graph.py`).

```bash
cd <skill-dir>/scripts/render
npm i @dagrejs/dagre d3-selection d3-zoom d3-transition esbuild playwright   # once; or `npm install` from package.json
npx playwright install chromium                                     # once
npm run bundle                                                      # d3-entry.js -> d3.min.js (~50 KB)
node build-data.js <scratch>                                        # -> <scratch>/data.json
node build.js --data <scratch>/data.json --out <scratch>/lineage.html --title "Acme Fabric lineage" [--subtitle S] [--explainer <scratch>/explainer.html]
node test.js <scratch>/lineage.html <focus-node-id> <search-term> <scratch>   # PASS/FAIL + screenshots
```

- `template.html` — page skeleton with `/*__TOKEN__*/` slots; `<!--__EXPLAINER__-->` takes an optional `<details class="panel">` block you write (macro-flow SVG).
- `app.js` — overview grouping, focus closure, dagre layout, details panel, search, filters, Coverage & gaps panel (rendered from `meta.gaps`).
- `style.css` — light/dark tokens on `:root`, layer colours `--c-<layer>`.
- `build-data.js` — picks per-layer detail keys from `graph.json` into the compact graph; edit the `pick(...)` lists to surface more fields.
- `test.js` — Playwright headless checks: console errors, external requests beyond Google Fonts, body horizontal scroll, focus on a key node, search, dark theme.
