# Bootstrap a project's Snowflake context

Use this guide when `.snowman/context.md` is absent or the user requests a
refresh. Discover what the account can tell you. Reuse choices and authorization
already supplied, and ask only for unresolved preferences.

## Choose connections

List named connections with `snow connection list`. This local CLI operation
is the exception to routing SQL through the wrapper. Use an explicitly named
connection, or the sole available connection, without another confirmation.
With several plausible connections, ask which belong to this project. If the
user chooses several accounts, also ask for their environment names.

If no connection exists, ask the user to run `snow connection add` in their own
terminal. The user owns credential setup. Snowman does not create connections.

Before context exists, run discovery with:

```bash
python3 <skill-dir>/scripts/snowman.py --connection <chosen> "<SQL>"
```

Stop passing `--connection` after writing context. The override uses the named
connection's warehouse setting. Queries require network access. Follow the
execution and failure guidance in [SKILL.md](../SKILL.md#handle-failures).

## Discover and resolve preferences

Announce the relevant discovery queries, then run them under the user's existing
Snowflake request. There is no separate approval gate for each query or account.
For multiple environments, run against each chosen connection:

```sql
SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_REGION()
SHOW TERSE DATABASES
SHOW WAREHOUSES ->> SELECT "name","size","state","auto_suspend" FROM $1
SHOW ROLES ->> SELECT "name" FROM $1
```

Inspect authentication setup below only when needed. Successful existing
sessions do not need another login. If the requested scope already identifies
a database or schema, discover that scope instead of inventorying the account.

Ask remaining setup questions together, with recommendations:

- Databases to record. Start with the requested scope and let the user expand it.
- Which databases are production in a single-account project. Confirm ambiguous
  names rather than assuming every raw database is production.
- Default warehouse per account. Recommend an appropriate small warehouse from
  the available choices. The wrapper passes it to queries and staged run commands.
- Default environment for multiple accounts. Recommend the non-production one.

Enumerate schemas only for the selected databases:

```sql
SHOW TERSE SCHEMAS IN DATABASE <db>
```

## Write context

Write `.snowman/context.md` using the resolved choices and observed metadata.
Existing authorization covers this local setup. Show the resulting file and
summarize any assumptions rather than asking for another approval. Record names
and architecture only, and keep the file in version control.

Use one of these mutually exclusive frontmatter forms. A single account uses:

```yaml
---
connection: <chosen-connection>
default_warehouse: <warehouse>
databases:
  - name: <database>
    env: dev
---
```

For multiple accounts, each environment holds its connection and warehouse.
The environment name replaces per-database environment flags:

```yaml
---
default_env: dev
environments:
  dev:
    connection: <dev-connection>
    default_warehouse: <dev-warehouse>
    databases: [<database>]
  prod:
    connection: <prod-connection>
    default_warehouse: <prod-warehouse>
    databases: [<database>]
---
```

`default_warehouse` is optional. If omitted, the connection's setting applies.
Use the body for facts that help later investigations, without repeating
frontmatter. Include database purpose, relevant schemas, warehouse sizes and
auto-suspend settings, observed roles, and the discovery date. For multiple
accounts, group those facts by environment. Do not invent access grants from
a role name or mark an untested database as readable.

## Offer project routing

Check root `AGENTS.md` and `CLAUDE.md`. If either already routes Snowflake work
to snowman, continue. Otherwise offer this project instruction once, unless
adding it is already authorized:

```markdown
## Snowflake

Use the `snowman` skill for Snowflake queries. Stage requested database changes
under `.snowman/staged/` for manual execution.
```

Append to `AGENTS.md` if present, otherwise `CLAUDE.md`, or create `AGENTS.md`.
If the user declines, continue without asking again during the session.
Once context is written, resume the original request through the wrapper.

## Authentication

On failure, relay the wrapper's hint matched to the named connection's
authenticator. Consult the connection list for its auth method if needed.
Do not edit `connections.toml`, inspect private keys, or ask for secrets.

For `OAUTH_AUTHORIZATION_CODE` or `EXTERNALBROWSER`, ask the user to run
`snow connection test -c <name>` in their terminal and complete login.
The CLI can then reuse its cached token. Do not drive the browser flow.

For an encrypted key-pair connection, the passphrase can come from the shell
environment or the nearest `.env` at or above the project root. Bootstrap
searches from the current directory. The wrapper relays `.env` values into the
CLI subprocess, with existing shell values taking precedence. It never sources
the file as shell code. Keep `.env` gitignored and never print its contents.

If the hint identifies a missing passphrase, tell the user to set
`PRIVATE_KEY_PASSPHRASE=...` locally. For connections with different passphrases,
use `SNOWFLAKE_CONNECTIONS_<NAME>_PRIVATE_KEY_PASSPHRASE=...` instead. The user
supplies those values privately.
