---
name: prefect-skill
description: Use when building, scaffolding, reviewing, or debugging Prefect 3 projects — flows, tasks, deployments, work pools, workers, schedules, blocks, results/retries/caching — or diagnosing failed, crashed, stuck, late, or zombie flow runs — or whenever unsure about a Prefect API or current best practice. Provides greenfield-build, existing-project-audit, and run-debugging modes, and always confirms version-sensitive details against the live Prefect docs.
license: Apache-2.0
metadata:
  author: sleeplessv
  version: 0.1.0
  prefect: "3.x"
---

# Prefect 3 Skill

Opinionated, version-aware guidance for Prefect **3.x**, plus the discipline of
checking the live docs when unsure. The core is a workflow + checklist; topic
detail is fetched from docs, never memorized. Prefect 2.x is out of scope — recommend migrating up.

## Response Contract

Keep it brief, but every Prefect response includes:

1. **Assumptions / target** — Prefect 3.x; Cloud vs self-hosted; work-pool type (process / docker / kubernetes / managed). State them; never silently assume.
2. **Recommendation + key tradeoff** — what to do and what it costs.
3. **Doc consulted** — the exact page URL fetched, or "baseline knowledge" if none was needed.
4. **Validation step** — a concrete check (e.g. `prefect deploy` dry run, `prefect.yaml` review, `prefect config view`).

## Doc-Lookup Protocol

Follow this whenever you are unsure, the task is version-sensitive, or the user asks for current/best practice:

1. Fetch the index `https://docs.prefect.io/llms.txt` and find the page matching the topic.
2. Fetch that page as markdown by appending `.md` (e.g. `https://docs.prefect.io/v3/concepts/flows.md`). [references/docs-map.md](references/docs-map.md) is a topic→URL shortcut.
3. If a URL 404s or the topic isn't in the map, **re-fetch `llms.txt` and re-resolve — never invent a URL.**
4. Web search is a **fallback only**.
5. Prefer the agent's web-fetch capability over shell `curl` (works under network sandboxing). Avoid `llms-full.txt` (whole corpus; context-heavy).

Cite the page you used in the Response Contract.

## CLI-First Protocol (query, don't guess state)

When the answer lives in the Prefect instance — deployments, work pools, runs, blocks, profiles — query it via the CLI instead of reasoning from memory or code alone.

- **Invocation:** in uv projects (`uv.lock` / `pyproject.toml` present) always `uv run prefect ...` — never bare `prefect` or ad-hoc pip installs. Bare `prefect` only when there's no uv project.
- **Auth preflight:** start with `uv run prefect config view` to confirm the active profile and `PREFECT_API_URL`. If unauthenticated or pointing at the wrong server, stop and ask the user to run `prefect cloud login` (interactive) — don't retry blindly.
- **Useful queries:** `deployment ls` / `deployment inspect`, `work-pool ls` / `work-pool inspect`, `flow-run ls` / `flow-run inspect <id>`, `block type ls`, `variable ls`, `profile ls`. Verify flags via `--help` or the docs, not memory.
- **Boundary:** read-only queries — run freely, eagerly. State-changing commands (`deploy`, `deployment run`, `work-pool create`, pause/cancel) — propose, confirm intent, then run.

## Diagnose → Route

| Intent | Checklist area | Start docs at |
|--------|----------------|---------------|
| New project / structure / deps | [Scaffolding & structure](references/greenfield-checklist.md#1-scaffolding--structure) | quickstart, projects, prefect.yaml |
| Writing flows/tasks, reliability | [Authoring + reliability](references/greenfield-checklist.md#2-authoring-patterns--reliability) | flows, tasks, task-runners, retries, caching, results |
| Deploying / executing / scheduling | [Deployment & execution](references/greenfield-checklist.md#3-deployment--execution) | deployments, prefect.yaml, work-pools, workers, schedules |
| Config, secrets, observability, tests | [Config/secrets/observability/testing](references/greenfield-checklist.md#4-config-secrets-observability--testing) | blocks, variables, logging, artifacts, automations, testing |
| Run failed / crashed / stuck / late | [Debug Workflow](#debug-workflow) | states, detect-zombie-flows, workers, retry-flow-runs |

Load only the area you need. Full URLs: [references/docs-map.md](references/docs-map.md).

## When to Use / Don't Use

**Use when:** scaffolding a new Prefect 3 project; auditing an existing one against current standards; authoring or debugging flows/tasks/deployments; choosing work pools, deployment style, or scheduling; or any time you're unsure about a Prefect 3 API.

**Don't use for:** Prefect 2.x (recommend migrating to 3.x); non-Prefect orchestration; trivial Python unrelated to Prefect.

## Greenfield Workflow

1. **Capture target** — Cloud vs self-hosted, execution environment (process/docker/k8s/managed), repo/deps tooling. State assumptions.
2. **Scaffold** with `prefect init` and current project conventions — don't hand-roll a layout. Look up the projects/quickstart pages.
3. **Walk the checklist** ([references/greenfield-checklist.md](references/greenfield-checklist.md)) area by area; apply each one-line standard, fetching the linked doc when you need detail.
4. **Author flows/tasks** with explicit reliability (retries/timeouts/caching/results) per the checklist.
5. **Define deployments + work pool**, choosing `prefect.yaml` vs `.deploy()`/`flow.from_source` vs `flow.serve()` deliberately.
6. **Wire config/secrets/observability/testing.**
7. **Validate** per the Response Contract before finishing.

## Audit Workflow

1. Confirm the project is on Prefect **3.x** (flag any 2.x → migrate).
2. **Query the live instance** (CLI-First Protocol) and compare deployed reality — deployments, work pools, schedules — against the repo's manifests.
3. Run the **same checklist as a rubric**; for each area note conformance vs drift.
4. Flag deprecated patterns explicitly — see Guardrails.
5. Report findings grouped by the four areas, each with a current-docs pointer for the fix.

## Debug Workflow

1. **Capture target** — Cloud vs self-hosted, work-pool type, Prefect version. State assumptions.
2. **Read the run via the CLI** — `flow-run ls` then `flow-run inspect <id>`: final state, state message, logs; confirm state semantics against the states doc.
3. **Classify the failure** — code (traceback in logs → fix the flow/task) vs infra (Crashed/zombie, stuck Pending, Late, lost worker).
4. For infra failures, **check the worker and pool** — worker online and polling the right pool/queue, healthchecks, concurrency limits not exhausted.
5. **Fix, then validate** — re-run via manual retry or `prefect deployment run` and confirm the resulting state.

Docs: see [references/docs-map.md](references/docs-map.md) § Debugging & states.

## Prefect 3 Guardrails (common stale-knowledge traps)

- **Workers, not agents.** Prefect 3 uses workers + work pools; the old agent model is gone.
- **No `Deployment` object.** Create deployments via `prefect.yaml`, `flow.deploy()`, `flow.from_source(...).deploy()`, or `flow.serve()` — not `prefect.deployments.Deployment` or `prefect deployment build`.
- **Don't guess `prefect.yaml` shape or CLI flags** — confirm via the prefect.yaml / deployments docs.
- **Results, caching, and transactions changed in 3.x** — verify against those pages before advising.
- When unsure whether an API is current, **look it up** (protocol above) rather than recalling.

## Reference patterns (portable)

Battle-tested shapes worth reusing — adapt, don't copy paths:
- **Dual deployment manifests** — a local `prefect.yaml` (process pool / bind-mount) plus a Cloud variant (managed pool / git_clone) selected via `--prefect-file`, so the same flows deploy to dev and prod.
- **Parametrized shared flow** — one flow keyed by a `source_name` parameter, deployed once per source, instead of near-duplicate flows.
- **`run_deployment` fan-out** — an orchestrator flow that triggers child deployments via `run_deployment`, so each stage keeps isolated logs, retries, and UI reruns.
