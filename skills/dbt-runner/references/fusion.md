# dbt-fusion quirks

Only relevant when the context file says `engine: fusion`. These are
fusion-specific behaviors whose error messages point *away* from the real
cause. Generic triage (and dbt-core experience) will mislead you here.

## `invalid identifier '<COLUMN>'` inside a **unit test**

The error names a column the model selects from one of its inputs. It
looks like a model bug. It usually isn't:

1. **Fixture schema inference failed.** When a unit test's `given:` input
   has `rows: []` (or its rows omit some columns) *and* that upstream
   model is **not in the build selection**, fusion cannot infer the input's
   schema and throws `invalid identifier` on any column the model selects
   from it. Discriminate: does the same test pass when the upstream is
   included in the selection (`dbt build --select <upstream>+<model>`)?
   If yes, this is the inference gap, not a regression.
   Fixes, best first:
   - add the referenced columns (even with null values) to the fixture's
     `rows:` so the schema is explicit;
   - or include the upstream model in the selection when running the test.
2. Only if (1) is excluded: a genuinely missing column. Treat it as a
   normal `invalid identifier` (see failures.md).

## A model's data tests silently don't run

After a build, expected `relationships`/`unique`/`not_null` results for a
model are simply absent from the output:

1. **A failing/erroring unit test blocks the model's sibling tests.**
   Fusion skips a model's other tests when one of its unit tests errors.
   The skipped tests don't appear as failures, they just don't run, so a
   "green-ish" log can hide an unverified model. Workaround to run them
   anyway:
   ```bash
   dbt run --select <model> > /tmp/dbt_run.log 2>&1
   dbt test --select <model>,test_name:relationships > /tmp/dbt_test.log 2>&1
   ```
   (swap the `test_name:` filter for the tests you need). Fix the unit
   test separately, often the fixture-inference entry above.

## Behavior changed between sessions · `New version available` nag

1. **Version drift.** Fusion is preview software; `dbt system update`
   changes behavior between previews, and an auto/explicit update may have
   happened since the context file was written. Compare `dbt --version`
   against `engine_version` in the context file; if they differ, update
   the context file and re-verify any quirk you were relying on, including
   the two above, since they may be fixed or changed.
