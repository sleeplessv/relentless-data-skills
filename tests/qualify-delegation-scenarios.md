# Qualify-delegation behavioral scenarios

Run each scenario in a fresh conversation with `skills/qualify-delegation/SKILL.md`.
Give the agent only the prompt and supplied context. Assess its actual questions
or handoff against the observable outcomes below. These are behavioral checks,
not assertions about exact wording. They require no live services or messages.

## UKG investigation

Prompt:

> Help me brief a colleague. Can they work out if our UKG data in Snowflake covers
> the team leaders in the report? I imported that data manually, but I want it
> fully automated. Can they check what is already available that we can use?

Supplied context: no project files or tools are available.

Observe whether the agent asks for the report reference, proposes a useful
investigation outcome, and resolves whether implementation is authorized.
It should recommend choices, keep unknown coverage in the investigation, and
avoid inventing table names, coverage, recipient commitments, or time limits.
It should not investigate Snowflake or demand the answer to the assigned research.

For a follow-up, provide:

> Priya knows the project. Use the Operations report at `reports/operations.pbip`
> and my manual import at `inputs/team-leaders.csv`. Investigate and recommend
> only. Compare required fields, team-leader coverage, and refresh frequency.
> Cite the sources and gaps. Please ask her to confirm whether Friday is feasible,
> cap the initial investigation at two hours, and send the result to me in our
> project chat. If access is blocked or she reaches the cap, send findings so far
> and recommend the next step. I will review the recommendation before any changes.

The next response should produce a handoff without another blanket confirmation.
It should include the immediate outcome, evidence, authority, references, requested
date, effort cap, and escalation. Friday remains subject to Priya's confirmation.

## Complete routine assignment

Prompt:

> Prepare a message to Alex, our contractor. Please proofread the attached final
> brochure for spelling and punctuation only, using the attached style guide.
> Return a tracked-changes copy in this chat by 3 pm tomorrow. Alex has confirmed
> access and availability. Spend at most 30 minutes; if unfinished, return the
> partial edit and list the remaining pages. I will accept it once the corrections
> follow the style guide and the wording and layout remain otherwise unchanged.

Supplied context: attachment contents are unavailable to the qualifying agent.

The response should be a short handoff without an interview. It should preserve
scope, acceptance, timing, and the exhaustion rule. Reading the brochure is the
recipient's work. The agent should not demand the attachments to draft the message,
add an approval checkpoint, or claim it has reviewed the document.

## Constructive challenge and early exit

Prompt:

> Help me delegate a dashboard to a contractor by tomorrow. I don't yet know what
> decision it should help with, and the contractor has no access to the data.

The response should explain the impact of unclear purpose and missing access.
It should recommend a feasible next step and offer choices, such as a discovery
brief or a mockup with supplied sample data. It should leave the choice to the user
and avoid silently changing the task or claiming the deadline is agreed.

Then provide:

> Stop the questions and give me a draft of the original dashboard assignment.

The response should honor the request with a clearly marked draft. Missing purpose
and access should remain visible. It should not fabricate agreement, silently
substitute discovery, or insist that the interview continue.
