# Skill authoring best practices: review checklist

Research date: 2026-10-09. This checklist was distilled from three first-party sources and used to review
every skill in this repo against Claude Code best practices; the high-severity findings were fixed in PR #84.
The judgement-call rules that review produced live in [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md);
mechanical checks live in `scripts/lint_skill.py`.

Sources (fetched 2026-10-09):
- [CC-BP] https://code.claude.com/docs/en/best-practices
- [CC-SK] https://code.claude.com/docs/en/skills
- [AS-BP] https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices (linked from CC-SK "Related resources")

Sections A to H are skill-specific checks; G1 to G14 are general Claude Code practices that apply to skill content.

Format: **Rule.** Rationale. Source.

## A. Frontmatter and naming

1. **`name` is at most 64 characters and uses only lowercase letters, digits and hyphens: no XML tags, and no "anthropic" or "claude".** These are the Agent Skills spec validation rules. [AS-BP]
2. **`name` matches the directory name, or is left out so it defaults to the directory name. It must not clash with reserved names (`anthropic-skills`, `anthropic-skills:*`, a folder named `synced`).** The command name comes from `name` or the directory, and those names are reserved for synced claude.ai skills. [CC-SK]
3. **Names are specific and follow one pattern across the repo (gerund such as `processing-pdfs`, noun phrase or action). Avoid vague names (`helper`, `utils`, `tools`) and overly generic ones (`data`, `files`).** Consistent names are easier to reference, find and understand at a glance. [AS-BP]
4. **Frontmatter field names are spelled exactly as documented (`disable-model-invocation`, `user-invocable`, `allowed-tools`, `when_to_use`, `argument-hint`, `context`, `agent`, `paths`, …).** Claude Code ignores unknown or misspelled fields without any error. [CC-SK]
5. **The frontmatter YAML parses. Run `claude plugin validate <skills dir>` (v2.1.233+) or `--debug`.** Malformed YAML loads the skill with empty metadata, so Claude can't match it by `description`. [CC-SK]
6. **Boolean fields use `true`/`false` (or yes/no, on/off, 1/0).** These are the only accepted forms. [CC-SK]

## B. Description and triggering

7. **`description` is present and non-empty, has no XML tags, and stays under 1,024 characters (spec limit).** It is required by the spec, and Claude uses it to pick among possibly 100+ skills. [AS-BP]
8. **`description` plus `when_to_use` together stay within 1,536 characters, with the key use case in the first clause.** The listing truncates the combined text at 1,536 characters, and when the listing goes over its budget some descriptions are dropped entirely. [CC-SK]
9. **The description says both WHAT the skill does and WHEN to use it ("Use when …").** Discovery depends on both parts. [AS-BP][CC-SK]
10. **The description is written in the third person ("Processes Excel files …"), not "I can …" or "You can …".** It is injected into the system prompt, and a mixed point of view hurts discovery. [AS-BP]
11. **The description contains concrete keywords and trigger phrases users would naturally say (file types, tool names, verbs). No vague text like "Helps with documents".** "Skill not triggering" is fixed first by adding natural keywords. [AS-BP][CC-SK]
12. **A skill that over-triggers has a narrower description, or `disable-model-invocation: true`.** These are the documented fixes for "triggers too often". [CC-SK]
13. **Descriptions don't overlap: no two skills in the repo should compete for the same requests.** Claude chooses by description alone. Ambiguity causes wrong or missed triggers. (Inferred from [AS-BP] selection guidance)

## C. Invocation control

14. **Skills with side effects or manual-only workflows (deploy, commit, push, PR, ticket work) set `disable-model-invocation: true`.** This stops Claude from running them on its own, and it also takes the description out of context. [CC-BP][CC-SK]
15. **Background or reference skills that users shouldn't type set `user-invocable: false`.** This hides them from the `/` menu while Claude can still load them. [CC-SK]
16. **Each skill is clearly one of two kinds: reference content (conventions or knowledge, applied inline) or task content (step-by-step action, usually user-invoked).** The type decides the invocation settings and the shape of the body. [CC-SK]
17. **`context: fork` is used only for skills with an explicit, self-contained task. The body must not depend on conversation history. `agent` is set to a suitable subagent type.** A forked skill becomes the subagent's prompt, and the subagent can't see the conversation. [CC-SK]
18. **`allowed-tools` lists only the narrow patterns the skill needs (e.g. `Bash(git status *)`), not broad grants.** It pre-approves tools for the invoking turn. It does not restrict other tools. [CC-SK]
19. **Arguments use the documented substitutions (`$ARGUMENTS`, `$0..$N`, named `arguments`) and set `argument-hint` when arguments are expected. Literal `$` is escaped (`\$1.00`).** Without the escape, text is substituted by mistake. [CC-SK]
20. **`` !`cmd` `` dynamic-context commands can't fail in normal environments, or a failure there is acceptable.** A failing command aborts the whole skill invocation. [CC-SK]

## D. Length, context cost, progressive disclosure

21. **SKILL.md body is under 500 lines.** This is the documented limit for good performance. Content beyond it goes into separate files. [CC-SK][AS-BP]
22. **The body is concise: each paragraph earns its tokens, and nothing explains what Claude already knows (what a PDF is, standard language conventions). It states what to do rather than narrating why.** Once loaded, the body stays in context every turn as a recurring cost. [CC-SK][AS-BP]
23. **The most important instructions are near the top of SKILL.md.** After compaction only the first ~5,000 tokens of each invoked skill are kept, from a shared 25k budget. [CC-SK]
24. **Large reference material, API specs and example collections go in supporting files, not inline.** Supporting files cost nothing until read. [CC-SK][AS-BP]
25. **Every supporting file is linked from SKILL.md, with a note on what it contains and WHEN to read it.** Otherwise Claude doesn't know it exists or when to load it. Files that are never accessed are probably unnecessary or poorly signalled. [CC-SK][AS-BP]
26. **References are one level deep: SKILL.md → file. No SKILL.md → a.md → b.md chains.** Claude may only partly read (`head`) files that are referenced from nested files. [AS-BP]
27. **Reference files over 100 lines start with a table of contents.** Claude can then see the full scope even when it previews only part of the file. [AS-BP]
28. **Multi-domain skills are split by domain (e.g. `reference/finance.md`, `reference/sales.md`).** Only the relevant domain gets loaded. [AS-BP]
29. **Supporting files have descriptive names (`form_validation_rules.md`, not `doc2.md`) and use forward-slash paths.** Claude navigates the skill like a filesystem, and backslashes break on Unix. [AS-BP]

## E. Content quality

30. **No time-sensitive statements ("before August 2025 …"). Legacy material goes in a collapsed "Old patterns" section.** Dated statements go stale and become wrong. [AS-BP]
31. **Terminology is consistent: one term per concept throughout (no mixing "field", "box" and "element").** Consistency helps Claude parse and follow instructions. [AS-BP]
32. **The skill gives one default approach plus an escape hatch, not a menu of equal options.** Too many choices confuse Claude. [AS-BP]
33. **The degree of freedom fits how fragile the task is: exact commands for fragile or ordered operations ("Run exactly …"), heuristics for open-ended judgment.** Fragile tasks need guardrails, and open tasks suffer from over-specification. [AS-BP]
34. **Examples are concrete (input/output pairs), not abstract.** Examples show style and detail better than descriptions do. [AS-BP]
35. **Output templates state how strict they are: "ALWAYS use this exact template" versus "sensible default, adapt".** Claude can only match the strictness the skill states. [AS-BP]
36. **Guidance that must hold for the whole task is worded that way ("Run the tests after every edit", not "Run the tests").** The skill is read once and not re-read on later turns. [CC-SK]
37. **Rules that must hold every time are enforced by a hook (optionally in the skill's `hooks` frontmatter), not only by prose.** Prose is advisory and hooks are deterministic. [CC-SK][CC-BP]
38. **Emphasis (IMPORTANT, MUST) is used sparingly, only on rules that are actually being skipped.** If many lines are emphasised, none stands out. [CC-BP]

## F. Workflows, verification, feedback loops

39. **Complex multi-step tasks use numbered sequential steps. Very complex ones include a copyable progress checklist.** This stops Claude from skipping critical steps such as validation. [AS-BP]
40. **Branching workflows state the decision point clearly ("Creating new? → X; Editing? → Y"), and large branches are pushed into separate files.** Claude can then follow only the branch that applies. [AS-BP]
41. **Quality-critical tasks include a feedback loop: run the validator, fix, repeat, and continue only when it passes.** This greatly improves output quality. [AS-BP]
42. **The skill defines a concrete pass/fail verification step (tests, build, linter, diff against a fixture, screenshot) and asks for evidence (the command run and its output) rather than an assertion.** Without a check, "looks done" is the only signal Claude has. [CC-BP]
43. **Batch, destructive or high-stakes operations use plan → validate → execute, with a verifiable intermediate artifact (e.g. `changes.json`).** Errors are caught before anything changes. [AS-BP]

## G. Scripts and tools

44. **Deterministic or fragile operations ship as bundled scripts instead of asking Claude to generate the code.** Bundled scripts are more reliable and consistent, and they save tokens because only their output enters context. [AS-BP]
45. **Every script reference says whether to EXECUTE it ("Run `x.py`") or READ it ("See `x.py` for the algorithm").** The two have different context cost and behaviour. [AS-BP]
46. **Scripts handle errors themselves with explicit, helpful messages (e.g. listing available valid values). They don't just crash and leave the problem to Claude.** That is the "Solve, don't defer" rule. [AS-BP]
47. **No voodoo constants: every timeout, retry count or threshold has a comment justifying it.** If the author doesn't know the right value, Claude can't either. [AS-BP]
48. **Required packages and CLIs are listed explicitly (with an install command), not assumed to be installed.** Environments differ. [AS-BP]
49. **Script paths inside the skill use `${CLAUDE_SKILL_DIR}` or skill-relative forward-slash paths, not machine-specific absolute paths.** Skills must work from any install location. [CC-SK substitutions][AS-BP]
50. **MCP tools are named in full. The spec format is `ServerName:tool_name`; in Claude Code the actual tool IDs are `mcp__server__tool`. Check that the names match the target runtime.** A bare tool name can fail with "tool not found" when several servers are connected. [AS-BP]
51. **External services are reached through CLI tools (`gh`, `aws`, `snow`, …) where possible.** CLIs are the most context-efficient interface. [CC-BP]

## H. Testing and iteration

52. **Each skill has at least three evaluation scenarios, with a baseline run without the skill.** Evaluations keep the skill aimed at real gaps, not imagined ones. [AS-BP]
53. **The skill has been tested on every model it will run on (Haiku, Sonnet, Opus).** Haiku may need more detail, and Opus may suffer from over-explanation. [AS-BP]
54. **Triggering has been checked with realistic prompts after every description change (for plugins, `claude plugin eval` with a `tool_used: Skill` grader).** This measures how reliably the skill triggers. [CC-SK]
55. **The skill's total listing cost has been checked with `/doctor` and `/context`, and low-value skills set to `name-only` or turned off.** Every listed description costs context on every turn. [CC-SK]

---

## General Claude Code best practices that apply to skill content

G1. **Context is the scarce resource.** Performance degrades as context fills, so skills should keep what they load and print small and push bulk work into subagents. https://code.claude.com/docs/en/best-practices
G2. **Give Claude a check it can run (tests, build, script, screenshot) and require evidence, not claims.** https://code.claude.com/docs/en/best-practices#give-claude-a-way-to-verify-its-work
G3. **Pick how hard the check gates the stop: in-prompt iteration, a `/goal` condition, a Stop hook (deterministic), or a verification subagent (second opinion).** Skills that claim "done" should pick one. https://code.claude.com/docs/en/best-practices
G4. **Explore → plan → implement → commit. Skip planning when the diff fits in one sentence.** Workflow skills shouldn't force planning onto trivial tasks. https://code.claude.com/docs/en/best-practices#explore-first-then-plan-then-code
G5. **Be specific: name files, constraints, example patterns and what "fixed" looks like.** Skill instructions should be equally concrete. https://code.claude.com/docs/en/best-practices#provide-specific-context-in-your-prompts
G6. **CLAUDE.md is for things that apply broadly. Domain knowledge or workflows needed only sometimes belong in skills.** Check that skills don't duplicate CLAUDE.md, and that CLAUDE.md doesn't hold what a skill should. https://code.claude.com/docs/en/best-practices#write-an-effective-claude-md
G7. **For every line, ask "Would removing this cause Claude to make mistakes?" If not, cut it.** Leave out what Claude can infer from code, standard conventions, long tutorials, frequently changing info and self-evident advice. Skills use the same conciseness test. https://code.claude.com/docs/en/best-practices + https://code.claude.com/docs/en/skills
G8. **Hooks are deterministic and prose is advisory.** Anything that must happen every time belongs in a hook. https://code.claude.com/docs/en/best-practices#set-up-hooks
G9. **Use subagents for investigation and wide reads so the main context stays clean. Scope investigations narrowly ("infinite exploration" is a failure pattern).** https://code.claude.com/docs/en/best-practices#use-subagents-for-investigation
G10. **Adversarial review: a fresh-context subagent checks the diff against criteria. Tell reviewers to flag only gaps that affect correctness or requirements, to avoid over-engineering.** https://code.claude.com/docs/en/best-practices#add-an-adversarial-review-step
G11. **Self-contained specs name files and interfaces, state what is out of scope, and end with an end-to-end verification step.** This applies to spec- or ticket-writing skills. https://code.claude.com/docs/en/best-practices#let-claude-interview-you
G12. **For fan-out or batch work, test on 2–3 items before running on all of them, and pre-approve only the needed tools (`--allowedTools`).** https://code.claude.com/docs/en/best-practices#fan-out-across-files
G13. **Treat instruction files like code: review them when things go wrong, prune them regularly, and test a change by checking that behaviour actually shifts.** https://code.claude.com/docs/en/best-practices#write-an-effective-claude-md
G14. **Use CLI tools for external services.** They are the most context-efficient option, and Claude can learn unfamiliar ones via `--help`. https://code.claude.com/docs/en/best-practices#use-cli-tools
