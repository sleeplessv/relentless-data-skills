"""The PR description, rendered from a branch's saved records only (#231 rules 15 to 24; #256 rules 33, 34).

`description(folder, ...)` reads the records folder of one branch and returns the whole
description. `pr` calls it with no options and so renders a pending blast radius. `ready` (#423)
is to call it again with the small test's blast radius, the door it settled and the measurement
block. Nobody edits the result by hand.

The record contract this reads, which `start`, `save` and `check` write:

- `request.md`: its first line is the source, exactly one of `Source: ticket #<N>`,
  `Source: conversation` or `Source: working tree, requirements written from the diff`. The
  lines after it are the quote, word for word: for a ticket, its body above the criteria, and the
  owner's answer when the entry check asked. With the working-tree source the quote is empty.
- `summary.md`: the author's Summary, rendered as written.
- `plan.md`: the check plan. Its requirement rows are `| R<n> | <requirement> | <proof> |`; a
  proof that is one code span, such as `` `python3 -m unittest tests.test_x` ``, is a command. Its
  assumptions are the `- ` lines after a line reading `Assumptions`, with their indented continuations, up to the next heading or other unindented
  line. Its door line is
  `door: two-way` or `door: one-way` followed by a one-line reason. A plan with no door line, or
  with another word after `door:`, is one-way (#256 rule 26). A plan with no requirement row, or a
  row without exactly three cells, raises `Unreadable`. `Plan` and `Requirement` have the shape of
  `plan.parse` (#414), so this reader can give way to that one.
- `records.jsonl`: each `check` event's `command`, as `check` saved it, `exit`, `commit` and
  `selected_nothing`. A proof's command matches a check whose `command` is the same text.

Every saved text, and every reason or value given by the caller, is checked for a secret first;
one ends the run with `core.Question`, so nothing is rendered. Requirements and checks are matched
on the original text; only the text shown is masked by `mask.py`, and the source line names what
was masked. A ticket source ends the top part with `Closes #<N>`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import core
import mask

SOURCES = ("conversation", "working tree, requirements written from the diff")
TICKET = re.compile(r"ticket #(\d+)")
ROW = re.compile(r"^\s*\|\s*(R\d+)\s*\|")
DOOR = re.compile(r"^door:\s*(\S+)\s*[-,.;:]?\s*(.*)$", re.IGNORECASE)
COMMAND = re.compile(r"^`([^`]+)`$")
MARKER = "<!-- deliver: rendered from the saved records by deliver.py; a hand edit does not survive -->"
NO_DOOR = "the plan has no door line, so it counts as one-way"
ODD_DOOR = "the plan's door line says neither two-way nor one-way, so it counts as one-way"
PENDING_BLAST = "pending. `deliver.py ready` runs the small test."
# The measurement block's opening and closing lines; `merge` finds the block by them.
MEASUREMENT_OPEN = ("<details><summary>Measurement</summary>", "", "```text")
MEASUREMENT_CLOSE = ("```", "", "</details>")


class Unreadable(Exception):
    """A saved text this module cannot read with certainty; `kind` names the text."""

    def __init__(self, kind: str, why: str):
        self.kind = kind
        super().__init__(why)


@dataclass
class Requirement:
    number: str
    text: str
    proof: str


@dataclass
class Plan:
    """The shape of `plan.parse` (#414), with the assumption lines this module also renders."""

    requirements: list[Requirement]
    door: str
    door_reason: str
    assumptions: list[str] = field(default_factory=list)


def read_source(request: str) -> tuple[str, int | None, str]:
    """The source line's words, the ticket number if any, and the quote of a saved request."""
    first, _, quote = request.partition("\n")
    source = first.removeprefix("Source: ").strip()
    ticket = TICKET.fullmatch(source)
    if not first.startswith("Source: ") or not (ticket or source in SOURCES):
        raise Unreadable("request", f"its first line is not a source line: {first!r}")
    return source, int(ticket.group(1)) if ticket else None, quote.strip("\n")


def read_plan(text: str) -> Plan:
    """The requirements, the door and the assumption lines of a saved check plan.

    A row's cells follow `plan.parse` (#414): a trailing `|` is optional, and `\\|` is a `|`
    inside a cell. The assumption lines are the `- ` lines after a line reading `Assumptions`, each
    with its indented continuation lines, up to the next line that is unindented and not a bullet,
    such as a heading.
    """
    rows, assumptions, door, in_assumptions = [], [], None, False
    for line in text.splitlines():
        if in_assumptions:
            continued = assumptions and line[:1] in (" ", "\t") and line.strip()
            if line.startswith("- ") or continued:
                assumptions.append(line)
                continue
            if not line.strip():
                continue
            in_assumptions = False
        if ROW.match(line):
            cells = _cells(line)
            if len(cells) != 3:
                raise Unreadable("plan", f"a requirement row does not have three cells: {line.strip()!r}")
            rows.append(Requirement(*cells))
        elif line.strip().strip("#:").strip().lower() == "assumptions":
            in_assumptions = True
        elif door is None and (door_line := DOOR.match(line.strip())):
            word = door_line.group(1).lower().rstrip(",.;:")
            door = (word, door_line.group(2)) if word in ("two-way", "one-way") else ("one-way", ODD_DOOR)
    if not rows:
        raise Unreadable("plan", "it has no requirement row such as | R1 | <requirement> | <proof> |")
    return Plan(rows, *(door or ("one-way", NO_DOOR)), assumptions)


def evidence_lines(requirements: list[Requirement], records: list[dict]) -> list[str]:
    """One Evidence line per requirement, from the newest check of its proof's command.

    A counted pass is a check that exited 0, is tied to a commit and selected something; it gives
    `R1: pass at <short sha>`. A failed check tied to a commit gives `fail at`. A command proof
    with no such check is pending; a proof that is not a command gives `no check run`.
    """
    lines = []
    for requirement in requirements:
        rid, command = requirement.number, COMMAND.match(requirement.proof)
        if not command:
            lines.append(f"{rid}: no check run")
            continue
        checks = [r for r in records if r.get("event") == "check" and r.get("command") == command.group(1)]
        last = checks[-1] if checks else None
        if last and last.get("commit") and last.get("exit") == 0 and not last.get("selected_nothing"):
            lines.append(f"{rid}: pass at {last['commit'][:7]}")
        elif last and last.get("commit") and last.get("exit") != 0:
            lines.append(f"{rid}: fail at {last['commit'][:7]}")
        else:
            lines.append(f"{rid}: pending")
    return lines


def description(folder: Path, *, blast: tuple[str, str] | None = None, door: tuple[str, str] | None = None,
                measurement: dict[str, str] | None = None) -> str:
    """The whole PR description from the records folder of one branch.

    `blast` is the small test's (`low` or `high`, reason); without it the blast radius is pending.
    `door` is (door, reason) once `ready` has settled it; without it the plan's door line counts.
    `measurement` is the measurement block's keys and values in order; without it there is none.
    These go through the same secret check and mask as the saved texts.
    """
    texts = {kind: (folder / f"{kind}.md").read_text(encoding="utf-8") for kind in ("request", "summary", "plan")}
    for kind, text in texts.items():
        refuse_secret(f"The saved {kind}.md", kind, text)
    given = {"door reason": door[1] if door else "", "blast radius reason": blast[1] if blast else "",
             **{f"measurement value {key}": value for key, value in (measurement or {}).items()}}
    for name, text in given.items():
        refuse_secret(f"The {name} given to the renderer", name, text)
    source, ticket, quote = read_source(texts["request"])
    plan = read_plan(texts["plan"])
    evidence = evidence_lines(plan.requirements, _records(folder))
    kinds: list[str] = []

    def shown(text: str) -> str:
        masked, found = mask.mask(text)
        kinds.extend(k for k in found if k not in kinds)
        return masked

    door_line = _sentence(*(door or (plan.door, plan.door_reason)), shown)
    blast_line = _sentence(*blast, shown) if blast else PENDING_BLAST
    out = ["## Summary", "", shown(texts["summary"]).strip(), "", "## Evidence", ""]
    out += [f"- {line}" for line in evidence]
    out += ["", "## Merge Danger", "", f"**Door:** {door_line}", "", f"**Blast Radius:** {blast_line}", ""]
    if ticket:
        out += [f"Closes #{ticket}", ""]
    quoted = [f"> {shown(line)}".rstrip() for line in quote.splitlines()]
    table = [f"| {r.number} | {_cell(shown(r.text))} | {_cell(shown(r.proof))} |" for r in plan.requirements]
    assumptions = [shown(line) for line in plan.assumptions]
    block = [f"{key}: {shown(value)}" for key, value in (measurement or {}).items()]
    masked = f" (masked: {' and '.join(kinds)})" if kinds else ""
    out += [MARKER, "", "## Request", "", f"Source: {source}{masked}"]
    if quoted:
        out += [""] + quoted
    out += ["", "## Requirements and check plan", "", "| # | Requirement | Proof |", "|---|---|---|"] + table
    if assumptions:
        out += ["", "Assumptions", ""] + assumptions
    out += ["", "## Findings", "", "No review: small edit."]
    if block:
        out += ["", *MEASUREMENT_OPEN, *block, *MEASUREMENT_CLOSE]
    return "\n".join(out) + "\n"


def refuse_secret(where: str, what: str, text: str) -> None:
    """End the run with a question when the text looks like it holds a secret; never print the text."""
    if secret := mask.find_secret(text):
        raise core.Question(
            f"{where} looks like it holds a secret ({secret[0]}) on line {secret[1]}, so nothing was pushed "
            f"or sent to gh. Is it a real secret that should be taken out of the {what} before the run goes on?")


def _sentence(word: str, reason: str, shown) -> str:
    reason = shown(reason)
    return f"{word}. {reason[:1].upper()}{reason[1:]}" if reason else f"{word}."


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", inner[1:])]


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _records(folder: Path) -> list[dict]:
    path = folder / core.RECORDS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
