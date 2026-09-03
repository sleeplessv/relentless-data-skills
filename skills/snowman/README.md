# snowman

The `snowman` agent skill is read-only Snowflake exploration through the
`snow` CLI: schema discovery, data profiling, hypothesis testing, and
data-quality investigation. It is built for ad-hoc exploration and
investigations where you want the agent poking around Snowflake without any
risk of it writing or mutating anything. When you do want a change, the agent
stages the DML or DDL as a script for you to review and run yourself. snowman
never executes writes.

## What it does

- **Per-project bootstrap (progressive disclosure).** On the first invocation
  in a project there is no `.snowman/context.md`, so the skill runs a
  discovery-first bootstrap in the style of the `grilling` skill. It lists `snow` connections, runs
  a read-only `SHOW` sweep to map databases, warehouses, roles, and schemas,
  asks only the genuine decisions (connection, in-scope databases, which are
  prod, default warehouse), and writes a committed context file. The install
  instructions live in `references/install.md` and load only on that first run.
- **Per-project context, never global.** All Snowflake architecture lives in
  `.snowman/context.md` in the project root (names only, no secrets). The file
  is committed, so it doubles as project documentation. The skill refuses to
  run without it.
- **Multi-account environments.** When dev and prod are separate Snowflake
  accounts, the context file maps named environments to connections
  (`environments:` plus `default_env:`), each with its own warehouses and
  databases. Selection is stateless and per-query: reads hit the default
  environment unless the agent passes `--env <name>`, so `--env prod` in the command
  line is itself the audit trail. Staging in these projects always requires
  an explicit `--env`, and the target environment lands in the staged
  filename and header. Single-account projects keep the plain `connection:`
  form.
- **Hard read-only guardrail.** Every query goes through the wrapper,
  `scripts/snowman.py`, which strips comments and quoted regions, rejects
  multi-statements, requires a read-only leading keyword (`SELECT`, `WITH`,
  `SHOW`, `DESCRIBE`, `DESC`, or `EXPLAIN`), and refuses any write or DDL keyword
  anywhere. On refusal it exits non-zero with a `BLOCKED: ...` reason. This
  is enforcement, not advice. The agent cannot talk the wrapper out of it, and
  there is no execute path for writes at all.
- **Staged writes, executed only by you.** When you ask for a change, the
  agent stages the DML or DDL with `snowman.py --stage` into
  `.snowman/staged/<timestamp>__<slug>.sql` (gitignored). The file header
  carries the exact `snow sql -f ...` run command and a warning line when
  destructive keywords are present. Running the script, and deleting it
  afterwards, is always your manual act.
- **Cost discipline (taught).** `references/guardrails.md` teaches bounding
  scans with `LIMIT` or `SAMPLE`, avoiding full scans, and minding the
  warehouse. The wrapper does not block on cost, because reliable cost
  detection needs real parsing.
- **Output shaping.** Results come back as CSV (header row, empty cell for
  NULL, `""` for an empty string, nested values as compact JSON, a `# types:`
  footer for scaled NUMBER, date/time, and VARIANT columns), a fraction of the tokens of the CLI's
  indented JSON. The wrapper shows 50 rows and writes an overflowing result in
  full to `.snowman/results/` (gitignored), cuts cells at 200 chars, flags
  each of those with a `#` footer line, and flattens the CLI's error panel to
  one `ERROR:` line. `--max-rows`, `--max-cell`, and `--json` lift or change
  the defaults.
- **Workflows.** Exploration, profiling, hypothesis testing, and investigation
  playbooks in `references/workflows.md`.

## Credentials

snowman uses named `snow` CLI connections only. It never creates connections
or stores credentials. If you have none, run `snow connection add` yourself
(interactive SSO or MFA), then invoke snowman. The context file stores only
the connection name.

snowman relays one credential, and never stores, prints, or asks for it. If
your connection uses key-pair auth with an encrypted private key, put the
passphrase in the project root `.env` (for example
`PRIVATE_KEY_PASSPHRASE=...`). The wrapper loads the nearest `.env` at or above the
project root into the `snow` subprocess on every query. The existing shell environment always wins over
`.env`. Keep `.env` gitignored as usual. With several key-pair connections
whose passphrases differ (for example separate dev and prod accounts), use
`snow`'s per-connection form in `.env` instead:
`SNOWFLAKE_CONNECTIONS_<NAME>_PRIVATE_KEY_PASSPHRASE=...`.

Browser-auth connections (`authenticator` set to `OAUTH_AUTHORIZATION_CODE` or
`EXTERNALBROWSER`) need no `.env` at all. Complete the login once with
`snow connection test -c <name>` in your own terminal. `snow` caches the
token, and wrapper queries then run without prompting. On an auth failure the
wrapper looks up the connection's authenticator with `snow connection list`
and prints a hint matched to the actual auth method.

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

It activates when you explore Snowflake data or ask to profile or investigate it.

## Files

- `SKILL.md`: core, first-run routing, wrapper invocation, guardrail summary.
- `references/install.md`: the first-run bootstrap (discovery, then writing the context file).
- `references/guardrails.md`: full guardrail policy (hard-enforced and taught).
- `references/workflows.md`: exploration, profiling, hypothesis, and investigation playbooks.
- `scripts/snowman.py`: the read-only wrapper (stdlib only). It ships with the
  skill, reads the per-project context file to resolve the connection, renders
  results as capped CSV (or `--json`) with spill files under
  `.snowman/results/`, and flattens error output. It also owns `--stage`, which
  writes DML or DDL scripts to `.snowman/staged/` and never executes them.

## Maintenance and CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget). See the
[root README](../../README.md#maintenance--ci).
