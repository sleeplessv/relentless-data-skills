---
name: astra-review
description: Get a ponytail review of a change from Astra (the Codex CLI on an Astra model) in a Herdr tab, then fix the findings that hold up. Use when the user asks for an Astra review, or to send work to Astra for review.
argument-hint: "[what to review]"
---

# Astra review

Astra is the Codex CLI on an Astra model. It reviews the change with
`ponytail-review` in a Herdr tab beside yours. You check its findings against
the code, fix the ones that hold, and report the rest.

## 1. Fix the scope

Review what the user names: a PR, a branch, a commit, files. With nothing
named, review the work this session produced. With neither, review the
uncommitted changes, or the last commit when there are none.

The scope is a checkout folder, `DIR`, plus the commands that print the
change there, such as `git diff <base>...HEAD`. Astra reads the code around
the diff in `DIR` and you fix it there, so `DIR` has the change's head commit
checked out. A PR or branch that is checked out nowhere gets its own git
worktree first. Uncommitted work is `git diff HEAD` plus
`git status --short`: untracked files are in the second and absent from the
first.

Done when `git -C "$DIR" rev-parse HEAD` prints the change's head commit and
the commands, run in `DIR`, print the change.

## 2. Resolve Astra and the review skill

```sh
CATALOG=$(codex debug models) || echo "codex debug models failed: $?"
MODEL=$(printf '%s' "$CATALOG" | jq -r '[.models[] | select(.visibility == "list" and (.slug | endswith("-astra")))] | sort_by(.priority) | .[0].slug // empty')
REVIEW=$(find -L ~/.agents/skills ~/.claude/skills ~/.codex/skills -maxdepth 2 -path '*/ponytail-review/SKILL.md' 2>/dev/null | head -n 1)
```

- `CATALOG` is Codex's model list. Read `MODEL` only after
  `codex debug models` exits 0. A non-zero exit means Codex is missing or
  could not read its catalog: show the user its error.
- `MODEL` is the newest Astra model in the catalog (`gpt-6.2-astra`). Empty
  after a successful catalog read means this account lists no Astra model.
  Without `jq`, read `CATALOG` yourself: the `slug` ending `-astra` with
  `visibility` `list` and the lowest `priority`.
- `REVIEW` is the installed `ponytail-review` skill file. The `find` line
  exits 0 whether or not it finds one, so go by the value. Empty means it is
  not in those folders: use the path where it is installed, or tell the user
  to install it (`npx skills add DietrichGebert/ponytail -g -y`).

Any of the three missing: tell the user which, and stop.

Done when `MODEL` holds a slug and `REVIEW` names a readable file.

## 3. Hand the review to Astra

```sh
SNAP=$({ git -C "$DIR" rev-parse HEAD; git -C "$DIR" status --porcelain; git -C "$DIR" diff HEAD; } | git hash-object --stdin)
RESULT="$(mktemp -d)/astra-review.md"
```

`SNAP` is a fingerprint of the checkout before Astra starts; step 4 takes it
again. `RESULT` sits in a folder of its own, so no other run can write it.

Follow the `herdr-delegate` skill up to and including its wait for the
report, with these inputs:

- **Name**: `astra-review`, with a suffix when a live terminal has that name.
- **Program**: `codex --no-daemon -m "$MODEL" "$BRIEF"`, started in `DIR`.
- **Result file**: `RESULT`.
- **Brief**: the four parts `herdr-delegate` asks for, where the scope is
  `DIR` and step 1's commands, read-only (no edits, commits or pushes), plus:
  - `Read and follow $REVIEW`, with the path expanded.
  - What the change is for, in a sentence or two, and where its spec or
    ticket is. Keep your own opinion of the change out: the review is worth
    having because it starts from the code.
  - `Read the repo's agent instructions (AGENTS.md, CLAUDE.md) first.`

An Astra review needs Herdr and `herdr-delegate`. Where `herdr-delegate`
is not installed, or it finds you outside Herdr, tell the user and stop: a
review by one of your own subagents is not an Astra review.

Done when Astra's `DONE` report naming `RESULT` has arrived.

## 4. Give every finding a disposition

Run the `SNAP` command again. The review was read-only, so a different
value means the checkout changed under it: show the user
`git -C "$DIR" status --short` and ask before you edit anything.

Read `RESULT` and check each finding against the code, as
`herdr-delegate`'s collect step says. Then give each numbered finding the
first disposition that applies:

| Disposition | When |
|---|---|
| **Decline** | It does not hold, or its fix costs more than the problem it removes. Give the reason in one line |
| **Ask** | The fix is the user's call: it changes behaviour they chose, or reaches outside the reviewed change |
| **Fix** | Every other finding |

Done when every numbered finding in `RESULT` has one disposition.

## 5. Fix and prove

Make each **Fix** in `DIR`, as the smallest change that removes the problem.
Then run the checks the project names (its `AGENTS.md` or README) there.
Commit or push only when the user asked for that.

Done when those checks pass, or their failing output is in your report.

## 6. Report and close

Tell the user, in this order:

1. Astra's verdict line.
2. Each finding by number and title, with its disposition: what changed for
   a **Fix**, the reason for a **Decline**.
3. Each **Ask** as a question the user can answer in a word.
4. The checks you ran and how they ended.

Then close the helper as `herdr-delegate`'s clean-up step says. Keep it
open when an **Ask** may send a question back to Astra.
