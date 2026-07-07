# Context

Ubiquitous language for this repo's skills. Glossary only — no implementation details.

## Terms

- **Integration branch** — the branch created off the default branch (`main` in most repos) for a whole feature; all per-issue work for that feature lands here before anything reaches the default branch.
- **Issue branch** — a branch created off the integration branch for exactly one issue's work.
- **Feature PR** — the single pull request from the integration branch into the default branch; the only PR a feature produces.
- **PRD** — a spec document stored as a GitHub issue (labelled `prd`); never implemented directly, always broken into issues first. In a feature run it is context, never a work item.
- **Work-set** — the resolved list of issues a feature run will implement; announced before any branch is created.
- **Wave** — the set of currently-unblocked issues dispatched in parallel; a wave's issue branches are cut from the integration-branch tip, so blockers are always merged before their dependants start.
- **Orchestrated dispatch** — an invocation of `implement-issue` by an orchestrator with sanctioned overrides (base branch, no per-issue PR, blockers pre-merged) rather than its solo defaults.
