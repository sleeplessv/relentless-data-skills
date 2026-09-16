---
name: prefect
description: Use when building, reviewing, or debugging Prefect 3 projects, including flows, tasks, deployments, work pools, workers, schedules, blocks, results/retries/caching; when diagnosing failed, crashed, stuck, late, or zombie flow runs; or whenever unsure about a Prefect API or current best practice. Queries the live instance via the CLI and confirms version-sensitive details against the live Prefect docs.
metadata:
  prefect: "3.x"
---

# Prefect 3

This skill encodes only what an agent gets wrong about Prefect by default:
stale 3.x knowledge, unqueried instance state, and house standards. Topic
detail is fetched from the live docs, never memorized. Prefect 2.x is out of
scope; recommend migrating up.

**Verify gate:** For project work, establish the installed Prefect version in
the project's environment and check its lockfile pin. Verify version-sensitive
claims against applicable fetched docs or local API/CLI evidence, and cite the
source or command. Latest docs alone do not establish support in an older
installation. If verification fails, state what remains unverified. For general
questions without a project, state the version scope supported by the docs.
For deployment incidents, check the affected worker, flow image, integration,
or server version when relevant. The local CLI version does not establish those versions.

Also on every Prefect answer:

- **State assumptions when they fork the answer.** Identify Cloud or self-hosted
  and the deployment mode: worker-backed pool, push/Managed pool, or `serve()`.
- **Answer at the depth asked.** A config question gets the config, not a tour
  of the concept. Link the doc page rather than restating it.

## Doc-lookup protocol

Follow this whenever unsure, the task is version-sensitive, or the user asks
for current/best practice:

1. Fetch the index `https://docs.prefect.io/llms.txt` and find the page matching the topic.
2. Fetch the exact page URL from the index; its links already include `.md`.
3. If a URL 404s, **re-fetch `llms.txt` and re-resolve. Never invent a URL.**
4. If the fetch tool rejects Markdown, try the equivalent HTML page by removing
   the trailing `.md`. Either format is valid evidence once fetched.
5. Use web search as a fallback when direct lookup fails.
6. Prefer the agent's web-fetch capability over shell `curl` when shell network
   access is restricted. Avoid `llms-full.txt`, which loads the whole corpus.

Anchors for the guardrails below:

- states => https://docs.prefect.io/v3/concepts/states.md
- deployments => https://docs.prefect.io/v3/concepts/deployments.md
- prefect.yaml => https://docs.prefect.io/v3/how-to-guides/deployments/prefect-yaml.md
- caching => https://docs.prefect.io/v3/concepts/caching.md
- results => https://docs.prefect.io/v3/advanced/results.md

Fetch relevant anchors and apply the verify gate before advising.

## CLI-first protocol (query, don't guess state)

When the answer lives in the Prefect instance, such as deployments, work
pools, runs, blocks, or profiles, query it via the CLI. An already-connected
Prefect MCP server can also supply read-only instance evidence; confirm its
target before using it. Use a read-only SDK/API query when the CLI cannot provide
the needed evidence, including pagination. Use the CLI or SDK for authorized mutations.

- **Invocation:** follow the project's documented dependency manager and
  environment. A `pyproject.toml` alone does not identify a uv project. Use
  `uv run prefect ...` for established uv projects, the existing Poetry runner
  for Poetry projects, or `prefect ...` in the intended active environment.
  Keep inspection from changing dependencies or lockfiles; check runner options
  locally when needed, since `uv run` can synchronize the environment.
- **Auth preflight:** inspect the effective API endpoint and active profile
  through the selected environment. Output only allowlisted target fields and
  strip credentials, query strings, and fragments from displayed URLs. Report
  authentication settings by presence, never their values. Filter before output
  reaches the transcript. `prefect config view` with default masking can expose
  tokens in `PREFECT_CLIENT_CUSTOM_HEADERS`; do not capture its unfiltered output.
  Account for overrides from environment variables, `.env`, `prefect.toml`, and
  `pyproject.toml`; a profile change alone may not change the target. For remote
  inspection, establish the matching endpoint before querying. An ephemeral
  local server is not evidence about a remote instance. Confirm
  access with a read-only query; displaying configuration does not verify auth.
  For Cloud auth failures, use the configured API-key path or interactive
  `prefect cloud login` when needed. For self-hosted servers, check the endpoint
  and configured auth, including `PREFECT_API_AUTH_STRING` for basic auth.
  A stray `PREFECT_API_KEY` takes precedence and can cause self-hosted auth to
  fail. Resolve the target and auth cause before retrying; ask the user only
  for missing target information or credentials they must supply.
- **Useful queries:** `deployment ls` / `deployment inspect`, `work-pool ls` /
  `work-pool inspect`, `flow-run ls` / `flow-run inspect <id>`, `block type ls`,
  `variable ls`, `profile ls`. Verify flags via `--help` or the docs, not memory.
- **Boundary:** run read-only queries freely and eagerly. Run state-changing
  commands only when they're the explicit task, and surface anything
  destructive or hard to reverse (pause, cancel, delete) before running it.

Two moves that aren't obvious. Both end in a report, not a fix: name the drift
or the root cause and stop there. Changing deployments, pools, or flow code is
in scope only when that change is the task (see Boundary, above).

- **Auditing a project:** diff deployed reality (deployments, pools, schedules,
  via read-only queries) against the repo's manifests. Check filters and pagination
  before claiming an object is absent or the inventory is complete. Paginate via
  SDK/API when necessary. Inspect expected deployments by identity to verify
  missing claims; find unexpected deployments only from a complete inventory.
  If coverage is incomplete, report that limit instead of asserting drift.
- **Debugging a run:** inspect the run, state transitions, and logs before
  classifying the cause. `Crashed` can include broken imports or syntax errors
  during startup; the state alone does not establish an infrastructure cause.
  For worker-backed pools, check worker health, pool/queue polling, concurrency,
  and infrastructure logs. Push and Managed pools need no worker; inspect
  submission and infrastructure errors instead. For `serve()`, check the
  serving process and its subprocess logs. For zombie runs, confirm whether
  the execution process still exists before concluding it is dead.

For implementation tasks, verify the changed flow imports and exercise the changed
behavior with suitable local inputs. Validate deployment configuration against the
installed version without deploying unless requested. Report checks and remaining
limits. Match verification to the change; a live production run is not a default check.

## Standards (house opinions)

- Pin Prefect **3.x** and manage deps with a lockfile (uv preferred).
- Separate dev vs prod by distinct work pools / deployment manifests / blocks,
  never by branching inside flow code.
- Keep flows importable via stable entrypoints (`module/path.py:flow_func`).
- Deploy from CI/CD with pinned source, not from a laptop.
- Attach schedules (cron / interval / rrule) at the deployment, not in flow code.
- Secrets live in Secret blocks / a secrets backend, never in code, parameters,
  or logs. Non-secret environment-varying values go in variables.
- **Dual deployment manifests.** A local `prefect.yaml` (process pool) plus a
  Cloud variant (managed pool / git_clone) selected via `--prefect-file`, for
  when dev and prod genuinely need different pools or source, not before.
- **Parametrized shared flow.** One flow keyed by a `source_name` parameter,
  deployed once per source, for when you're about to write a second
  near-identical flow.
- **`run_deployment` fan-out.** An orchestrator flow triggering child
  deployments, for when stages need independent logs/retries/reruns, not as a
  starting architecture.

## Guardrails (stale-knowledge traps)

- **Workers, not agents.** Use workers for worker-backed pools, with the push,
  Managed, and `serve()` exceptions described above; the agent model is gone.
- **No `Deployment` object.** Create deployments via `prefect.yaml`,
  `flow.deploy()`, `flow.from_source(...).deploy()`, or `flow.serve()`, not
  `prefect.deployments.Deployment` or `prefect deployment build`.
- **Don't guess `prefect.yaml` shape or CLI flags.** Check applicable docs or
  the installed CLI's `--help` output.
- **Results, caching, and transactions changed in 3.x.** Apply the verify gate.
