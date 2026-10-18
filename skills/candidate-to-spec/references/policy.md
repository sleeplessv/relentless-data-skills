# Policy bootstrap

Read when the target project has no `docs/architecture-policy.md`. The policy answers the taste
questions a designer cannot answer from the code, once per project instead of once per candidate.

Ask the user these five questions in one round, in plain English, each with its default in
brackets. Yes accepts the default.

1. **Dependencies**: may a refactor add a new library or service? [No: standard library and
   dependencies the project already has.]
2. **Off-limits areas**: which modules are under active change or frozen for a release, so a
   refactor must leave them alone for now? [None.]
3. **Size**: how large may one refactor PR be before it should become separate specs? [One
   deepened module and its callers. A wide refactor stays in one spec, sequenced expand–contract.]
4. **Tests**: where should tests sit? [At the highest existing seam. A new seam only when the
   decision log shows no existing seam covers the behaviour.]
5. **Anything else** a reviewer should know: conventions, deadlines, people to consult. [Nothing.]

Fixed and not asked: external behaviour does not change by default, and a behaviour change is an
escalation to the user.

On answers, a worker writes the file in the target project, uncommitted, and the report tells the
user to commit it. On "skip", write nothing, run with the defaults, and record them in each spec's
Further Notes.

```markdown
# Architecture policy

Read by `candidate-to-spec` designers and reviewers before any design decision. Edit by hand at
any time; the next run reads the current file.

- **Dependencies**: <answer>
- **Off-limits areas**: <answer>
- **Size of one refactor**: <answer>
- **Tests**: <answer>
- **Behaviour**: unchanged by default; a change is escalated to the user.
- **Notes**: <answer>
```
