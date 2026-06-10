# snowman — bootstrap (first run in a project)

You are here because the project has **no `.snowman/context.md`**. Your job is
to discover this project's Snowflake architecture and write that file, so
every later invocation has a per-project source of truth.

**Style: discovery-first, grill-me spirit.** Don't interrogate the user for
things the account can tell you — *run the read-only SQL and propose what you
found*. Ask only for the genuine decisions. One decision at a time, with a
recommended answer. All discovery here is read-only and goes through the
wrapper (`python3 <skill-dir>/scripts/snowman.py "<SQL>"`) — except the
connection-listing step, which uses the `snow` CLI directly.

All `snow` commands need network access to reach Snowflake — run them with
sandboxing disabled. In a sandboxed shell they fail with DNS/connection
errors that masquerade as a broken connection config.

## Step 0 — pick the connection (the only thing not via the wrapper)

snowman uses **named `snow` CLI connections only**. It never creates
connections, handles credentials, key-pairs, or `account/user/password`.

```bash
snow connection list
```

- **Exactly one** → propose it, ask the user to confirm.
- **Several** → list them, ask which one this project should use.
- **None** → **stop.** Tell the user to run `snow connection add` themselves
  (interactive auth — SSO/MFA may open a browser), then re-invoke snowman.

The chosen connection *name* is the only auth detail that ever lands in the
context file.

If the chosen connection uses key-pair auth with an **encrypted private key**,
its passphrase must live in the project root `.env` (e.g.
`PRIVATE_KEY_PASSPHRASE=...`) — the wrapper relays `.env` to the `snow`
subprocess automatically. If the first query fails mentioning a private
key/passphrase/JWT, tell the user to add that line to `.env`; never ask for
the passphrase or print `.env` contents.

> From here on, every command is the read-only wrapper. The wrapper needs the
> connection, but the context file doesn't exist yet — so for the discovery
> sweep only, pass it explicitly:
> `python3 <skill-dir>/scripts/snowman.py --connection <chosen> "<SQL>"`.
> Drop `--connection` as soon as the context file is written.

## Step 1 — announce the read-only sweep, then run it (one gate)

Tell the user: *"I'll run these read-only `SHOW`/`SELECT` commands to map the
account — nothing is written. OK?"* Gate **once** for the whole batch, not per
statement. Then run them — one wrapper call per statement (the wrapper
rejects multi-statement submissions):

```sql
SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_REGION();
SHOW DATABASES;
SHOW WAREHOUSES;
SHOW ROLES;
```

## Step 2 — decisions (ask these; recommend an answer each)

1. **Which databases** to include in scope? Recommend the ones the current
   role can actually read; let the user trim.
2. **Which databases are production** (`env: prod`)? Recommend flagging
   anything named/described as prod or raw. snowman **never executes writes**
   anywhere (DML/DDL is only ever staged for the user to run manually), but
   the flag documents intent and powers cost/safety warnings.
3. **Default warehouse** for ad-hoc queries? Recommend the smallest
   ad-hoc/analytics warehouse you saw.

For each in-scope database, enumerate schemas (still read-only):

```sql
SHOW SCHEMAS IN DATABASE <db>;
```

## Step 3 — render the context, confirm, then write (one gate)

Compose `.snowman/context.md` (template below), **show it to the user**, get
approval, then write it to the **project root** (`.snowman/context.md`). It is
safe to commit — names only, no secrets. Suggest the user commit it.

```markdown
---
connection: <chosen-connection-name>
default_warehouse: <warehouse>
databases:
  - name: <db>
    env: dev        # or prod
# snowman never executes writes; user-requested DML/DDL is staged to
# .snowman/staged/ (gitignored) for manual execution.
---

# Snowflake context for <project>

_Discovered <by snowman bootstrap>. Names only — no credentials. Edit freely;
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
- <schema> — <note>
```

## Done

Confirm the file is written, then switch to the wrapper for all further
queries and proceed with the user's original request.
