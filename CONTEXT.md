# Context

Ubiquitous language for this repo's skills. Glossary only — no implementation details.

## Terms

- **Ticket** — the unit of implementable work. On GitHub or GitLab the ticket is stored as an issue; the skills' mechanics use GitHub (`gh`).
- **Integration branch** — the branch created off the default branch (`main` in most repos) for a whole feature; all per-ticket work for that feature lands here before anything reaches the default branch.
- **Ticket branch** — a branch created for exactly one ticket's work; in a feature run it is cut from the integration branch, in solo work from the default branch.
- **Feature PR** — the single pull request from the integration branch into the default branch; the only PR a feature produces.
- **Spec** — a spec document (formerly PRD) stored as a GitHub issue, labelled `spec` (`prd` on older repos); never implemented directly, always broken into tickets first. In a feature run it is context, never a work item.
- **Work-set** — the resolved list of tickets a feature run will implement; announced before any branch is created.
- **Wave** — the set of currently-unblocked tickets dispatched in parallel; a wave's ticket branches are cut from the integration-branch tip, so blockers are always merged before their dependants start.
- **Orchestrated dispatch** — an invocation of `implement-ticket` by an orchestrator with sanctioned overrides (base branch, no per-ticket PR, blockers pre-merged) rather than its solo defaults.
- **Verification plan** — the human-facing walkthrough a run authors once implementation is complete and verified: scenario steps for a human to use the delivered application and inspect the resulting data, traceable to acceptance criteria. Not a test run — expected results orient the human's judgement rather than assert pass/fail; distinct from a PR's Test plan, which records what the agent itself ran.
- **Actor** — the GitHub user whose activity a report describes; discovered at invocation time (the authenticated `gh` user), never committed to a repo, overridable per invocation. The actor bounds a report's scope: the report covers the actor's activity wherever it happened, across every account and repo.
- **Owner** — an optional per-invocation filter narrowing a report to one GitHub account's repos. When absent (the default), the report is actor-bounded and no owner is involved.
