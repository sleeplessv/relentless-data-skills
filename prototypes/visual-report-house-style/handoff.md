# Handoff: visual-report house style redesign

Written 2026-10-30 for a fresh session. The previous session ran in orchestrator mode (the coordinator dispatched subagents and wrote nothing itself) and grilled, modelled, and prototyped the redesign of the `visual-report` skill. Nothing in the repo has changed yet. The working tree on `main` was clean at `a590a62`.

## What the user wants

The repo owner (sleeplessv) wants `skills/visual-report/` (version 0.1.3 in `skills/visual-report/plugin.json`) to produce sharper, crisper, clearer reports. In their words: "visual presentation is everything, as well as consistency from document to document." The reports it makes today look generic.

The session reached a shared understanding of the redesign, then built three throwaway prototypes. The user picked variant B with feedback (quoted below). Two warmer revisions of B were being built when the session ended.

## Why the current output looks generic

The diagnosis comes from rendering a real report the skill produced for a client. [Redacted at capture: the client report, its rendered copy and its check output are client material and are not committed.]

- Everything is a same-weight white card on stone grey. The verdict, a table, and a side note all look alike.
- Only two visual families get used in practice: Mermaid flowcharts and HTML tables. The two sample reports had 3 Mermaid blocks, 23 tables, and no SVG or charts.
- Proportion bars with no axis are the only chart.
- No table of contents, no figure numbers, no captions, no "what this shows" line.
- Tailwind defaults do the styling, so every report looks like every Tailwind page.

## Decisions the user agreed to

### Output contract

1. A mandatory answer box at the top holds the one claim the report defends. It exists even for explainers.
2. A table of contents appears when the report has four or more sections. It is a sticky left sidebar above 1100px and an inline list below.
3. Every visual is a numbered figure or table. Figures and tables use separate counters ("Figure 3", "Table 2"). Each has a two-part caption (what it shows, then how to read it) and a separate "so what" sentence set apart typographically. Prose refers to figures by number.
4. Takeaways are short sentences in a list, never chip rows.
5. A mandatory closing Limits section lists unverified diagrams, numbers not re-checked, and exploration gaps. "None" is allowed, but the section stays.
6. A print stylesheet hides the sidebar and the switcher and forbids page breaks inside figures. No dark mode. The page stays readable down to 768px. No phone work.

### Visual families

Keep the existing eight, each with a real recipe: Mermaid graph, boxes-and-arrows, cross-section, mass diagram, collapse, comparison matrix, timeline, proportion bars.

Add five:

- Data table.
- Axis charts (bar, line, scatter, small multiples) in Vega-Lite.
- DAG with size thresholds.
- Sequence diagram.
- Annotated code excerpt. CSS line numbers start at the real source line. Numbered margin markers carry the annotations. No highlighting library.

Not added, by decision: state diagrams, ER diagrams, pan-and-zoom libraries, syntax highlighting.

### Libraries

Tailwind goes. Hand-written CSS ships inside a new `assets/scaffold.html`. The user left this to the agent's judgement, and the agent chose removal because utility classes let each run restyle the page, which kills consistency from report to report.

The allowlist is fixed, every version pinned, every file on cdn.jsdelivr.net. All of these rendered and passed `check_render.py` in `libs-smoke.html` (see below):

| Library | Path on cdn.jsdelivr.net | Loaded as |
|---|---|---|
| Mermaid 11.17.2 | `mermaid@11.17.2/dist/mermaid.esm.min.mjs` | ES module |
| ELK layout 0.2.3 | `@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs` | ES module |
| Vega 6.4.0 | `vega@6.4.0` | classic script tag |
| Vega-Lite 6.5.0 | `vega-lite@6.5.0` | classic script tag |
| Vega-Embed 7.3.0 | `vega-embed@7.3.0` | classic script tag |

ELK 0.2.3 is the last release that pairs with Mermaid 11. The 1.0.x line needs Mermaid 12 and is unproven here.

Mermaid setup: `startOnLoad: false`, `securityLevel: "strict"`, `registerLayoutLoaders(elkLayouts)`, then `await mermaid.run()` at the end of the script. Hide tabs only after `run()` returns, because `mermaid.run()` replaces the element text with SVG.

Vega setup: `renderer: "svg"`, `actions: false`, inline data, `width: "container"`. The draw check for a Vega figure is that `#id.vega-embed > svg.marks > g path` exists.

Two footguns the prototypes hit:

- A wide ELK graph fails the render check as "shrunk" unless `flowchart: { useMaxWidth: false }` is set and the figure scrolls, or the direction is TB.
- Use the `.esm.min.mjs` ELK build. The `.core.mjs` build has bare imports that do not resolve in the browser.

All chunks load from cdn.jsdelivr.net, which is already in the `CDN_HOSTS` set at `skills/visual-report/scripts/check_render.py` line 65.

### Type and colour

- System fonts only, on a 1.25 modular scale. Prose is capped at about 72 characters, which is 640px in practice. Headings are a heavy grotesque with tight tracking. Numbers are tabular. Identifiers are monospace.
- One baked-in palette as CSS custom properties: paper, ink, one accent, red only for problems, amber only for callouts, six categorical colours, slate for de-emphasis. The `dataviz` plugin skill is not consulted.

### DAG thresholds

The original proposal was plain Mermaid up to 30 nodes, ELK from 31 to 80, and above 80 draw the subject's two-hop neighbourhood with the full count in the caption and the cut nodes in a collapsed table.

The prototypes changed this. A 56-node graph laid out at 1,900 to 2,800px wide under every engine. The current proposal is: apply the neighbourhood rule from 40 nodes, and make the check fail any diagram wider than its container.

### Sequence diagrams

A 17-step sequence ran about 1,100px tall in every prototype. Proposal: cap at about 12 steps per diagram and split beyond that.

### Tables

Units go in the header. Numbers are right-aligned, tabular, with thousands separators. The header is sticky. Click-to-sort runs on inline JS. Show 20 rows, then a `<details>` element that states the hidden count. Over 200 rows is a data file, not a table.

Known conflict: a sticky header dies inside an `overflow-x: auto` wrapper. The scaffold must solve this. Variant B's approach works and is the one to copy.

### Locked stylesheet

The scaffold CSS has a locked block (tokens, scale, pattern classes) that `check_render.py` hashes. If the block changes, the check fails the report. A second, marked block holds per-report geometry only.

### Render check extensions

`scripts/check_render.py` gains Vega and ELK draw checks, the stylesheet hash, and a structure pass.

Fails on: no answer box, no Limits section, a figure or table without a numbered caption, an unknown host, or an unpinned version.

Warns on: a section with no figure or table, a paragraph over 60 words, four or more sections without a table of contents, a table over 20 visible rows. Added after prototyping: red or amber used as a category fill, and slop words such as "pivotal" leaking in from source material.

Tests go in `tests/test_visual_report.py` (exists). The gallery render test is skipped when Playwright or the network is absent.

### Gallery

`assets/gallery.html` holds one worked example of every pattern. It is the test fixture and the file the agent opens before writing any figure. The `assets/` folder does not exist yet.

### Writing

Resolve `technical-writing` and `unslop` by following the symlinks to their installed `SKILL.md`, the way `skills/implement-ticket/references/setup.md` line 8 does (`readlink -f`). Read both before any prose. If either is missing, fall back to a three-line rule. The Diátaxis mode is explanation by default and reference on request.

Today the two skills resolve to `/Users/tumul/.agents/skills/technical-writing/SKILL.md` and `/Users/tumul/.agents/skills/unslop/SKILL.md`.

### Housekeeping

- Minor version bump to 0.2.0, per `README.md` section "Version skill changes" (line 263) and `docs/adr/0001-skill-version-boundary.md`.
- Update `skills/visual-report/README.md`.
- Add glossary terms to `GLOSSARY.md`: visual report, answer box, figure, limits section, locked block.
- Draft `docs/adr/0002-visual-report-locked-house-style.md`. It does not exist yet. The decision it records is dropping Tailwind plus the hashed stylesheet. It earns an ADR because it is hard to reverse, surprising without context, and a real trade-off.
- Standards from `CODING_STANDARDS.md` to apply: CS2 (every shell command tested), CS6 (done gates checkable by command), CN3 (branch-only material moves to `references/`), CN4 (no client names in a general skill), CT3 (every optional dependency has a stated fallback).
- `SKILL.md` line budget is 150 (`LINE_BUDGET` in `scripts/lint_skill.py`). The file is 56 lines today.

## Prototypes

The prototypes are throwaway files in the session scratchpad, not in the repo. The scratchpad dies with the session, so capture what you need early. The `prototype` skill says to capture the variants on a throwaway branch once the design settles.

Folder: `/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/`

| File | What it is |
|---|---|
| `content.md` | The report's facts, all sourced from this repo: a catalogue table of 18 skills, a 56-node dependency DAG, the render-check sequence, and a verdict code excerpt |
| `libs.md`, `libs-smoke.html` | The proven import block and its smoke page |
| `variant-a.html` | Editorial |
| `variant-b.html` | Dossier (the user's pick) |
| `variant-c.html` | Brief |
| `compare.md` | The verifier's contract-by-contract comparison |
| `variant-?-check.log`, `verify-?.log`, `variant-?-check/` | Render check logs and screenshot folders per variant |
| `variant-?-768-?.png`, `variant-?-sticky.png` | 768px and sticky-header screenshots |

Generators (each a `gen.py` plus `template.html`):

- Editorial: `proto/gen-a/` (inside the proto folder, not beside it)
- Dossier: `/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/gen-b/`
- Brief: `/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/work-c/`

The warmer revisions `variant-b1.html` and `variant-b2.html` did not exist when this handoff was written.

### Verifier findings

All three variants pass the render check.

A is the cleanest. It holds at 768px and runs 18 screens. Its captions fuse the "what" and the "how" into one sentence, and its sticky headers are dead.

B has the only working sticky headers and the densest reading aids. Its faults: figures out of numeric order, h2 forced to all caps, the DAG clipped to a 400px strip, Figure 7 crammed under Figure 2, the word "Pivotal" printed from source material, and one unsourced sentence ("new skills start at 0.1.0").

C is the shortest. Limits is a table. Tall figures leave an empty left column, and the DAG is cut at the right edge.

Faults shared by all three: red and amber used as DAG category fills, the switcher pill overlaps content, and the 56-node DAG is clipped.

One fact got settled during verification: exactly one commit (`dc788de`) followed `088a29f` on `skills/visual-report/`. The "three" in `content.md` is wrong. Fix it before reusing that file.

## The user's choice, verbatim

"Like B, however, it feels a bit clinical, and whenever there is a code block, it looks as if it's a different font, so there is no highlighting around it. Maybe let's dial down on this kind of pure white look and add a bit more colour and a bit more shapes in there. In the table, for example, in the Catalogue at a Glance, the numbers' colours are so muted that I can't really distinguish that it's highlighted."

Read as a fix list: warm the paper, add colour and shape beyond flat white, give code blocks a visible background and border so the font change reads as intended, and make highlighted numbers in the catalogue table stand out.

## Next steps, in order

1. Build two warmer revisions of B with the fixes above and the B faults from the verifier list: `variant-b1.html` (moderate) and `variant-b2.html` (bolder). Run `check_render.py` on both. The user picks.
2. Capture the winner and its siblings on a throwaway branch `prototype/visual-report-house-style`. No such branch exists yet.
3. Rewrite the skill: `SKILL.md`, `references/VISUAL-LANGUAGE.md`, `references/HTML-REPORT.md`, new `assets/scaffold.html` and `assets/gallery.html`, extended `scripts/check_render.py`, tests in `tests/test_visual_report.py`, the skill README, the glossary terms, ADR 0002, and version 0.2.0 in `plugin.json`.

## Suggested skills

Call the Skill tool for these before the matching work:

- `orchestrator-mode`, if the user wants the coordinator to keep dispatching only.
- `prototype`, for the B1 and B2 revisions and for the throwaway branch capture.
- `technical-writing` and `unslop`, before writing any prose in the skill, the ADR, the glossary, or the README.
- `writing-for-agents`, when editing `SKILL.md` and the references.
- `domain-modeling`, when adding the glossary terms and drafting ADR 0002.
- `visual-report`, to read the current skill before rewriting it.
- `grilling`, only if a decision above reopens.
