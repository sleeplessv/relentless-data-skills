# Greenfield Checklist & Audit Rubric

Each item is a one-line **standard**. In greenfield mode, apply it. In audit
mode, check the project against it and flag drift. Fetch the linked doc (see
[docs-map.md](docs-map.md)) when you need detail — don't rely on memory for
version-sensitive specifics.

## 1. Scaffolding & structure
- Use `prefect init` with an appropriate recipe rather than hand-rolling layout. → projects / quickstart
- Pin to Prefect **3.x** and manage deps with a lockfile (uv / poetry / pip-tools). → quickstart
- Separate dev vs prod targets explicitly (distinct work pools / deployment manifests / blocks), not by branching inside flow code. → deployments, work-pools
- Keep flows importable via a stable entrypoint (`module/path.py:flow_func`) for deployments. → prefect.yaml
- Add a `.prefectignore` to keep deploy uploads lean. → prefect.yaml

## 2. Authoring patterns & reliability
- Decorate with `@flow` / `@task`; type-hint parameters so Prefect validates them. → flows, tasks
- Factor reusable units into tasks; compose with subflows instead of one god-flow. → flows, tasks
- Set `retries` / `retry_delay_seconds` on tasks that touch flaky I/O. → retries (advanced)
- Add `timeout_seconds` to guard against hangs. → flows, tasks
- Use caching (`cache_policy` / cache key) for expensive idempotent work; verify 3.x cache semantics. → caching
- Configure result persistence deliberately where retries/caching must survive across processes. → results
- Use a concurrent/async task runner only when tasks are independent; confirm the current task-runner API. → task-runners
- Wrap multi-step side effects in transactions where atomicity matters. → transactions
- Protect rate-limited resources with global or tag-based concurrency limits. → global-concurrency-limits, tag-based-concurrency-limits

## 3. Deployment & execution
- Choose deployment style deliberately: `prefect.yaml` (declarative, multi-deploy) vs `.deploy()` / `flow.from_source().deploy()` (pythonic) vs `flow.serve()` (long-running local). → deployments, prefect.yaml, how-to deployments
- Pick a work-pool type to match infra: process (simple/local), docker, kubernetes, or Prefect-managed (no infra to run). → work-pools
- Run a worker for the pool (workers replace agents). → workers
- Decide Cloud vs self-hosted server early; it shapes auth, blocks, and pools. → server / Cloud
- Attach schedules (cron / interval / rrule) at the deployment, not in flow code. → schedules
- Deploy from CI/CD with pinned source, not from a laptop. → deploy-ci-cd
- Tag deployments for filtering and observability. → deployments

## 4. Config, secrets, observability & testing
- Store connection/config as blocks; reference them, don't inline. → blocks
- Use variables for non-secret, environment-varying values. → variables
- Keep secrets in Secret blocks / a secrets backend — never in code, parameters, or logs. → blocks (secrets)
- Use the Prefect logger and `PREFECT_LOGGING_*` settings, not ad-hoc prints. → logging
- Emit artifacts (markdown / table / link) for run outputs you want surfaced in the UI. → artifacts
- Drive reactive behavior with automations + events/triggers instead of polling. → automations, events
- Test flows with `prefect_test_harness`; assert external behavior, not internals. → testing

## Audit notes
- First confirm the project is on Prefect **3.x**. Any 2.x usage — agents, `prefect.deployments.Deployment`, `prefect deployment build` — is a migration flag.
- Report findings grouped by the four areas above; for each gap, link the current doc page for the fix (see [docs-map.md](docs-map.md)).
