# Visual language

The named visual families a dossier draws from, how to pick one, and which colour token plays
which role. Build recipes are in [HTML-REPORT.md](HTML-REPORT.md); a worked example of each
family is in `assets/gallery.html`. Reach for a family below before inventing a shape, and call
each family by its name here.

## Families

| Family | The message it carries | Built with |
|---|---|---|
| **Data table** | Many items compared on the same attributes, for lookup | `table.data` |
| **Axis chart** | A trend, distribution or comparison that needs an axis: bar, line, scatter, small multiples | Vega-Lite |
| **Proportion bars** | One number per item, where the magnitude is the point; up to about 12 bars | `.bars` |
| **DAG** | What depends on, calls, reads or runs what | `scripts/dag_svg.py` |
| **Sequence diagram** | Messages between actors, in order | Mermaid `sequenceDiagram` |
| **Timeline** | Dated events, with one key event | `ol.timeline` |
| **Comparison matrix** | Options or conditions against criteria, with a mark per cell | `table.data.matrix` |
| **Annotated code excerpt** | What specific lines of real source do | `pre.code` |
| **Diff** | How a file changed, line by line | `pre.code.diff` from `scripts/diff_html.py` |
| **Boxes-and-arrows** | A few parts where one dominates; deliberate layout and weight | hand-built HTML and inline SVG |
| **Cross-section** | The layers a request or process passes through | hand-built stacked bands |
| **Mass diagram** | Surface area against substance (shallow against deep) | hand-built paired rectangles |
| **Collapse** | Many parts that become one | hand-built, with a before and after state |

Not in the language, by decision: flowcharts drawn by Mermaid, state diagrams, ER diagrams,
pan-and-zoom, syntax highlighting.

## Picking a family

Ask what the reader must see, then take the first match:

1. **What depends on what** → DAG. More than about 11 nodes → merge sibling sets into group nodes
   or draw the two-hop neighbourhood of the subject, and put every node in a data table.
2. **Who sends what to whom, in order** → sequence diagram. More than about 12 messages → split
   into two figures at a natural phase boundary.
3. **When things happened** → timeline.
4. **How big each number is** → proportion bars for one number per item; axis chart when the
   reader needs gridlines, a trend over time, two variables, or more than about 12 items.
5. **How options compare on criteria** → comparison matrix.
6. **Look up any of many items** → data table.
7. **What this code does** → annotated code excerpt. **How it changed** → diff.
8. **How a structure is shaped** (weight, layers, depth, consolidation) → boxes-and-arrows,
   cross-section, mass diagram or collapse.
9. **Before against after** → two of the above side by side in one figure, or a collapse.

Vary the families across a dossier. A dossier where every figure is a table or every figure is
a DAG reads as generic; match the shape to the idea.

## Colour roles

The scaffold's `:root` holds every colour. A figure uses `var(--token)` or a scaffold class,
never a literal colour. The rules that govern colour are the house rules in `SKILL.md`; this
table says which token carries each role.

| Token | Value | Role |
|---|---|---|
| `--paper` | `#ffffff` | Page and figure frames |
| `--ink` | `#102542` | Text, structure, the first chart series, filled markers |
| `--surface` | `#f4f7f7` | Sidebar, "So what" box, takeaways, DAG canvas, stats |
| `--muted` | `#5f5348` | Caption reading points, labels, metadata. The lightest text colour allowed |
| `--line`, `--line-2` | `#e1e7e7`, `#d3dcdc` | Table rules and dividers |
| `--rule` | `#7b8786` | DAG edges and node borders |
| `--coral` | `#f87060` | Fill only, with ink text on it: the at-limit bar, the key timeline dot, the current section number |
| `--coral-text` | `#c2493a` | Coral as text on white: figure and section numbers, small labels |
| `--coral-line` | `#d95646` | Coral as a line, bullet or the second chart series |
| `--coral-soft` | `#fff1ed` | Coral tint: the DAG focus node, the key timeline row, row hover |
| `--code-*` | teal family, `--code-fg` `#24514e` on `--code-bg` `#eef3f3` | Code panels, gutters and inline `code` |
| `--code-mark`, `--code-mark-gutter` | `#e3e9f2`, `#d5deeb` | Slate tint on an annotated code line |
| `--red`, `--red-soft`, `--red-text` | `#a3123a`, `#fbe7ec`, `#8c0f32` | Problems only: `.callout.problem`, a FAIL mark |
| `--amber`, `--amber-soft`, `--amber-text` | `#b7791f`, `#fcf2dd`, `#714800` | Callouts only: `.callout.note`, ADR citations |
| `--sage`, `--taupe` | `#4f7f7c`, `#8a7766` | Third and fourth chart series; taupe also marks an "other" bucket |
| `--gh-*` | GitHub light theme | Added, removed and hunk lines inside a diff, nowhere else |
| `--ans-*` | `#ffffff` bg, `#184e77` border, `#1a759f` label, `#102a3f` text | The answer box only |

DAG node-type badges use six slots, `--tag-1` to `--tag-6`: `#102542`, `#4f7f7c`, `#1a759f`,
`#5f5348`, `#24514e`, and `#4a5755` as an outline badge on paper. `dag_svg.py` gives each node
type a slot in legend order and emits the classes `g.dn.tag-N` on the node and
`span.tgk.tag-N` in the legend. The subject node takes `.focus` (coral) instead of its slot
colour. Never set these colours by hand.

### Chart series

Categorical marks use these four, in this order, and no others:

1. `#102542` (ink)
2. `#d95646` (coral line)
3. `#4f7f7c` (sage)
4. `#8a7766` (taupe)

A single-series chart is ink. To single out one mark, colour it coral line and leave the rest
ink. More than four categories → group the tail as "other" in taupe, or use small multiples.
Red and amber never colour a category, a DAG node or a bar.

## Size limits

| Visual | Limit | Past the limit |
|---|---|---|
| DAG | About 11 nodes drawn. `dag_svg.py` warns above 11 and refuses 16 or more; the render check warns at 12 to 15 and fails at 16 | Merge siblings into a group node, or draw the neighbourhood; caption says "N of M nodes drawn" |
| Sequence diagram | About 12 messages | Split into two figures |
| Data table | 20 visible rows | Rest behind `details.more`, which states the hidden count. Over 200 rows is a data file, not a table |
| Proportion bars | About 12 bars | Axis chart, or top N plus "other" |
| Any figure | The width of its container at 768, 1200, 1280 and 1440px | Change the layout; a figure wider than its container, or clipped by it, fails the check. A code block may scroll inside `pre.code`; the check only warns |
