# Dossiers share one locked house style

The `dossier` skill (formerly `visual-report`) styled its reports with Tailwind utility classes
and a short style guide. Each run restyled the page, so reports looked generic and differed from
one another. The repo owner's priority is visual presentation and consistency from document to
document. We decided that every dossier starts from one hand-written stylesheet in
`skills/dossier/assets/scaffold.html`. Its locked block (colour tokens, type scale, every
component class) must match the scaffold byte for byte, and the render check fails a dossier
whose locked block differs. A second, marked block holds per-report geometry only. Tailwind is
gone.

## Considered options

- **Tailwind with a shared config preset.** Rejected. Utility classes still let each run compose
  a new look, and nothing checkable stops it.
- **A free stylesheet plus written guidance.** This was the old approach. Rejected: guidance drifts
  run by run, and the reports it produced all looked like default Tailwind pages.
- **A locked, hashed stylesheet.** Chosen. It gives up per-report flexibility for a guarantee the
  render check can enforce.

## Consequences

- The check derives the expected hash from the installed skill's own scaffold at run time, not
  from a stored constant. A palette change is a scaffold edit plus a skill version bump. Dossiers
  written under an older version keep their older look.
- Colour carries fixed roles, written as house rules in `SKILL.md`. Red marks problems only,
  always with ✕ and the word "Problem". Amber marks callouts only. GitHub's light diff colours
  appear only on diff lines, the single exception to "red means a problem". Category fills use
  four chart series. Nothing carries a decorative side strip or accent rule.
- Every text and graphic pair in the tokens must meet WCAG AA. `scripts/check_contrast.py` and its
  guard test fail the build when a scaffold edit breaks a pair, so captions stay readable.
- Figures the script cannot judge (Vega charts, generated SVG, hand-built shapes) still need the
  agent to read the screenshots. The lock fixes the style, not the content.

## Static-SVG DAGs

Dependency graphs are static SVG from `scripts/dag_svg.py`, which uses the locked classes and no
literal colours. Mermaid stays for sequence diagrams only, and ELK layout is dropped.

During prototyping, a 56-node graph laid out 1,900 to 2,800px wide under every engine, Mermaid
and ELK included. It was clipped or shrunk past legibility, and the engine's styling ignored the
palette. The generator caps a figure at about 11 drawn nodes: it warns above 11 and refuses 16 or
more. Larger graphs merge sibling sets into dashed group nodes or show the subject's two-hop
neighbourhood. The caption states how many nodes are drawn of the total, and a data table lists
every node.

The trade-off: no automatic layout of large graphs, and an author who must decide what to merge.
We accept it because a legible 11-node picture with a complete table beside it tells the reader
more than a complete picture they cannot read.

## Status

Accepted.
