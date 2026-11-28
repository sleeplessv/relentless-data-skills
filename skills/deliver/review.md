# Review a change

`ready` refused `ready.needs-review` and named the reviews this change needs. `deliver.py` is the
program the skill names. Follow these steps, then go back to the skill.

1. Load the `router` skill and route each reviewer as an agent of this session, on a model from this
   harness's own vendor, never through Herdr: the requirements reviewer on class `standard`, the
   defect reviewer on class `strong`, both at effort `high`.
2. Run `deliver.py brief requirements --model <id>`. Unless the refusal named the requirements review
   alone, also run `deliver.py brief defect --model <id>`. Each `<id>` is that reviewer's routed
   model, or `session` where the harness takes no model for an agent.
3. In one step, start `deliver:deliver-requirements-reviewer` and, when you briefed it,
   `deliver:deliver-defect-reviewer`, each on its model with the line its `brief` printed as its
   whole prompt. Wait for each to finish.
4. For each reviewer, write its final message word for word into `.deliver/review.md`, then run
   `deliver.py save review <role>`, where the role is `requirements` or `defect`.
5. For each finding, do what `save` printed: fix it, run
   `deliver.py settle F<n> --check <command>` or `deliver.py settle F<n> --unsettled`, or run
   `deliver.py follow-up F<n>`.

   After your fixes, commit with `git commit -m "<message>"`, run every check as
   `deliver.py check -- <command>`, then run `deliver.py pr`. For each reviewer whose finding you
   fixed, run `deliver.py brief callback <role>`. Start a fresh agent of that role on its review's
   model, with the printed line as its whole prompt, never a resumed one. Write its final message
   word for word into `.deliver/callback.md`, run `deliver.py save callback <role>`, and do what it printed.
6. Run `deliver.py ready`, then the rest of the skill's step 8.
