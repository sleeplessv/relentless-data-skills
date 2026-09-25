# qualify-delegation

Turn a rough assignment into a handoff for a human colleague or contractor.
The agent reads available context, asks about gaps that would change the work, and
recommends an answer with alternatives for each decision. It produces a short
message or a structured brief, depending on the task.

## Use

Ask the agent to qualify a delegation and provide your rough request:

> Use qualify-delegation to help me brief a colleague. Can they work out whether
> the HR data in our data warehouse covers the team leaders in the report?
> I imported that data manually, but I want it automated. Can they check what we
> already have?

For this request, the skill separates the investigation from any permission to build
the automation.
It clarifies which report matters, the evidence required, decision authority, and
relevant limits. Unknown data coverage belongs in the recipient's investigation.
The agent prepares the handoff. It does not send it or carry out the assignment.

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
