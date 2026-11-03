# Session ticket

Read only when the argument is `session`. The main thread works this file itself, before loading
`orchestrator-mode`: workers never see the conversation. Solo only; a feature dispatch supplies
a ticket number. The result is an ordinary ticket, so the run continues at step 1 with its number.

## Draft

Read the whole conversation and draft the ticket it asks for. Use `to-tickets`' issue template
(`## What to build`, `## Acceptance criteria`) plus two sections of its own:

- `## Decisions`: choices the user settled in the conversation (an interface shape, a storage
  choice, a name). Step 1 saves them under `## Requirements`, so review enforces them. A choice
  the user left open stays out; the implementer records its own under `## Author decisions`.
- `## Context`: file names, snippets, and pointers that help the implementer. Step 1 saves them
  under `## Context only`, so review reads them for interpretation and never as work.

Criteria describe behaviour the user can observe and a verifier can check. A subjective or
unverifiable criterion ("looks right", "feels fast") is settled with the user here, since the user
is present; step 5's stop condition exists for criteria that reach the run unexamined. A
criterion tied to a reference artifact (mockup, screenshot, spec doc) is specified and stays.
Keep file paths out of criteria; the `to-tickets` prototype-snippet exception applies.

Size the work before the gate:

- One deliverable: one draft.
- Several deliverables that are independent of each other: one draft each. The gate asks which
  one runs now.
- Deliverables that depend on each other (one cannot land before another): the work is a
  feature. Stop at the gate and name the route: `/to-spec`, then `/to-tickets`, then
  `/implement-feature <spec#>`.
- Nothing to draft: stop and ask what to implement.

## Gate

Show the user, in one message, and wait for one confirmation. Nothing external happens before
the yes. A correction revises the draft and shows it again.

- The title and the full body.
- The uncommitted files in the checkout (`git status --porcelain`), with the question whether
  they are part of this work. Their answer settles step 3's uncommitted-inputs question for
  these files.
- For several independent drafts: which one runs now, and whether to file the others as
  `needs-triage` issues. A no leaves them unfiled, noted in the run record.

## File

From the repository's main checkout:

```bash
gh issue create --title "<title>" --body-file <body-file> --label ready-for-agent --assignee @me
```

Record the number as `<N>` and that this run added the assignment, so the stop path releases it.
File each other chosen draft with `--label needs-triage` and no assignee, and report the numbers.
Then continue at step 1 with `<N>`.

## Session inputs

When the user keeps the uncommitted files: save `git diff --binary HEAD -- <tracked files>` as
`session-inputs.patch` in the run directory and copy each untracked file to
`session-inputs/<path>` there. Create `ticket-snapshot.md` in the run directory with a
`## Session inputs` section listing the files and both locations; step 1 adds `## Requirements`.
The checkout stays as it is.

The implementing worker applies the patch (`git apply --3way`) and copies the untracked files
into the worktree as the first commit of step 5, before any other edit, after step 4's baseline
has run on the clean `base_sha`. The before observation for the PR's Evidence is the pinned base;
that first commit is the starting point, not the delivered behaviour.
