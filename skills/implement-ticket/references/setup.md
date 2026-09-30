# Workflow setup

Solo ticket owners and feature coordinators run this check before claims, lifecycle comments,
branch creation, or implementation. Orchestrated ticket workers reuse the coordinator's record.

Resolve `code-review`, `pr`, `technical-writing`, and `unslop` through the active skill catalog.
Confirm their `SKILL.md` files are readable. Load the writing references before authoring prose,
as described under [Writing](#writing). Load review and PR guidance when those phases start.
Record absolute paths and package versions or source revisions in the findings or run record
when available. Record unknown provenance as unknown.

Feature runs also resolve `orchestrator-mode` and `implement-ticket`. Confirm the ticket skill's
`references/orchestrated.md` and `references/review-and-pr.md` are readable. The feature and ticket
skills must be installed or updated together from the same repository revision. Their version
numbers are independent. If recorded source revisions disagree, report the mixed installation
before dispatch. If revision metadata is unavailable, record that limit and check required files.
Resolve cross-skill links from each named skill's discovered root, not an assumed sibling folder.
Pass the resolved paths and dependency results to workers so they reuse setup's discovery.

Report missing or incompatible dependencies during setup, with the affected phase and required
update. Continue independent authorized work. An unavailable `code-review` blocks independent
review and readiness; an unavailable `pr` blocks PR creation and body updates, not branch pushes.
Missing feature-worker contracts or a known mixed installation block ticket dispatch while
scope discovery can continue.
Installing or updating skills requires the user's authorization; preflight only inspects them.

## Writing

Read the resolved `technical-writing` and `unslop` files as shared references before authoring
prose. This works for companions marked `disable-model-invocation`; automatic skill invocation
is not required. Reuse instructions already loaded in this worker's context.

Apply `technical-writing` to documentation and technical prose, then use `unslop` to edit all
authored prose. This covers commits, issue comments, PR titles and bodies, worker briefs,
findings, handoffs, progress updates, and final reports. `pr` and required repository templates
own the PR structure; the writing skills govern its wording.

Pass this section and the resolved reference paths in every worker brief, including nested
reviewers and tracker or PR authors. Each worker reads the references before writing.
Preserve source quotations, commands, raw output, identifiers, and structured handoff fields.
Copyedits must preserve technical meaning, uncertainty, and evidence.

If a writing reference is unavailable, report it once during setup and use the available one.
Use plain words, active voice, and short sentences as the fallback. Keep claims tied to evidence.
Continue authorized work without adding a writing-dependency approval or publication gate.
