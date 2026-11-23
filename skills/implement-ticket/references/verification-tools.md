# Verification tools

Step 4 defines a **data change** and sends it here. For these a clean exit proves the change
compiles. The evidence is an observation of the result, and each skill below is the tool that
takes it.

## Tools

| The change | Skill | Observation it gives |
| --- | --- | --- |
| A dbt model, seed, test or macro | `dbt-runner` | The build of the changed selection in the working target: which models built and which tests passed |
| A Snowflake relation, including one a dbt build writes | `snowman` | Read-only SQL over that relation: counts, key uniqueness, a criterion's number |
| A Power BI measure, table, column or relationship | `pbi` (installed from the `sleeplessv/pbi-toolkit` repo, not this one) | A DAX query against a published dataset; see [Power BI](#power-bi) |

Setup does not resolve these. Invoke a skill the session lists; otherwise locate its installed
`SKILL.md` on disk as [Setup](setup.md) locates companions and read it as a file. Record the
resolved path in the findings artifact.

**When a skill is not installed, or the project's warehouse or BI tool has no row**, take the
same observation through a read path the project documents, and record the substitution. In a
dbt project that is the project's own dbt runner. Read the query into `SQL` with a quoted heredoc
in the same shell call, so the shell keeps its quotes and `$` (`show` appends its own limit, so
the SQL carries none):

```bash
unset SQL && { IFS= read -r -d '' SQL || [ -n "$SQL" ]; } <<'SQL' &&
<SQL>
SQL
<runner> show --inline "$SQL" --limit <N>
```

With no documented read path, or with credentials or network missing, the observation is a
blocked check as step 7 defines it.

**Verification is reads plus builds into the working target.** Every other command here is a
read. An observation that needs a write to shared state (a production build, a staged script, a
dataset refresh or publish) waits for the user, who runs the write after merge. Its criterion
is **pending, not blocked**: record the before, why the after waits, and the query that will
show it, and list it as a post-merge check in the [PR body](review-and-pr.md#pr-body). An
orchestrated worker returns the same record in `open_questions`, because its `success` covers
only criteria observed on its head.

## Data check

Step 7's check for a data change. Done when every acceptance criterion that names a number, a
column, a row set or a grain has a recorded query whose output shows it holding on the built
relation, or is recorded as pending under the rule above.

1. **Write the queries.** One per criterion, plus the duplicate count on the relation's key and
   its row count. Each reruns to the same answer and states its pass condition: bound it by a
   closed date range, or compare two relations inside one query, and expect zero rows or equal
   counts. Name every relation in full (`database.schema.relation`).
2. **Before.** Run them on the **base relation**: one built from a commit you can name. That is
   the working target right after a build of `base_sha` (step 4's baseline run, when it
   builds), or the deployed relation when the deployed commit is the base. Record which, and
   its commit. A relation of unknown provenance, such as a working-target relation nobody
   rebuilt, is not a before: with no base relation, say the before is unavailable. A relation
   the ticket creates has none.
3. **Build.** Build the changed models and their tests in the working target. The build counts
   when its log lists the models you selected and a count query shows each has rows: a
   selection that matched nothing and a model built from an empty source both exit 0
   (`dbt-runner`: "Verify the selection matched", "Check the run was not vacuous").
4. **After.** Run the same queries on the **built relation**, the one the build log names.
   `snowman` queries its default environment unless told otherwise, so pass the environment
   the build wrote to: a before and an after that both read production show no difference and
   prove nothing. The ticket explains every difference from the before. One it does not
   explain is a defect to fix, or to report when it is out of scope.
5. **Record.** Save the build command and the queries as one script in the findings artifact,
   with the working target, the relations queried, the output and the checked SHA.
   [Closing verification](review-and-pr.md#closing-verification) reruns that script from a
   fresh checkout, which starts without `dbt_packages/`, so record `deps` with the install
   commands.

Builds into one working-target schema collide. A worker dispatched beside others builds only
into the schema its brief allocates, and with none allocated returns the question in
`open_questions` before its first build.

## Power BI

`pbi` queries a published dataset, and the worktree's TMDL reaches the Service only when an
operator publishes. What the ticket can observe depends on what it changes:

- **A changed measure:** two queries on the same dataset and stage, both named in the record.
  The before evaluates the deployed measure with no `DEFINE` block. The after follows "Test
  measures from local TMDL" in the `pbi` skill's `references/querying.md`: its `DEFINE` block
  shadows the deployed measure with the local definition, so one query cannot hold both.
  Build that index with `--tmdl-path` set to the ticket worktree's TMDL and `--output` set to
  a file in the run directory, which leaves the project's shared index on the base
  definitions. A new measure has only the after.
- **A changed table, column or relationship:** run the before query now. The after is pending
  until an operator publishes.
