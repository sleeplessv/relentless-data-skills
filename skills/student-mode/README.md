# student-mode

Put the agent into **student mode**: every piece of code it writes for the rest of the
session is tutorial-grade, the shape a textbook shows when a topic is first introduced.
One file, plain variables, the library the tutorial would use, a function only when lines
repeat, a class only when the language forces one. The code still runs and produces the
result; it just drops the production habits (error hierarchies, abstraction layers, type
hints, scaffolding, tests, logging) that bury the idea a learner is trying to see.

Turn it on with "student mode", "keep it simple", "tutorial style", or "no production
code". It stays on until the user says "normal mode". Covers Python, SQL, and Java with a
before/after example for each. The full rules live in [SKILL.md](SKILL.md).

For a course, add one line to the course repo's `CLAUDE.md` so every session starts in it:

```text
Start every session in student mode (see the student-mode skill).
```

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/student-mode
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install student-mode@relentless-data-skills
```

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`. Behaviour scenarios
live in [tests/student-mode-scenarios.md](../../tests/student-mode-scenarios.md).
