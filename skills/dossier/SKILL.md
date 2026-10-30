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
| `assets/gallery.html` | Before you build any figure. A worked example of every family except the four hand-built ones |
| [references/VISUAL-LANGUAGE.md](references/VISUAL-LANGUAGE.md) | You pick a visual family for an idea, or a colour for a mark |
| [references/HTML-REPORT.md](references/HTML-REPORT.md) | You build a figure, table, DAG, code excerpt or chart in the scaffold |
| [references/WRITING.md](references/WRITING.md) | Before you write any prose: answer box, key findings, captions, bullets, headings |

Report on the subject at the scope asked. If exploring surfaces a bug, a stale doc or a design
problem, record it in the dossier; leave the fix to the user.

## 1. Explore

Find where the subject's substance lives and gather from there:

- **Codebase.** Walk it with up to three Explore subagents (`subagent_type=Explore`), one per
  truly independent area; explore inline when the areas overlap. The cap keeps a casual request
  cheap. You keep the writing. Extract the structure worth drawing, not file dumps.
- **Already in the conversation.** The analysis is done. Organise what is there.
- **Named sources.** Read the docs or URLs the user pointed at.

In a repo, read `GLOSSARY.md` and `docs/adr/`. Use the glossary's terms exactly, and reflect ADR
decisions rather than contradicting them silently. Note the commit or date you measured at; the
byline states it. Stop exploring once you can draw each idea and source each number.

## 2. Write

1. Read the prose rules in [WRITING.md](references/WRITING.md) before writing any
   prose.
2. Copy `<skill-dir>/assets/scaffold.html` to the output path. Default to
   `${TMPDIR:-/tmp}/<slug>-<YYYYMMDD-HHMM>.html`; write elsewhere when the user names a
   destination or says to keep or commit it.
3. Open `<skill-dir>/assets/gallery.html` and read the families you plan to use.
4. List the ideas. Give each one a section and pick its visual family with the decision tree in
   [VISUAL-LANGUAGE.md](references/VISUAL-LANGUAGE.md#picking-a-family).
5. Build each figure from its recipe in [HTML-REPORT.md](references/HTML-REPORT.md), copying the
   gallery's markup and classes. The hand-built families (boxes-and-arrows, cross-section, mass
   diagram, collapse) have no gallery example; build them as their recipe says.
6. Write the key findings last, from the finished sections, as
   [WRITING.md](references/WRITING.md#key-findings) says.
7. Print the absolute path and open it (`open` on macOS, `xdg-open` on Linux, `start` on
   Windows). In a headless session, print the path and say it could not be opened.

The step is done when every idea has a numbered figure or table and the output contract holds.

### Output contract

- **Answer box** at the top, holding the one claim the dossier defends. Explainers have one too.
- **Key findings** directly under the answer box: three to five numbered one-sentence findings,
  in report order, each linking to its section.
- **Contents** in the sidebar when the dossier has four or more sections; the scaffold shows it
  inline below 1100px.
- **Numbered figures and tables**, on separate counters ("Figure 3", "Table 2"), numbered in the
  order they appear. Each has a "So what" pull quote above its caption. Prose cites them by
  number.
- **Takeaways** as a short list of sentences, where a section needs them.
- **Limits** as the last section, always: unverified diagrams, numbers not re-checked, gaps in
  exploration. It says "None" when there are none.
- A stats row of up to four headline numbers under the answer box is optional, with or without
  the answer's lead number.
- Light theme only. Readable down to 768px. The scaffold's print stylesheet stays.

### House rules

- Edit only the marked per-report block of the stylesheet, and only for geometry (column widths,
  narrow-screen overrides). The locked block between `dossier:locked:begin` and
  `dossier:locked:end` stays byte-for-byte; the render check fails any change.
- Colour comes only from the scaffold's tokens. Red marks problems, always with ✕ and the word
  "Problem". Amber marks callouts. GitHub's red and green appear only on the lines of a diff.
  Category fills use the four chart series. Token roles are in
  [VISUAL-LANGUAGE.md](references/VISUAL-LANGUAGE.md#colour-roles).
- Descriptions follow one pattern down the page: the "So what" pull quote leads, then the
  caption. Both sit beside the visual in a side row, or under a wide visual with the pull quote
  in the left column and the caption in the right. A figure goes wide only when it is
  unreadable in the left column. The rule is in
  [HTML-REPORT.md](references/HTML-REPORT.md#figure-row).
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
uv run --python 3.13 --no-project --with playwright python <skill-dir>/scripts/check_render.py <report.html>
```

If `uv` is missing, run `python3 <skill-dir>/scripts/check_render.py <report.html>` with a
Python 3.13+ interpreter, with Playwright if one has it. Run it even without Playwright: the
structure pass needs no browser, so a `FAIL` there still comes through.

It prints JSON, then the verdict as its last line. Screenshots go to `<report-stem>-check/`.

- `FAIL` (exit 1): fix every entry under `problems` and rerun.
- `BLOCKED` (exit 2): unverified, not passing; the source pass was clean, but the environment
  kept the render from running.
  Apply the fix it prints, or hand the dossier over and say its render is unchecked.
- `PASS` (exit 0): structure holds and everything drew, but the script does not judge meaning.
  Read every screenshot it lists: each chart has its marks, axes and labels, each DAG's text sits
  inside its boxes, nothing overlaps or spills. Fix what you see and rerun. Resolve every
  `warnings` entry and name every `unverified` entry at handover.

Every problem and warning the check reports is listed in
[HTML-REPORT.md](references/HTML-REPORT.md#the-render-check).

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
