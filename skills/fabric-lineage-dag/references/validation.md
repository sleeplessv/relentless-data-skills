# Merge + validate

One dispatch after all five extracts exist. `scripts/merge_graph.py --out <scratch> --config lineage.config.json --coverage coverage.txt [--alias old=new]` writes `graph.json`, `graph-compact.json`, `validation-report.md`. Pass the same `--config` the extractors used: merge reads its fork rules from it (`forkNamePattern`, `forkDirPattern`, `notebooks.forkDirs`, `notebooks.forkNamePrefixes`), with `--fork-pattern` / `--fork-dirs` as overrides. The dispatched agent runs it, reads the report, and fixes extractor bugs it reveals before the render step sees the data.

## Merge rules

- **Nodes** union by `id`. First non-empty `name / layer / type / path / partner / country / loadType` wins; `details` deep-merge (lists union, dicts recurse, disagreeing scalars land under `details._conflicts`). Each node records `sources` (which extracts contributed).
- **Edges** union by `(from, to, kind)`; `via` and `path` become arrays; `note` values collect under `details.notes`.
- **Aliases**, applied before the union and every one logged in the report:
  - schema-less table ids (`silver.fgstore`) → the unique schema-prefixed id with the same table name in the same layer (`silver.slang_fgstore`); ambiguous or no candidate → left as-is and logged.
  - notebook ids differing only in case or whitespace → the one present in `notebook-inventory.json`.
  - `--alias` for identities only a human can assert (the REST-refreshed dataset GUID vs the Git model). The report states the identity is NOT verified from the repo.
- **Stubs**: any edge endpoint with no node gets a `stub: true` node; the count is a validation number and should be zero after extractor fixes.
- **isFork**: notebooks from the inventory flag; pipelines / dataflows / configs from `isDevFork` / `fork` or the fork regexes over name and path; reports from name / path; tables from the config's `fork` flag.
- **isLive**: roots are enabled `trigger.schedule.*` nodes and the pipelines they trigger; live = reachable **forwards or backwards** from a root over lineage kinds (`runs invokes copy transform reads writes directlake refreshes triggers calls binds partof`), excluding `dax` and `relationship`. A Gold table a scheduled pipeline writes is live; a report bound to a model refreshed by a scheduled chain is live; a notebook nothing runs is not.
- **Inheritance**: `partner` and `country` propagate downstream over `transform` / `copy` edges to a fixpoint when every input agrees; the node records `details.inherited`.
- **Size**: `graph.json` caps strings at 600 chars and arrays at 60 items; `graph-compact.json` keeps only `SHORT_KEYS` details (200-char strings, 12-item lists) and `via[:5]` per edge. Expect roughly 1.3 MB for ~2000 nodes / ~4800 edges.

## Report checklist

`validation-report.md` must contain every item; the dispatched agent confirms each is present and reports the numbers back to the main thread:

1. Coverage text from the extractors, **verbatim** (pass it in via `--coverage`).
2. Totals: nodes, edges, raw input rows, stub count with ids, alias count, live count, fork count, scheduled roots, inheritance counts, truncation counts, compact size.
3. Per-layer counts (nodes / live / fork), edges by kind, edges by layer pair.
4. Alias log, one line per alias, and nodes with `_conflicts`.
5. Orphan tables (no edges at all).
6. Gold tables with no upstream `transform` / `writes` / `copy`.
7. Semantic tables with no Gold `directlake` source, alongside the list of calculated / calc-group tables so the expected ones are distinguishable.
8. Bronze tables with no `copy` / `writes` in (runtime table lists explain most).
9. Silver tables with no Bronze input, and the subset with no upstream at all.
10. Non-fork notebooks never `runs` / `calls` / `invokes`-targeted.
11. Pipelines with no schedule and no invoker; pipelines whose only trigger is a disabled schedule.
12. Unresolved nodes.
13. Non-fork pipelines not live; Gold tables not live; DirectLake sources no ETL writes.

The same lists ride along in `graph-compact.json` `meta.gaps`, which is what the page's Coverage & gaps panel renders, so a number in the report and a number on the page always agree.

## Reading the report

Treat each non-zero gap as either a real finding (say so in the Gaps panel: "22 pipelines have no schedule and no invoker") or an extractor miss (fix the extractor and rerun). Typical extractor misses: a stub from an id convention slip (`gold.fact_x` vs `gold.x`), a Silver table with no Bronze input because `perCountryBronzeDatabases` is incomplete, a Gold table with no upstream because its loader's function name differs from the config's `additionalProcedure`.
