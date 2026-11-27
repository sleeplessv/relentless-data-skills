"""The entry check: does a ticket hold what a run needs (#231 rules 1, 2 and 48; #256 rule 20)?

`check(body, comments)` is the one function. `start` calls it for one ticket; the start-author
script of a later stage is to call it for each ticket of a multi-ticket run.

A criterion is a list item (checkbox, bullet or number) under a heading whose text is
`Acceptance criteria`, `Acceptance` or `Done when`, in any case and at any level, or under a
bold line with that text such as `**Acceptance criteria:**`, the form Agent Briefs use. A
heading's section ends at the next heading of the same or a higher level; a bold line's ends at
the next heading or bold line. Several sections are read in the order they appear, and their
items are numbered R1 on. An indented line, or a nested item, joins the item above it. A line
inside a code fence is never an item.

When a comment holds an `Agent Brief` heading, the newest such comment's criteria replace the
body's. A ticket has a gap when neither the body nor the brief used has text saying what to
build (a line outside the criteria sections that is not a heading), and when it has no
criterion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NAMES = ("acceptance criteria", "acceptance", "done when")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BOLD = re.compile(r"^ {0,3}\*\*(.+?)\*\*\s*:?\s*$")
ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*\S)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
BRIEF = "agent brief"
BOLD_LEVEL = 7  # below every heading, so any heading or bold line ends a bold line's section
NO_TEXT = "it has no text saying what to build"
NO_CRITERION = ("it has no criterion: no list item under a heading Acceptance criteria, Acceptance or "
                "Done when, in the body or in the newest Agent Brief comment")


@dataclass
class Entry:
    requirements: list[str]
    gaps: list[str]
    quote: str  # the body above its first criteria heading


@dataclass
class _Read:
    items: list[str]
    prose: bool
    first: int | None  # the line index of the first criteria heading


def check(body: str, comments: list[str]) -> Entry:
    """The ticket's requirements in order, its gaps, and the body above its criteria."""
    read = _read(body)
    briefs = [c for c in comments if any(_name(_heading(line)) == BRIEF for line in c.splitlines())]
    items, prose = read.items, read.prose
    if briefs:
        brief = _read(briefs[-1])
        items, prose = brief.items, prose or brief.prose
    gaps = ([] if prose else [NO_TEXT]) + ([] if items else [NO_CRITERION])
    quote = "\n".join(body.splitlines()[:read.first]).strip("\n")
    return Entry(items, gaps, quote)


def _read(text: str) -> _Read:
    items: list[str] = []
    prose, first = False, None
    section: int | None = None  # the level of the criteria section the line is in
    base: int | None = None  # the indent of the section's first item
    current = False  # whether a line may join the last item
    fenced = False
    for index, line in enumerate(text.splitlines()):
        if FENCE.match(line):
            fenced, current = not fenced, False
            continue
        heading = None if fenced else _heading(line)
        if heading:
            level = heading[0]
            if section is not None and level <= section:
                section = None
            if _name(heading) in NAMES:
                section, base, current = level, None, False
                first = index if first is None else first
            continue
        if not line.strip():
            continue
        if section is None:
            prose = True
            continue
        item = None if fenced else ITEM.match(line)
        indent = len(line) - len(line.lstrip())
        if item and (base is None or indent <= base):
            base = indent if base is None else base
            items.append(item.group(2))
            current = True
        elif current and indent > (base or 0):
            items[-1] += " " + line.strip()
        else:
            current = False
    return _Read(items, prose, first)


def _heading(line: str) -> tuple[int, str] | None:
    if found := HEADING.match(line):
        return len(found.group(1)), found.group(2)
    if found := BOLD.match(line):
        return BOLD_LEVEL, found.group(1)
    return None


def _name(heading: tuple[int, str] | None) -> str | None:
    return heading[1].strip().rstrip(":").strip().lower() if heading else None
