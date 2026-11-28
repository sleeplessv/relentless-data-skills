---
name: deliver
description: Take a change from request to pull request through deliver.py, which runs preflight, saves the evidence and guards the merge.
disable-model-invocation: true
---

# Deliver

You are the author: you read, plan, edit, run the checks and open the PR yourself. The program is
`uv run --python 3.13 --no-project <this skill's folder>/scripts/deliver.py`, or `python3` 3.13 or
newer running that file when `uv` is missing; below it is `deliver.py`. Run every command as one plain
command, with no pipe, chain, variable or glob.

## The path

1. Start the run with one of:
   - `deliver.py start <ticket>` for a ticket;
   - `deliver.py start request` for a request in words, once you have written it to `.deliver/request.md`;
   - `deliver.py start` for the changes already in the tree;
   - `deliver.py start --resume` to resume a run.

   When the owner says `stop at ready`, add `--stop-at-ready` to a new run's `start`.
2. Run the probe step `start` prints; the guard refuses it, as it should. Then run the command `start`
   names next.
3. Write each text into `.deliver/`, then run `deliver.py save <kind>` for it:
   - `requirements.md`, when there is no ticket;
   - `plan.md`: a `| # | Requirement | Proof |` table with one row per requirement (`R1`, `R2`, ...)
     and the proof of each, your assumptions, and one line `door: two-way — <reason>` or
     `door: one-way — <reason>`.
4. Edit.
5. Commit with plain `git commit -m "<message>"`.
6. After the last commit, run every check, test runs included, as `deliver.py check -- <command>`.
7. Write `.deliver/summary.md` and run `deliver.py save summary`.
8. Run `deliver.py pr`, then `deliver.py ready`, then `deliver.py merge`.
9. Run `deliver.py finish`, however the run ended. It prints the state line.

## When a command does not go through

On exit 10 or 20, do what the output says; a question goes to the owner.

When the guard or the permission system refuses a command other than the probe, never retry it in
another form: finish what does not depend on it, run `deliver.py finish`, and stop, naming the exact
command refused.

## Reading

Start one `deliver:deliver-reader`, and give it the question, only for a search that would bring more
than about 1,000 tokens of mostly irrelevant material.

## The report

End with the state line `finish` printed. When something went wrong, add a lesson line under it:

```
Lesson: <what went wrong, in one sentence>. Seen in PR #<n>, <route>, <harness>.
```

A lesson says what went wrong, not a rule. Add `Possible run rule: <text>` as a second line only when
the cause is specific to this repo.
