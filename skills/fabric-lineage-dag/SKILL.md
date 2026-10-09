---
name: fabric-lineage-dag
description: Build an interactive data-lineage DAG for a Microsoft Fabric Git-exported workspace (pipelines, notebooks, JSON-config Silver/Gold, TMDL semantic models, reports) as one self-contained HTML artifact. Use when asked for a lineage graph ("what feeds what") or a dbt-docs-style DAG over a Fabric medallion repo.
metadata:
  author: sleeplessv
---

# Fabric lineage DAG

The main thread **coordinates**: it fixes the contract, fans out five extractors in parallel, applies their shared `lineage_common.py` patches, then dispatches merge, render, copy pass, and publishes. Every dispatched agent gets the scratchpad path, `--repo`, the id contract below, and the reference file for its step. Scripts run from the run's own copy in `<scratch>/scripts/` (made in Step 1) with `python3` (stdlib) and the render step with Node. `<skill-dir>` is the installed skill: agents read it and never edit it; every script patch lands in `<scratch>/scripts/` and is logged in `<scratch>/patches.md` for the user to upstream.

**Input:** a Fabric workspace exported to Git (`*.DataPipeline`, `*.Notebook`, `*.Lakehouse`, `*.SemanticModel`, `*.Report` folders with `.platform` files). **Output:** `lineage.html` published as an artifact, plus `validation-report.md` in the scratchpad.

## Id contract (every extractor uses exactly this)

Schema: `{nodes:[{id,name,layer,type,path,partner,country,loadType,details{}}], edges:[{from,to,kind,via,path}]}`.

| thing | id | note |
|---|---|---|
| lakehouse table | `<layer>.<schema>_<table>` lower-case | schema kept: Fabric stores `Tables/<Schema>/<Table>` and names collide across schemas; `dbo` / no schema → `<layer>.<table>` |
| source SQL table | `source.<database>.<schema>.<table>` | |
| partner file drop | `source.partnerdrop.<partner>/<report>[/<country>]` | |
| blob path | `source.blob.<container>/<path>` | exports: `export.blob.*`, `export.sftp.*` |
| lakehouse file | `<layer>.files/<path>` | |
| notebook | `notebook.<displayName>` | displayName from `.platform`, never the folder GUID |
| pipeline / dataflow | `pipeline.<displayName>` / `dataflow.<displayName>` | |
| schedule | `trigger.schedule.<pipeline>` | `details.enabled` decides liveness |
| semantic | `semantic.<Model>` / `semantic.<Model>.<Table>` | |
| report | `report.<Name>` | |
| config | `config.<file>` | orchestration / rules files |
| anything dynamic | `unresolved.<raw text>` | f-strings, `@item()`, runtime lookups |

Edge kinds: `copy transform reads writes calls runs invokes triggers refreshes directlake relationship partof binds dax`. Layers: `source bronze silver gold semantic report notebook pipeline dataflow metadata awsstaging export unresolved`.

## Step 1: Contract and config

Copy `<skill-dir>/scripts/` to `<scratch>/scripts/` once, before any dispatch. Read the repo map (README / REPO-MAP / CONTEXT) for: lakehouse names, per-country Bronze databases, partner names, developer fork folders, the Silver and Gold wrapper notebooks, config globs, the key fact table. Write `<scratch>/lineage.config.json` from `scripts/lineage.config.example.json` (every key optional; defaults in `scripts/lineage_common.py`).

Done when: `<scratch>/scripts/` exists, the config file exists, the key fact table id is written down in the contract form (e.g. `gold.fact_fgfactitemsale`), and a search term for the test is chosen.

## Step 2: Five parallel extractors

Dispatch five agents at once, each with [`references/extractors.md`](references/extractors.md), the config, and one script. Each agent owns its `extract_<name>.py` in `<scratch>/scripts/` and nothing else there: the five share `lineage_common.py`, so a fix it needs comes back as a proposed patch, and the main thread applies all such patches once after the five return, then reruns the affected extractors.

1. pipelines + schedules + dataflows → `extract_pipelines.py` (also writes `guid-map.json`)
2. Silver configs → `extract_silver.py`
3. Gold configs + wrapper notebooks → `extract_gold.py`
4. notebook code → `extract_notebooks.py` (also writes `notebook-inventory.json`)
5. semantic model + reports → `extract_semantic.py`

```bash
python3 <scratch>/scripts/extract_<name>.py --repo <repo> --out <scratch> --config <scratch>/lineage.config.json
```

Each agent runs its script, reads the printed stats, spot-checks ten nodes against the repo, fixes misses in its own extractor script, and returns a one-line coverage summary: `found / parsed / partial` with reasons (runtime table lists, missing files, unresolved GUIDs), plus a patch list: the diff it applied to its script, any proposed `lineage_common.py` diff, and any config key it needs (the main thread owns `lineage.config.json`).

Done when: all five `extract-*.json` files exist and reflect every applied shared patch and config change, every coverage line names its partial cases, the main thread has appended the five lines to `<scratch>/coverage.txt`, and every patch list is collected in `<scratch>/patches.md`.

## Step 3: Merge and validate

One dispatch with [`references/validation.md`](references/validation.md):

```bash
python3 <scratch>/scripts/merge_graph.py --out <scratch> --config <scratch>/lineage.config.json --coverage <scratch>/coverage.txt [--alias semantic.dataset-<guid>=semantic.<Model>]
```

`--config` is the same file the extractors used, so fork rules (`forkNamePattern`, `forkDirPattern`, `notebooks.forkDirs`, `notebooks.forkNamePrefixes`) are defined once.

The agent reads `validation-report.md`, classifies every non-zero gap as a real finding or an extractor miss, fixes misses in `<scratch>/scripts/` (rerun the extractor, rerun merge, add the diff to `<scratch>/patches.md`), and returns the report's totals and gap counts.

Done when: stubs = 0, every alias is logged, the report contains all thirteen checklist items, and `graph-compact.json` is under 2 MB.

## Step 4: Render

One dispatch with [`references/render.md`](references/render.md) and `scripts/render/README.md`. The agent bundles d3, builds `data.json` and `lineage.html` (title from the workspace, optional explainer SVG written from the report numbers), and runs `test.js` against the key fact table and the search term.

Done when: `test.js` prints `PASS` (no console errors, no external hosts beyond Google Fonts, no horizontal body scroll, focus and search work, dark theme computed), overview layout is under 100 ms for ~300 nodes, and the four screenshots have been looked at.

## Step 5: Copy pass

Run `unslop` over the page's user-facing strings (title, subtitle, explainer caption, gap bullets, notices, empty states) and rebuild.

Done when: the rebuilt page still passes `test.js`.

## Step 6: Publish

Load `artifact-design`, then publish `lineage.html` with the Artifact tool: noun-phrase title, one-sentence description, an `icon` on the first publish (omit it on redeploys so the artifact keeps it), a version label. Relay the artifact URL, the validation totals, the top gaps, and the script patches from `<scratch>/patches.md` to the user.

Done when: the URL is returned and the message names the numbers the page shows (nodes, edges, live, forks, unresolved) and the gap headlines.
