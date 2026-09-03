# snowman bootstrap (first run in a project)

You are here because the project has **no `.snowman/context.md`**. Your job is
to discover this project's Snowflake architecture and write that file, so
every later invocation has a per-project source of truth.

**Style: discovery-first, grill-me spirit.** Don't interrogate the user for
things the account can tell you. *Run the read-only SQL and propose what you
found*. Ask only for the genuine decisions. One decision at a time, with a
recommended answer. All discovery here is read-only and goes through the
wrapper (`python3 <skill-dir>/scripts/snowman.py "<SQL>"`), except the
connection-listing step, which uses the `snow` CLI directly.

All `snow` commands need network access to reach Snowflake. Run them with
sandboxing disabled. In a sandboxed shell they fail with DNS/connection
errors that masquerade as a broken connection config.

## Step 0: pick the connection(s) (the only thing not via the wrapper)

snowman uses **named `snow` CLI connections only**. It never creates
connections, handles credentials, key-pairs, or `account/user/password`.

```bash
snow connection list
```

- **Exactly one** → propose it, ask the user to confirm.
- **Several** → list them and ask **which connection(s) this project uses,
  and if more than one, what environment each one is** (e.g.
  `acme-dev → dev`, `acme-prod → prod`). One connection → single-environment
  flow below; several → multi-environment, with separate accounts mapped as
  named environments. Environment names are the user's choice
  (`dev`/`staging`/`prod`…).
- **None** → **stop.** Tell the user to run `snow connection add` themselves
  (interactive auth; SSO/MFA may open a browser), then re-invoke snowman.

**Check each chosen connection's `authenticator`** in the
`snow connection list` output before running anything. The auth method
decides one setup step:

- **Browser auth** (`OAUTH_AUTHORIZATION_CODE` or `EXTERNALBROWSER`): have
  the user run `snow connection test -c <name>` **in their own terminal,
  before the discovery sweep**. A browser opens, they complete the login,
  and `snow` caches the token; wrapper queries then run silently. Don't rely
  on the browser opening mid-query: wrapper calls run non-interactively and
  time out while the user is still logging in.
- **Key-pair auth** (`SNOWFLAKE_JWT` / a `private_key_file`) with an
  **encrypted private key**: its passphrase must live in the project root
  `.env` (e.g. `PRIVATE_KEY_PASSPHRASE=...`). The wrapper relays `.env` to
  the `snow` subprocess automatically. If the first query fails mentioning a
  private key/passphrase/JWT, tell the user to add that line to `.env`;
  never ask for the passphrase or print `.env` contents. With several
  key-pair connections whose passphrases differ, one `PRIVATE_KEY_PASSPHRASE`
  can't serve both. Point the user at `snow`'s per-connection form instead
  (`SNOWFLAKE_CONNECTIONS_<NAME>_PRIVATE_KEY_PASSPHRASE=...`), still in
  `.env`.

> From here on, every command is the read-only wrapper. The wrapper needs the
> connection, but the context file doesn't exist yet, so for the discovery
> sweep only, pass it explicitly:
> `python3 <skill-dir>/scripts/snowman.py --connection <chosen> "<SQL>"`.
> Drop `--connection` as soon as the context file is written.

## Step 1: announce the read-only sweep, then run it (one gate)

Tell the user: *"I'll run these read-only `SHOW`/`SELECT` commands to map the
account, nothing is written. OK?"* (multi-environment: *"…against each
account…"*). Gate **once** for the whole batch, not per statement, not per
account. Then run them: one wrapper call per statement (the wrapper rejects
multi-statement submissions), and in a multi-environment project run the
whole sweep **once per environment**, passing that environment's connection
via `--connection`:

```sql
SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_REGION();
SHOW DATABASES;
SHOW WAREHOUSES;
SHOW ROLES;
```

## Step 2: decisions (ask these; recommend an answer each)

In a multi-environment project, ask 1 and 3 **per environment**. Each
account has its own databases and warehouses.

1. **Which databases** to include in scope? Recommend the ones the current
   role can actually read; let the user trim.
2. *Single-environment only:* **which databases are production**
   (`env: prod`)? Recommend flagging anything named/described as prod or raw.
   In a multi-environment project the environment a database sits under *is*
   its env, so skip this. snowman **never executes writes** anywhere (DML/DDL
   is only ever staged for the user to run manually), but the flag documents
   intent and powers cost/safety warnings.
3. **Default warehouse** for ad-hoc queries? Recommend the smallest
   ad-hoc/analytics warehouse you saw.
4. *Multi-environment only:* **`default_env`**, which environment queries
   hit when none is named. Recommend the non-prod one; the user may
   legitimately prefer prod (snowman is read-only either way).

For each in-scope database, enumerate schemas (still read-only):

```sql
SHOW SCHEMAS IN DATABASE <db>;
```

## Step 3: render the context, confirm, then write (one gate)

Compose `.snowman/context.md` (template below), **show it to the user**, get
approval, then write it to the **project root** (`.snowman/context.md`). It is
safe to commit, names only, no secrets. Suggest the user commit it.

**Single-environment frontmatter** (one account; per-database `env:` flags):

```yaml
---
connection: <chosen-connection-name>
default_warehouse: <warehouse>
databases:
  - name: <db>
    env: dev        # or prod
# snowman never executes writes; user-requested DML/DDL is staged to
# .snowman/staged/ (gitignored) for manual execution.
---
```

**Multi-environment frontmatter** (separate accounts; the environment name
*is* the env, so there are no per-database flags, and each environment carries its own
connection and default warehouse). The two forms are mutually exclusive:

```yaml
---
default_env: <env>            # queries hit this unless --env says otherwise
environments:
  dev:
    connection: <dev-connection-name>
    default_warehouse: <warehouse>
    databases: [<db>, <db>]
  prod:
    connection: <prod-connection-name>
    default_warehouse: <warehouse>
    databases: [<db>, <db>]
# snowman never executes writes; user-requested DML/DDL is staged to
# .snowman/staged/ (gitignored) for manual execution. Staging here always
# needs an explicit --env.
---
```

**Body** (multi-environment: repeat the sections per environment, e.g.
`## Databases (dev)` / `## Databases (prod)`):

```markdown
# Snowflake context for <project>

_Discovered <by snowman bootstrap>. Names only, no credentials. Edit freely;
re-run the bootstrap to refresh._

## Connection
`<chosen-connection-name>` (named `snow` CLI connection)

## Databases
| Database | Env | Purpose |
|----------|-----|---------|
| <db>     | dev | <note>  |

## Warehouses
| Warehouse | Size | Purpose | Auto-suspend |
|-----------|------|---------|--------------|
| <wh>      | <sz> | <note>  | <s>          |

## Roles
| Role | Access |
|------|--------|
| <role> | <note> |

## Schemas (in-scope databases)
### <db>
- <schema>: <note>
```

## Step 4: route Snowflake work to snowman (one gate)

Skills compete with the agent's habit of calling `snow sql` directly; a
routing rule in the project's agent instructions makes the skill fire
reliably. Check `AGENTS.md` and `CLAUDE.md` in the project root. If either
already mentions `snowman`, skip this step. Otherwise propose appending this
block and gate once:

```markdown
## Snowflake

All Snowflake access goes through the `snowman` skill: queries run via its
read-only wrapper, and requested changes are staged under `.snowman/staged/`,
never executed.
```

Append to `AGENTS.md` if it exists, else `CLAUDE.md` if it exists, else
create `AGENTS.md` with just this block. If the user declines, move on.
Never re-propose within the session.

## Done

Confirm the file is written, then switch to the wrapper for all further
queries and proceed with the user's original request.
