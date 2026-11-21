# herdr-delegate

Have an agent running in the Herdr desktop app hand a task to another agent,
such as Codex reviewing Claude's change. The helper opens in the caller's own
Herdr space, whatever space the person is looking at, and sends its result back
as a message pointing at a findings file.

## Use

Inside a Herdr terminal, ask your agent:

> Get Codex to review the last commit and report back.

The agent finds its space from its own terminal's labels, starts Codex there as
a new tab, waits for the report, checks the findings, and closes the helper.

Requires Herdr with herdr-core (`hc`) and the helper agent's CLI on `PATH`.
`jq` is optional.

## Install

Use the [repository installation instructions](../../README.md#install), or install
this skill directly:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/herdr-delegate
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install herdr-delegate@relentless-data-skills
```
