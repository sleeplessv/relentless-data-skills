# Verification tools

Read this in step 4 when the ticket changes something whose result lives outside the repo: a dbt
model, warehouse SQL, a Power BI measure or report, a dashboard query, or a scheduled flow. For
these a clean exit proves the change compiles. The evidence is an observation of the result, and
each skill below is the tool that takes it.

## Tools

| The ticket changes | Skill | Observation it gives |
| --- | --- | --- |
| A dbt model, seed, test or macro | `dbt-runner` | The build of the changed selection in the dev target: models built, rows, test results |
| A Snowflake relation, or the data a dbt model builds there | `snowman` | Read-only SQL over the built relation: counts, key uniqueness, the criterion's number |
| A Power BI measure or semantic model | `pbi` (installed separately) | A DAX query against a published dataset; see [Power BI](#power-bi) |
| A PBIP report or model diff | `review-pbi-diff` | Its step 1 extractor's change model: each changed page, visual, binding and measure |
| A Metabase card or the SQL behind one | `metabase` | The SQL the card compiles to (`mb sql-of`) and its result (`mb run`, `mb sql`) |
| A Prefect flow or deployment | `prefect` | The state and logs of a run of the changed flow |

Invoke a skill the session lists. Otherwise locate its installed `SKILL.md` as
[Setup](setup.md) locates companions and read it as a file; `review-pbi-diff` is user-only, so
that is its only route. Record the resolved path with the commands step 4 records.

**When a skill is not installed**, take the same observation through the read path the project
documents, and record the substitution. In a dbt project that is the project's own dbt runner,
with `<runner> show --inline "<SQL>" --limit <N>` for a query. With no documented path, or with
credentials or network missing, the observation is a blocked check as step 7 defines it.

**Verification is reads plus dev builds.** dbt builds into the project's dev target, and every
other command here is a read. An observation that needs a write to shared state (a production
build, a staged script, a dataset refresh or publish, a live card edit) is a post-merge check:
the user runs the write, and the [PR body](review-and-pr.md#pr-body) lists the check.

## Data check

This is step 7's check for a data change. Done when every acceptance criterion that names a
number, a column, a row set or a grain has a recorded query whose output shows it holding on
the built result.

1. **Before.** Before the first build, query the relation as it stands and save the output: its
   row count, the duplicate count on its key, and each criterion's number. The build overwrites
   a dev relation, so this observation cannot be taken later. A new relation has no before; say so.
2. **Build.** Build the changed models and their tests in the dev target. The build counts when
   its log shows the models you selected and each one has rows: a selection that matched nothing
   and a model built from an empty source both exit 0 (`dbt-runner`'s invocation rules 5 and 6).
3. **After.** Run the same queries against the relation the build wrote. Where the base and dev
   relations are both readable, also compare them in one query: counts by the changed column,
   or the rows one holds and the other lacks. The ticket explains every difference from the
   before; a difference it does not explain is a defect to fix, or to report when it is out of scope.
4. **Record.** Save the build command and the queries as one script in the findings artifact,
   with the target or environment, the relations queried, the output and the checked SHA.
   [Closing verification](review-and-pr.md#closing-verification) reruns that script from its
   own checkout, so it rebuilds before it queries, and a different result is a divergence.
   Write each query to rerun to the same answer: bound it by a closed date range or compare
   two relations inside one query, and state the pass condition as zero rows or equal counts.

The dev schema is a shared resource under step 7's allocation rule: parallel workers that build
the same models serialize, or build into separate target schemas where the project provides them.

## Power BI

`pbi` queries a published dataset. The worktree's TMDL reaches the Service only when an operator
publishes, so what the ticket can observe depends on what it changes:

- **A changed or new measure:** follow "Test measures from local TMDL" in the `pbi` skill's
  `references/querying.md`. It evaluates the local definition against the published dataset,
  beside the deployed measure for the before. Build the index from the ticket worktree's TMDL;
  the main checkout holds the base definitions.
- **A changed table, column or relationship:** run the before query now, and list the after
  as a post-merge check.
