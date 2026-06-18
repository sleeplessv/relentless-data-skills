---
name: prefect
description: Use when building, reviewing, or debugging Prefect 3 projects — flows, tasks, deployments, work pools, workers, schedules, blocks, results/retries/caching — or diagnosing failed, crashed, stuck, late, or zombie flow runs — or whenever unsure about a Prefect API or current best practice. Queries the live instance via the CLI and confirms version-sensitive details against the live Prefect docs.
metadata:
  prefect: "3.x"
---

# Prefect 3

This skill encodes only what an agent gets wrong about Prefect by default:
stale 3.x knowledge, unqueried instance state, and house standards. Topic
detail is fetched from the live docs, never memorized. Prefect 2.x is out of
scope — recommend migrating up.

**Verify gate (completion criterion):** Before emitting any version-sensitive
claim, you MUST either cite a fetched `.md` doc page or label the claim
"baseline knowledge". No exceptions.

Two obligations on every Prefect answer:

1. **State assumptions when they fork the answer** — Cloud vs self-hosted,
   work-pool type (process / docker / kubernetes / managed). Never silently assume.
2. **Pass the verify gate above** — cite the fetched doc page, or say "baseline
   knowledge" explicitly.

## Doc-Lookup Protocol

Follow this whenever unsure, the task is version-sensitive, or the user asks
for current/best practice:

1. Fetch the index `https://docs.prefect.io/llms.txt` and find the page matching the topic.
2. Fetch that page as markdown by appending `.md` to its URL.
3. If a URL 404s, **re-fetch `llms.txt` and re-resolve — never invent a URL.**
4. Web search is a fallback only.
5. Prefer the agent's web-fetch capability over shell `curl` (works under
   network sandboxing). Avoid `llms-full.txt` (whole corpus; context-heavy).

Anchors for the guardrails below:

- states => https://docs.prefect.io/v3/concepts/states.md
- deployments => https://docs.prefect.io/v3/concepts/deployments.md
- prefect.yaml => https://docs.prefect.io/v3/how-to-guides/deployments/prefect-yaml.md
- caching => https://docs.prefect.io/v3/concepts/caching.md
- results => https://docs.prefect.io/v3/advanced/results.md

**Anchors are authoritative — cite or fetch before advising.**

## CLI-First Protocol (query, don't guess state)

When the answer lives in the Prefect instance — deployments, work pools, runs,
blocks, profiles — query it via the CLI instead of reasoning from memory or code alone.

- **Invocation:** in uv projects (`uv.lock` / `pyproject.toml` present) always
  `uv run prefect ...` — never bare `prefect` or ad-hoc pip installs. Bare
  `prefect` only when there's no uv project.
- **Auth preflight:** start with `uv run prefect config view` to confirm the
  active profile and `PREFECT_API_URL`. If unauthenticated or pointing at the
  wrong server, stop and ask the user to run `prefect cloud login`
  (interactive) — don't retry blindly.
- **Useful queries:** `deployment ls` / `deployment inspect`, `work-pool ls` /
  `work-pool inspect`, `flow-run ls` / `flow-run inspect <id>`, `block type ls`,
  `variable ls`, `profile ls`. Verify flags via `--help` or the docs, not memory.
- **Boundary:** read-only queries — run freely, eagerly. State-changing
  commands — only when they're the explicit task; surface anything destructive
  or hard to reverse (pause, cancel, delete) before running it.

Two moves that aren't obvious:

- **Auditing a project:** diff deployed reality (deployments, pools, schedules
  — via the CLI) against the repo's manifests; drift is the finding.
- **Debugging a run:** `flow-run inspect` first, then classify — code failure
  (traceback in logs → fix the flow/task) vs infra failure (Crashed/zombie,
  stuck Pending, Late → check worker online, polling the right pool/queue,
  concurrency limits not exhausted). The fix paths diverge completely.

## Standards (house opinions)

- Pin Prefect **3.x** and manage deps with a lockfile (uv preferred).
- Separate dev vs prod by distinct work pools / deployment manifests / blocks —
  never by branching inside flow code.
- Keep flows importable via stable entrypoints (`module/path.py:flow_func`).
- Deploy from CI/CD with pinned source, not from a laptop.
- Attach schedules (cron / interval / rrule) at the deployment, not in flow code.
- Secrets live in Secret blocks / a secrets backend — never in code, parameters,
  or logs. Non-secret environment-varying values go in variables.
- **Dual deployment manifests** — a local `prefect.yaml` (process pool) plus a
  Cloud variant (managed pool / git_clone) selected via `--prefect-file` — when
  dev and prod genuinely need different pools or source, not before.
- **Parametrized shared flow** — one flow keyed by a `source_name` parameter,
  deployed once per source — when you're about to write a second near-identical flow.
- **`run_deployment` fan-out** — an orchestrator flow triggering child
  deployments — when stages need independent logs/retries/reruns, not as a
  starting architecture.

## Guardrails (stale-knowledge traps)

- **Workers, not agents.** Prefect 3 uses workers + work pools; the agent model is gone.
- **No `Deployment` object.** Create deployments via `prefect.yaml`,
  `flow.deploy()`, `flow.from_source(...).deploy()`, or `flow.serve()` — not
  `prefect.deployments.Deployment` or `prefect deployment build`.
- **Don't guess `prefect.yaml` shape or CLI flags** — anchors are authoritative
  (or `--help` for flags).
- **Results, caching, and transactions changed in 3.x** — anchors are authoritative.
