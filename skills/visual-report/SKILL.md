---
name: visual-report
description: Produce a single self-contained HTML visual report — an explainer, writeup, or diagram-heavy document built with Tailwind and Mermaid via CDN plus hand-crafted CSS/SVG. Use when the user wants a visual report, an explainer, a single-file HTML writeup of a system/process/findings, or asks to visualize or diagram something as a shareable document.
license: Apache-2.0
metadata:
  author: sleeplessv
  version: 0.1.0
---

# Visual Report

Turn a subject — a system, a process, research findings, a decision — into a single self-contained HTML document that **carries its meaning in visuals**, not paragraphs. Tailwind and Mermaid come from CDNs; hand-built CSS/SVG handles the editorial visuals Mermaid can't. The output is one file: portable, no build step — though Tailwind and Mermaid load from CDNs, so it renders fully only with network access.

The skill names its diagram patterns consistently — see [VISUAL-LANGUAGE.md](references/VISUAL-LANGUAGE.md). The full scaffold, diagram recipes, interactivity rules, and house style live in [HTML-REPORT.md](references/HTML-REPORT.md).

## Process

### 1. Explore

Find the subject and where its substance lives, then gather from there:

- **About the codebase?** Use the Agent tool with `subagent_type=Explore` to walk it. Don't dump files into the report — extract the structure worth drawing.
- **Already in the conversation?** The analysis is done (a finished design discussion, a debugging session, a research summary). Organize what's there; don't re-investigate.
- **Pointed at sources?** Read the named docs/URLs.

If you're in a repo, read `docs/adr/`. ADRs record decisions the report should reflect — and not contradict silently. Stop exploring once you can draw the thing; over-exploring a subject that's already settled wastes the run.

### 2. Visualize

Write one self-contained HTML file and open it.

- **Where:** default to the OS temp dir — resolve `$TMPDIR`, fall back to `/tmp` (or `%TEMP%` on Windows) — at `<tmpdir>/<slug>-<timestamp>.html`. If the user names a destination ("save to `docs/`") or says "keep/commit it," write there instead. Either way, **print the absolute path and open it** (`open` on macOS, `xdg-open` on Linux, `start` on Windows). If opening fails (headless/SSH session), just print the path and say so.
- **Self-contained:** the only dependencies are the Tailwind CDN and the Mermaid ESM import. Light interactivity (collapsible sections, before→after toggles, CSS animations) is allowed via **inline vanilla JS only** — no extra libraries, no build step, one file.
- **Visual-first:** every major idea earns a visual. Mix Mermaid (graph-shaped relationships) with hand-built divs/SVG (mass diagrams, cross-sections, collapses). If a section needs a paragraph to be understood, redraw the visual. See [HTML-REPORT.md](references/HTML-REPORT.md).
- **House style:** the editorial aesthetic in [HTML-REPORT.md](references/HTML-REPORT.md) is the style — lean, not corporate-dashboard. Apply it; don't invent a new look per report.
- **Verify:** a Mermaid syntax error doesn't fail loudly — it renders as an error blob in the page. Before handing over, re-read every Mermaid block for the known footguns (quote labels containing parentheses, colons, or HTML) and confirm the page renders as intended; fix and reload until it does.

**Cite ADRs (if applicable).** When the report depicts something governed by an existing ADR, cite it in an amber callout (_"this flow follows ADR-0012"_) so a reader can trace *why it's built this way* to the decision record. Only when an ADR genuinely governs what's drawn — never staple an ADR callout onto every diagram.

### 3. Grill loop

After the file is written, interview the user relentlessly about what the report gets wrong or underweights — a section, a diagram pattern choice, the emphasis — until it says what they mean. Ask the questions one at a time, as plain prose, and give your recommended answer with each. If a question can be answered by re-reading the sources or codebase, do that instead of asking. Iterate on the same file after each answer; stop when the user has nothing left to change.

**Propose an ADR (if applicable).** If the grilling surfaces a load-bearing decision nobody had recorded — the visualization made a design choice explicit and a future reader would wonder "why this way?" — offer to draft one: _"Want me to record this as an ADR?"_ Only when it clears all three tests: it's hard to reverse, it's surprising without context, and it's the result of a real trade-off. Skip ephemeral or self-evident reasons.
