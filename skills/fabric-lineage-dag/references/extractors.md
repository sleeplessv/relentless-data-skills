# Extractors: per-source parsing rules and gotchas

Five read-only extractors, one per evidence source, each writing `extract-<name>.json` in the schema from `SKILL.md` and returning a coverage line (`found / parsed / partial + reasons`). Dispatch per SKILL.md Step 2.

Shared: `scripts/lineage_common.py` builds the **GUID map** from every `.platform` file (displayName, type, path, logicalId) keyed by logicalId, folder GUID, the byte-swapped form, and the segment-reversal form. Resolve every item reference through it; emit `unresolved.*` when it misses.

## GUID forms (the gotcha that breaks everything)

Pipelines and TMDL expressions reference items by a transformed GUID that is neither the logicalId nor the documented little-endian byte swap. For logicalId `14aedf53-5d85-8100-4f82-5c29aee97a45` the reference is `aee97a45-5c29-4f82-8100-5d8514aedf53`: with groups `g1-g2-g3-g4-g5`, the reference is `g5[4:]-g5[:4]-g4-g3-g2+g1`. The transform is its own inverse (`alt_guid` in `lineage_common.py`). Store all four forms in the map.

## 1. Pipelines (`extract_pipelines.py`)

Inputs: `**/*.DataPipeline/pipeline-content.json`, sibling `.schedules`, `**/*.Dataflow/mashup.pq`. Pipelines live outside `Pipelines/` too; glob the whole repo.

- Walk activities recursively: `ForEach.activities`, `IfCondition.ifTrue/ifFalseActivities`, `Switch.cases[].activities` + `defaultActivities`, `Until.activities`. Record `dependsOn` so the activity chain reads in order.
- Unwrap `{value, type: Expression}` wrappers everywhere (`val()`).
- **Copy**: dataset type (`AzureSqlTable` / `SqlServerTable` → `source.<db>.<schema>.<table>`; `Json` / `DelimitedText` / `Binary` / `Parquet` with `AzureBlobStorageLocation` → `source.blob.<container>/<path>`, with a lakehouse location → `<layer>.files/<path>`; `LakehouseTable` → `<layer>.<schema>_<table>`). Sink: `LakehouseTable` → table node; file sinks → `export.blob.*` / `export.sftp.*` / `<layer>.files/*`. Lakehouse layer comes from the `artifactId` in `linkedService` / `connectionSettings` resolved through the GUID map. Edges: `copy` source→sink (via `<pipeline>/<activity>`, query kept), plus `reads` / `writes` from the pipeline.
- **ForEach table lists**: when `items` is `@variables('X')` / `@pipeline().parameters.X` with an array default (`FullLoadTables`, `DeltaLoadTables_*`), expand the inner Copy once per item, substituting `@item().field`. When the list comes from a runtime `Lookup` (`INFORMATION_SCHEMA.TABLES`), emit `unresolved.source.<db>.<schema>.@item().table_name`, keep the lookup query on the node, and mark the pipeline **partial** in the coverage line.
- **TridentNotebook**: `notebookId` → displayName via the map. Keep `parameters` verbatim on the `runs` edge. Partner ingests are notebook-driven with no Copy, so lineage comes from the parameters: `BasePathPattern` (`Files/Partners/<partner>/<report>/{Country}`) → `source.partnerdrop.*`; `TargetTable` → `bronze.<schema>_<table>`; `SilverJsonFileName` / `jsonFileName` → Silver config. `{Country}` expands from the enclosing ForEach over a country list.
- **InvokePipeline / ExecutePipeline** → `invokes`; **RefreshDataflow** → `triggers` a `dataflow.*` node; native semantic refresh activities → `refreshes`; **WebActivity** (Key Vault) and **Office365Email** recorded on the activity only; **Lookup** with `INFORMATION_SCHEMA` flags partial.
- **Schedules**: one `trigger.schedule.<pipeline>` node per entry with `enabled / type / times / weekdays / interval / timezone`, `triggers` edge to the pipeline. Only enabled schedules make a pipeline a live root.
- **Semantic refresh via REST**: refresh often happens from a notebook POSTing to `datasets/<id>/refreshes`; the extractor greps run notebooks for `dataset_id` / `workspace_id` GUIDs and emits `refreshes`. The dataset id usually lives in a *different* workspace than the Git model: record both ids on the node and leave the identity to the merge step (`--alias`).
- **Dataflows** (`mashup.pq`): `Sql.Database("server","db",[Query=...])` → FROM/JOIN tables as `source.*`; `lakehouseId = "<guid>"` navigation chains with `Id = "Files"` → lakehouse file nodes; `_DataDestination` → `writes`.

## 2. Silver configs (`extract_silver.py`)

Inputs: `files/config/Silver/**/*.json` (+ extra globs from config). Two shapes:

- **Orchestration**: `integrationName` + `etlTasks[]` with `procedureName` that is a full `Files/config/...` path, a bare filename (sibling of the orchestration file), or a `.py` step. `.py` steps drive a JSON through a hard-coded path: declare them in `silver.pyStepConfigs`.
- **Table definition**: `databaseMapping` (`sourceLayer`, `sourceDatabase`, `targetDatabase`, `tableCountries`, `transformProcedure`) + `tables[]` (`sourceTable`, `targetTable`, `loadType` Full / Delta with casing that varies, `targetTableSurrogateKeys`, `partitionColumn`, `columns`).
- Bronze path resolution (read it from the repo's generic view-creation notebook and set `perCountryBronzeDatabases`): `<sourceDatabase>/<country>_<sourceTable>` for per-country databases, else `<sourceDatabase>/<sourceTable>`. One Bronze node per country in `tableCountries`.
- Pipeline wiring: grep each `pipeline-content.json` for `Files/config/...json` (pipeline variable `SilverJsonFileName` → notebook param `jsonFileName`); the pipeline `runs` the notebooks whose GUIDs appear in it.
- **Flag** in the coverage line: table configs referenced by no orchestration file; orchestration files referenced by no pipeline; case-mismatched filenames between a pipeline parameter and the repo (`LgEnergy…` vs `LGEnergy…` load fine on the case-insensitive OneLake and fail on a case-sensitive check, so say which); pipelines pointing at files missing from the repo.
- `Config.conf`: capture layer abfss paths and every lakehouse GUID in a `config.generic_conf` metadata node.

## 3. Gold configs + wrapper notebooks (`extract_gold.py`)

- Orchestration JSONs (`GoldDimMainLoad`, `GoldFactMainLoad`, `GoldFactPartnersLoad`, …) list steps in order with `critical` flags; map each to the pipeline activity that runs it in `gold.orchestrationPipelines`.
- Table JSONs: `sourceTable[]` / `sourceTableName` name Silver tables under `sourceLayer` (a schema here, the lakehouse is `sourceDatabase`), `targetTable`, `additionalProcedure`. Store mapping: `storeCodeColumn` + `integrationPartnerId` join through `<StoreSchema>.FgIntegrationPartnerStore` and `FgStore` (SCD2) to `SkStoreId`; add those as `transform` inputs.
- **`additionalProcedure` is a FUNCTION name resolved via `globals()`, not a notebook name**: `FgEtlLoadGoldFactTableItemSale.py` in config is satisfied by `%run ./FgEtlGoldFactTableItemSale.py` defining `def FgEtlLoadGoldFactTableItemSale`. Resolve by scanning `def` names in every `%run` target of the wrapper.
- `GoldWrapperMain.py` `%run`s the wrappers: a loader is **wired** when the wrapper `%run`s the notebook that defines its function, **orphaned** otherwise (config + notebook exist, nothing runs them). Report both lists. Wrapper `%run` targets missing from the repo are shared helpers living elsewhere; list them.
- Hand-written Gold notebooks: qualified names in SQL (`Gold.Dimension.X`, ``delta.`…/Fact/X` ``) become edges; unqualified names are temp views over the config-declared Silver tables, already covered. Override or extend with `gold.handWritten` when the SQL parse misses (CTE-heavy notebooks).
- No literal `saveAsTable` / `MERGE INTO` in config-driven loaders: writes go through the generic load function to `goldFactDBFSPath/Fact|Dimension/<target>`. DQ notebooks read configs that may be absent from Git → `unresolved.` node with the missing path.

## 4. Notebook code (`extract_notebooks.py`)

Inputs: every `*.Notebook/notebook-content.py` + `.platform`. Outputs the graph and `notebook-inventory.json` (reads / writes / calls / isFork per notebook, used by merge).

- Patterns: `spark.read.table` / `spark.table` / `DeltaTable.forName`, SQL `FROM` / `JOIN` / `MERGE INTO` / `INSERT INTO|OVERWRITE` / `CREATE TABLE` / `DROP` / `TRUNCATE` / `OPTIMIZE` / `VACUUM` in python strings and `%%sql` cells, `saveAsTable`, `.save/.load/.parquet/.csv/.json(path)`, `DeltaTable.forPath`, `%run` and `notebookutils|mssparkutils.notebook.run` → `calls`, `runMultiple` → unresolved DAG.
- Layer resolution order: lakehouse GUID inside an abfss path → `Lakehouse.Schema.Table` three-part name → schema hint (`Fact` / `Dimension` → gold) → the notebook's default lakehouse from the `# META` header or `%%configure` → a catalog built from every config JSON's source/target tables. Unqualified names that match no temp view / CTE and pass the prefix regex become `<default layer>.<name>` marked `unqualified`.
- f-string names: one level of variable substitution from `name = "..."` assignments; still templated → `unresolved.{template}`.
- Gotchas: folder names differ from displayName (`validateInputParameters.py.Notebook` displays `etlValidateInputParameters.py`), so ids use displayName only; config-driven wrappers have no default lakehouse and rely on the wrapper's session, so resolve their tables via the config they name (`"X.json"` in code → that config's tables); `%run` hubs run 60+ notebooks, which is fine for `calls` but means a notebook with no table refs is not necessarily dead.
- Forks: developer folders, `Test` / `Stage` prefixes, `bkp` / `Copy` / date suffixes; set `notebooks.forkDirs` and `forkNamePrefixes` from the repo map.

## 5. Semantic model + reports (`extract_semantic.py`)

- `definition/tables/*.tmdl`: `partition X = entity` with `entityName`, `schemaName`, `expressionSource` → `definition/expressions.tmdl` holds `AzureStorage.DataLake("https://onelake.dfs.fabric.microsoft.com/<workspace>/<lakehouse>")`; the lakehouse GUID matches a `*.Lakehouse/.platform` logicalId only after the segment-reversal transform. Edge `directlake` from `<layer>.<schema>_<entity>`.
- Calculated tables and calc groups (`DATATABLE`, `GENERATESERIES`, `calculationGroup`, `INFO.VIEW.COLUMNS`) have no Gold source: list them as **expected** unresolved, with count. Calculated columns and calculated partitions referencing other tables → `dax` edges.
- `relationships.tmdl` → `relationship` edges with cardinality, cross-filter, `isActive`. Measures count per table, `#measures` table separately.
- Reports: `*.Report/definition.pbir` `datasetReference.byPath` (relative path to a `.SemanticModel`; flag when the folder is missing) or `byConnection` (`initial catalog=` in the connection string) → `binds` edge from the model. Reports in sandbox folders (`semantic.sandboxReportDirs`) are flagged, not dropped.
- A model named in the repo map but absent from Git (e.g. a `SalesModel` that exists only in the service) goes in the coverage line.
