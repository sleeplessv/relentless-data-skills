# qualify-delegation

Turn a rough assignment into a handoff for a human colleague or contractor.
The agent uses available context, asks about material gaps, and offers constructive
recommendations with choices. It produces a short message or a structured brief,
depending on the task.

## Use

Ask the agent to qualify a delegation and provide your rough request:

> Use qualify-delegation to help me brief a colleague. Can they work out whether
> our UKG data in Snowflake covers the team leaders in the report? I imported
> that data manually, but I want it automated. Can they check what we already have?

The skill helps distinguish an investigation from permission to implement automation.
It clarifies which report matters, the evidence required, decision authority, and
relevant limits. Unknown data coverage belongs in the recipient's investigation.
The agent prepares the handoff; it does not send it or carry out the assignment.

## Install

Use the [repository installation instructions](../../README.md#install), or install
this skill directly:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/qualify-delegation
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install qualify-delegation@relentless-data-skills
```

## Maintenance

The workflow is self-contained in [SKILL.md](SKILL.md).
The repository keeps the [research](../../docs/research/delegation-qualification.md)
and [behavioral scenarios](../../tests/qualify-delegation-scenarios.md) for maintainers.
These files are not needed to use an installed copy.
