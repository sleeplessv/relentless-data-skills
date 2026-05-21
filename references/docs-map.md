# Prefect 3 Docs Map

**Durable contract (won't rot):**
- Index of every page: `https://docs.prefect.io/llms.txt`
- Any page as clean markdown: append `.md` to its URL (e.g. `https://docs.prefect.io/v3/concepts/flows.md`)
- Whole corpus (avoid by default — context-heavy): `https://docs.prefect.io/llms-full.txt`
- All Prefect 3 docs live under `/v3/` (integrations under `/integrations/`).

The URLs below are a convenience cache, validated by CI. **If any 404s, re-fetch
`llms.txt` and re-resolve — do not invent URLs.**

## Getting started
- quickstart / install => https://docs.prefect.io/v3/get-started/quickstart.md
- how-to guides index => https://docs.prefect.io/v3/how-to-guides/index.md
- examples index => https://docs.prefect.io/v3/examples/index.md
- API & SDK reference => https://docs.prefect.io/v3/api-ref/index.md

## 1. Scaffolding & structure
- projects / prefect init => https://docs.prefect.io/v3/how-to-guides/projects/index.md
- prefect.yaml => https://docs.prefect.io/v3/how-to-guides/deployments/prefect-yaml.md

## 2. Authoring & reliability
- flows => https://docs.prefect.io/v3/concepts/flows.md
- tasks => https://docs.prefect.io/v3/concepts/tasks.md
- task runners => https://docs.prefect.io/v3/concepts/task-runners.md
- caching => https://docs.prefect.io/v3/concepts/caching.md
- results / result persistence => https://docs.prefect.io/v3/advanced/results.md
- transactions => https://docs.prefect.io/v3/advanced/transactions.md
- retries / advanced => https://docs.prefect.io/v3/advanced/index.md
- global concurrency limits => https://docs.prefect.io/v3/concepts/global-concurrency-limits.md
- tag-based concurrency limits => https://docs.prefect.io/v3/concepts/tag-based-concurrency-limits.md

## 3. Deployment & execution
- deployments => https://docs.prefect.io/v3/concepts/deployments.md
- how-to deploy => https://docs.prefect.io/v3/how-to-guides/deployments/index.md
- work pools => https://docs.prefect.io/v3/concepts/work-pools.md
- workers => https://docs.prefect.io/v3/concepts/workers.md
- self-hosted server => https://docs.prefect.io/v3/concepts/server.md
- schedules => https://docs.prefect.io/v3/concepts/schedules.md
- deploy via CI/CD => https://docs.prefect.io/v3/advanced/deploy-ci-cd.md

## 4. Config, secrets, observability & testing
- blocks => https://docs.prefect.io/v3/concepts/blocks.md
- secrets / blocks how-to => https://docs.prefect.io/v3/how-to-guides/blocks/index.md
- variables => https://docs.prefect.io/v3/concepts/variables.md
- logging => https://docs.prefect.io/v3/advanced/logging-customization.md
- artifacts => https://docs.prefect.io/v3/concepts/artifacts.md
- automations => https://docs.prefect.io/v3/concepts/automations.md
- events / triggers => https://docs.prefect.io/v3/concepts/events.md
- testing => https://docs.prefect.io/v3/how-to-guides/testing/index.md

## Integrations
- prefect-dbt => https://docs.prefect.io/integrations/prefect-dbt/index.md
- prefect-dbt runner (PrefectDbtRunner) => https://docs.prefect.io/integrations/prefect-dbt/runner.md
