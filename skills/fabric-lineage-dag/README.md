# fabric-lineage-dag

The **`fabric-lineage-dag`** agent skill: turn a Microsoft Fabric workspace
exported to Git (pipelines, notebooks, lakehouses, JSON-config Silver/Gold,
TMDL semantic models, PBIR reports) into an interactive "what feeds what"
lineage DAG — one self-contained HTML page with an overview, dbt-style focus
mode, a details panel with inherited schedules, and a Coverage & gaps panel
that states what the graph had to guess or skip.

## What it does

- **Fixed id contract first.** Table ids keep their schema
  (`gold.fact_fgfactitemsale`) because Fabric stores `Tables/<Schema>/<Table>`
  and names collide across schemas; notebooks use the `.platform` displayName,
  never the folder GUID; anything dynamic becomes an `unresolved.*` node
  instead of vanishing.
- **Five parallel extractors**, stdlib-only Python, one per evidence source:
  pipelines + schedules + dataflows, Silver configs, Gold configs + wrapper
  notebooks, notebook code, semantic model + reports. Each returns a
  found / parsed / partial coverage line. They know the gotchas: the
  segment-reversed GUID form pipelines and TMDL use to reference items,
  `additionalProcedure` being a function name resolved via `globals()`,
  per-country Bronze paths, runtime `INFORMATION_SCHEMA` table lists.
- **Merge + validate.** Union by id, alias schema-less ids, stub dangling
  refs, derive `isFork` and `isLive` (reachable from an enabled schedule),
  inherit partner/country downstream, and write a validation report with
  thirteen gap lists (Gold with no upstream, notebooks nothing runs,
  pipelines with no schedule and no invoker, …).
- **Render.** dagre + a 50 KB d3 bundle inlined under a strict CSP (Google
  Fonts only). Overview groups sources per database and Bronze per
  schema + country (~300 nodes, under 100 ms); focus mode walks the directional
  closure with a depth selector and a 400-node cap. Light/dark tokens, layer
  text tags so identity is never colour-alone, Playwright verification.

## Requirements

- A Fabric Git export: `*.DataPipeline`, `*.Notebook`, `*.Lakehouse`,
  `*.SemanticModel`, `*.Report` folders with `.platform` files.
- `python3` on PATH for the extractors and merge (standard library only).
- Node for the render step: `npm install` in `scripts/render/` pulls dagre,
  d3-selection/zoom/transition, esbuild and Playwright.
- A repo map or README naming lakehouses, wrapper notebooks, partner names,
  and developer fork folders — copied into `lineage.config.json`.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/fabric-lineage-dag
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install fabric-lineage-dag@relentless-data-skills
```

## Files

- `SKILL.md` — the id contract and the six-step procedure (config → five
  extractors → merge/validate → render → copy pass → publish).
- `references/extractors.md` — per-source parsing rules and gotchas.
- `references/validation.md` — merge rules and the report checklist.
- `references/render.md` — UX spec, performance rules, design tokens,
  verification checklist.
- `scripts/lineage_common.py` — shared CLI, config defaults, GUID map,
  graph builders.
- `scripts/extract_*.py`, `scripts/merge_graph.py` — the pipeline.
- `scripts/lineage.config.example.json` — every repo-specific knob.
- `scripts/render/` — `template.html`, `style.css`, `app.js`,
  `build-data.js`, `build.js`, `test.js`, `package.json` (see its README).

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
