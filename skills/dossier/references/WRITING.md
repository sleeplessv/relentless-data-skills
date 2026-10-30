# Writing a dossier

The words in a dossier: what goes in each slot, how long it runs, and which words stay out. The
figures carry the argument; the prose points at them. Write little and make each sentence state
a fact, a number or a conclusion about this subject.

## Before you write

Resolve the writing skills by locating their installed `SKILL.md` and following symlinks, since
user-invoked skills are absent from the invocable list:

```bash
for s in technical-writing unslop; do
  f=$(find -L "$HOME/.claude/skills" "$HOME/.agents/skills" -path "*/$s/SKILL.md" 2>/dev/null | head -n 1)
  if [ -n "$f" ]; then readlink -f "$f"; else echo "missing: $s"; fi
done
```

The loop uses only `$HOME`, `$s` and `$f`, and always exits 0; a `missing:` line is the signal.
Read each file it prints before writing any prose. The Diátaxis mode is explanation, or
reference when the user asks for one.

If either skill is missing, apply this rule instead and say so at handover:

1. Use short, plain words, one idea per sentence, and the active voice.
2. Make every sentence a fact, number or conclusion specific to this subject; cut the rest.
3. Use no em dashes and no hedges, and none of the banned words below.

Use the project's `GLOSSARY.md` terms exactly when the subject has one.

## Slots

### Answer box

One claim the dossier defends, in one to three sentences, with the numbers that make it true.
An explainer states what the reader will understand that they did not ("The render check fails
on a drawn defect and blocks on an environment fault"). The claim is never a topic or a promise
("This report looks at…").

### Masthead

The kicker names the kind of dossier and the subject. The byline states where every number
comes from and when it was measured: the commit, the date, the source.

### Stats row

Up to four headline numbers, each with a label of a few words. Use it only when the numbers
carry the answer.

### Section headings

Sentence case, carrying the point or the question the section answers ("How the verdict is
decided", "Where the lines live"). No all caps, no title case, no trailing full stop.

### Prose

Up to three sentences before a section's first figure, ending with a pointer to it ("Figure 4
follows one run"). Paragraphs stay under 60 words; the render check warns above that. Cite every
figure and table by number in the prose or bullets.

### Text around figures

Around DAGs and other dense figures, write short bullets (`ul.points`), not a paragraph: what
the graph counts, what an edge means, where the hubs are, which figure draws what. One fact per
bullet, two to four bullets.

### Captions

A caption has two parts:

1. **What it shows**, after the figure number: one sentence ("Every commit that touched the
   skill, oldest first").
2. **How to read it**, in `.how`: one to three short points. Name the encoding (what a colour,
   a dashed line, a symbol or a bar length means), the unit, the scale, and any count that
   explains a total.

The caption never states the conclusion; that goes in the "So what" box.

### So what

One or two sentences: the conclusion the reader should draw from this figure alone. Specific
and checkable against the figure ("Five skills are at the limit and two more are within 3 lines
of it"). Not a restatement of the caption.

### Takeaways

Up to three sentences in `ul.takeaways` at the end of a section that needs them. Each one is a
finding, with its number. Skip takeaways when the "So what" boxes already say it.

### Limits

What the dossier could not establish: diagrams read from source rather than traced, numbers not
re-checked, counting rules that skew a total, areas not explored. One item per line. When there
are none, write "None" and keep the section.

## Figure numbering

Figures and tables count separately, each from 1, in the order they appear on the page. Figure 3
never appears above Figure 2; the render check fails it. Renumber after moving a figure, and
update every reference in prose, captions and the sidebar list.

## Length

A dossier the size of the gallery (eight sections, nine figures, two tables) runs to about
1,100 words of prose, counting the answer, stats labels, prose, bullets, captions, "So what"
boxes, takeaways, code markers and Limits. Tables, code and timelines do not count. If a section
needs a paragraph to be understood, redraw its figure instead.

## Sources

Every number and every claim traces to the repo, the conversation or a named source. Cut a
sentence you cannot source. Write facts in your own words; source material often carries the
banned words below, and copying them in is the most common way they reach a dossier.

## Banned words

The list lives in one place: the `SLOP` pattern in `scripts/check_render.py`. Read it before you
write; the render check warns on each match. Replace each banned word with the plain word or the
fact it stands for.

Also judge "landscape" by hand. In its abstract sense ("the tooling landscape") it is banned too,
but a regex cannot tell that use from a literal one, so the check leaves it to you.

Also keep out: em dashes, "serves as" and "stands as" for "is", "not just X but Y", chatbot
phrases, and generic conclusions ("The future looks bright").
