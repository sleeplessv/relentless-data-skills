# Writing a dossier

The words in a dossier: what goes in each slot, how long it runs, and which words stay out. The
figures carry the argument; the prose points at them. Write little and make each sentence state
a fact, a number or a conclusion about this subject.

## Sentences

Write in the explanation mode: say what the evidence means and which way it points. Switch to
reference, which only describes, when the user asks for one. These rules apply to every slot:

1. Use the short, everyday word, one idea per sentence, and about 25 words at most. Split a
   sentence that carries two ideas.
2. Name the actor in the active voice: "the render check fails it", not "it is failed".
3. Call each thing by its real name (the file, command, table or flag) and keep that one name
   throughout. Use the project's `GLOSSARY.md` terms exactly when the subject has one. Make every
   "it" and "this" point at one obvious noun, and repeat the noun when in doubt.
4. Name the mechanism or the number, not the feeling: "a column rename fails the build", not
   "schema changes can cause issues". A sentence that could appear unchanged in another dossier
   says nothing about this subject; cut it.
5. State facts plainly and replace an adverb with its number: "the build takes 40 s", not "the
   build runs quickly". Hedge only a claim the Limits section names as unchecked.
6. Write whole sentences with their articles and verbs, captions and bullets included. Spell out
   arrows and abbreviations.

For general prose beyond dossiers, the `technical-writing` and `unslop` skills go further, if
installed.

## Slots

### Answer box

One claim the dossier defends, in one to three sentences, with the numbers that make it true.
An explainer states what the reader will understand that they did not ("The render check fails
on a drawn defect and blocks on an environment fault"). The claim is never a topic or a promise
("This report looks at…").

`.claim` holds the claim in one or two sentences; `.rest` holds any qualifying sentences in
normal weight. Add the lead number when one figure carries the answer ("0/18", "4.2×"), with a
unit label of a few words saying what it counts. Leave it out when the answer is qualitative or
no single number sums it up.

### Key findings

Three to five findings, one sentence each, in the order their sections appear. Each states a
concrete result with the number that makes it true ("Five of 18 SKILL.md files sit exactly on
the 150-line budget"), never the section's topic ("The 150-line budget"). Together they are what
a reader keeps after reading only the top of the page, so pick the findings that carry the
answer, not one per section. Link each to the section holding its evidence.

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

The caption never states the conclusion; that goes in the "So what".

### So what

The conclusion the reader should draw from this figure alone, set large as a pull quote above
the caption. Specific and checkable against the figure. Not a restatement of the caption.

- `.claim` is one sentence of 20 words or fewer, so it reads at display size ("Five skills are
  at the 150-line limit"). The render check warns above 20.
- Wrap the one key figure or phrase in `<em>`, which sets it in coral: `<em>Five skills</em>`.
  One at most, and none when no single figure carries the point.
- `.rest` is optional: one sentence of supporting detail in normal type ("Two more are within
  3 lines of it").

### Takeaways

Up to three sentences in `ul.takeaways` at the end of a section that needs them. Each one is a
finding, with its number. Skip takeaways when the "So what" claims already say it.

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
1,100 words of prose, counting the answer, key findings, stats labels, prose, bullets, captions, "So what"
claims, takeaways, code markers and Limits. Tables, code and timelines do not count. If a section
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
