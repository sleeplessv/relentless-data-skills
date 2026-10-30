# Building a dossier from the scaffold

How to fill `assets/scaffold.html`: the page skeleton, the figure row, a recipe per visual
family, the pinned libraries, interactivity, and what the render check reports. Which family to
pick is in [VISUAL-LANGUAGE.md](VISUAL-LANGUAGE.md); the words that go in each slot are in
[WRITING.md](WRITING.md). `assets/gallery.html` holds a worked example of every family except the
four hand-built ones: that example is the reference markup, so find it by the class named here
and copy it. The hand-built families have no example; their recipe says how to build them.

## The two stylesheet blocks

The scaffold's `<style>` holds two marked blocks:

```css
/* dossier:locked:begin v1 */  ...  /* dossier:locked:end */
/* dossier:report:begin */     ...  /* dossier:report:end */
```

- The **locked block** holds the tokens, type scale and every pattern class. The render check
  compares it with the skill's own scaffold and fails the dossier on any difference.
- The **report block** holds this dossier's geometry only: column widths for a named table
  (`#table-2 col.c-id { width: 29%; }`), `table-layout: fixed`, and narrow-screen overrides inside
  `@media (max-width: 900px)`. It holds no colours, fonts or new components.

If a figure seems to need a new class or colour, pick a different family or simplify the figure.

## Page skeleton

The scaffold already holds each part below in this order, with placeholders:

1. **Sidebar** `aside.side`: `.brand` (the title), `.meta` (commit or date), `ol.toc#toc` with one
   `li > a[href="#sN"]` per section (`span.n` "01", then the heading text), then `dl.visuals`
   listing every table and figure by number and short name. The current section turns into a
   navy pill with a coral number as the reader scrolls; the scaffold's script does this.
2. **Masthead** `header.masthead`: `.kicker.eyebrow`, `h1`, `.byline` (source and date).
3. **Answer box** `section.answer`, framed by full-width navy rules above and below. Inside,
   an optional `.lead` (`.n` the number, with an optional `span.key` around the part to show in
   coral; `.u` the unit label), then `.text` with `.label.eyebrow` "Answer", `p.claim` and an
   optional `p.rest`. Without `.lead` the text starts at the left edge. Below 560px the number
   stacks above the text.
4. **Stats row** (optional) `.stats` with up to four `.stat` (`.v` value, `.l` label). Delete the
   whole element when unused.
5. **Inline contents** `nav.toc-inline`, the same list without numbers; shown below 1100px.
6. **Sections** `section.sec#sN`, each opening with
   `h2.sec-head` > `span.n` (two digits), `span` (heading), `span.count` (the figures and tables
   it holds, such as "Figures 5 and 6").
7. **Limits**, the last `section.sec`, heading text exactly "Limits", body `ol.limits`.

Delete the sidebar and inline contents when the dossier has fewer than four sections.

## Figure row

Every figure and table sits in a `.fig` row: the visual on the left, the caption and "So what"
box in a margin column on the right. `.fig.wide` stacks them, for anything that needs the full
width: DAGs, timelines, diffs, sequence diagrams, wide tables.

```html
<div class="fig" id="fig-3">
  <div class="visual"><div class="figframe">…</div></div>
  <div class="margin">
    <p class="caption"><span class="figno">Figure 3.</span> What it shows.
      <span class="how">How to read it, in one to three sentences.</span></p>
    <p class="sowhat"><span class="lbl">So what</span>The conclusion.</p>
  </div>
</div>
```

- Figure ids are `fig-N`; table rows use `id="table-N-fig"` on the row and `id="table-N"` on the
  `<table>`. Number figures and tables in the order they appear.
- Add each to `dl.visuals` in the sidebar.
- Put a short `ul.points` list before a figure when the section needs context; see
  [WRITING.md](WRITING.md#text-around-figures).

## Recipes

### Data table

```html
<div class="figframe table">
  <table class="data sortable" id="table-1" data-show="20">
    <thead><tr><th class="txt" data-type="txt">Skill</th><th class="num" data-type="num">Lines</th></tr></thead>
    <tbody>…first 20 rows…</tbody>
    <tbody id="t1-rest" hidden>…the rest…</tbody>
  </table>
  <details class="more" data-target="t1-rest">
    <summary><span class="when-closed">Show 36 more rows</span><span class="when-open">Show fewer</span></summary>
  </details>
</div>
```

- Units go in the header ("Lines", "Size (KB)"), not in the cells.
- Numbers: `td.num`, right-aligned, tabular, thousands separators. Identifiers: `td.id`
  (monospace). Free text: `td.txt`.
- The header sticks under the section heading. Keep the table out of any `overflow-x: auto`
  wrapper (including `.figframe.scroll`); that kills the sticky header. Fit a wide table with
  report-block geometry instead.
- Show 20 rows. Put the rest in a second, hidden `tbody` behind `details.more`, whose summary
  states the hidden count. `data-show` keeps the split when the reader sorts. Over 200 rows,
  link a data file instead.
- To make a number column stand out, put a bold numeral over an in-cell bar:
  `<td class="num bar"><span class="cbar" style="--w: 64%">96</span></td>`, with `--w` the
  value's share of the scale. Add the `key` class (`td.bar.key`) to the cells to single out, such
  as those at the limit; their bars turn coral.

### Comparison matrix

A `table.data.matrix`. Each `td.mark` holds a symbol and a class, never colour alone: `●` with
`pass`, `✕` with `fail`, `◆` with `blocked`. The caption's reading points name each symbol.
`span.mark-note` adds a two-word qualifier under a mark.

### Axis chart

A `<div id="vl-name" class="chart"></div>` inside a `.figframe`. In the scaffold's Vega script,
add one `["#vl-name", spec]` pair to the `CHARTS` array, with a Vega-Lite v6 spec that has inline
`data.values` and `width: "container"`. The scaffold merges `VL_CONFIG` (the four series colours
and muted axes) into each spec, embeds it with `VL_OPTS`, and sets `window.__vegaDone` to the
promise of all the embeds. Take any colour in a spec from a token, `TOKEN("coral-line")`, never
a hex value.

- Inline data only; no `url` data.
- A dashed rule marks a budget or threshold; say so in the caption.
- The render check confirms marks were drawn. Only the screenshot shows whether the chart reads.

### Proportion bars

`.figframe.bars` holding one `.bar-row` per item: `.bar-label`, then `.bar-track` with
`.bar-fill` (`style="width: 64%"`, scaled to the largest value) and `.bar-num` (the value in `b`,
then `.bar-sub` for a share or unit). The first row's bar is coral; the rest are ink. An "other"
row takes the `other` class (taupe).

### DAG

Write the graph as JSON and run the generator:

```bash
uv run --python 3.13 --no-project <skill-dir>/scripts/dag_svg.py graph.json --out dag.html   # "-" reads stdin
```

Without `uv`, plain `python3` works if it is 3.13 or newer; the same holds for `diff_html.py`.

`<skill-dir>` is the skill's directory. Without `--out` the fragment goes to stdout. Exit codes:

- 0: fragment written. Warnings go to stderr; above 11 nodes it names the sibling sets you can
  merge. Treat a warning as a fault to fix.
- 1: invalid input, reason on stderr: 16 or more nodes, more than six tags, a cycle, an edge to
  an unknown node, or a duplicate id.
- 2: usage error.

```json
{
  "nodes": [
    {"id": "lint", "name": "lint_skill.py", "tag": "SCR", "caption": ["scripts/", "degree 21"]},
    {"id": "dossier", "name": "dossier", "tag": "SKL", "caption": "skills/ · degree 4"}
  ],
  "edges": [["dossier", "lint"]],
  "groups": [{"id": "rest", "name": "other skills", "tag": "SKL", "caption": "skills/",
              "members": ["a", "b", "c"]}],
  "focus": "dossier",
  "legend": {"SKL": "skill", "SCR": "root script"},
  "label": "Two-hop neighbourhood of the dossier skill",
  "total_nodes": 56
}
```

- `tag` is a node type of one to four letters or digits (`SKL`, `CI`), drawn as a badge. Use
  six types at most. `legend` labels each one, and its order sets the badge slots, `tag-1` to
  `tag-6`, for the types nodes use. Slot 6 is the outline badge.
- `caption` is the second line, a string or a list joined with " · ".
- `groups` collapse their `members` into one dashed node with a count chip, and move their edges
  to it; a member cannot be another group. `group_count` on a node draws the same chip for a
  node you merged yourself. Merge siblings that share a parent and say nothing alone.
- `focus` (or `subject`) is the one subject node; it gets the coral tint.
- `rank` per node is optional, a lower bound; the script ranks by longest path.
- `label` is the SVG's accessible name. `total_nodes` is the size of the full graph. `id`
  optionally names the arrow-marker ids (`fig-3`); the default is a hash of the graph.

The output is a `div.figframe.dag-frame` holding a left-to-right and a top-to-bottom SVG, then
the `p.legend` naming each badge, the subject and the dashed group box. Paste it into the
`.visual` of a `.fig.wide` row, between `<!-- generated: … -->` and
`<!-- end generated: dag_svg.py -->` comments that record the command. The frame shows the
left-to-right drawing when it is at least 980px wide and the top-to-bottom one below that.
Replace the margin column with `div.dag-notes`, three blocks of bullets: `.cap` (caption, then
"N of M nodes drawn" and what was merged), "How to read" and "So what". Put every node in a data
table when nodes were cut.

### Sequence diagram

A `pre.mermaid` inside `.figframe.seq` in a `.fig.wide` row, with up to about 12 messages.

- Give each actor a short id and its display name: `participant CR as check_render.py`.
- Write `;` and `#` in message text as Mermaid entity codes (`#59;`, `#35;`). A parse error makes
  Mermaid draw an error diagram, with no console message.
- Use `alt` and `loop` boxes for branches; name the condition.
- The scaffold's module script initialises Mermaid with the sequence theme and runs it last.

### Timeline

`ol.timeline` in its own `.fig.wide` row, never beside another figure. Each `li` holds
`.tl-n`, `.tl-date`, `.tl-dot`, `.tl-body` and an optional `.tl-note`. Give the one key event
`li.key`; everything else stays plain.

### Annotated code excerpt

```html
<pre class="code" style="counter-reset: ln 353"><code><span class="l">def verdict(facts):</span>
<span class="l mark" data-m="1">    if facts.blocked:</span>
…</code></pre>
<ol class="markers">
  <li><span class="k">1</span><span class="ln">355</span> What this line does.</li>
</ol>
```

- Set `counter-reset: ln N` with N one less than the first source line, so the gutter matches
  the file.
- `l mark` with `data-m` puts the navy numbered marker in the right margin and the slate tint on
  the line. `ol.markers` under the panel explains each marker, with its line number.
- Copy the source verbatim, one `span.l` per line, HTML-escaped. No highlighting library.
- Up to about 25 lines; cut to the lines the markers discuss.

### Diff

Generate the rows from a unified diff; word-level highlights by hand are error-prone:

```bash
git show <rev> -- <file> | uv run --python 3.13 --no-project <skill-dir>/scripts/diff_html.py - \
  --lines 35-49 --note 'old:36=Before.' --note 'new:39=After: run `check_render.py`.' \
  --out diff.html
diff -u old.md new.md | uv run --python 3.13 --no-project <skill-dir>/scripts/diff_html.py -
```

The input is any unified diff (`git diff`, `git show`, `diff -u`), as a file or `-` for stdin.

- `--path FILE` picks one file when the diff covers several, as in `+++ b/FILE`. Required then.
- `--lines FIRST-LAST` keeps new-file lines FIRST to LAST and the removals between them, and
  rewrites the hunk headers to match. The header text after `@@` stays git's own.
- `--note SIDE:LINE=TEXT` puts a numbered marker on line LINE of the `old` or `new` file, with
  TEXT in the notes list. Markers are numbered from the top; `backticks` in TEXT become `code`.
  Repeat it for each marker.
- `--out FILE` writes the fragment there instead of stdout.

Exit codes: 0 fragment written, 1 invalid input (reason on stderr), 2 usage error.

The output is a `pre.code.diff` (GitHub's red and green, old and new line numbers, changed words
tinted darker) followed by the `ol.markers` list. Paste it into the `.visual` of a `.fig.wide`
row, between `<!-- generated: … -->` and `<!-- end generated: diff_html.py -->` comments that
record the command. The caption's reading points say red is removed, green is added, and which
column numbers which file.

### Boxes-and-arrows, cross-section, mass diagram, collapse

Hand-built HTML boxes and inline SVG inside a `.figframe`. The gallery has no example of these
four. Build the figure from the scaffold's tokens and classes (`.figframe`, `.fig`, the callouts)
to the family's description in [VISUAL-LANGUAGE.md](VISUAL-LANGUAGE.md#families), then run the
render check and read its page screenshots.

- Colour SVG with `var(--token)` from [VISUAL-LANGUAGE.md](VISUAL-LANGUAGE.md#colour-roles).
- Text inside a box fits the box at 768px; the screenshot is the only check.
- A collapse shows the before and after states side by side, or toggles between them with
  inline JS.

### Callouts

```html
<p class="callout note"><b>Note.</b> This flow follows ADR-0012.</p>
<p class="callout problem"><b>Problem.</b> The cache never expires.</p>
```

The scaffold prefixes "Problem." with ✕. Use a note for an ADR citation or an aside, and a
problem for a defect the dossier found.

## Libraries

The scaffold pins every library on `cdn.jsdelivr.net`; the render check fails any other host and
any unpinned version.

| Library | Version | Loaded as |
|---|---|---|
| Mermaid | 11.17.2, `dist/mermaid.esm.min.mjs` | ES module |
| Vega | 6.4.0 | classic script |
| Vega-Lite | 6.5.0 | classic script |
| Vega-Embed | 7.3.0 | classic script, after the two above |

- Mermaid runs with `startOnLoad: false` and `securityLevel: "strict"`; `await mermaid.run()` is
  the last line of the module script.
- Vega embeds use `renderer: "svg"` and `actions: false`.
- Delete a library's script tags when the dossier has no figure that uses it.

## Interactivity

Inline vanilla JS only. The scaffold already wires click-to-sort on `table.sortable`, the
`details.more` row toggle, and the current-section tracker.

A tab or toggle that hides panels with `hidden` or `display: none` must let Mermaid draw first.
Leave every panel visible in the markup, run Mermaid, then hide the inactive panels:

```html
<script type="module">
  // after mermaid.initialize(...) in the scaffold's module script
  await mermaid.run();
  showTab("before");
</script>
<script>
  function showTab(id) {
    document.querySelectorAll("[data-tab]").forEach((p) => (p.hidden = p.dataset.tab !== id));
  }
</script>
```

The render check opens hidden panels the way a reader would, so a diagram drawn while hidden
fails it.

## The render check

`scripts/check_render.py` renders the page in headless Chromium at 768, 1200, 1280 and 1440px and
prints JSON, then the verdict. `--shots DIR` moves the screenshots from `<report-stem>-check/`.

Each of these is a problem, and any problem makes the verdict `FAIL`:

- No answer box, or Limits missing or not the last section.
- A figure or table without a numbered caption, or numbered out of order.
- A Mermaid diagram that is not a sequence diagram.
- A DAG of 16 or more nodes.
- A changed locked block.
- A script host other than `cdn.jsdelivr.net`, or a version that is not an exact x.y.z pin.
- A page or figure wider than its frame at any of the four widths.
- A diagram, chart or DAG that drew wrong: a parse error, empty, clipped or illegible.

`BLOCKED` means the environment kept the check from running: no Playwright or Chromium, or the
CDN unreachable. A missing scaffold leaves the locked block unverified, not blocked.

Each of these is a warning, which the agent resolves or names at handover:

- A heading not in sentence case.
- A DAG of 12 to 15 nodes.
- A code block that scrolls sideways inside `pre.code`.
- A figure without a "So what" box.
- Small text, or a paragraph over 60 words.
- Banned words from [WRITING.md](WRITING.md).
- Colour misuse: red or amber on a category mark, a side strip on a box.
- A library outside the scaffold's block, or at another version.
