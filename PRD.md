# PRD: `prefect-skill` — a Prefect 3 greenfield-and-audit agent skill with live doc lookup

> Status: ready to build · Type: standalone, publishable agent skill (own GitHub repo)
> Origin: synthesized from a `/grill-me` design session, then `/to-prd`.

## Problem Statement

When I (a data/platform engineer) ask a coding agent to set up a new Prefect
project, or to review an existing one, the agent leans on whatever Prefect
knowledge happens to be baked into its training. Prefect moved from 2.x to 3.x
with major breaking changes, and 3.x itself keeps evolving, so that baked-in
knowledge is frequently stale or subtly wrong — it invents deprecated APIs
(`prefect.deployments.Deployment`, agents instead of workers), guesses at
`prefect.yaml` shape, and gives me deployment/work-pool advice that no longer
matches current standards. I have no consistent way to make the agent (a) start
a greenfield Prefect 3 project against *current* best practice, and (b) stop and
consult the real Prefect docs when it is unsure, rather than confabulating.

I want a reusable, publishable agent skill that encodes the durable Prefect 3
standards I care about, forces the agent to look things up in the live Prefect
docs when uncertain, and works the same in any project — not just the one repo
it was born in.

## Solution

A single, portable agent skill — `prefect-skill` — published as its own GitHub
repository so I and others can install it anywhere. From the user's perspective:

- When I ask the agent to scaffold or extend a Prefect 3 project, it follows an
  opinionated **greenfield workflow** and a **standards-and-gotchas checklist**
  covering scaffolding/structure, authoring + reliability, deployment +
  execution, and config/secrets/observability/testing.
- When I point it at an existing Prefect project, the same checklist runs as an
  **audit rubric** that flags drift from current standards.
- Whenever the agent is unsure about a Prefect API or approach, it follows a
  built-in **doc-lookup protocol**: fetch `docs.prefect.io/llms.txt` to locate
  the right page, then fetch that page as markdown (`<page>.md`) for detail,
  with web search only as a fallback.
- Every Prefect response follows a **lightweight response contract** so I always
  see what version/target was assumed, the recommendation and its key tradeoff,
  which doc page was consulted (or that it came from baseline knowledge), and a
  concrete validation step.

The skill is deliberately **thin**: it embeds opinions, a workflow, a checklist,
and a docs map — but delegates topic *detail* to live docs so it never goes
stale. It targets the **Prefect 3.x generation** without hardcoding any patch
version. Prefect 2.x is explicitly out of scope.

## User Stories

### Greenfield authoring
1. As a data engineer starting a new project, I want the agent to scaffold a Prefect 3 project against current best practice, so that I don't inherit deprecated patterns from the agent's training data.
2. As a data engineer, I want the skill to lean on `prefect init` and current project conventions rather than a bespoke scaffolder, so that my project structure matches what Prefect itself recommends today.
3. As a data engineer, I want opinionated defaults for flows, tasks, subflows, parameters/typing, async, and task runners, so that my day-to-day flow code follows current idioms.
4. As a data engineer, I want guidance on retries, timeouts, caching, and results persistence at authoring time, so that reliability is designed in rather than bolted on.
5. As a data engineer, I want clear guidance on choosing how deployments are defined (`prefect.yaml` vs `.deploy()` / `flow.from_source`), so that I pick an approach that fits my execution model.
6. As a data engineer, I want guidance on work pools and workers (process, docker, kubernetes, managed) and on Cloud vs self-hosted, so that I choose an execution environment deliberately.
7. As a data engineer, I want guidance on scheduling (cron/interval/rrule) and on automations/events/triggers, so that orchestration is event- and time-driven correctly.
8. As a data engineer, I want guidance on blocks, variables, and secret handling, so that credentials and config are managed the Prefect-native way rather than ad hoc.
9. As a data engineer, I want guidance on logging, artifacts, and observability, so that my runs are debuggable and surface results.
10. As a data engineer, I want guidance on testing flows (e.g. `prefect_test_harness`), so that my pipelines have automated coverage.
11. As a data engineer, I want guidance on CI/CD-based deployment, so that deploys are reproducible and not run from a laptop.

### Auditing an existing project
12. As an engineer maintaining an existing Prefect project, I want to run the same checklist as an audit, so that I can find where the project has drifted from current standards.
13. As an engineer, I want the audit to flag deprecated APIs (e.g. agents instead of workers, `Deployment` objects), so that I know what to migrate.
14. As an engineer, I want the audit output organized by the same four decision areas as the greenfield checklist, so that build and audit speak the same language.
15. As an engineer on this data platform specifically, I want the skill to recognize patterns like dual local/Cloud deployment manifests, a parametrized shared flow, and `run_deployment` fan-out as legitimate, so that it doesn't flag good patterns as problems.

### Doc lookup (uncertainty guardrail)
16. As a user, I want the agent to consult the live Prefect docs whenever it is unsure about an API or approach, so that I get current answers instead of confident guesses.
17. As a user, I want the agent to resolve a topic to the right doc page via `llms.txt` and then fetch that page as markdown, so that lookups are precise rather than vague web searches.
18. As a user, I want web search used only as a fallback when the structured doc path fails, so that lookups stay cheap and deterministic.
19. As a user, I want the lookup protocol to work under sandboxed environments, so that it relies on the sanctioned fetch path rather than shell `curl` that may be network-blocked.
20. As a user, I want the agent to tell me which doc page it consulted, so that I can verify the answer and learn where to look myself.

### Response discipline
21. As a user, I want every Prefect response to state its assumptions (Prefect 3.x, Cloud vs self-hosted, work-pool type), so that I can catch a wrong assumption before acting on the advice.
22. As a user, I want every response to name the key tradeoff of its recommendation, so that I understand what I'm giving up.
23. As a user, I want every response to include a concrete validation step (e.g. a `prefect deploy` dry run or `prefect.yaml` check), so that I can confirm the change is sound.
24. As a user, I want the contract to stay lightweight, so that routine flow authoring isn't buried in ceremony.

### Portability, versioning, freshness
25. As a user, I want the skill to be portable across any project, so that I can use it on greenfield work elsewhere, not just the repo it came from.
26. As a user, I want the skill to target the Prefect 3.x generation without pinning a patch version, so that it stays correct as 3.x evolves.
27. As a user, I want Prefect 2.x treated as out of scope (migrate up), so that the skill doesn't dilute its 3.x advice.
28. As a user, I want topic detail delegated to live docs rather than embedded, so that the skill doesn't rot.

### Publishing & installation
29. As the skill author, I want the skill in its own GitHub repo with a README, LICENSE, and proper SKILL.md metadata (name, description, license, author, version), so that I can publish and version it independently.
30. As a teammate, I want clear install instructions in the README, so that I can add the skill to my own agent setup.
31. As a user installing the skill, I want its description to carry broad Prefect-3 triggers, so that the agent loads it for greenfield setup, audits, and any uncertain Prefect work — not only explicit "set up a project" requests.
32. As the skill author, I want the skill's structure to mirror a known-good tool-skill template (workflow + response contract + routing table + on-demand references), so that it's familiar and maintainable.

### Maintenance / integrity (the skill's own "tests")
33. As the skill author, I want CI to check that the doc URLs in the docs map are still live (via `llms.txt` plus a sampled set), so that I'm alerted when Prefect moves or renames pages.
34. As the skill author, I want CI to lint SKILL.md (frontmatter present, description contains "Use when" triggers, SKILL.md within its line budget), so that the skill stays well-formed as I edit it.

## Implementation Decisions

### Scope & positioning
- **One skill, broad trigger.** A single skill — not two — whose description triggers on any Prefect 3 work: greenfield scaffolding, auditing an existing project, and any moment the agent is building/debugging Prefect flows or deployments or is unsure about a Prefect API. This makes the doc-lookup guardrail reachable in everyday Prefect work, not only during explicit setup.
- **Portable, this repo as example only.** The skill teaches generic latest-Prefect-3 standards. The thorit data platform's patterns (dual local/Cloud `prefect.yaml`/`prefect.cloud.yaml`, a parametrized shared extract-and-load flow, `run_deployment`-based fan-out orchestration, `prefect-dbt`'s `PrefectDbtRunner`) appear only as portable *pattern sketches* with no hardcoded paths — never as mandatory rules.
- **Greenfield + audit, same checklist.** The standards checklist serves double duty: a build guide for new projects and an audit rubric for existing ones.
- **Version anchor: Prefect 3.x generation.** The skill states it targets Prefect 3 and assumes 3.x APIs/CLI, but never hardcodes a patch number; anything version-sensitive is confirmed via live docs. Prefect 2.x is out of scope (migrate up).

### Doc-lookup mechanism
- **Live fetch, structured.** The protocol is: fetch `https://docs.prefect.io/llms.txt` (the index of every page) to locate the right page, then fetch that page as markdown by appending `.md` to its URL for detail. Web search is a **fallback only** when the structured path doesn't resolve.
- **`llms-full.txt` avoided** as the default path — it's the entire docs in one file and can blow the context window; reserved for rare whole-corpus needs.
- **Fetch via the agent's sanctioned web-fetch capability**, not shell `curl`, so the protocol works in sandboxed environments where outbound shell network access may be blocked.
- **No vendored doc snapshot and no MCP/Context7 dependency** — vendoring rots and contradicts "latest docs"; an MCP server breaks portability. The skill is instruction-only.

### Skill artifacts (the "modules")
The skill is structured to mirror a proven tool-skill template (a workflow-first SKILL.md with depth in on-demand reference files):

- **`SKILL.md` (core, deep module).** The stable, simple-interface heart. Contains: frontmatter metadata; the lightweight Response Contract; the doc-lookup protocol; a diagnose/routing table mapping user intent → the relevant checklist area and doc area; a "When to Use / Don't Use" block; and the greenfield and audit workflows. Kept within a tight line budget (progressive disclosure — detail lives in references).
- **`references/greenfield-checklist.md`.** The four decision areas, each as one-line standards plus a live-doc pointer, doubling as the audit rubric:
  1. *Scaffolding & structure* — project init, repo layout, dependency management, dev/prod environment separation.
  2. *Authoring patterns + reliability* — flows, tasks, subflows, params/typing, async, task runners, retries, timeouts, caching, results persistence.
  3. *Deployment & execution* — `prefect.yaml` vs `.deploy()`/`flow.from_source`, work pools (process/docker/kubernetes/managed), workers, Cloud vs self-hosted, CI/CD, scheduling.
  4. *Config, secrets, observability & testing* — blocks/variables/secrets, logging, artifacts, automations/events, `prefect_test_harness`.
- **`references/docs-map.md`.** A durable topic → `docs.prefect.io` URL map (a navigation aid, not embedded content) so lookups are fast and deterministic and so the liveness CI has a concrete list to check.
- **Repo scaffolding for publishing** — `README.md` (what the skill is, install instructions, how the lookup protocol works), `LICENSE` (permissive, e.g. Apache-2.0 or MIT), and SKILL.md frontmatter metadata (`name`, trigger-rich `description`, `license`, author, version).
- **Optional, deferred:** a `references/patterns.md` of portable pattern sketches may be added later if the checklist alone proves too terse; not part of the first build.

### Response Contract (interface every Prefect response honors)
Lightweight, four points:
1. **Assumptions / target** — Prefect 3.x, Cloud vs self-hosted, work-pool type.
2. **Recommendation + key tradeoff.**
3. **Doc consulted** — the specific page fetched, or explicitly "baseline knowledge" when none was needed.
4. **Validation step** — a concrete check (e.g. a `prefect deploy` dry run, a `prefect.yaml` review).
A heavier terraform-style contract (mandatory rollback notes, risk categories on every response) was considered and rejected as too much ceremony for routine flow authoring.

### Distribution
- **Standalone publishable repo**, seeded by this PRD, intended to be pushed to GitHub and installable independently. Not installed via the local `~/.agents/skills` symlink convention and not coupled to the thorit data platform's issue tracker.

## Testing Decisions

Because the skill is instruction-only (no executable scripts ship inside it), its "tests" are CI checks on the skill's own integrity rather than unit tests of code. A good test here verifies *externally observable* properties of the skill artifacts — that links resolve and that the skill is well-formed — not internal prose phrasing.

- **Doc-URL liveness check (will be built).** CI fetches `docs.prefect.io/llms.txt` and a sampled set of the URLs in `references/docs-map.md`, failing when pages 404 or move. This guards the single biggest rot risk: Prefect renaming or relocating docs. Runs on a schedule and on PRs.
- **SKILL.md lint (will be built).** CI validates that SKILL.md has required frontmatter (`name`, `description`, `license`), that the description contains explicit "Use when …" triggers, and that SKILL.md stays within its line budget. This keeps the skill well-formed as it's edited.
- **Prior art.** The repo has no existing skill-CI to copy; these checks are new and should be implemented as small, dependency-light CI jobs (a fetch-and-grep liveness job and a frontmatter/line-count linter). Model them on conventional docs-link-checker and markdown-frontmatter-lint patterns.
- **Out of test scope:** asserting the *content* of advice the agent gives (non-deterministic, model-dependent) and end-to-end agent-behavior eval harnesses.

## Out of Scope

- Prefect 2.x guidance beyond "migrate to 3.x."
- A bespoke project scaffolder/generator script (the skill leans on `prefect init` and current conventions instead).
- Vendored/offline doc snapshots and any MCP/Context7 retrieval dependency.
- Hardcoding the thorit data platform's file paths or treating its conventions as mandatory rules (they are illustrative examples only).
- Installing the skill into the local `~/.agents/skills` + `~/.claude/skills` symlink setup, or filing this PRD as an issue on the `sleeplessv/thorit-data-platform` tracker.
- Deep embedded per-topic reference manuals (explicitly rejected in favor of the thin + live-lookup approach).
- An automated eval harness that grades the agent's Prefect answers.

## Further Notes

- **Why thin + live lookup:** it's the only design that actually satisfies "latest docs and standards" while honoring the skill-authoring rule against time-sensitive content. The skill owns *opinions, workflow, and navigation*; the docs own *detail*.
- **Confirmed external facts (May 2026):** Prefect publishes `https://docs.prefect.io/llms.txt` (page index) and `https://docs.prefect.io/llms-full.txt` (full corpus), all docs live under `/v3/` paths, and any page is available as clean markdown by appending `.md` (e.g. `https://docs.prefect.io/v3/get-started.md`). These underpin the lookup protocol.
- **Template lineage:** the structure intentionally parallels a known-good tool-skill (workflow + response contract + diagnose/routing table + on-demand `references/`, with author/version/license frontmatter), kept lighter than that template's many reference files per the "thin" decision.
- **Next step after this PRD:** build the skill artifacts in this repo directory, then publish to GitHub.
