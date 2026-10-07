# student-mode

Puts the agent into student mode. Every piece of code it writes for the rest of the
session is tutorial-grade, the shape a textbook shows when a topic is first introduced.
The code is one file with plain variables and the library the tutorial would use. It has
a function only when lines repeat and a class only when the language forces one. The code
still runs and produces the result. It drops the production habits that hide the idea the
learner is studying, such as error hierarchies, abstraction layers, type hints, project
layouts, tests, and logging.

Turn it on by typing `/student-mode`. It is user-invoked only, so the agent never switches
into it on its own. It stays on until the user says "normal mode". It covers Python, SQL,
and Java with a before and after example for each. The full rules are in [SKILL.md](SKILL.md).

For a course, have students type `/student-mode` as the first message of each session.

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
