# Visual Language

A small glossary of the diagram patterns this skill uses. Name them consistently — when you decide how to visualize something, reach for one of these before inventing a new shape. Recipes for each are in [HTML-REPORT.md](HTML-REPORT.md).

- **Mermaid graph** — a `flowchart`/`graph`/`sequenceDiagram` for graph-shaped relationships: call flow, dependencies, round-trips. The workhorse. Use when the point is "X connects to Y connects to Z."

- **Boxes-and-arrows** — hand-built `<div>`s and inline-SVG arrows. Use when you need visual *weight* Mermaid won't give you — one dominant element, greyed-out internals, deliberate layout.

- **Cross-section** — stacked horizontal bands showing the layers a request/call/process passes through. Use to contrast "many thin layers each doing little" against "one thick band that owns the responsibility."

- **Mass diagram** — paired rectangles for surface area vs substance. Use for "shallow vs deep": a wide surface over little substance, against a small surface over a lot.

- **Collapse** — a nested tree that folds into a single box with its internals faded inside. Use for "all of this becomes one thing." Pairs with a CSS `max-height` transition so the reader can play before→after.

- **Comparison matrix** — a verdict table: options as columns, criteria as rows, compact chips in the cells. Use for "we weighed A against B against C."

- **Timeline** — events on a spine, the pivotal one accented. Use when time order is the message: incidents, rollouts, migrations.

- **Proportion bars** — plain `<div>` bars sized to a value, labelled with the number. Use when a number's magnitude is the message — counts, durations, cost.

## Picking between them

- **Relationships are graph-shaped** (who calls whom, what depends on what, ordering of steps) → **Mermaid graph**.
- **You want editorial weight or a custom layout** Mermaid fights you on → **boxes-and-arrows**, **cross-section**, **mass diagram**, or **collapse**.
- **Weighing options or findings against criteria** → **comparison matrix**.
- **Time order is the message** → **timeline**.
- **A number's magnitude is the message** → **proportion bars**.
- **Before/after is the message** → pair two of the above side by side, or use **collapse** as a single playable visual.

Mix patterns across a report. If every section is a Mermaid flowchart, it reads generic — vary the shape to match the idea.
