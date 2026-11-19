# Orchestrator reference

Read the section the current dispatch needs.

- [Model classes](#model-classes): which class of model each kind of worker runs on, and
  when a task moves up a class.
- [Harness notes](#harness-notes): limits and defaults the tool schemas omit, by harness.
- [Decision list](#decision-list): where the run's decisions live and how entries are
  written.
- [Nesting sub-orchestrators](#nesting-sub-orchestrators): when and how a subtree gets its
  own coordinator.
- [Parallel writes worktrees](#parallel-writes-worktrees): isolation, integration, and
  cleanup for parallel writers.
- [Promotion checks](#promotion-checks): which checks a promotion requires, who runs them,
  and what must pass before it goes ahead.
- [Worked example](#worked-example): a refactor from search through verification.

## Model classes

A **class** is a level of model capability, named by an alias that follows the level's newest
version. Pass the alias that this harness's subsection of [Harness notes](#harness-notes)
gives, and an exact model id only where that subsection says the harness has no alias.

- **Session class**: the model this coordinator runs on, which for a nested coordinator is
  its own model. The coordinator stays on it, and no worker runs on a class above it.
- **Strong class**: work that turns on judgement, such as writing or changing code, a
  design, a review, an integration, or a fix.
- **Standard class**: work a recorded procedure settles, such as rerunning recorded
  commands, locating files, and tracker or git housekeeping.

A model the user names wins, then a consumer skill's assignment, then this section. A worker
whose class is the session's, or would be above it, gets no model, and so does a fork. A
worker with no model runs on its spawner's, unless a worker definition or a harness default
sets another. Where that subsection ranks model families and the session's model is in none
of them, or an exact id is needed and the harness has shown no model list to take it from,
no worker gets a model. A resumed worker keeps the model it started on.

**Class escalation.** A task fails its check when a verifier, a re-check, or a rerun of its
checks reports its done-when unmet; the worker that reports the failure has not failed. After
a failure on the standard class, the next attempt goes to a fresh strong-class worker. After
a second failure on the strong class, it goes to a fresh worker on the session class, where
that is higher. Every attempt counts toward Collect's three, which still ends the dispatch,
and the decision list records each move with the failed check. A worker that is stuck
returns the obstacle and what it tried in `open_questions`; the coordinator answers from
what it holds and resumes it.

## Harness notes

Facts the tool schemas leave out, checked against vendor docs and source in November 2026.
The named settings are the durable handle; check them when a number matters. Read the
general notes, then the subsection for the harness this session runs in.

- **Project rules.** When a harness's subsection says a worker skips project instructions,
  or says nothing about them, that worker's handoff carries the project rules it needs.
- **Scripted fan-out.** When a scripted multi-agent workflow tool is exposed and its own
  opt-in rules are met, use it for a wide, uniform fan-out such as one check across many
  files; dispatch directly when each step depends on the last.

### Claude Code

- **Questions.** Only a fork can ask; other workers lose `AskUserQuestion`.
- **Limits.** Up to 20 workers run at once (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`);
  resuming a finished worker takes a slot without checking the limit, so resumes can push
  the count past it. Workers nest 3 layers below the main thread
  (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`), and a fork cannot start another fork.
- **Model and effort.** The per-call `model` takes an alias: `fable`, `opus`, `sonnet`,
  `haiku`, highest first. Strong class is `opus` and
  standard class is `sonnet`. On a third-party provider an alias can resolve to an older
  version. The model comes from the per-call `model`, then the definition's
  `model`, then `CLAUDE_CODE_SUBAGENT_MODEL`, then the spawner's model.
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` ignores definition models and refuses per-call ones;
  `CLAUDE_CODE_EFFORT_LEVEL` overrides a per-call `effort`. A fork keeps the main thread's
  model and effort, so a task that needs another gets a clean worker.
- **Worktrees.** Native isolation starts from `origin/<default>` while `worktree.baseRef` is
  `fresh` (the default), and from local HEAD when it is `head` or no remote is configured.
- **Completion.** Workers the main thread spawns run in the background and report through
  completion notifications. By default a worker gets its own workers' results before it
  finishes; with fork mode off (`CLAUDE_CODE_FORK_SUBAGENT=0`) in `claude -p` or the Agent
  SDK, they run in the background and report to the main thread if they outlast it.
- **Resume, instructions and skills.** Built-in Explore and Plan workers cannot be resumed.
  They skip CLAUDE.md and AGENTS.md, and so does a worker whose definition sets
  `omitClaudeMd: true`; other workers load them. A worker the user stopped refuses
  messages, and background workers keep the `Skill` tool.
- **Scripted fan-out.** Workers other than forks never get the `Workflow` tool. A workflow
  runs up to 16 agents at once by default, fewer on machines with fewer CPUs
  (`CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS`, 1 to 256), apart from the 20-worker cap.

### Codex

Codex has two multi-agent versions, V1 and V2 (its source's names). It runs V2 on most
current models, and on any model when `features.multi_agent_v2` is set; otherwise V1. A
session is in V2 when `spawn_agent` requires `task_name` and takes `fork_turns`. The V2
keys come from Codex's source, because its docs omit them.

- **Questions.** `request_user_input` works only on the main thread.
- **Limits.** V2 allows 4 open threads, the main thread included, so 3 workers
  (`features.multi_agent_v2.max_concurrent_threads_per_session`); it unloads finished idle
  workers to make room, so the limit binds on running ones.
  `agents.max_concurrent_threads_per_session` counts workers only: V1's limit, default 6.
  When V2's own key is unset and this one is set, V2 allows this value plus 1. V1 nests 1
  layer (`agents.max_depth`); V2 sets no depth limit, but a nested worker can spawn only if
  its own model's catalog entry is V2.
- **Forks.** A V2 spawn inherits the whole conversation unless `fork_turns` is `"none"`
  (default `all`), so set `fork_turns: "none"` on every spawn that is not meant as a fork
  or that sets a model or effort; a V1 spawn starts clean unless `fork_context` is true.
- **Permission.** Below Ultra effort, Codex is instructed to spawn only when the user,
  AGENTS.md, or a skill explicitly asks for subagents, delegation, or parallel work; V1's
  spawn tool adds that a request for depth or thoroughness does not count. Activating this
  skill is that permission; say so in the dispatch.
- **Model and effort.** Workers inherit their spawner's model and effort unless the spawn
  sets them; `agents.default_subagent_model` and `agents.default_subagent_reasoning_effort`
  set the defaults, and a V2 full-history fork rejects both overrides. A custom agent
  file's model wins over the spawn's, and
  `features.multi_agent_v2.expose_spawn_agent_model_overrides` set to false removes both
  spawn parameters. No alias exists: the spawn takes an exact catalog id, and an unknown id
  fails with a list of the available ones. The families are Astra, Sol, Terra, and Luna,
  highest first. Strong class is the newest Sol id and standard class the newest Terra id.
- **Worktrees.** No native isolation: all workers share one working directory.
- **Completion and resume.** V2 delivers a worker's final answer to its spawner
  automatically; `wait_agent` reports only which workers have updates. `followup_task`
  starts a new turn on an idle worker; `send_message` delivers without starting one.
- **Project instructions and skills.** Workers inherit their spawner's AGENTS.md and skills.

### Cursor

- **Questions.** A custom worker can ask when its definition tells it to use the
  ask-question tool.
- **Limits.** No concurrency cap is documented; depth is 2, so a grandchild cannot spawn.
- **Model.** The worker definition's `model` field, or `inherit`; the spawner can also name
  a model at launch. Both take an exact id, and no alias exists. Families rank as the Claude
  Code and Codex subsections give them. Within the session model's vendor, strong class is
  the newest Opus or Sol id and standard class the newest Sonnet or Terra id. Team restrictions, plan limits, and the legacy Max Mode
  setting make Cursor fall back to another model without an error.
- **Worktrees.** Isolation is opt-in, as a local worktree or a cloud VM, from an
  undocumented base.
- **Completion and resume.** A background worker writes its output to files under
  `~/.cursor/subagents/`, which its spawner reads. A finished worker resumes by its ID.

### Cortex Code

- **Questions.** The tools page describes `RunSubagent` (the changelog's `task` tool) as
  launching "an autonomous subagent", which never blocks for questions; the docs name no
  setting for a non-autonomous one.
- **Limits.** Up to 50 background workers run at once, with no setting documented; a
  background worker cannot spawn background workers.
- **Model.** The worker definition's `model` field, or `inherit`; the spawn call accepts
  `model: "inherit"`, and no other spawn value is documented. A definition sets the class:
  `auto-intelligent` for strong and `auto-efficient` for standard, which the account's
  configuration maps to models. Without such a definition, or in a session that itself runs
  on `auto-efficient`, leave the model unset.
- **Worktrees.** A worker is isolated when the spawn prompt asks for a worktree, on branch
  `agent/<agentId>`. `--worktree-base` sets its base (changelog 1.2.14); where the flag
  goes and the default base are undocumented.
- **Completion and resume.** The spawner fetches a worker's output, or resumes a killed
  worker, by its ID.

## Decision list

The coordinator's context is lost at compaction; the decision list is a file, so decisions
survive it and reach workers by path. A lookup or a single wave carries its decisions in
the handoff. Standing mode and any run of more than one wave keep the list in
`decisions.md` in the run directory, or in the file a consumer skill names.

- Append each decision as it is made: the date, the decision, its reason, and its source
  (the user, the coordinator, or a worker's `decisions_made`).
- A reversal is a new entry that names the entry it supersedes. Earlier entries stay as
  written, so a worker briefed on one can be traced.
- An entry about code cites the commit it held at.

## Nesting sub-orchestrators

Prefer flat dispatches. A sub-orchestrator earns its slot when it can own an independent
subtree and return decisions and evidence without sending its internal reports to the root.
Pass the scope, artifact paths, return contract, and allocated depth and slot budget. Decrement
that budget for descendants and respect any stricter runtime limit.

Reserve capacity for workers before spawning coordinators. With four total slots, a root,
a verifier, and a reviewer that needs two children cannot all run together. Finish the
verifier first, then run the reviewer and its two children, or flatten the review axes into
root-owned workers. A coordinator at its depth limit executes as a leaf only when that
fallback is authorized; otherwise it returns the missing capability for the parent to flatten.

Designate a coordinator with a general worker; read-only search agents cannot dispatch.
Open its handoff with "Load the orchestrator-mode skill and coordinate this scope". Where
workers cannot load skills, paste this skill's SKILL.md into the handoff instead. The
coordinator returns its verification evidence with its other return fields. At Verify, a
parent coordinator verifies the seams between its children and reuses their evidence for
the parts they own.

## Parallel writes worktrees

1. **Prepare.** A setup worker records git status, intended base SHA, branch conventions,
   and existing worktrees. Preserve unrelated dirty files. Isolate work that does not need
   them; if required uncommitted inputs or overlapping edits have ambiguous ownership,
   surface that specific decision before touching them. Serialization alone does not resolve
   an overlapping dirty file. No automatic stash, commit, reset, or checkout of user changes.
2. **Create.** Use native isolation if exposed, or have a worker run
   `git worktree add -b <task-branch> <absolute-writable-path> <base_sha>`.
   Choose a permitted path rather than assuming a sibling directory is writable. Honor the
   environment's branch prefix. Confirm the writer's initial HEAD equals the intended SHA.
   Record exact created paths and branches, including any native initial branch, with ownership
   evidence. Native isolation may start at a different base; cut the working branch from the
   supplied SHA before editing. Allocate ports, databases, and output paths separately, or
   serialize operations using shared external state.
3. **Return.** Each writer reports `branch`, `base_sha`, `head_sha`, `worktree_path`,
   `initial_branch`, task-created resources, dirty status, verification evidence, and any
   push outcome with the remote SHA. A failed push is local WIP, not preserved remote WIP.
4. **Integrate and verify.** One worker checks returned SHAs against the pinned base and
   merges only successful work. Resolve conflicts with both writers' intent available.
   Preserve the pre-merge tip and report actual state on failure. Aborting a merge may leave
   earlier successful merges intact; do not claim it restored the last pushed tip. A separate
   worker verifies any conflict resolution. Repeat fix then verification before releasing
   dependants or cleaning up.
5. **Clean up.** Remove only resources explicitly recorded as task-created and still in their
   expected state. Check worktrees for uncommitted and untracked work first. Retain failed WIP
   unless every change is durably preserved and removing its checkout is authorized. Before
   deleting a local or remote branch, prove its current tip is included in the verified,
   preserved integration history; unique WIP remains even if its behavior was superseded.
   Recheck the remote tip immediately before deletion and use an expected-tip lease where
   supported. Branch names, absence of an origin counterpart, and matching base tips do not
   prove ownership. Report retained resources and cleanup failures with paths. For merged
   PRs, a branch-cleanup skill such as `cleanup-merged-branches`, when installed, can run
   this step.

## Promotion checks

A **promotion** moves one version of the work (a commit, a build, or a package version) to
its next stage, such as a release branch, a test deployment, or production. Its
**promotion checks** are the checks that the user, the project's release process, or a
consumer skill requires before that move. Each one names the place it must pass, such as a
database, a workspace, a CI runner, or a live deployment.

1. **List.** Take the promotion checks from those three sources and put them in the plan,
   each with its place. When no source names one, confirm with the user that the promotion
   needs none.
2. **Assign.** Give each promotion check to a worker that can run it in that place, with
   the access and tools the check needs there. The handoff names the check, the place, and
   the version. Report a check that no worker can run there as blocked.
3. **Return.** The worker's `verification_evidence` gives the check, the place it ran, the
   version it ran on (a commit SHA or version id), the command, and its exit code or output.
4. **Gate.** Promote once every listed check has a passing result from its place for the
   version being promoted. A failing, pending, or missing result holds the promotion, and so
   does a result from another place or for another version. A failure goes back to the
   writer as Verify describes, and the fixed version runs every promotion check again.

## Worked example

For a refactor of `foo()` across several files, choose a run directory, then dispatch two
read-only search workers in one message. One lists callers of `foo()` as `file:line`; the
other lists configuration that sets the related timeouts. Each writes its findings to the
run directory and returns a short index. Send one writer the quoted index entries, the
agreed scope, and the decisions so far. A separate verifier runs the affected tests and
reviews the diff. A failing check goes back to the writer, resumed once with the
verifier's report, then to a fresh verifier. If that fix fails too, a fresh writer gets
the report, the diff, and the first writer's `decisions_made`. A single-file change keeps
the same evidence, but its writer's diff and test output can stand as the verification.
