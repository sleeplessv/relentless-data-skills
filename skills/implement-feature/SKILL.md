---
name: implement-feature
argument-hint: "[spec#] [ticket#...]"
disable-model-invocation: true
description: "Implement a whole feature as one PR: orchestrate subagent waves over a spec's tickets on a shared integration branch. Use when you have a spec (PRD) and/or its tickets (from to-spec / to-tickets) to implement end-to-end."
---

# Implement Feature

Take a spec and its tickets from open → integration branch → parallel ticket branches →
integrated review + tests → verification plan → **one feature PR** into the default branch.

Operate under the `orchestrator-mode` skill for the whole run — every git / gh / file /
test action below is a subagent dispatch (its 1–3-sentence report rule yields to this
skill's per-wave and close-out reports). Per-ticket work composes the `implement-ticket`
skill via its **Orchestrated dispatch** contract.

## Vocabulary

- **Work-set** — the resolved list of tickets this run will implement.
- **Integration branch** — `feat/spec-<N>-<slug>`, cut from the default branch; all ticket work merges here. The main tree stays checked out on it for the whole run. (Legacy runs named it `feat/prd-<N>-<slug>` — treat that as equivalent.)
- **Ticket branch** — `feat/ticket-<N>-<slug>`, cut from the integration-branch tip. (Legacy: `feat/issue-<N>-<slug>`.)
- **Wave** — the currently-unblocked tickets, dispatched in parallel.
- **Feature PR** — the single PR from integration branch to default branch.
- **Verification plan** — the human-facing walkthrough of the delivered feature (see `CONTEXT.md`): using the application and inspecting the data, not re-running tests. Authored after the gates, embedded in the feature PR body.

## Rules

- **Prose published to git or GitHub (PR body, ticket and spec comments, commit messages) follows the `technical-writing` and `unslop` skills when installed; baked-in minimum either way: plain words, active voice, and no em dashes (—)** — use commas, colons, or parentheses. Dispatch prompts that write such prose carry this rule (subagents may not have the skills).
- **Network `gh` / `git fetch|pull|push` run outside the sandbox** — every dispatch prompt says so.
- The spec is context, never a work item.
- **Implement the work-set at the scope its tickets ask for, as the smallest change that solves it** — adjacent bugs, refactors, and cleanups get reported in the feature PR body, not fixed. Ticket dispatches inherit the frugality bar via `implement-ticket`; steps 3–4 fix dispatch prompts carry it explicitly (the `principle-laziness-protocol` skill when installed): prefer deletion over addition and the smallest diff that fixes it.
- **One dispatch per ticket per wave** — no helper or double-check agents alongside it, none to re-read what a dispatch already returned. Only the dispatches steps 0-5 already prescribe (integration, resolver, targeted tests, gates, fixes, verification plan, PR) run beside it.
- Dispatch prompts tell the subagent to invoke `implement-ticket`; if subagents cannot load skills, paste its body verbatim into the prompt.
- **Every ticket dispatch gets worktree isolation, even a one-ticket wave** — deliberately stricter than orchestrator-mode's two-writer rule, so the main tree never leaves the integration branch. Use the delegation tool's native worktree isolation (orchestrator-mode reference, Tool Mapping); none available → stop and say so rather than sharing the main tree.

## Workflow

### 0. Resolve the work-set

One read-only dispatch (general-purpose — it runs networked `gh`; inherit the session model, this is read-only but not mechanical) gathers:

- **Args** — spec number, ticket list/range, or both. Spec-only → list its open tickets by scanning bodies for a `## Parent` section referencing `#<spec>` (the reliable link — current `to-tickets` doesn't dependably create native sub-issues). The match must be anchored to the heading — a prose mention of `#<spec>` elsewhere in a body is not a link, and `gh search issues` cannot express this:
  `gh issue list --state open --limit 500 --json number,title,body --jq '[.[] | select((.body // "") | test("(?m)^(## Parent[^\n]*[\r\n]+[^#\n]*|Part of )#<spec>\\b"))]'`
  (the alternation also catches wayfinder's `Part of #<n>` fallback and CRLF bodies; `[^#\n]*` keeps `#90 supersedes #<spec>` out). Union in the native sub-issue results (`gh api repos/<owner>/<repo>/issues/<spec>/sub_issues --jq '.[].number'` — empty or 404 is normal), dedupe by number, keep open issues only. List-only → resolve the shared parent spec for context. Both → the explicit list is the authoritative work-set — but a listed ticket whose `## Parent` names a different spec, or a list spanning two specs, is a stop-and-ask (likely a typo, and step 3 reviews against one spec).
- Closed tickets: skip, naming them in the announcement. Spec body + acceptance criteria: capture verbatim for later handoffs.
- Blocking edges → the dependency graph: for **every** work-set ticket, union the native dependency API (`gh api repos/<owner>/<repo>/issues/<n>/dependencies/blocked_by --jq '.[].number'`) with the body scan — either source alone may carry an edge, so the body scan is per-ticket, never skipped because the API returned edges elsewhere. Body-side extraction (accepts `## Blocked by` sections, inline `Blocked by #n`, and `Depends on #n`; anchored, so prose mentions don't count):
  `--jq '[ (.body//"") | scan("(?mi)^(?:##\\s*)?(?:Blocked by|Depends on)\\b[^\n]*(?:\n[ \t]*[-*][^\n]*)*") | scan("#[0-9]+") ]'`
  An edge to an open issue outside the work-set → stop and ask (a resume-merged ticket of this feature counts as satisfied, not outside); to a closed one → ignore.
- The **feedback-loop commands** — install/setup, type-check, test, and run commands (same sources as `implement-ticket` step 4) — for the dispatch handoffs and the step 3 gates.
- `git status --porcelain`; whether the integration branch exists (`feat/spec-<N>-*`, the legacy `feat/prd-<N>-*`, or the `feat/<slug>` a prior no-spec run named — probe origin with `git ls-remote origin 'feat/*'`, then fetch just the branch found: the commit scan below needs its history). If it does, the **resume state** per work-set ticket: **merged** iff it carries a "merged into" comment naming the discovered branch (under any accepted name), or a commit on `<default>..<integration branch>` matches `#<N>\b`, `ticket-<N>\b`, or the legacy `issue-<N>\b` in a closing or subject position (`closes/fixes #<N>`, a `ticket-<N>` branch slug; a bare mention like `revert #<N>` or `see #<N>` is not evidence — report it and ask); any pushed `feat/ticket-<N>-*` (or legacy `feat/issue-<N>-*`) WIP branch.

Then, in the main thread:

- **Announce the work-set** (numbers + titles) and the wave plan before any branch is created.
- **Work-set of one, no existing integration branch → do not orchestrate.** Say so, hand the ticket to `implement-ticket` in a single dispatch on its solo defaults (own branch, own PR, no overrides), and stop: the machinery below only pays off across several tickets. On resume, stay here — that ticket belongs to the feature PR.
- **Work-set of zero → no waves.** With an existing integration branch, the branch is merged-but-ungated: go straight to step 3's gates, then steps 4-5. With none, report there is nothing to implement and stop.
- **Cycle in the graph → stop** and surface it.
- **Dirty tree → stop and ask** (stash / commit / abort).
- Existing integration branch → **resume**: keep its discovered name verbatim everywhere (never rename or re-create it); merged tickets move to a resolved set — they satisfy blocker edges and step 5's `Closes` scan but are not re-dispatched; WIP branches go to their wave's dispatch as `resume_branch`. A `needs-info` label beside a WIP branch is a ticket a prior run parked, not human triage: name it in the announcement and dispatch it (the contract swaps the label back). `needs-info` with no WIP branch, `wontfix`, or `needs-triage` still stops. `awaiting-verification` on the spec or on a work-set ticket (a prior run's PR awaits human verification) is not a stop: name it in the announcement and proceed — this run's Verification plan supersedes the old one.

Done when: work-set announced, graph acyclic, tree clean, resume state known.

### 1. Integration branch

Dispatch (git plumbing with judgement forks — inherit the session model): `git switch <default> && git pull --ff-only`,
create `feat/spec-<N>-<slug>` (slug = kebab of the spec title, ≤5 words, drop filler),
push with `-u origin`. No spec in play → ask the user for a slug, use `feat/<slug>`.
On resume: skip creation, switch to the **step-0 discovered name** (legacy names stay),
`git pull --ff-only`, and push if local is ahead (a manual fix may be local-only).

Done when: the dispatch reports the branch pushed, checked out in the main tree, and its origin tip SHA.

### 2. Implement in waves

Repeat until the work-set drains, reporting once per wave (what merged, what is next), not per dispatch:

1. **Wave** = every remaining ticket whose blockers are all merged into the integration branch.
2. Dispatch the wave in parallel — one worktree-isolated coding subagent per ticket
   (model per orchestrator-mode). Each prompt is a rich handoff: ticket number, title, and body verbatim,
   spec excerpts, decisions so far, the step-0 feedback-loop commands (worktrees start
   without installed dependencies — install before baselining), and the
   `implement-ticket` **Orchestrated dispatch** overrides:
   `base_branch: <integration branch>`, `open_pr: false`, blockers pre-merged,
   `resume_branch` when step 0 found a WIP branch for it.
3. **Integrate**: a dedicated dispatch merges the wave's `status: success` branches
   into the integration branch in ascending ticket number (mechanical conflicts
   resolved, semantic ones escalated to one resolver dispatch, per orchestrator-mode;
   if the resolver also fails, `git merge --abort` so the main tree sits clean at the
   last pushed tip, then stop per Stop conditions), pushes it, and **only after the
   push succeeds** comments "merged into `<integration branch>`" on each merged ticket
   (including this wave's `already_satisfied` ones). It then removes every wave
   worktree, returned as `worktree_path` or not (failed ones too — their WIP is
   pushed), any branch the harness auto-created per worktree (identify via
   `git worktree list --porcelain`; delete nothing not found that way), and the merged branches. Return contract: `merged_tickets`,
   `conflicts_found`, `worktrees_cleaned`, `integration_tip`. **On escalation the
   resolver inherits those duties** for what it merges; the orchestrator opens the
   next wave only on a returned `integration_tip`, after a targeted test
   dispatch — the affected tests when a conflict was resolved, otherwise the merged
   tickets' tests (merged parallel writers always clear orchestrator-mode's Rule 6 bar).
4. A failed ticket (three strikes) keeps `implement-ticket`'s orchestrated stop
   behaviour (WIP pushed, findings commented, labels and assignment untouched) and
   returns `status: failed` with the WIP branch, `worktree_path`, and root cause.
   **Its dependants leave the work-set**; independent tickets continue
   (drain-around-failure); any returned `open_questions` go into the wave report.
   Failed tickets' WIP branches are never merged. `status: already_satisfied` →
   treat as merged; its "merged into" comment is the integrate dispatch's duty.

Done when: every work-set ticket is merged, or recorded as failed / skipped-as-downstream.

### 3. Integration gates

After the last wave, two separate dispatches by fresh subagents (no self-certification,
per orchestrator-mode: the first look at the *merged* result of many agents' work):

1. **Verify** — the step-0 feedback-loop commands: full type-check + test suite + runtime smoke check on the integration branch.
2. **Review** — the `code-review` skill with `<default>` as its fixed point (the main tree has the integration branch checked out, so HEAD is its tip). The Review dispatch prompt carries the step-0 spec body verbatim; the subagent writes it to a scratch file **outside the repo tree** (the session scratchpad), passes that path as the spec source, and deletes it after — this overrides code-review's own spec search, which would otherwise follow commit refs to the *tickets* instead of the spec; it must not ask the user. Dispatch it as a plain worker, not a sub-orchestrator: `code-review` carries its own fan-out.

Findings → sequential write-intent fix dispatches on the integration branch, then
re-verify; three strikes stops the run. On a partial work-set (anything failed or
skipped) run Verify so the pushed branch is known-green, skip Review, the Verification
plan, and the PR, and stop.

Done when: Verify and Review are clean on the pushed integration branch (partial work-set: Verify clean, then stop).

### 4. Verification plan

One dispatch (it runs the delivered software — inherit the session model) authors the
**Verification plan**: the walkthrough a human follows to use the delivered feature and
inspect its data. Its prompt carries the step-0 spec body and acceptance criteria
verbatim, the work-set tickets' criteria, and the step-0 feedback-loop and run commands.

- **Structure**: an **Environment** block up top (where to run it — the same environment
  the gates used — and estimated time), then per-scenario: **Goal** (which acceptance
  criterion), **Preconditions/setup**, **Steps** (copy-paste-ready commands/queries, one
  action each), **What you should see**, **Cleanup** when steps mutate anything.
- **Traceability**: scenarios cover the spec's acceptance criteria first, plus any ticket
  criterion not subsumed by them; a criterion with no human-facing surface is listed as
  "verified by automated tests only, because <reason>" instead of getting a scenario.
- **Not a test run**: expected results orient the human's judgement ("you should see
  ~1,200 rows, `order_total` populated from 2024 on"), never assert pass/fail —
  acceptance is the human's call.
- **Execute before publishing**: the dispatch runs every command/query in the plan
  against that environment; the observed output becomes the what-you-should-see text. A
  step the run's environment cannot reach is still authored, flagged
  "not executed, requires <env>", and named in the Environment block.
- **Evidently broken** (a step errors, or the data plainly contradicts a criterion) →
  back into step 3's fix machinery (sequential fix dispatches, re-run step 3's Verify,
  re-author the plan; the same three strikes). The plan never walks the human into a
  known defect.
- **Nothing to walk through** (docs-only, config tweak): return a one-line waiver —
  "No human verification beyond code review: <reason>" — never omit the section.

Done when: the dispatch returns the plan (or its waiver) as a markdown section, every runnable step executed.

### 5. Feature PR

One dispatch:

- Repo PR template if present; body carries a **Summary**, a **Test plan** (what the
  step-3 Verify gate ran and observed), the step-4 **Verification plan** verbatim,
  and rebuilt `Closes #<n>` lines: scan every
  ticket from any run's work-set plus every open ticket of the spec (re-run the step-0
  ticket scan) and include each one covered by step 0's evidence rule (a "merged into"
  comment, or a closing/subject-position commit ref) — whichever run or human put it
  there. Add `Closes #<spec>` only when every open ticket of the spec is covered;
  otherwise comment progress on the spec.
- **Size the body to the change**: a line per ticket in the Summary, what actually ran in
  the Test plan, no filler sections and no restated ticket bodies.
- Create it **ready-for-review** (not draft); if a prior run already opened the feature
  PR, update its body instead — replacing the old Verification plan section, not
  appending a second one. Merging is the human's.
- Apply `awaiting-verification` to the spec, or to each work-set ticket when the run has
  no spec (`gh label create` it first if the repo lacks it) — unless the plan is a
  waiver, when there is nothing to verify. Removing the
  label is the human's, after working the plan; never remove it yourself.
- Close out leading with the outcome (PR URL + what landed), detail after.

Done when: the PR URL is reported.

## Stop conditions

A strike-out never halts mid-wave: drain the independent tickets (step 2.4), run step 3's
Verify, then stop before Review, the Verification plan, and the PR. A three-strikes
stop in step 3's or step 4's fix loop halts the same way: no PR, the plan's findings
reported. A semantic merge conflict surviving its one
resolver dispatch stops immediately instead — no further waves, no Verify; unmerged
tickets are reported and their dependants leave the work-set as in step 2.4. When
stopping, push the integration branch if it is ahead of origin, and report leading with
the outcome (what merged and what did not), then the detail: what failed (root cause +
WIP branch names), what was skipped as downstream, and that re-invoking resumes from step 0.
