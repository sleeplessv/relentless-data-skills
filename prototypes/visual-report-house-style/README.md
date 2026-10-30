# PROTOTYPE, throwaway: visual-report house style

This branch (`prototype/visual-report-house-style`) keeps the prototypes from the
house-style redesign of the `visual-report` skill as a primary source. It is not
meant to merge into `main`. `main` gets only the validated decision.

The skill is being renamed from `visual-report` to `dossier`. The prototypes still
say "visual report" because they were built before the rename.

## The question

What should a visual report look like so that reports are sharper, clearer, and
consistent from one document to the next? Every prototype renders the same report,
built only from facts about this repo (see `content.md`).

## How to open

Open `prototypes.html` in a browser. It is a gallery that lists every prototype in
decision order and shows each one in an iframe. Each variant has a floating
"← All prototypes" pill that links back to the gallery. All pages sit side by side
in this folder, so the relative links work from a plain checkout. The pages load
Mermaid and Vega-Lite from CDNs, so they need a network connection.

## Decision tree

1. **Structure.** Three layouts of one report:
   - `variant-a.html`, A. Editorial: rejected.
   - `variant-b.html`, B. Dossier: **chosen**. Sticky sidebar, dense reading aids,
     working sticky headers.
   - `variant-c.html`, C. Brief: rejected.
2. **Revisions of B.** User feedback on B: too cold, low-contrast captions, code
   needs colour. Both revisions were superseded by the palette round:
   - `variant-b1.html`, B1. Warm paper with a teal accent: superseded.
   - `variant-b2.html`, B2. Cool paper with a dark sidebar: superseded.
3. **Palettes.**
   - `palette-test-v1.html`, round 1 (oxblood, brass, forest and copper, navy and
     gold): rejected.
   - `palette-test.html`, round 2 (Navy & coral, Green–blue ramp, Sky & amber,
     Relentless Data): **Navy & coral chosen**, with the answer box taken from the
     Green–blue ramp palette.
4. **Navy & coral.**
   - `variant-navy-coral.html`: the Dossier layout in Navy & coral with the
     Green–blue ramp answer box. Superseded by v2.
   - `variant-navy-coral-v2.html`: **current**. Diffs use GitHub's light diff
     colours (green and red, Figure 8). Code annotations use a navy margin marker
     and a slate line tint. DAG nodes (Figure 3) are hand-built SVG with type badges.

## Files

| Path | What it is |
|---|---|
| `prototypes.html` | Gallery of every prototype, in decision order |
| `variant-*.html`, `palette-test*.html` | The prototypes listed above |
| `content.md` | The report's facts, all sourced from this repo |
| `handoff.md` | The design record: decisions, verifier findings, the user's feedback. One line naming a client report was redacted at capture |
| `generators/gen-a/` | Generator for variant A (`gen.py`, `data.py`, `template.html`) |
| `generators/gen-b/` | Generator for variant B |
| `generators/gen-b1/`, `generators/gen-b2/` | Generators for B1 and B2 |
| `generators/work-c/` | Generator for variant C |
| `generators/gen-c/` | Generator for `variant-navy-coral.html`, plus its contrast check |
| `generators/gen-c2/` | Generator for `variant-navy-coral-v2.html` (`v2parts.py` builds the diff and the SVG DAG nodes) |
| `generators/palette/` | `contrast.py` (round 2) and `contrast_v1.py` (round 1): palette tokens, WCAG contrast check, and the palette-test pages |
| `generators/gallery/` | Render check for the gallery and the script that patched the switcher pill |
| `screenshots/` | Key 1440px screenshots of v2 (DAG, diff, code figure) and of the gallery |

## Caveats

- The generators use absolute paths into the original session scratchpad
  (`/private/tmp/claude-501/.../scratchpad/...`) and into the main checkout. They
  were copied unchanged and will not run from here without editing those paths.
  The HTML pages in this folder are the generated output and need no generator.
- Screenshot folders, logs, backups and `__pycache__` were left out.
- No client material is included.
