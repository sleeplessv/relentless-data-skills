# snowman

`snowman` is an agent skill for Snowflake exploration, data profiling,
transformation experiments, and data-quality investigations through the `snow`
CLI. When you request a database change, it prepares a SQL script for you to
review and run manually.

The wrapper filters write statements, multiple statements, `SYSTEM$` calls,
and sequence advancement. This is a lexical check, not a proof that SQL has no
side effects. Use a least-privilege connection and trusted read functions.
UDFs and external functions can have effects the filter cannot detect.

## How it works

The first invocation discovers the relevant Snowflake objects and writes
`.snowman/context.md`. It reuses choices you already made and asks for unresolved
connection, environment, database, and warehouse preferences. The context stores
names and architecture, never credentials, and belongs in version control.

A project can use one named connection or map several accounts to environments
such as `dev` and `prod`. Queries use the default environment unless you request
another. Staged changes require an explicit environment in multi-account
projects. The configured warehouse applies to queries and staged run commands.

Query stdout contains CSV or, with `--json`, a compact JSON array. Notes go to
stderr. Defaults limit previews to 50 rows, 200 retained characters per cell,
and 16,000 UTF-8 data bytes. Any truncation saves full rows and schema in a
JSON artifact for local inspection, so long DDL or VARIANT values do not require
another query. SQL errors are flattened from the CLI's panel output.

Staged scripts live in the gitignored `.snowman/staged/` directory. Their headers
include the target connection, manual run command, and destructive-keyword
warnings where applicable. Snowman never executes staged scripts or deletes them.

## Install

```bash
npx skills add sleeplessv/relentless-data-skills/skills/snowman
```

Or install through the plugin marketplace:

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install snowman@relentless-data-skills
```

See the [repository README](../../README.md) for other installation methods.
Snowman activates for Snowflake work. It uses existing named `snow` connections.
Create one with `snow connection add` if needed. Authentication setup is in
[the bootstrap guide](references/install.md#authentication).

## Documentation and code

- [SKILL.md](SKILL.md) contains the agent's core workflow.
- [Bootstrap](references/install.md) covers project context and authentication.
- [Guardrails and output](references/guardrails.md) specifies filtering,
  result formats, limits, errors, and staging behavior.
- [Workflows](references/workflows.md) provides focused SQL examples.
- [snowman.py](scripts/snowman.py) implements the standard-library-only wrapper.

Repository CI checks the skill with `python3 scripts/lint_skill.py`.
