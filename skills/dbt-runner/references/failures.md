# dbt failure signatures — causes ranked by prior, then the fix

Keyed by the **verbatim string to grep for in the logfile**. Within each
entry, causes are ordered by how often they're the real culprit — check
them in order and stop at the first hit. Engine-agnostic; for
`engine: fusion` projects also see [fusion.md](fusion.md).

## `Env var required but not provided`

dbt fails at **parse time** — it never reached the warehouse.

1. The env var named in the message is unset/empty in *this shell*. New
   shells and subagents don't inherit a sourced `.env`. Fix: source the
   project `.env` / export the var; re-run the preflight to catch the rest
   in one pass.

## `JWT token is invalid` · `Could not deserialize key data` · key file errors

Key-pair auth failed. In order:

1. **Wrong passphrase** for the encrypted `.p8` — the passphrase env var is
   set but stale. Fix: user updates it; never ask for or print the value.
2. **Key path wrong** — file moved/missing. The preflight `key` check
   catches this; re-run it.
3. **Key not registered for this user/account** — `RSA_PUBLIC_KEY` on the
   Snowflake user doesn't match, or `SNOWFLAKE_USER`/account mismatch.
   Discriminate: 1–2 fail locally before any network call; 3 fails *after*
   connecting. Fix: user re-registers the public key.

## DNS / connection errors — `Could not connect`, `getaddrinfo`, `Failed to resolve`, TLS/certificate errors

1. **Sandboxed shell** — see SKILL.md invocation rule 1 (sandbox-first).
   Suspect and rule this out before debugging credentials, proxies, or
   account URLs.
2. Genuinely wrong account identifier/host — only after (1) is excluded.
   Discriminate with `--connect` (live `dbt debug`) outside the sandbox.

## `Object does not exist or not authorized`

Snowflake deliberately doesn't say which. In order:

1. **Upstream not built in your dev schema** — the ref'd model/source was
   never materialized in this target's schema. Fix: build upstream first
   (`dbt build --select +<model>`), or seed/stage before facts.
2. **Role lacks grants** — expired or insufficient on the source schema.
   Discriminate: can you `select 1 from <object>` via your SQL tool with
   the same role? Fix: grants, not dbt.
3. **Wrong target** — pointed at an environment where the object genuinely
   doesn't exist. Check the target line in dbt's startup output against
   the context file.

## Hang while acquiring a warehouse, or `is suspended` / resource-monitor errors

1. Warehouse suspended and the role lacks `OPERATE`/auto-resume — the run
   hangs, then fails. Fix: user resumes the warehouse or grants usage.
2. Resource monitor exhausted its credit quota — nothing runs until reset.
   Either way this is account-side: report it, don't retry in a loop.

## `dbt_utils` undefined · `is undefined` on a packaged macro · `generate_surrogate_key` not found

1. **`dbt deps` never ran** in this checkout — `dbt_packages/` missing.
   The preflight `packages` check catches this; run `dbt deps`.
2. **Stale/dirtied `package-lock.yml`** — versions drifted (subagents
   running `dbt deps` are a known offender). `git diff package-lock.yml`;
   revert unless intentional, then `dbt deps`.

## `No models available` · `Nothing to do`

**This exits 0 and looks like success while doing nothing.**

1. Typo'd `--select` — model name, selector syntax, or path. Fix: verify
   with `dbt ls --select <sel>` before re-running the build.
2. Selector excluded everything (tags/state filters). Same verification.

## Blank output from a piped dbt command

1. Pipe buffering — `dbt build | tail` can return nothing in a background
   shell. Never pipe; redirect: `> /tmp/dbt_run.log 2>&1`, then grep/tail
   the file. The command may have *run fine* — check the logfile and exit
   code before assuming failure.

## Command killed at the tool timeout

1. The build is just long (large facts, full refresh). Re-run in the
   background or with a raised timeout, redirecting to a logfile and
   polling it. Check the context file's Project lore for known-slow
   models. The partial run may have completed some models — dbt resumes
   fine; don't treat the kill as a model error.

## Non-zero exit but every model shows `OK created`

Not a build problem. Classify run-error vs test-failure vs warning from the
summary line — see SKILL.md "Reading the result". Triage notes for the
test-failure case specifically:

- `relationships` orphans usually mean build order (fact built before its
  dim/seed).
- `accepted_values` usually means a new raw value needs a seed row + an
  accepted-values entry.
