"""The entry check: does a ticket hold what a run needs (#231 rules 1, 2 and 48; #256 rule 20)?

`check(body, comments)` is the one function. `start` calls it for one ticket; the start-author
script of a later stage is to call it for each ticket of a multi-ticket run.

A criterion is a list item (checkbox, bullet or number) under a heading whose text is
`Acceptance criteria`, `Acceptance` or `Done when`, in any case and at any level, or under a
bold line with that text such as `**Acceptance criteria:**`, the form Agent Briefs use. A
heading's section ends at the next heading of the same or a higher level; a bold line's ends at
the next heading or bold line; when a criteria section nested in another ends, the outer one
goes on. Several sections are read in the order they appear, and their items are numbered R1 on.
An indented line, or a nested item, joins the item above it. A line that is not part of an item
ends the list, and a list after it starts at its own indent. An item with no text once its
`[ ]` or `[x]` is dropped is no criterion. HTML comments are not read. A line inside a code
fence, from an opening run of three or more backticks or tildes to a run of the same character
at least as long, is never read as an item or a criteria heading.

When a comment holds an `Agent Brief` heading, the newest such comment's criteria replace the
body's. A ticket has a gap when neither the body nor the brief used has text saying what to
build (a line that is not a heading, a criterion or a comment, such as prose above a criteria
list), and when it has no criterion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NAMES = ("acceptance criteria", "acceptance", "done when")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BOLD = re.compile(r"^ {0,3}\*\*(.+?)\*\*\s*:?\s*$")
ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])(?:\s+(?:\[[ xX]\](?!\S))?(.*))?$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
COMMENT = re.compile(r"<!--.*?-->", re.S)
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
    sections: list[int] = []  # the levels of the criteria sections the line is in, outermost first
    base: int | None = None  # the indent of the current list's first item
    current = False  # whether a line may join the last item
    fence: str | None = None  # the run of backticks or tildes that opened the fence the line is in
    text = COMMENT.sub(lambda found: "\n" * found.group().count("\n"), text)  # keeps line numbers
    for index, line in enumerate(text.splitlines()):
        if found := FENCE.match(line):
            run, rest = found.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not rest.strip():
                fence = None
            current = False
            continue
        heading = None if fence else _heading(line)
        if heading:
            level = heading[0]
            while sections and sections[-1] >= level:
                sections.pop()
            if _name(heading) in NAMES:
                sections.append(level)
                first = index if first is None else first
            base, current = None, False
            continue
        if not line.strip():
            continue
        item = ITEM.match(line) if sections and not fence else None
        indent = len(line) - len(line.lstrip())
        if item and (base is None or indent <= base):
            base, current = indent if base is None else base, False
            if words := (item.group(2) or "").strip():
                items.append(words)
                current = True
        elif current and indent > base:
            items[-1] += " " + line.strip()
        else:
            prose, base, current = True, None, False
    return _Read(items, prose, first)


def _heading(line: str) -> tuple[int, str] | None:
    if found := HEADING.match(line):
        return len(found.group(1)), found.group(2)
    if found := BOLD.match(line):
        return BOLD_LEVEL, found.group(1)
    return None


def _name(heading: tuple[int, str] | None) -> str | None:
    return heading[1].strip().rstrip(":").strip().lower() if heading else None
