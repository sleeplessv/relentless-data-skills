# dbt-runner — bootstrap (first run in a project)

You are here because the project has **no `.dbt-runner/context.md`**. Your
job is to discover this project's dbt setup and write that file, so every
later invocation (and the preflight script) has a per-project source of
truth.

**Style: discovery-first.** Everything below is readable from files and
`dbt --version` — don't interrogate the user for things the repo can tell
you. Ask only the genuine decisions, one at a time, with a recommended
answer.

**Names only, never secrets.** The context file records env-var *names* and
file *paths*, never values. Never read or print the value of a credential
env var, the private key, or a passphrase during discovery.

## Step 1 — discover (no questions yet)

1. **Profile name** — `profile:` in `dbt_project.yml` at the project root.
2. **Profile config** — find that profile in `profiles.yml`
   (`$DBT_PROFILES_DIR/profiles.yml`, default `~/.dbt/profiles.yml`).
   Record:
   - the default `target:` and the list of `outputs:`;
   - every `env_var('NAME')` reference → the `required_env_vars` list
     (names only). Include vars with defaults only if dbt would fail
     without them;
   - if an output sets `private_key_path` from an env var → that var name
     is `private_key_path_var` (key-pair auth).
3. **Engine** — run `dbt --version` (sandbox-safe, no network). dbt-fusion
   identifies itself as `dbt-fusion <x.y.z>`; otherwise it's dbt-core.
   Record engine and version.
4. **Packages** — note whether `packages.yml` / `package-lock.yml` exist
   and whether `dbt_packages/` is populated (preflight checks this every
   session; just note the state).

## Step 2 — decisions (ask; recommend an answer each)

1. **Which target is the working target?** Recommend the profile's default
   `target:`. If several outputs exist (e.g. `local` dev vs `prd`), confirm
   the agent should always use the dev one — building against prod without
   grants fails late and noisily.
2. **Known-slow models?** Ask if any models are big enough that a build
   exceeds normal timeouts (row counts help). Goes into Project lore; fine
   to leave empty and let it accumulate.

## Step 3 — render, confirm, write

Compose `.dbt-runner/context.md` from the template, **show it to the
user**, get approval, then write it to the dbt project root. Safe to
commit — suggest the user commit it.

```markdown
---
profile: <profile-name>
target: <working-target>
engine: fusion              # fusion | core
engine_version: <x.y.z>
required_env_vars:
  - <VAR_NAME>
  - <VAR_NAME>
private_key_path_var: <VAR_NAME>   # omit if not key-pair auth
# profiles_path: <path>            # only if non-standard location
---

# dbt context for <project>

_Discovered by the dbt-runner bootstrap. Names only — no credentials.
Edit freely; re-run the bootstrap to refresh the frontmatter._

## Setup
- Profile `<profile>`, target `<target>` → <database>.<schema> on
  <warehouse> (names as found in profiles.yml — for orientation only).
- Auth: <key-pair via `<VAR>` | password | SSO>.

## Project lore
_Append entries as you learn them the hard way — seed/test couplings,
known-slow models, schema quirks. One or two lines each. Newest last._

- <e.g. fct_call is ~5M rows; full build needs a background run.>
- <e.g. adding a region means a seed row in region_config AND an
  accepted_values entry, or the seed/int tests fail.>
```

## Done

Confirm the file is written, run the preflight
(`python3 <skill-dir>/scripts/preflight.py`), then proceed with the user's
original request.
