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
installation; the release notes for a minor say when a behavior landed. If
verification fails, state what remains unverified. For general
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

1. Fetch the index `https://www.prefect.io/docs/llms.txt` and find the page matching the topic.
   Integrations and the API reference sit in nested `/_llms/*.txt` indexes; follow them recursively.
2. Fetch the exact page URL from the index (links include `.md`). If its host is
   `*.mintlify.dev`, swap the host for `www.prefect.io` and keep the path.
3. If a URL 404s, re-fetch the index that listed it and re-resolve rather than guessing.
4. If the fetch tool rejects Markdown, try the equivalent HTML page by removing
   the trailing `.md`. Either format is valid evidence once fetched.
5. When direct lookup fails, fall back to a connected Prefect MCP server's
   documentation tools, then to web search.

Fetch with the agent's web-fetch capability when shell network access is
restricted. Fetch single pages; `llms-full.txt` loads the whole corpus.

Anchors, each under `https://www.prefect.io/docs/v3/`:

- states => `concepts/states.md`
- deployments => `concepts/deployments.md`
- prefect.yaml => `how-to-guides/deployments/prefect-yaml.md`
- caching => `concepts/caching.md`
- results => `advanced/results.md`
- transactions => `advanced/transactions.md`
- 2.x-to-3.x changes => `how-to-guides/migrate/upgrade-to-prefect-3.md`
- release notes, one page per minor => `release-notes/oss/version-3-<minor>.md`
- CLI reference, one page per command group => `api-ref/cli/<group>.md`

Fetch relevant anchors and apply the verify gate before advising.

## CLI-first protocol (query, don't guess state)

When the answer lives in the Prefect instance, such as deployments, work
pools, runs, blocks, or profiles, query it via the CLI. An already-connected
Prefect MCP server can also supply read-only instance evidence; confirm its
target before using it. Use a read-only SDK/API query when the CLI cannot provide
the needed evidence, including pagination; `prefect api` sends one from the
CLI. Use the CLI or SDK for authorized mutations.

- **Invocation:** follow the project's documented dependency manager and
  environment. A `pyproject.toml` alone does not identify a uv project. Use
  `uv run prefect ...` for established uv projects, the existing Poetry runner
  for Poetry projects, or `prefect ...` in the intended active environment.
  Keep inspection from changing dependencies or lockfiles; check runner options
  locally when needed, since `uv run` can synchronize the environment.
- **Target first:** before the first instance query, establish the effective
  API endpoint, active profile, and auth by following
  [references/instance.md](references/instance.md#establish-the-target). Report
  auth by presence, never by value. Keep unfiltered `prefect config view` output
  out of the transcript: it prints `PREFECT_CLIENT_CUSTOM_HEADERS` tokens.
- **Useful queries:** `deployment ls` / `inspect`, `work-pool ls` / `inspect`,
  `flow-run ls` / `inspect <id>` / `logs <id>`, `block type ls`, `variable ls`,
  `profile ls`. Add `--output json` for complete identifiers. Verify flags via
  `--help` or the CLI reference anchor, not memory.
- **Boundary:** read-only queries need no confirmation. Run state-changing
  commands only when they're the explicit task, and surface anything
  destructive or hard to reverse (pause, cancel, delete) before running it.

Two moves that aren't obvious. Both end in a report, not a fix: name the drift
or the root cause and stop there. Changing deployments, pools, or flow code is
in scope only when that change is the task (see Boundary, above).

- **Auditing a project:** diff deployed reality against the repo's manifests,
  following [references/instance.md](references/instance.md#audit-a-project).
  An object is absent only once the inventory is complete.
- **Debugging a run:** read the run, its state transitions, and its logs before
  classifying the cause, following
  [references/instance.md](references/instance.md#diagnose-a-run) for the checks
  each deployment mode needs and for zombie runs.

For implementation tasks, verify the changed flow imports and exercise the changed
behavior with suitable local inputs. Validate deployment configuration against the
installed version without deploying unless requested. Report checks and remaining
limits. Match verification to the change; a live production run is not a default check.

## Standards (house opinions)

- Pin Prefect **3.x** and manage deps with a lockfile (uv preferred).
- Separate dev vs prod by distinct work pools / deployment manifests / blocks,
  never by branching inside flow code.
- Keep flows importable via stable entrypoints (`module/path.py:flow_func`).
- Deploy from CI/CD with pinned source, not from a laptop. Run
  `prefect --no-prompt deploy` there, so a missing value fails instead of hanging.
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
- **A failed task does not fail its flow.** The flow fails only when an
  exception propagates or its return value carries a failed state.
- **Sync and async.** `.submit()` is synchronous, so it takes no `await`. An
  async task called from a sync flow returns an unawaited coroutine and never
  runs; make the flow async. Dual-mode methods such as `Secret.load` return a
  coroutine in async code: `await` them, call `aload`, or pass `_sync=True`.
- **Results are not persisted by default, and caching needs persistence.**
  `persist_result=False` leaves a task without a cache. Locally persisted
  results are out of reach of a retry on fresh infrastructure; use remote
  result storage there. Inside a transaction, results are written at commit.
  Fetch the caching, results, and transactions anchors before changing these.
- **Don't guess `prefect.yaml` shape or CLI flags.** Check applicable docs or
  the installed CLI's `--help` output. When `prefect deploy` selects several
  deployments, explicit CLI options are ignored.
