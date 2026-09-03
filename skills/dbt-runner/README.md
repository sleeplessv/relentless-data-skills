# dbt-runner

The **`dbt-runner`** agent skill: invocation discipline and failure triage
for running dbt against a warehouse. Built from a simple observation about
agent sessions: half of all "dbt is broken" time goes to environment
problems that were detectable *before* the first command, and most of the
rest goes to misreading output (a blank pipe, a silently-empty `--select`,
a `severity: warn` test reported as a failure).

## What it does

- **Per-project bootstrap (progressive disclosure).** On first invocation
  in a project there is no `.dbt-runner/context.md`, so the skill runs a
  discovery-first bootstrap: it reads `dbt_project.yml` and `profiles.yml`
  for the profile, target, and the `env_var()` *names* the connection
  needs, runs `dbt --version` to record the engine (fusion vs core), asks
  only the genuine decisions, and writes a committed context file. The
  instructions live in `references/install.md` and only load on that first
  run.
- **Per-project context, never global.** Everything project-specific lives
  in `.dbt-runner/context.md`, names only, no secrets, including a
  free-form *Project lore* section that accumulates hard-won knowledge
  (seed/test couplings, known-slow models) across sessions.
- **Static preflight, once per session.** `scripts/preflight.py` (stdlib
  Python, sandbox-safe, no network) verifies required env vars are set,
  the private key file exists, `dbt_packages/` is present with a clean
  `package-lock.yml`, and the profile/target resolve in `profiles.yml`.
  These are the failures that are cheapest to detect statically and most
  expensive to diagnose from a `JWT token is invalid` error. A `--connect`
  flag escalates to a live `dbt debug` when diagnosing.
- **Invocation rules.** Run outside the sandbox (egress-blocked shells
  produce connection errors that masquerade as auth failures), redirect
  output to a logfile instead of piping, background long builds, and
  verify the selection actually matched models.
- **Signature-indexed failure catalogue.** `references/failures.md` is
  keyed by the verbatim string in the log, with causes ranked by prior:
  a DNS error means *suspect the sandbox first*, not the credentials.
- **dbt-fusion quirks.** `references/fusion.md` (loaded only when the
  context says `engine: fusion`) covers the failure modes whose error
  messages point away from the cause: unit-test fixture schema inference
  throwing `invalid identifier`, and a failing unit test silently blocking
  its model's other tests.

## Layout

```
dbt-runner/
├── SKILL.md                  # rules + escalation ladder (always loaded)
├── references/
│   ├── install.md            # first-run bootstrap → .dbt-runner/context.md
│   ├── failures.md           # error-signature catalogue
│   └── fusion.md             # dbt-fusion-specific quirks
└── scripts/
    └── preflight.py          # static env checks; --connect for dbt debug
```

## Install

From the repo root, with the [skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add -g ./skills/dbt-runner
```

(`-g` installs user-level into `~/.claude/skills`; without it the skill
lands in the current project's `./.agents/skills`.)

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Stdlib only. The preflight never talks to a warehouse in tests; the
`--connect` path is exercised with the `dbt` binary stubbed.
