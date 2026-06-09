# snowman

The **`snowman`** agent skill: **read-only Snowflake exploration** via the
`snow` CLI — schema discovery, data profiling, hypothesis testing, and
data-quality investigation. Built for ad-hoc exploration and investigations
where you want the agent poking around Snowflake **without any risk of it
writing or mutating anything**.

## What it does

- **Per-project bootstrap (progressive disclosure).** On the first invocation
  in a project there is no `.snowman/context.md`, so the skill runs a
  discovery-first, grill-me-style bootstrap: it lists `snow` connections, runs
  a read-only `SHOW` sweep to map databases/warehouses/roles/schemas, asks
  only the genuine decisions (connection, in-scope DBs, which are prod,
  default warehouse), and writes a committed context file. The install
  instructions live in `references/install.md` and only load on that first run.
- **Per-project context, never global.** All Snowflake architecture lives in
  `.snowman/context.md` in the project root — **names only, no secrets** —
  committed so it doubles as project documentation. The skill refuses to run
  without it.
- **Hard read-only guardrail.** Every query goes through `scripts/snowman.py`,
  which strips comments/strings, rejects multi-statements, requires a
  read-only leading keyword (`SELECT`/`WITH`/`SHOW`/`DESCRIBE`/`EXPLAIN`), and
  refuses any write/DDL keyword anywhere. On refusal it exits non-zero with a
  `BLOCKED: …` reason. This is enforcement, not advice — it can't be talked out
  of it. There is **no write path at all** in v1.
- **Cost discipline (taught).** Bounding scans with `LIMIT`/`SAMPLE`, avoiding
  full scans, and minding the warehouse are taught in `references/guardrails.md`
  rather than hard-blocked (reliable cost detection needs real parsing).
- **Workflows.** Exploration, profiling, hypothesis testing, and investigation
  playbooks in `references/workflows.md`.

## Credentials

snowman uses **named `snow` CLI connections only** — it never creates
connections or handles credentials. If you have none, run `snow connection add`
yourself (interactive SSO/MFA), then invoke snowman. The context file only ever
stores the connection *name*.

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

- `SKILL.md` — core: first-run routing, wrapper invocation, guardrail summary.
- `references/install.md` — the first-run bootstrap (discovery + writing context).
- `references/guardrails.md` — full guardrail policy (hard-enforced vs taught).
- `references/workflows.md` — exploration / profiling / hypothesis / investigation.
- `scripts/snowman.py` — the read-only wrapper (stdlib only). Ships with the
  skill; reads the per-project context to resolve the connection.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
