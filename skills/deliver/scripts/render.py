"""The PR description, rendered from a branch's saved records only (#231 rules 15 to 24; #256 rules 33, 34).

`description(folder, ...)` reads the records folder of one branch and returns the whole
description. `pr` calls it with no options and so renders a pending blast radius; `ready` calls it
again with the small test's blast radius, the door it settled and the measurement block. Nobody
edits the result by hand.

The record contract this reads, which `start`, `save` and `check` write:

- `request.md`: its first line is the source, exactly one of `Source: ticket #<N>`,
  `Source: conversation` or `Source: working tree, requirements written from the diff`. The
  lines after it are the quote, word for word: for a ticket, its body above the criteria, and the
  owner's answer when the entry check asked. With the working-tree source the quote is empty.
- `summary.md`: the author's Summary, rendered as written.
- `plan.md`: the check plan. Its requirement rows are `| R<n> | <requirement> | <proof> |`; a
  proof that is one code span, such as `` `python3 -m unittest tests.test_x` ``, is a command. Its
  assumptions are the `- ` lines after a line reading `Assumptions`. Its door line is
  `door: two-way` or `door: one-way` followed by a one-line reason. A plan with no door line, or
  with another word after `door:`, is one-way (#256 rule 26). A plan with no requirement row, or a
  row without exactly three cells, raises `Unreadable`. `Plan` and `Requirement` have the shape of
  `plan.parse` (#414), so this reader can give way to that one.
- `records.jsonl`: each `check` event's `command`, as `check` saved it, `exit`, `commit` and
  `selected_nothing`. A proof's command matches a check whose `command` is the same text.

Every saved text is checked for a secret first; one ends the run with `core.Question`, so nothing
is rendered. Every saved text is then masked by `mask.py`, and the source line names what was
masked. A ticket source ends the top part with `Closes #<N>`.
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
    """The requirements, the door and the assumption lines of a saved check plan."""
    rows, assumptions, door, in_assumptions = [], [], None, False
    for line in text.splitlines():
        if ROW.match(line):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])]
            if len(cells) != 3 or not line.strip().endswith("|"):
                raise Unreadable("plan", f"a requirement row does not have three cells: {line.strip()!r}")
            rows.append(Requirement(*(c.replace("\\|", "|") for c in cells)))
        elif line.strip().strip("#:").strip().lower() == "assumptions":
            in_assumptions = True
        elif in_assumptions and line.startswith("- "):
            assumptions.append(line)
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
    `door` is (door, reason) when `ready` settled it; without it the plan's door line counts.
    `measurement` is the measurement block's keys and values in order; without it there is none.
    """
    texts = {kind: (folder / f"{kind}.md").read_text(encoding="utf-8") for kind in ("request", "summary", "plan")}
    for kind, text in texts.items():
        if secret := mask.find_secret(text):
            raise core.Question(
                f"The saved {kind}.md looks like it holds a secret ({secret[0]}) on line {secret[1]}, so "
                f"nothing was pushed or sent to gh. Is it a real secret that should be taken out of the "
                f"{kind} before the run goes on?")
    masked_kinds = []
    for kind in texts:
        texts[kind], found = mask.mask(texts[kind])
        masked_kinds += [k for k in found if k not in masked_kinds]
    source, ticket, quote = read_source(texts["request"])
    plan = read_plan(texts["plan"])
    door_line = _sentence(*(door or (plan.door, plan.door_reason)))
    blast_line = _sentence(*blast) if blast else PENDING_BLAST
    records = _records(folder)
    masked = f" (masked: {' and '.join(masked_kinds)})" if masked_kinds else ""

    out = ["## Summary", "", texts["summary"].strip(), "", "## Evidence", ""]
    out += [f"- {line}" for line in evidence_lines(plan.requirements, records)]
    out += ["", "## Merge Danger", "", f"**Door:** {door_line}", "",
            f"**Blast Radius:** {blast_line}", ""]
    if ticket:
        out += [f"Closes #{ticket}", ""]
    out += [MARKER, "", "## Request", "", f"Source: {source}{masked}"]
    if quote:
        out += [""] + [f"> {line}".rstrip() for line in quote.splitlines()]
    out += ["", "## Requirements and check plan", "", "| # | Requirement | Proof |", "|---|---|---|"]
    out += [f"| {r.number} | {_cell(r.text)} | {_cell(r.proof)} |" for r in plan.requirements]
    if plan.assumptions:
        out += ["", "Assumptions", ""] + plan.assumptions
    out += ["", "## Findings", "", "No review: small edit."]
    if measurement:
        out += ["", "<details><summary>Measurement</summary>", "", "```text"]
        out += [f"{key}: {value}" for key, value in measurement.items()]
        out += ["```", "", "</details>"]
    return "\n".join(out) + "\n"


def _sentence(word: str, reason: str) -> str:
    return f"{word}. {reason[:1].upper()}{reason[1:]}" if reason else f"{word}."


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _records(folder: Path) -> list[dict]:
    path = folder / core.RECORDS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
