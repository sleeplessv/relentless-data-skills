# Research: qualifying a delegation before handoff

Dated 2026-09-25. This note checks the concepts in the supplied "Delegation Masking Best Practices" transcript. It supports the interview for a future agent skill. It does not specify that skill or establish that these frameworks improve every kind of delegation.

## Intent gives the recipient a basis for adaptation

The US Army's ADP 6-0, dated 31 July 2019, describes commander's intent as a concise expression of purpose and the desired end state. Paragraphs 1-45 through 1-51 explain how it supports initiative when operations depart from the plan. Intent may include the broader purpose, key tasks, and desired future conditions. Key tasks are essential activities of the force as a whole. Intent also defines the boundaries for initiative. [ADP 6-0, chapter 1](https://rdl.train.army.mil/catalog-ws/view/100.ATSC/1FE33715-CFD1-4614-A489-B3E0480C3F80-1428688882108/adp6_0.pdf).

The transcript's "task, purpose, and end state" is a useful simplification. The design implication is to capture why the work matters, what must be true afterward, and which constraints survive a change of plan. A procedural checklist alone cannot supply that context.

Access limitation: the search tool retrieved the relevant paragraphs from the official Army source, but opening its PDF directly failed. The findings above concern this dated edition, not a claim that it is the latest doctrine.

## Delegation levels allocate decision authority

Michael Hyatt's original article redirects to Full Focus. Its five levels distinguish who decides, whether authorization is needed, and whether reporting is required. These are paraphrases of his distinctions:

| Level | Recipient's authority and reporting duty |
|---|---|
| 1 | Execute the delegator's specified instructions without deviation. |
| 2 | Investigate and report findings. The delegator decides what happens next. |
| 3 | Investigate options and recommend a choice. Wait for authorization before proceeding. |
| 4 | Decide and act, then tell the delegator what happened. |
| 5 | Act independently without a required report back. |

The transcript's level-2-versus-level-4 example appears in Hyatt's article. His advice is a practitioner framework, rather than a demonstrated universal scale of delegation quality. [Michael Hyatt, The Five Levels of Delegation](https://fullfocus.co/the-five-levels-of-delegation/).

The design implication is to state actual permissions alongside any level number. Prescribing a method and granting decision authority are separate choices. A level also needs a scope: authority to research options does not itself confer authority to spend money or commit other people. If the eventual skill adds exception reporting to level 5, it should identify that as an adaptation of Hyatt's model.

## Completion, acceptance, and benefit answer different questions

The 2020 Scrum Guide defines Definition of Done through the quality state of an Increment and the team's shared understanding of completed work. It separately describes a Product Goal. Meeting the Definition of Done does not, by itself, establish that the desired business effect occurred. [Scrum Guide, Definition of Done](https://scrumguides.org/scrum-guide.html#commitment-definition-of-done).

The Agile Alliance and IIBA glossary describes acceptance criteria as conditions associated with requirements, products, or delivery that must be met for stakeholder acceptance. [Agile Extension to the BABOK Guide, glossary](https://www.agilealliance.org/wp-content/uploads/2017/08/AgileExtension_V2-Member-Copy.pdf).

For service outcomes, GOV.UK recommends agreeing metrics with stakeholders and comparing observed benefits with forecasts. It treats benefit evaluation as work that continues during service operation. [Measuring the benefits of your service](https://www.gov.uk/service-manual/measuring-success/measuring-service-benefits).

The proposed skill should distinguish the deliverable, the evidence that makes it acceptable, and the intended effect. For example, a recommendation can be complete and well supported before the business acts on it. The interview must establish which result the recipient can control and when its effect can be measured. These sources come from software and government service delivery, so the vocabulary should be adapted to the user's task.

## A time budget needs an exhaustion rule

Parkinson's text opens with an observation about work expanding to consume available time, then discusses the growth of administrative staffing and internally generated work. The accessible author's text is a reproduction of the 1958 book passage. It supplies no experiment showing that arbitrary reductions in deadlines preserve quality. [C. Northcote Parkinson, Parkinson's Law](https://www.panarchy.org/parkinson/parkinsonlaw.html).

Access limitation: the [original Economist article dated 19 November 1955](https://www.economist.com/news/1955/11/19/parkinsons-law) returned a paywall error. The accessible reproduction is hosted by a third party. Its opening editorial note is separate from Parkinson's text.

The design implication is to distinguish the calendar deadline from allowed effort and cost. An explicit rule is needed for what happens when the allowance runs out: deliver the best supported partial result, stop, seek more budget, or narrow the scope. Parkinson's observation does not determine which choice is appropriate or how much effort is sufficient.

## A handoff can include a check of understanding

AHRQ's TeamSTEPPS check-back uses a communication loop: the sender gives a message, the recipient confirms its contents, and the sender verifies that understanding. Acknowledging receipt alone does not complete the loop. [AHRQ, Check-Back](https://www.ahrq.gov/teamstepps-program/curriculum/communication/tools/checkback.html).

This is a healthcare communication method. Applying it to general delegation is a proposed design transfer, not direct evidence about this future skill. A short restatement of the outcome, authority, deadline, and unresolved assumptions could expose misunderstandings before work starts. A generated brief cannot claim that the downstream recipient understood or accepted it without a response from that recipient.

## Decisions the interview must resolve

The following are design proposals arising from the research, not claims established by its sources:

- Identify who delegates and who receives the work. A human, an AI agent, and a team may need different handoff details.
- Decide whether qualification can challenge the task's premise, propose a smaller first step, or conclude that the task is not ready to delegate.
- Establish the smallest useful output and the user's tolerance for questions. A brief for a familiar task should not require a project charter.
- Decide what information must be explicit and what may remain a labeled assumption. The agent should not invent the user's deadline, authority, resources, or quality threshold.
- Separate routine updates, exception escalation, and completion reporting. Capture the recipient, channel, trigger, and expected action where they matter.
- Check that essential resources are accessible and dependencies have owners. A link in a brief does not establish that its recipient can open it.
- Test the eventual skill with a real failed delegation and a successful one. Evaluate whether a recipient can act correctly using only the resulting handoff.
