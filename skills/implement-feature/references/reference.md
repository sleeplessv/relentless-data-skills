# Implement Feature — Reference

Per-dispatch contracts disclosed from [SKILL.md](../SKILL.md). A dispatch prompt cites a section by this file's absolute path plus the anchor; the subagent reads its section and executes it.

## Work-set resolution

Commands and evidence rules for the step 0 resolver dispatch.

- **Spec-only ticket listing** — scan bodies for a `## Parent` section referencing `#<spec>` (the reliable link — current `to-tickets` doesn't dependably create native sub-issues). The match must be anchored to the heading — a prose mention of `#<spec>` elsewhere in a body is not a link, and `gh search issues` cannot express this:
  `gh issue list --state open --limit 500 --json number,title,body --jq '[.[] | select((.body // "") | test("(?m)^(## Parent[^\n]*[\r\n]+[^#\n]*|Part of )#<spec>\\b"))]'`
  (the alternation also catches wayfinder's `Part of #<n>` fallback and CRLF bodies; `[^#\n]*` keeps `#90 supersedes #<spec>` out). Union in the native sub-issue results (`gh api repos/<owner>/<repo>/issues/<spec>/sub_issues --jq '.[].number'` — empty or 404 is normal), dedupe by number, keep open issues only.
- **Blocking edges** — for every work-set ticket, union the native dependency API (`gh api repos/<owner>/<repo>/issues/<n>/dependencies/blocked_by --jq '.[].number'`) with the body scan — the body scan is per-ticket, never skipped because the API returned edges elsewhere. Body-side extraction (accepts `## Blocked by` sections, inline `Blocked by #n`, and `Depends on #n`; anchored, so prose mentions don't count):
  `--jq '[ (.body//"") | scan("(?mi)^(?:##\\s*)?(?:Blocked by|Depends on)\\b[^\n]*(?:\n[ \t]*[-*][^\n]*)*") | scan("#[0-9]+") ]'`
- **Integration branch discovery** — probe origin with `git ls-remote origin 'feat/*'` for `feat/spec-<N>-*`, the legacy `feat/prd-<N>-*`, or the `feat/<slug>` a prior no-spec run named, then fetch just the branch found: the merged-evidence scan needs its history.
- **Merged evidence** (resume state, also reused by the Feature PR `Closes` scan) — a ticket is **merged** iff it carries a "merged into" comment naming the discovered branch (under any accepted name), or a commit on `<default>..<integration branch>` matches `#<N>\b`, `ticket-<N>\b`, or the legacy `issue-<N>\b` in a closing or subject position (`closes/fixes #<N>`, a `ticket-<N>` branch slug; a bare mention like `revert #<N>` or `see #<N>` is not evidence — report it and ask). Also collect any pushed `feat/ticket-<N>-*` (or legacy `feat/issue-<N>-*`) WIP branch.

## Wave integration

Contract for the step 2 integrate dispatch. On escalation the resolver dispatch inherits these duties for what it merges.

- Merge the wave's `status: success` branches into the integration branch in ascending ticket number; mechanical conflicts resolved in place, semantic ones escalated to one resolver dispatch, per orchestrator-mode. If the resolver also fails, `git merge --abort` so the main tree sits clean at the last pushed tip, then stop per SKILL.md's Stop conditions.
- Push the integration branch; **only after the push succeeds**, comment "merged into `<integration branch>`" on each merged ticket — including this wave's `already_satisfied` ones.
- Cleanup: remove every wave worktree, returned as `worktree_path` or not (failed ones too — their WIP is pushed); any branch the harness auto-created per worktree (identify via `git worktree list --porcelain`; delete nothing not found that way); and the merged branches.
- Return contract: `merged_tickets`, `conflicts_found`, `worktrees_cleaned`, `integration_tip`.

## Integration review

The step 3 Review dispatch prompt carries the step-0 spec body verbatim. The subagent writes it to a scratch file **outside the repo tree** (the session scratchpad), passes that path as the spec source, and deletes it after — this overrides code-review's own spec search, which would otherwise follow commit refs to the *tickets* instead of the spec; it must not ask the user.

## Verification plan

Authoring contract for the step 4 dispatch.

- **Structure**: an **Environment** block up top (where to run it — the same environment the gates used — and estimated time), then per-scenario: **Goal** (which acceptance criterion), **Preconditions/setup**, **Steps** (copy-paste-ready commands/queries, one action each), **What you should see**, **Cleanup** when steps mutate anything.
- **Traceability**: scenarios cover the spec's acceptance criteria first, plus any ticket criterion not subsumed by them; a criterion with no human-facing surface is listed as "verified by automated tests only, because <reason>" instead of getting a scenario.
- **Not a test run**: expected results orient the human's judgement ("you should see ~1,200 rows, `order_total` populated from 2024 on"), never assert pass/fail — acceptance is the human's call.
- **Execute before publishing**: run every command/query in the plan against that environment; the observed output becomes the what-you-should-see text. A step the run's environment cannot reach is still authored, flagged "not executed, requires <env>", and named in the Environment block.
- **Waiver**: nothing to walk through (docs-only, config tweak) → the one-line form "No human verification beyond code review: <reason>" — never a silently missing section.

## Feature PR

Body contract for the step 5 dispatch.

- **`Closes` evidence scan**: scan every ticket from any run's work-set plus every open ticket of the spec (re-run the work-set resolution ticket scan above) and include a `Closes #<n>` line for each one covered by the merged-evidence rule (a "merged into" comment, or a closing/subject-position commit ref) — whichever run or human put it there. Add `Closes #<spec>` only when every open ticket of the spec is covered; otherwise comment progress on the spec.
- **Size the body to the change**: a line per ticket in the Summary, what actually ran in the Test plan, no filler sections and no restated ticket bodies.
- A prior run's feature PR gets its body updated in place: replace the old Verification plan section, never append a second one.
- **Labels**: apply `awaiting-verification` to the spec, or to each work-set ticket when the run has no spec (`gh label create` it first if the repo lacks it) — unless the plan is a waiver, when there is nothing to verify.
