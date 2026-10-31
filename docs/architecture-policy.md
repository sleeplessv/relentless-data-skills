# Architecture policy

Read by `candidate-to-spec` designers and reviewers before any design decision. Edit by hand at
any time; the next run reads the current file.

- **Dependencies**: No new library or service: only the standard library and what the project already depends on.
- **Off-limits areas**: None.
- **Size of one refactor**: One module and the code that calls it. A change that touches many call sites stays in one spec and lands in stages: add the new form, move callers, remove the old form.
- **Tests**: Where the existing tests already exercise the behaviour; tests on shallow modules that the deepened interface's tests replace are deleted in the contract phase. A new test entry point only when no existing one covers it.
- **Behaviour**: unchanged by default; a change is an open question for the user.
- **Notes**: Nothing.
