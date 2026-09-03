# snowman

The **`snowman`** agent skill is **read-only Snowflake exploration** via the
`snow` CLI: schema discovery, data profiling, hypothesis testing, and
data-quality investigation. Built for ad-hoc exploration and investigations
where you want the agent poking around Snowflake **without any risk of it
writing or mutating anything**. When a change *is* wanted, the agent stages
the DML/DDL as a script for you to review and run manually. It never
executes writes itself.

## What it does

- **Per-project bootstrap (progressive disclosure).** On the first invocation
  in a project there is no `.snowman/context.md`, so the skill runs a
  discovery-first, grill-me-style bootstrap: it lists `snow` connections, runs
  a read-only `SHOW` sweep to map databases/warehouses/roles/schemas, asks
  only the genuine decisions (connection, in-scope DBs, which are prod,
  default warehouse), and writes a committed context file. The install
  instructions live in `references/install.md` and only load on that first run.
- **Per-project context, never global.** All Snowflake architecture lives in
  `.snowman/context.md` in the project root (**names only, no secrets**),
  committed so it doubles as project documentation. The skill refuses to run
  without it.
- **Multi-account environments.** When dev and prod are separate Snowflake
  accounts, the context maps named environments to connections
  (`environments:` + `default_env:`), each with its own warehouses and
  databases. Selection is stateless and per-query: reads hit the default
  environment unless `--env <name>` is passed, so `--env prod` in the command
  line is itself the audit trail. Staging in these projects always requires
  an explicit `--env`, and the target environment lands in the staged
  filename and header. Single-account projects keep the plain `connection:`
  form.
- **Hard read-only guardrail.** Every query goes through `scripts/snowman.py`,
  which strips comments/strings, rejects multi-statements, requires a
  read-only leading keyword (`SELECT`/`WITH`/`SHOW`/`DESCRIBE`/`EXPLAIN`), and
  refuses any write/DDL keyword anywhere. On refusal it exits non-zero with a
  `BLOCKED: …` reason. This is enforcement, not advice; it can't be talked out
  of it. There is **no execute path for writes at all**.
- **Staged writes, executed only by you.** When you ask for a change, the
  agent stages the DML/DDL via `snowman.py --stage` into
  `.snowman/staged/<timestamp>__<slug>.sql` (gitignored) with a header
  carrying the exact `snow sql -f …` run command and a warning line when
  destructive keywords are present. Running the script, and deleting it
  afterwards, is always your manual act.
- **Cost discipline (taught).** Bounding scans with `LIMIT`/`SAMPLE`, avoiding
  full scans, and minding the warehouse are taught in `references/guardrails.md`
  rather than hard-blocked (reliable cost detection needs real parsing).
- **Output shaping.** Results come back as CSV (header row, empty cell =
  NULL, nested values as compact JSON), a fraction of the tokens of the
  CLI's indented JSON. The wrapper shows 50 rows and writes an overflowing
  result in full to `.snowman/results/` (gitignored), cuts cells at 200
  chars, flags each of those with a `#` footer line, and flattens the CLI's
  error panel to one `ERROR:` line. `--max-rows`, `--max-cell`, and `--json`
  lift or change the defaults.
- **Workflows.** Exploration, profiling, hypothesis testing, and investigation
  playbooks in `references/workflows.md`.

## Credentials

snowman uses **named `snow` CLI connections only**. It never creates
connections or stores credentials. If you have none, run `snow connection add`
yourself (interactive SSO/MFA), then invoke snowman. The context file only ever
stores the connection *name*.

The one credential snowman *relays* (never stores, prints, or asks for): if
your connection uses key-pair auth with an encrypted private key, put the
passphrase in the project root `.env` (e.g. `PRIVATE_KEY_PASSPHRASE=...`).
The wrapper loads `.env` into the `snow` subprocess on every query; existing
shell environment always wins over `.env`. Keep `.env` gitignored as usual.
With several key-pair connections whose passphrases differ (e.g. separate
dev/prod accounts), use `snow`'s per-connection form in `.env` instead:
`SNOWFLAKE_CONNECTIONS_<NAME>_PRIVATE_KEY_PASSPHRASE=...`.

Browser-auth connections (`authenticator` = `OAUTH_AUTHORIZATION_CODE` or
`EXTERNALBROWSER`) need no `.env` at all. Complete the login once with
`snow connection test -c <name>` in your own terminal; `snow` caches the
token and wrapper queries then run silently. On an auth failure the wrapper
looks up the connection's authenticator via `snow connection list` and
prints a hint matched to the actual auth method.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/snowman
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install snowman@relentless-data-skills
```

It activates when you explore Snowflake data or ask to profile/investigate it.

## Files

- `SKILL.md`: core, first-run routing, wrapper invocation, guardrail summary.
- `references/install.md`: the first-run bootstrap (discovery + writing context).
- `references/guardrails.md`: full guardrail policy (hard-enforced vs taught).
- `references/workflows.md`: exploration / profiling / hypothesis / investigation.
- `scripts/snowman.py`: the read-only wrapper (stdlib only). Ships with the
  skill; reads the per-project context to resolve the connection, renders
  results as capped CSV (or `--json`) with spill files under
  `.snowman/results/`, and flattens error output. Also owns `--stage`, which
  writes (never executes) DML/DDL scripts to `.snowman/staged/`.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget); see the
[root README](../../README.md#maintenance--ci).
