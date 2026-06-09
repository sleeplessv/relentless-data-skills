# HTML Report Format

The report is a single self-contained HTML file. Tailwind and Mermaid both come from CDNs. Mermaid handles graph-shaped relationships reliably; hand-built divs and inline SVG handle the more editorial visuals (mass diagrams, cross-sections, collapses). Mix the two — don't lean on Mermaid for everything, it'll start to look generic. Pattern names are defined in [VISUAL-LANGUAGE.md](VISUAL-LANGUAGE.md).

## Scaffold

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{{report title}}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script type="module">
      import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
      mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "loose" });
    </script>
    <style>
      /* Headings: tight, heavy grotesque sans — system stack only, no web font. */
      .display {                      /* main title / h1 */
        font-family: "Helvetica Neue", Arial, system-ui, sans-serif;
        font-weight: 800;
        letter-spacing: -0.03em;
      }
      .subhead {                      /* section headings / h2 */
        font-family: "Helvetica Neue", Arial, system-ui, sans-serif;
        font-weight: 700;
        letter-spacing: -0.02em;
      }
      /* small custom layer for what Tailwind doesn't cover cleanly:
         dashed seam lines, hand-drawn arrow heads, collapse keyframes. */
      .seam { stroke-dasharray: 4 4; }
      .accent { stroke: #4f46e5; }
      .warn { stroke: #dc2626; }
      .collapse { transition: max-height 0.4s ease, opacity 0.3s ease; overflow: hidden; }
    </style>
  </head>
  <body class="bg-stone-50 text-slate-900 font-sans">
    <main class="max-w-5xl mx-auto px-6 py-12 space-y-12">
      <header>...</header>
      <section class="space-y-10">...</section>
    </main>
    <!-- inline vanilla JS only, for collapse/toggle interactions -->
    <script>/* no external libs beyond Tailwind + Mermaid */</script>
  </body>
</html>
```

## Header

Title, date, and a compact legend mapping the visual vocabulary you actually use (solid box = X, dashed line = seam, red = warning/leak, thick band = the consolidated thing). No throat-clearing intro paragraph — straight into the content.

The top-level title gets `.display` paired with a tight line-height (`leading-[1.05]`). Example: `<h1 class="display text-5xl leading-[1.05]">…</h1>`.

## Section card

The visuals carry the weight. Prose is sparse and plain. Each major idea is one `<section>` or `<article>`:

- **Title** — short, names the idea. Every section heading gets `.subhead` (e.g. `<h2 class="subhead text-2xl">…</h2>`), so the document reads as one type system.
- **Badge row** (optional) — status or category tags. Pick a small palette: emerald for "strong/done," amber for "watch/in-progress," slate for "neutral/speculative."
- **The visual** — the centrepiece. Pick the pattern that fits (below). Before/after pairs sit side by side in two columns.
- **One sentence of framing** — what the visual shows. Not a paragraph.
- **Takeaways** — bullets, ≤6 words each.
- **ADR callout** (if applicable) — one line in an amber-tinted box (_"follows ADR-0012"_).

If a section needs a paragraph to be understood, redraw the visual.

## Diagram patterns

Pick the pattern that fits. Mix them — don't make every visual look the same; variety is part of the point.

### Mermaid graph (the workhorse for relationships / flow)

Use a Mermaid `flowchart`, `graph`, or `sequenceDiagram` when the point is "X connects to Y connects to Z." Wrap it in a Tailwind card so it doesn't feel parachuted in. Use `classDef` to colour the edges that matter (accent indigo, red for the problem path). Sequence diagrams work well for "before: 6 round-trips; after: 1."

```html
<div class="rounded-lg border border-slate-200 bg-white p-4">
  <pre class="mermaid">
    flowchart LR
      A[Intake] --> B[Validate]
      B --> C[Store]
      C -.problem.-> D[External call]
      classDef problem stroke:#dc2626,stroke-width:2px;
      class C,D problem
  </pre>
</div>
```

### Hand-built boxes-and-arrows (when Mermaid's layout fights you)

Things as `<div>`s with borders and labels; arrows as inline SVG `<line>`/`<path>` positioned absolutely over a `relative` container. Reach for this when you want one element to read as thick and dominant with greyed-out internals — weight Mermaid won't render.

### Cross-section (good for layers a thing passes through)

Stack horizontal bands (`h-12 border-l-4`) to show the layers a request/call/process traverses. Before: 6 thin layers each doing little. After: 1 thick band with the consolidated responsibility.

### Mass diagram (good for "surface vs substance")

Two rectangles per item — one for surface area, one for what's behind it. Before: the surface rectangle is nearly as tall as the substance (shallow). After: surface short, substance tall (deep).

### Collapse (good for "this whole tree becomes one thing")

Before: a tree of nested boxes. After: the same tree collapsed into one box with the now-internal pieces faded inside. A CSS `max-height` transition on a `.collapse` element, triggered by an inline-JS toggle, lets the reader play it.

## Interactivity

Allowed, kept minimal and self-contained:

- **CSS only** for motion where possible — keyframes, `transition`, `:hover`/`:target` reveals.
- **Inline vanilla JS** for collapsibles, tabs, and before→after toggles. No frameworks, no extra CDN libraries beyond Tailwind + Mermaid. It must stay one file with no build step.

If an interaction needs a library, it doesn't belong in this report.

## Style guidance

This is the house style — apply it, don't reinvent per report.

- Lean editorial, not corporate-dashboard. Generous whitespace.
- **Headings are a tight, heavy grotesque sans — never serif.** Apply `.display` to the top-level title (with `leading-[1.05]`) and `.subhead` to every section heading, so the whole document reads as one type system. Both classes use a system font stack only — no `font-serif`, no Google Fonts or other web fonts unless the user explicitly asks; the output must stay one portable file that works offline. This governs titles and headings only — body text, small uppercase eyebrow labels, and monospace code labels are unaffected.
- Colour sparingly: one accent (indigo or emerald) plus red for problems/warnings and amber for callouts. Resist a rainbow.
- Keep diagrams ~320px tall so before/after pairs sit side by side without scrolling.
- Use `text-xs uppercase tracking-wider` for labels inside diagrams — they should read as schematic, not as UI chrome.
- Static by default; the only motion is the CSS/inline-JS interactivity above.

## Tone

Plain English, concise. No hedging, no "it's worth noting that…". If a sentence could be a bullet, make it a bullet. If a bullet could be cut, cut it. When the report is about a domain with its own vocabulary (a project's `CONTEXT.md`, an ADR's terms), use that vocabulary exactly — don't drift into synonyms.
