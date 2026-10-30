# dossier

The **`dossier`** agent skill turns a subject (a system, a process, research findings, a
decision) into a dossier: one self-contained HTML document that opens with the claim it defends
and carries the argument in numbered figures and tables. Every dossier shares one locked house
style, so the tenth looks like the first.

Formerly `visual-report`. The rename started a new identity at `0.1.0`; the old install name no
longer resolves.

## What it does

- **Explore.** Gathers the substance worth drawing: walks a codebase with `Explore` subagents,
  organises what is already in the conversation, or reads the sources you name.
- **Write.** Copies the scaffold, picks a visual family per idea (data table, Vega-Lite axis
  chart, proportion bars, static-SVG DAG, sequence diagram, timeline, comparison matrix,
  annotated code, diff, and four hand-built shapes), and fills it with short, sourced prose: an
  answer box, captions with reading points, "So what" boxes, and a closing Limits section.
- **Verify.** Renders the page in headless Chromium. The check fails on render faults and on
  structure faults (no answer box, no Limits, an unnumbered or out-of-order figure, a
  non-sequence Mermaid diagram, a DAG of 16 or more nodes, a changed locked stylesheet, an
  unpinned or unknown script host, sideways overflow), then the agent reads every screenshot,
  because the script cannot judge a chart or a hand-built SVG by eye.
- **Grill loop.** Interviews you about what the dossier gets wrong or underweights, one question
  at a time with a recommended answer, and edits the same file.

## The house style

Navy and coral on white, system fonts on a 1.25 scale, a sticky sidebar of contents, tinted
surfaces instead of decorative bars, and one answer box per dossier. Red marks problems only and
amber marks callouts only; GitHub's diff colours appear only inside diffs. Every text pair meets
WCAG AA. The reasons and the trade-off are in
[ADR-0002](../../docs/adr/0002-dossier-locked-house-style.md).

The page loads Mermaid (sequence diagrams) and Vega-Lite (axis charts) from `cdn.jsdelivr.net`
at pinned versions, so it renders fully only with network access. Interactivity is inline
vanilla JS.

## Prerequisites

The render check needs [Playwright](https://playwright.dev/python/), a Chromium build, and
network access for the CDN. With `uv` installed, the command in `SKILL.md` fetches Playwright
into a throwaway environment; install the browser once:

```bash
uv run --python 3.13 --no-project --with playwright playwright install chromium
```

Without them the check reports `BLOCKED`, and the skill hands the dossier over as unverified
rather than claiming it rendered. The DAG and diff generators need only Python 3.13 or newer.

## Install

See the [repo root README](../../README.md) for the general install patterns (`npx skills`,
Claude Code plugin, manual clone). For this skill:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/dossier
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install dossier@relentless-data-skills
```

If you installed `visual-report` before, remove that copy. It activates when you ask for a
visual report, an explainer, a writeup, or a diagram of a system, process or set of findings as
one shareable document.

## Files

- `SKILL.md`: the explore, write, verify and grill process, the output contract and the house
  rules.
- `assets/scaffold.html`: the page every dossier starts from: locked stylesheet, page shell,
  pinned library block, sort, toggle and current-section scripts, print stylesheet.
- `assets/gallery.html`: worked examples of nine families (data table, axis chart, proportion
  bars, DAG, sequence diagram, timeline, comparison matrix, annotated code, diff); also the
  render-check fixture. The four hand-built shapes have no example yet.
- `references/VISUAL-LANGUAGE.md`: the visual families, how to pick one, colour roles and size
  limits.
- `references/HTML-REPORT.md`: how to fill the scaffold, a recipe per family, the libraries and
  their footguns.
- `references/WRITING.md`: the prose rules: answer box, captions, "So what", headings, length,
  banned words.
- `scripts/check_render.py`: the headless render and structure check (`PASS`, `FAIL`,
  `BLOCKED`).
- `scripts/dag_svg.py`: turns a graph in JSON into two static SVGs (wide and narrow layouts).
- `scripts/diff_html.py`: turns a unified diff (`git show`, `diff -u`) into GitHub-style diff
  rows with word-level highlights and numbered markers.
- `scripts/check_contrast.py`: checks every text and graphic colour pair in the scaffold's
  tokens against WCAG AA.

## Maintenance and CI

Repo CI lints `SKILL.md` through `scripts/lint_skill.py` and runs the unit tests in
`tests/test_dossier*.py`. See the [root README](../../README.md#maintenance-and-ci).

Changing the palette or any locked class means editing `assets/scaffold.html`, then running:

```bash
uv run --python 3.13 --no-project skills/dossier/scripts/check_contrast.py skills/dossier/assets/scaffold.html
uv run --python 3.13 --no-project --with playwright python skills/dossier/scripts/check_render.py skills/dossier/assets/gallery.html
```

The first exits 1 on any pair below AA. The second must end `PASS`. Read its screenshots, since
every dossier checks its locked block against the scaffold. This skill ships no
`references/docs-map.md`, so the doc-URL liveness check skips it.
