# Evaluate DLT and Prefect behavior

Run these scenarios after changes to either skill's workflow. They supplement
the automated structural tests. Use an independent agent with the relevant
`SKILL.md`, its linked references, and the scenario's request and fixtures.
Keep expected outcomes with the reviewer rather than in the execution prompt.

Create a temporary project for each case. Supply synthetic package, CLI, and
instance evidence. Allow writes only in that project. Do not install packages,
read real credentials, connect to a live service, or commit fixture files.
Save the request, tool transcript, resulting artifacts, and pass/fail evidence.
State which behavior was simulated and which artifact was actually inspected.

## DLT scenarios

| Case | Request and fixture | Observable outcome |
| --- | --- | --- |
| Agent formats | Finish house-rule setup separately for Claude, Cursor, and Codex. Supply installed toolkit metadata and the active agent. | Claude gets a project `.md` rule, Cursor gets `.mdc` with `alwaysApply: true`, and Codex gets one managed root `AGENTS.md` section. Required bookkeeping and safety text survive. |
| Re-entry | Add SQL ingestion to a project with an existing REST rule. Run for a standalone rule and a managed section. Include unrelated memory instructions and an uncommitted rule. | Existing state is discovered, only missing setup is proposed, unrelated text survives, and no duplicate rule appears. A second identical run leaves the artifact unchanged. |
| Interrupted setup | Supply a rule and toolkit record that claim installation, but omit a recorded agent file. | The agent identifies missing local setup instead of declaring the record sufficient. The repair preserves existing configuration. |
| Destination and companions | Finish a BigQuery filesystem project with no `prefect`, `ship`, or `snowman` companion skills. Supply the installed filesystem entrypoint. | Inspection guidance targets BigQuery. Handoff uses the installed filesystem entrypoint and describes available fallbacks without promising missing commands. No Snowflake-specific instruction remains. |
| Snapshot promotion | Promote a small current-state source with updates/deletions but no cursor or change feed. Supply development code with `dev_mode=True` and a resource limit. | A suitable replacement strategy remains allowed. Production output disables development mode, removes limits, and proposes repeated-run checks for source changes. |
| Restart pending | Setup files exist, but the current session cannot load the new MCP or entry skill. | The report separates written setup from pending runtime readiness and identifies the post-restart check. |

For rule-format cases, inspect the actual generated file extension and parsed
frontmatter. For re-entry, compare file content before and after the second run.
Checking that the skill contains an instruction is not evidence of its execution.

## Prefect scenarios

| Case | Request and fixture | Observable outcome |
| --- | --- | --- |
| Auth output | Establish the target for a proxy-authenticated self-hosted instance. Supply a dummy custom-header token and an API URL containing dummy credentials and a query token. | Tool output reports the target and auth presence without either token, URL credentials, query, or fragment. Redaction occurs before transcript capture. |
| Inventory | Audit manifests against an API fixture with 201 deployments and a 200-object page limit. Put an expected deployment and an unexpected deployment beyond the first page in separate variants. | The agent retrieves complete evidence or states incomplete coverage. It does not call an expected deployment missing from one listing alone. |
| Remote target | Diagnose a known Cloud run with no effective API URL and ephemeral mode enabled. | The agent identifies missing remote target information instead of using an empty local instance as remote evidence. |
| Version and mode | Diagnose a worker-backed deployment whose image has an older Prefect version than the local CLI. Separately supply Managed and `serve()` cases. | Advice uses the affected runtime's version and checks the appropriate execution mechanism. Workerless modes do not trigger worker-repair advice. |
| Implementation | Change a local flow or deployment manifest with no deployment request. | The agent verifies the changed artifact locally and reports limits without creating remote resources. |

The inventory fixture's limit tests one concrete case; it is not a universal
Prefect limit. An extracted source function with mocked collaborators is useful
evidence, but report it separately from a complete CLI or server execution.
