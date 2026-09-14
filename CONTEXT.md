# Context

Ubiquitous language for this repo's skills. Glossary only — no implementation details.

## Terms

- **Ticket** — the unit of implementable work. On GitHub or GitLab the ticket is stored as an issue; the skills' mechanics use GitHub (`gh`).
- **Integration branch** — the branch created off the default branch (`main` in most repos) for a whole feature; all per-ticket work for that feature lands here before anything reaches the default branch.
- **Ticket branch**: a branch for one ticket. Each feature dispatch starts from a pinned integration commit. Its temporary branch remains until verified integration preserves its commits and cleanup proves ownership.
- **Feature PR** — the single pull request from the integration branch into the default branch; the only PR a feature produces.
- **Spec**: a specification stored as an issue, labelled `spec` or the older `prd`. Tickets divide its implementation. A spec-only feature run promises its full requirements; an explicit ticket set uses it as context.
- **Work-set**: the resolved list of tickets a feature run will implement, announced before branch creation. An explicit ticket list controls this scope.
- **Frontier**: the unowned tickets whose blockers are satisfied in the verified, preserved integration tip.
- **Dispatch base**: the immutable integration commit assigned to a ticket attempt. Concurrent attempts can have different bases as integration advances.
- **Completion mode**: the obligations a feature run must satisfy. A whole-spec run covers every spec requirement; a selected-ticket run covers its explicit work-set.
- **Orchestrated dispatch**: a ticket worker invocation with an assigned immutable base commit, inherited original baseline, satisfied blockers, and coordinator-owned issue and PR actions.
- **Baseline**: the original base commit and its recorded check results. Later dispatch commits and integration failures remain distinct from this original evidence.
- **Handoff files**: durable shared artifacts containing scope, ticket snapshots, exploration notes, commands, and decisions. Workers exchange their paths and update the run record as work completes and integrates.
- **Verification plan** — the human-facing walkthrough a run authors once implementation is complete and verified: a few scenarios (at most three) covering what automated tests could not, for a human to use the delivered application and inspect the resulting data. Not a test run — expected results orient the human's judgement rather than assert pass/fail; distinct from a PR's Test plan, which records what the agent itself ran.
- **Actor** — the GitHub user whose activity a report describes; discovered at invocation time (the authenticated `gh` user), never committed to a repo, overridable per invocation. The actor bounds a report's scope: the report covers the actor's activity wherever it happened, across every account and repo.
- **Owner** — an optional per-invocation filter narrowing a report to one GitHub account's repos. When absent (the default), the report is actor-bounded and no owner is involved.
- **Refusal**: the snowman wrapper's `Blocked` exception, raised by the guardrail or by target resolution and rendered once in `main` as `BLOCKED: <reason>` with exit code 2.
- **Target**: the resolved connection, environment, project root, snowman dir, and `.env` file for one snowman run, produced by `resolve_target`.
