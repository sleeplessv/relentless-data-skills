# prefect

The **`prefect`** agent skill for **Prefect 3**. It encodes only what an agent
gets wrong by default: stale 3.x knowledge, unqueried instance state, and house
standards. It checks version-sensitive advice against fetched Prefect docs
or local API and CLI evidence for the project's installed version.

## What it does

- **Doc-lookup protocol.** Fetches the exact Markdown URL in
  `www.prefect.io/docs/llms.txt`, with an HTML fallback when the fetch tool
  rejects Markdown. Follows nested `/_llms/` indexes and cites pages under the
  public docs host. Re-resolves missing pages through the index, then falls back
  to a connected Prefect MCP server's documentation tools and web search. Anchors
  cover the per-minor release notes and the CLI reference, so a claim can be
  tied to the version that introduced it. Advice cites docs or local evidence
  and states what remains unverified.
- **CLI-first protocol.** Queries the live instance through the project's
  established environment. An already-connected Prefect MCP server can also
  provide read-only evidence. Checks effective settings and confirms access
  with a read-only query, using the relevant Cloud or self-hosted auth path.
  Filters authentication output before capture and checks inventory completeness
  before drift claims. Uses paginated read-only SDK or API queries when needed.
  Destructive or hard-to-reverse actions are surfaced before running.
- **Run diagnosis.** Uses state transitions and logs to identify the cause,
  with separate checks for worker-backed pools, push and Managed pools, and
  `serve()`. Startup code errors can produce `Crashed` runs too. Zombie runs
  are checked against the heartbeat mechanism: the client version that emits
  heartbeats and the policy or automation that acts on a silent run.
- **Implementation checks.** Verifies the changed flow or deployment configuration
  locally and reports remaining limits. Incident checks include the affected
  runtime's version when the local installation is insufficient evidence.
- **Standards.** Covers version pinning, environment separation, CI deployments,
  deployment schedules, and secrets in blocks. Patterns state when they apply.
- **Guardrails.** The classic stale-knowledge traps: workers not agents, no
  `Deployment` object, task failures that leave a flow `Completed`, sync and
  async call rules, and results that are not persisted by default.

Targets the **Prefect 3.x** generation (no patch pin). Prefect 2.x is out of scope.

## How it works

`SKILL.md` holds what every Prefect task needs: the verify gate, the lookup
protocol, standards, and guardrails. The detail that only instance work needs
(target and auth checks, project audits, run diagnosis) sits in
`references/instance.md`, which `SKILL.md` points to at the step that uses it.
The lookup protocol uses exact paths from `llms.txt` on the public docs host
and accepts fetched Markdown or HTML. Anchors point to common topics; the skill
re-resolves them through the index if they move.

## Alongside Prefect's official plugin

Prefect publishes its own Claude Code plugin, also named `prefect`, from the
`prefecthq/prefect-mcp-server` marketplace. It connects Prefect's hosted,
read-only MCP server and ships a `workflows` skill that treats those MCP tools
as the source for Cloud state and documentation. The two install side by side:
the marketplace qualifies each name (`prefect@relentless-data-skills` here).

They overlap on run diagnosis and documentation lookup. This skill covers what
the official one leaves out: project code, self-hosted instances, house
standards, and the stale-knowledge guardrails. With both installed, this skill
uses the MCP tools as read-only evidence once their Cloud workspace matches the
project's target, and as a documentation fallback.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/prefect
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install prefect@relentless-data-skills
```

It activates automatically when you do Prefect 3 work or ask about Prefect.

## Files

- `SKILL.md`: the verify gate, doc-lookup and CLI-first protocols, standards, and guardrails.
- `references/instance.md`: target and auth checks, project audits, and run diagnosis.

## Maintenance / CI

Repo CI lints this skill via **`scripts/lint_skill.py`** (frontmatter, "Use
when" trigger in the description, line budget). There is no automated
doc-URL liveness check for this skill. Its lookup protocol handles upstream
page moves at use time; the linter does not validate Prefect API behavior.

[Behavior scenarios](../../tests/dlt-prefect-scenarios.md) cover masked custom
headers, complete inventories, target selection, version evidence, stale APIs,
documentation lookup, and zombie runs. These
are separate evaluations with synthetic data, not automated tests of a live instance.
