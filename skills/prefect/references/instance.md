# Instance queries

Detail for the CLI-first protocol in `SKILL.md`: establishing the target,
auditing a project, and diagnosing a run. Each section is read-only work.

## Establish the target

Before the first instance query, run the bundled script from the project root
with the project's own Python, through the runner chosen for the CLI (for
example `uv run python` in an established uv project). `<skill-dir>` is the
directory that holds this skill's `SKILL.md`:

```bash
python <skill-dir>/scripts/target.py
```

It prints one `key: value` line per fact: the Prefect version, the active
profile, the API URL, `target` (`cloud`, `server`, `ephemeral`, or `none`), and
each auth setting by presence and source. Read the exit code:

- `0`: the summary was printed. Its output is safe to keep in the transcript.
- `2`: Prefect is not importable in that interpreter. Fix the runner; do not
  fall back to another environment's Prefect.
- `3`: this Prefect version's settings layout is not recognized. Establish the
  same facts by hand under the redaction rule below.

- **Effective settings.** Environment variables, `.env`, `prefect.toml`, and
  `pyproject.toml` outrank the profile in that order, so a profile change alone
  may not change the target. The script marks each value as `env` or `not env`.
  Setting names and their environment variables:
  https://www.prefect.io/docs/v3/api-ref/settings-ref.md
- **Redaction.** When inspecting by hand, output only allowlisted target fields
  and strip credentials, query strings, and fragments from displayed URLs.
  Report authentication settings by presence, never their values. Filter before
  output reaches the transcript: `prefect config view` masks only settings
  typed as secrets, so it prints tokens held in `PREFECT_CLIENT_CUSTOM_HEADERS`
  and credentials embedded in the API URL.
- **Remote targets.** For remote inspection, establish the matching endpoint
  before querying. An ephemeral local server is not evidence about a remote
  instance.
- **Access.** Confirm access with a read-only query; displaying configuration
  does not verify auth.
- **Auth failures.** For Cloud, use the configured API-key path or interactive
  `prefect cloud login` when needed. For self-hosted servers, check the endpoint
  and configured auth, including `PREFECT_API_AUTH_STRING` for basic auth. A
  stray `PREFECT_API_KEY`, in the environment or the active profile, takes
  precedence and makes self-hosted auth fail with HTTP 401. Resolve the target
  and auth cause before retrying; ask the user only for missing target
  information or credentials they must supply.
- **MCP evidence.** Prefect's hosted MCP server reads the Cloud workspace chosen
  at sign-in, not the project's profile. Match its workspace to the project's
  target before treating its results as evidence about that target.

## Audit a project

Diff deployed reality (deployments, pools, schedules) against the repo's
manifests.

- Read listings with `--output json` for complete identifiers; rendered tables
  truncate them.
- Check filters and pagination before claiming an object is absent or the
  inventory is complete. Listings are capped (`flow-run ls` shows 15 runs
  unless `--limit` says otherwise). Paginate via `prefect api` or the SDK when
  necessary.
- Inspect expected deployments by identity to verify missing claims; find
  unexpected deployments only from a complete inventory.
- If coverage is incomplete, report that limit instead of asserting drift.

## Diagnose a run

Read `flow-run inspect <id>` and `flow-run logs <id>`, with the run's state
transitions, before classifying the cause.

- **`Crashed` is not a cause.** It can include broken imports or syntax errors
  during startup; the state alone does not establish an infrastructure cause.
- **Worker-backed pools.** Check worker health, pool/queue polling, concurrency,
  and infrastructure logs. Process workers (3.8.3+) may launch runs via
  `uv run`; confirm the run's environment rather than assuming the inspected one.
- **Push and Managed pools.** These need no worker; inspect submission and
  infrastructure errors instead.
- **`serve()`.** Check the serving process and its subprocess logs.
- **Zombie runs** stay `Running` after their infrastructure died. Detection
  rests on heartbeats: deployment-triggered runs emit them by default from
  client 3.6.22 (every 180 seconds), and from 3.1.8 only when a heartbeat
  frequency is set. The setting was introduced as
  `PREFECT_RUNNER_HEARTBEAT_FREQUENCY` and is now also
  `PREFECT_FLOWS_HEARTBEAT_FREQUENCY`; confirm which name the run's client
  version reads. Something must also act on the silence: Cloud's "Unresponsive
  run detection" workspace policy, or on a self-hosted server an automation
  that moves silent runs to `Crashed`. Check the run's client version and
  whether either exists before expecting a zombie to resolve itself, and
  confirm whether the execution process still exists before concluding it is
  dead. Setup and thresholds:
  https://www.prefect.io/docs/v3/advanced/detect-zombie-flows.md
