---
name: dossier
description: Produce a dossier, one self-contained HTML document with an answer box, numbered figures and tables, and a fixed house style, checked in a headless browser. Use when the user wants a visual report, an explainer, a writeup, or a diagram of a system, process, findings or decision as one shareable document, not an interactive dashboard or a single chart.
metadata:
  author: sleeplessv
---

# Dossier

A dossier explains one subject (a system, a process, findings, a decision) in a single HTML file.
It opens with the claim it defends and carries the argument in numbered figures and tables.
Every dossier looks the same: same palette, type, components and page shape. Consistency from
document to document outranks every local preference, so you fill a fixed scaffold and never
restyle it.

`<skill-dir>` is this skill's directory. Its files:

| File | Read it when |
|---|---|
| `assets/scaffold.html` | You start the dossier. Copy it; it is the whole stylesheet, page shell and scripts |
| `assets/gallery.html` | Before you build any figure. One worked example of every visual family |
| [references/VISUAL-LANGUAGE.md](references/VISUAL-LANGUAGE.md) | You pick a visual family for an idea, or a colour for a mark |
| [references/HTML-REPORT.md](references/HTML-REPORT.md) | You build a figure, table, DAG, code excerpt or chart in the scaffold |
| [references/WRITING.md](references/WRITING.md) | Before you write any prose: answer box, captions, bullets, headings |

Report on the subject at the scope asked. If exploring surfaces a bug, a stale doc or a design
problem, record it in the dossier; leave the fix to the user.

## 1. Explore

Find where the subject's substance lives and gather from there:

- **Codebase.** Walk it with Explore subagents (`subagent_type=Explore`), one per independent area.
  You keep the writing. Extract the structure worth drawing, not file dumps.
- **Already in the conversation.** The analysis is done. Organise what is there.
- **Named sources.** Read the docs or URLs the user pointed at.

In a repo, read `GLOSSARY.md` and `docs/adr/`. Use the glossary's terms exactly, and reflect ADR
decisions rather than contradicting them silently. Note the commit or date you measured at; the
byline states it. Stop exploring once you can draw each idea and source each number.

## 2. Write

1. Resolve the writing skills and read the prose rules, as
   [WRITING.md](references/WRITING.md#before-you-write) describes.
2. Copy `<skill-dir>/assets/scaffold.html` to the output path. Default to
   `${TMPDIR:-/tmp}/<slug>-<YYYYMMDD-HHMM>.html`; write elsewhere when the user names a
   destination or says to keep or commit it.
3. Open `<skill-dir>/assets/gallery.html` and read the families you plan to use.
4. List the ideas. Give each one a section and pick its visual family with the decision tree in
   [VISUAL-LANGUAGE.md](references/VISUAL-LANGUAGE.md#picking-a-family).
5. Build each figure from its recipe in [HTML-REPORT.md](references/HTML-REPORT.md), copying the
   gallery's markup and classes.
6. Print the absolute path and open it (`open` on macOS, `xdg-open` on Linux, `start` on
   Windows). In a headless session, print the path and say it could not be opened.

The step is done when every idea has a numbered figure or table and the output contract holds.

### Output contract

- **Answer box** at the top, holding the one claim the dossier defends. Explainers have one too.
- **Contents** in the sidebar when the dossier has four or more sections; the scaffold shows it
  inline below 1100px.
- **Numbered figures and tables**, on separate counters ("Figure 3", "Table 2"), numbered in the
  order they appear. Each has a caption and a "So what" box. Prose cites them by number.
- **Takeaways** as a short list of sentences, where a section needs them.
- **Limits** as the last section, always: unverified diagrams, numbers not re-checked, gaps in
  exploration. It says "None" when there are none.
- A stats row of up to four headline numbers under the answer box is optional.
- Light theme only. Readable down to 768px. The scaffold's print stylesheet stays.

### House rules

- Edit only the marked per-report block of the stylesheet, and only for geometry (column widths,
  narrow-screen overrides). The locked block between `dossier:locked:begin` and
  `dossier:locked:end` stays byte-for-byte; the render check fails any change.
- Colour comes only from the scaffold's tokens. Red marks problems, always with ✕ and the word
  "Problem". Amber marks callouts. GitHub's red and green appear only on the lines of a diff.
  Category fills use the four chart series. Token roles are in
  [VISUAL-LANGUAGE.md](references/VISUAL-LANGUAGE.md#colour-roles).
- Borders are full or absent. Boxes, nodes and callouts carry no side strip, and titles carry no
  accent rule beneath them.
- Every text and background pair meets WCAG AA. Captions use the muted token, never light grey.
- Code sits in the teal code family on a light panel with a line-number gutter. Annotations are
  navy numbered markers on a slate tint, so only real diff lines look like a diff.
- DAGs come from `scripts/dag_svg.py` as static SVG, about 11 nodes or fewer. Mermaid draws
  sequence diagrams only, up to about 12 messages each.
- Prose stays short: bullets around DAGs and figures, one-sentence captions with one to three
  reading points, sentence-case headings. The rules and the banned words are in
  [WRITING.md](references/WRITING.md).

**Cite ADRs.** When a figure depicts something an ADR governs, cite it in an amber callout
("This flow follows ADR-0012"). Only where an ADR governs what is drawn.

## 3. Verify

Render the page headlessly:

```bash
uv run --no-project --with playwright python <skill-dir>/scripts/check_render.py <report.html>
```

It prints JSON, then a final line and exit code: `PASS` (0), `FAIL` (1) or `BLOCKED` (2).
Screenshots go to `<report-stem>-check/` beside the report (`--shots DIR` to change it).

- `FAIL`: fix every entry under `problems` and rerun. Structure faults fail like render faults:
  no answer box, Limits missing or not last, a figure without a numbered caption or out of
  order, a Mermaid diagram that is not a sequence diagram, a DAG of 16 or more nodes, a changed
  locked block, a script host other than `cdn.jsdelivr.net` or an unpinned version, and a page
  or figure wider than its frame at 768, 1200, 1280 or 1440px.
- `BLOCKED`: unverified, not passing. The environment kept the check from running (no Playwright
  or Chromium, a CDN unreachable). Apply the fix it prints, or hand the dossier over and say its
  render is unchecked.
- `PASS`: open and read every screenshot it lists. The script cannot judge Vega charts,
  `dag_svg.py` output or hand-built SVG by eye: check each chart has its marks, axes and labels,
  each DAG's text sits inside its boxes, and nothing overlaps or spills. Fix what you see and
  rerun. Resolve every `warnings` entry: a heading not in sentence case, a DAG of 12 to 15
  nodes, a code block that scrolls sideways inside `pre.code`, a figure without "So what", small
  text, a paragraph over 60 words, banned words, colour misuse. Name every `unverified` entry at
  handover; a missing scaffold leaves the locked block unverified, not blocked.

Verify is done at `PASS` with every screenshot read and every warning resolved or named.

## 4. Grill loop

Hand the dossier over in one sentence: what it covers and where it is. Then interview the user
relentlessly about what it gets wrong or underweights (a section, a family choice, the emphasis)
until it says what they mean. Ask one question at a time, in plain prose, with your recommended
answer. Answer from the sources yourself when you can. Edit the same file after each answer and
rerun the check. Stop when the user has nothing left to change.

**Propose an ADR.** If the grilling surfaces a load-bearing decision nobody recorded, offer to
draft one ("Want me to record this as an ADR?"). Only when it is hard to reverse, surprising
without context, and the result of a real trade-off.
