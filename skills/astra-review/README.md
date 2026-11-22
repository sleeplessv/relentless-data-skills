# astra-review

Send a change to Astra for a second opinion and act on what comes back. Astra
is the Codex CLI on an Astra model. It runs a `ponytail-review` of the change
in a Herdr tab next to your agent. Your agent then checks each finding against
the code and fixes it by default. It declines a finding that does not hold,
with a reason, and asks you first when a fix is your call.

## Use

Inside a Herdr terminal, ask your agent:

> /astra-review

or name what to review:

> Send the last two commits to Astra for review.

With nothing named, the agent reviews the work the session produced, or the
uncommitted changes.

Requires:

- Herdr with herdr-core (`hc`), and the
  [`herdr-delegate`](../herdr-delegate/) skill `0.1.0` or later.
- The Codex CLI on `PATH`, signed in to an account that lists an Astra model
  (`codex debug models`).
- `approvals_reviewer = "auto_review"` in `~/.codex/config.toml`. Codex's
  sandbox holds Astra's closing `hc send` for approval; under the default
  reviewer, `user`, the review waits on you and never reports back.
- The `ponytail-review` skill from
  [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).
- `jq` is optional.

The agent commits or pushes its fixes only when you ask.

## Install

Use the [repository installation instructions](../../README.md#install), or install
this skill with the one it depends on:

```bash
npx skills add sleeplessv/relentless-data-skills -s astra-review -s herdr-delegate
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install astra-review@relentless-data-skills
/plugin install herdr-delegate@relentless-data-skills
```
