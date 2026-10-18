# Policy bootstrap

Read when `<run>/setup.md` says the target project has no `docs/architecture-policy.md`. The
policy answers the taste questions a designer cannot answer from the code, once per project
instead of once per candidate.

Ask the user these five questions in one round, in plain English, each with its default in
brackets. "Yes" accepts the default, an unanswered question takes its default, and "skip" takes
every default.

1. **Dependencies**: may a refactor add a new library or service? [No: only the standard
   library and what the project already depends on.]
2. **Off-limits areas**: which modules are under active change or frozen for a release, so a
   refactor must leave them alone for now? [None.]
3. **Size**: how large may one refactor be before it should become separate specs? [One module
   and the code that calls it. A change that touches many call sites stays in one spec and lands
   in stages: add the new form, move callers, remove the old form.]
4. **Tests**: where should tests sit? [Where the existing tests already exercise the behaviour;
   tests on shallow modules that the deepened interface's tests replace are deleted in the
   contract phase. A new test entry point only when no existing one covers it.]
5. **Anything else** a reviewer should know: conventions, deadlines, people to consult. [Nothing.]

Fixed and not asked: external behaviour does not change by default, and a behaviour change is an
open question for the user.

The worker writes the file below in the target project, uncommitted, from the answers or the
defaults, so the next run reads it instead of asking. Before writing, it runs each command an
answer names (with `--version` or `--help`) and reports a command that fails back to the main
thread, which confirms the answer with the user. The run report tells the user to commit the
file.

```markdown
# Architecture policy

Read by `candidate-to-spec` designers and reviewers before any design decision. Edit by hand at
any time; the next run reads the current file.

- **Dependencies**: <answer>
- **Off-limits areas**: <answer>
- **Size of one refactor**: <answer>
- **Tests**: <answer>
- **Behaviour**: unchanged by default; a change is an open question for the user.
- **Notes**: <answer>
```
