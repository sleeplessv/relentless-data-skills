# Glossary

Ubiquitous language for this repo's skills. Glossary only — no implementation details.

## Terms

- **Skill**: an independently versioned bundle of agent instructions and supporting files. Its documentation belongs to the same bundle.
- **Skill update**: a set of changes delivered together to one skill. Documentation corrections count as updates, even when the skill's behavior stays the same.
- **Skill version**: the identifier of a skill revision, used to track changes and support updates to installed copies.
- **Ticket** — the unit of implementable work. On GitHub or GitLab the ticket is stored as an issue; the skills' mechanics use GitHub (`gh`).
- **Integration branch** — the branch created off the default branch (`main` in most repos) for a whole feature; all per-ticket work for that feature lands here before anything reaches the default branch.
- **Ticket branch**: a branch for one ticket. Each feature dispatch starts from a pinned integration commit. Its temporary branch remains until verified integration preserves its commits and cleanup proves ownership.
- **Feature PR** — the single pull request from the integration branch into the default branch; the only PR a feature produces.
- **Spec**: a specification stored as an issue, labelled `spec` or the older `prd`. Tickets divide its implementation. A spec-only feature run promises its full requirements; an explicit ticket set uses it as context.
- **Work-set**: the resolved list of tickets a feature run will implement, announced before branch creation. An explicit ticket list controls this scope.
- **Deepening candidate**: a proposed refactor, produced by an architecture review, that turns a shallow module into a deep one. It carries the files involved, the problem, the proposed solution, and a recommendation strength.
- **Decision log**: the answered design tree for one deepening candidate, each decision paired with its evidence. The spec for that candidate is written from it.
- **Frontier**: tickets with no active implementer whose blockers are satisfied in the verified, preserved integration tip. Assignment to the authenticated actor is advisory and does not make that actor an active implementer.
- **Dispatch base**: the immutable integration commit assigned to a ticket attempt. Concurrent attempts can have different bases as integration advances.
- **Completion mode**: the obligations a feature run must satisfy. A whole-spec run covers every spec requirement; a selected-ticket run covers its explicit work-set.
- **Orchestrated dispatch**: a ticket worker invocation with an assigned immutable base commit, inherited original baseline, satisfied blockers, and coordinator-owned issue and PR actions.
- **Baseline**: the original base commit and its recorded check results. Later dispatch commits and integration failures remain distinct from this original evidence.
- **Handoff files**: durable shared artifacts containing scope, ticket snapshots, exploration notes, commands, and decisions. Workers exchange their paths and update the run record as work completes and integrates.
- **Actor** — the GitHub user whose activity a report describes; discovered at invocation time (the authenticated `gh` user), never committed to a repo, overridable per invocation. The actor bounds a report's scope: the report covers the actor's activity wherever it happened, across every account and repo.
- **Owner** — an optional per-invocation filter narrowing a report to one GitHub account's repos. When absent (the default), the report is actor-bounded and no owner is involved.
- **Refusal**: the snowman wrapper's `Blocked` exception, raised by the guardrail or by target resolution and rendered once in `main` as `BLOCKED: <reason>` with exit code 2.
- **Target**: the resolved connection, environment, project root, snowman dir, and `.env` file for one snowman run, produced by `resolve_target`.
- **Branch diff**: the lines the checked-out branch adds and removes, measured from the point where it split from the default branch to the working tree. It is what the branch's PR would show if everything were committed now. _Avoid_: session lines, PR diff.
- **Session edits**: the lines Claude added and removed during one Claude Code session, whatever branch they landed on. Distinct from the branch diff.
- **Dossier**: a single self-contained HTML document that explains one system, process, finding or decision through numbered figures and tables, in the house style every dossier shares. _Avoid_: visual report, explainer, writeup (as names for the document).
- **Answer box**: the box at the top of a dossier stating the one claim the dossier defends. Every dossier has one, explainers included. _Avoid_: summary, TL;DR, verdict box.
- **Figure**: a numbered visual in a dossier, with a caption and a so-what box. Tables follow the same rule on their own counter ("Table 2"). _Avoid_: chart (for the general case), diagram (for the general case).
- **Caption**: the text beside a figure: one sentence on what it shows, then one to three points on how to read it. It never states the conclusion. _Avoid_: description, legend.
- **So-what box**: the tinted box labelled "So what" beside a figure, holding the conclusion the reader should draw from that figure alone. _Avoid_: takeaway (takeaways are the section-level list).
- **Limits section**: the closing section of every dossier, listing what it could not establish. It stays when it says "None". _Avoid_: caveats, disclaimers.
- **Locked block**: the part of the dossier stylesheet (colour tokens, type scale, component styles) that every dossier carries unchanged. A dossier may change only the per-report geometry beside it. _Avoid_: theme, base CSS.
- **Visual family**: one of the named kinds of figure a dossier draws from, such as a DAG, a timeline or a comparison matrix. _Avoid_: pattern, chart type.
