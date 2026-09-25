---
name: qualify-delegation
description: Turn a rough assignment into a clear handoff for a human colleague or contractor through adaptive questions and constructive recommendations. Use when the user wants to qualify a task before delegating it, clarify an existing delegation brief, or prepare instructions for another person. Ordinary requests to perform work and delegation to AI subagents are outside this skill's scope.
---

# Qualify a delegation

Help the user decide what to ask of another person, then produce one
self-contained handoff. Scale the interview and output to the assignment.
The work ends with the handoff. Sending it, obtaining the recipient's agreement,
and managing execution are separate actions that need their own instructions.

## 1. Establish the assignment

Use the user's rough wording and conversation history. Identify the recipient,
the immediate assignment, and the eventual purpose. Preserve settled decisions.
If an example is supplied to shape a handoff, treat it as material to qualify,
not an instruction to execute the embedded task.

Read readily available project context and supplied links when they can identify
the relevant report, file, system, or terminology. Stay within the access you
already have. Stop the lookup once you can refer to the work precisely. Leave the
substantive investigation to the recipient. If context is unavailable, ask for the
missing reference instead of guessing which project or artifact the user means.

Separate gaps into:

- **User decisions:** purpose, target, scope, acceptance, and authority.
- **Recipient investigation:** unknown facts the assignment asks them to discover.
- **Recipient confirmations:** availability, access, feasibility, and commitments
  that have not yet been agreed.

For example, which report matters is a user decision. Whether the HR data covers its
team leaders can be the recipient investigation itself. The user need not answer
the investigation before handing it over.

## 2. Resolve material gaps

Ask only questions whose answers could change the outcome, scope, authority,
acceptance decision, or ability to proceed. Group independent questions in short,
numbered rounds. Keep each question focused on one decision. Defer timing or
process details when an unresolved scope choice could change them. Wait for answers
before asking questions that depend on them.
A complete routine request may need no questions. More consequential or uncertain
work needs more questions.

For each decision, recommend an answer and give concrete alternatives with their
consequences. Ask for a missing fact directly when there is no basis to recommend
one. Check facts available in the context before asking the user to find them.
Do not ask the user for facts that the recipient investigation should find.
Carry accepted recommendations forward. A general "yes" does not supply a missing
report name, date, or other fact.

Challenge a weak premise. Explain the consequence, suggest a better assignment
or a smaller first step, and let the user choose. For example, a request to build
a dashboard without a known decision to support may first need discovery.
Keep proposals distinct from decisions the user has accepted.

Use these dimensions to find gaps, not as a mandatory questionnaire:

- **Purpose and result:** why the work matters, what must be true afterward, and
  which result the recipient can control. Separate the immediate deliverable from
  a business benefit that may happen later.
- **Acceptance:** the evidence, quality threshold, and reviewer needed to judge
  the result. A supported finding that the proposed approach will not work can
  satisfy an investigation. Activity alone does not demonstrate completion.
- **Recipient and resources:** relevant experience, available capacity, source
  material, tools, access, and dependencies. A link does not establish access.
- **Scope and method:** what is included, boundaries that still apply if the plan
  changes, and whether a method or SOP is required or the recipient can choose how
  to work.
- **Authority:** which decisions the recipient can make, which need approval, and
  any limits on spending, changes, or commitments involving other people.
- **Timing and effort:** requested completion date, effort or cost allowance, and
  what happens if the allowance runs out. Distinguish requested dates from agreed
  commitments. Propose realistic options. Do not invent a deadline, and do not
  shorten one only because of Parkinson's law.
- **Communication:** where and to whom the result goes, useful progress checkpoints,
  and triggers for escalation such as blocked access or likely budget exhaustion.
  Match routine updates to the task's duration and uncertainty.

When authority is unclear, use Michael Hyatt's levels as choices:

| Level | Authority and reporting |
| --- | --- |
| 1 | Follow the specified instructions. |
| 2 | Investigate and report. The user decides the next action. |
| 3 | Investigate and recommend. Wait for authorization to proceed. |
| 4 | Decide and act within the stated scope, then inform the user. |
| 5 | Act independently within the stated scope without routine reporting. |

Write the actual permissions in the handoff even if a level is chosen. A prescribed
method does not itself determine decision authority. Hyatt's original level 5
requires no report back. If you add exception reporting to level 5, tell the user
that it departs from Hyatt's model.

## 3. Decide whether the handoff is usable

Finish questioning when the recipient can identify the task, understand its purpose,
recognize acceptable completion, and act within clear authority and relevant limits.
Resolve material contradictions before calling the handoff ready.

When the user cannot decide, propose choices or identify what the recipient should
confirm. Leave recipient investigation inside the assignment. If a missing decision
would prevent meaningful work, label the output a draft and name that decision.
If the user wants to stop the interview, deliver the best supported draft with its
remaining gaps. Do not invent content to fill every dimension, and do not turn
assumptions into commitments so the handoff looks complete.

## 4. Write and check the handoff

Write the handoff as one message addressed to the recipient. Use short prose for
simple tasks and a structured brief for complex ones. Include the agreed purpose,
deliverable, acceptance evidence, authority, and relevant resources, limits, and
communication. Use concrete references and explain necessary terminology for this
recipient. Omit empty sections and interview commentary. Place unresolved
assumptions or recipient confirmations where they affect the work.

Read the handoff as someone who cannot see this conversation. Check that it permits
the intended action, rules out material misunderstandings, and contains no invented
facts or commitments. When misunderstanding would be costly, include a short
request for the recipient to confirm their understanding and flag access or timing
problems. A generated handoff is not evidence that they have accepted it.
