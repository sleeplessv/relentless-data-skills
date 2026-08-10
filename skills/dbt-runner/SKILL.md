---
name: dbt-runner
description: Use when running any dbt command (build, run, test, compile, seed, deps) or debugging a dbt failure — connection and auth errors, parse errors, hanging or silently-empty runs, and dbt-fusion quirks. Enforces preflight checks and output-capture discipline before the first dbt invocation of a session, and maps error signatures to causes and fixes. Bootstraps a per-project .dbt-runner/context.md on first use.
---

# dbt-runner

Invocation discipline and failure triage for running dbt against a warehouse.
Half of all "dbt is broken" sessions are environment problems detectable
before the first command, and most of the rest are misread output — this
skill front-loads the former and catalogues the latter.

## First action, every invocation

Check for **`.dbt-runner/context.md`** in the dbt project root.

- **Absent** → first run. Read [references/install.md](references/install.md)
  and run the bootstrap (discovers profile, target, engine, required env
  vars → writes the context file). Then continue.
- **Present** → load it; it is the source of truth for this project's dbt
  setup (profile, target, engine, required env-var *names*, project lore).

The context file holds **names only, never secrets** — no env-var values,
no passphrases. It is committed to the project repo.

## Preflight — once per session, before the first dbt command

```bash
python3 <skill-dir>/scripts/preflight.py --project-root <dbt-project-root>
```

Static checks only (sandbox-safe, no network): required env vars set, the
private key file exists, `dbt_packages/` present with a clean
`package-lock.yml`, and the profile/target resolve in `profiles.yml`. One
line per check (`OK`/`FAIL`/`SKIP`), non-zero exit on any `FAIL` — fix every
`FAIL` before running dbt; each line says how. Don't re-run it before every
command; once per session is the contract, plus once more after any
environment change (new shell, edited `.env`, switched target).

## Invocation rules — every dbt command

1. **Invoke via the context file's `runner`, never bare `dbt`.** dbt-fusion
   ships as `dbt`, so PATH often resolves to a different engine than the one
   the project pins — a fusion binary on a core project hard-errors on
   deprecations and never reaches SQL compilation, which reads as "the project
   is broken". If the context file has no `runner`, derive it (`uv.lock` →
   `uv run dbt`, `poetry.lock` → `poetry run dbt`, `.venv/` →
   `.venv/bin/dbt`) and record it. Before trusting a parse-stage failure,
   confirm the engine with `<runner> --version`.
2. **Run outside the sandbox.** dbt needs network access to the warehouse.
   In a sandboxed shell it fails with DNS/connection errors that masquerade
   as auth problems. If you see a connection error, suspect the sandbox
   *first* — do not start debugging credentials.
3. **Never pipe dbt output — redirect to a logfile.** Piped output
   (`dbt build | tail`) can buffer and return blank. Always:
   ```bash
   <runner> build --select <sel> > /tmp/dbt_run.log 2>&1
   ```
   then grep/tail the logfile. Exit code first, log second.
4. **Long runs go to the background.** Full builds or large facts can
   exceed default tool timeouts. Run in the background (or raise the
   timeout) and poll the logfile. The context file's lore section lists
   known-slow models.
5. **Verify the selection matched.** After every run, confirm the log shows
   a non-zero model count. `No models available` / "Nothing to do" from a
   typo'd `--select` exits 0 and looks like success while doing nothing.
6. **Check the run was not vacuous.** A model whose spine is empty in the
   local environment builds 0 rows, and every data test on it passes
   trivially. `PASS=n ERROR=0` on an empty model proves it compiles, nothing
   more. When a model's source is populated outside dbt's DAG (ML scores,
   externally-loaded tables), count the rows before reporting success, and
   exercise the logic on synthetic rows via `<runner> show --inline`.

## Reading the result

`dbt build` exiting non-zero does **not** mean models failed to build.
Read the summary line — `PASS=… WARN=… ERROR=…` — and distinguish three
outcomes before reacting (this trichotomy is the authoritative reference;
failures.md points here):

- **Run error** — a model errored; its SQL or upstream is broken.
- **Test failure** — models built fine, a data test failed. Fix data or
  test, don't touch the build invocation.
- **Warning** — `severity: warn` tests print WARN and do *not* fail the
  run. Don't "fix" a warning as if it were a failure, and don't report a
  warned run as broken.

## When something fails

Fix the failure in front of you, at the scope it demands. Model refactors,
test additions, and cleanup the failure did not require get reported, not
performed. Work the escalation ladder below inline — it is greps and file
lookups, not subagent work.

Escalation ladder — in order, no skipping:

1. Grep the logfile for the error signature and look it up in
   [references/failures.md](references/failures.md) — entries are keyed by
   the verbatim string, with causes ranked by prior.
2. If the signature looks like connection/auth and the static preflight
   passes, run the live check:
   `python3 <skill-dir>/scripts/preflight.py --connect` (outside the
   sandbox).
3. If the context file says `engine: fusion`, also check
   [references/fusion.md](references/fusion.md) — fusion has failure modes
   with misleading error messages (unit-test fixture inference, blocked
   sibling tests).

Project-specific lore (seed/test couplings, known-slow models, schema
quirks) accumulates in the context file's **Project lore** section — append
a line or two when you learn something the hard way, not a writeup.

While a build runs, speak up only on a finding or a change of direction.
Report back leading with the outcome — what the run did, or what the root
cause was — then the supporting detail.
