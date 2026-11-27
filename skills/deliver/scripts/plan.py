"""The check plan's reader: each requirement with its proof, and the door (#256 rules 24, 26; #231 rule 19).

The author writes the plan once, as `.deliver/plan.md`, and `deliver.py save plan` keeps it word
for word. Only two parts of it are read, and only in this form:

- One table whose header is `| # | Requirement | Proof |`, then a separator row, then one row
  per requirement up to the first line that does not start with `|`. Each row has three cells,
  numbered `R1`, `R2`, ... in order; a `|` inside a cell is written `\\|`. A proof cell that is
  empty or only dashes is no proof, which `save plan` refuses.
- At most one door line: `door: two-way` or `door: one-way`, a separator (` — `, ` – `, ` - `,
  `: `, `; ` or `, `) and a one-line reason. With no door line the door is one-way.

Anything else (a heading, the assumptions, notes) is kept and not read, and neither part is
looked for inside a fenced code block (``` or ~~~). Text that looks like either part but does
not fit raises `PlanError` rather than being guessed at.

`read(run)` reads the saved plan of the run's branch. `ready` (#423), the small test (#422) and the
PR description (#415) are to call it for the requirements, their proofs and the door; for now
only the tests do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import core

HEADER = ["#", "Requirement", "Proof"]
SEPARATOR = re.compile(r"\|(?:\s*:?-+:?\s*\|){2}\s*:?-+:?\s*\|?")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
DOOR = re.compile(r"door: (two-way|one-way)(?: [—–-] |[:;,] )(\S.*)")
LOOKS_LIKE_DOOR = re.compile(r"^\W*door\s*[:=-]", re.I)
NO_PROOF = re.compile(r"[-–—]*")
NO_DOOR_LINE = "the plan has no door line"
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


class PlanError(Exception):
    """The plan cannot be read with certainty."""


@dataclass
class Requirement:
    number: str
    text: str
    proof: str


@dataclass
class Plan:
    requirements: list[Requirement]
    door: str
    door_reason: str


def cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip().replace("\\|", "|") for c in CELL_SPLIT.split(inner[1:])]


def fenced(lines: list[str]) -> set[int]:
    """The numbers of the lines in fenced code blocks, fences included; an open fence runs to the end."""
    inside, fence = set(), None
    for i, line in enumerate(lines):
        found = FENCE.match(line)
        if fence is None:
            if found:
                fence = found[1]
                inside.add(i)
            continue
        inside.add(i)
        if found and found[1][0] == fence[0] and len(found[1]) >= len(fence) and not line[found.end():].strip():
            fence = None
    return inside


def parse(text: str) -> Plan:
    lines = text.splitlines()
    skip = fenced(lines)
    heads = [i for i, line in enumerate(lines)
             if i not in skip and line.lstrip().startswith("|") and cells(line) == HEADER]
    if len(heads) != 1:
        raise PlanError(f"the plan needs one table headed | {' | '.join(HEADER)} |, and it has {len(heads)}")
    first = heads[0] + 1
    if first >= len(lines) or not SEPARATOR.fullmatch(lines[first].strip()):
        raise PlanError(f"line {first + 1}: the table's header is not followed by a separator row")
    requirements = []
    for i in range(first + 1, len(lines)):
        if not lines[i].lstrip().startswith("|"):
            break
        row = cells(lines[i])
        want = f"R{len(requirements) + 1}"
        if len(row) != 3:
            raise PlanError(f"line {i + 1}: a row has 3 cells, and this one has {len(row)}")
        if row[0] != want:
            raise PlanError(f"line {i + 1}: the requirement is numbered {row[0]!r}, where {want} comes next")
        if not row[1]:
            raise PlanError(f"line {i + 1}: {want} has no requirement text")
        requirements.append(Requirement(want, row[1], "" if NO_PROOF.fullmatch(row[2]) else row[2]))
    if not requirements:
        raise PlanError("the table has no requirement")
    doors = [(i, line) for i, line in enumerate(lines) if i not in skip and LOOKS_LIKE_DOOR.match(line)]
    if not doors:
        return Plan(requirements, "one-way", NO_DOOR_LINE)
    if len(doors) > 1:
        raise PlanError(f"the plan has {len(doors)} door lines, on lines {', '.join(str(i + 1) for i, _ in doors)}")
    i, line = doors[0]
    found = DOOR.fullmatch(line.rstrip())
    if not found:
        raise PlanError(f"line {i + 1}: the door line reads 'door: two-way' or 'door: one-way', a separator and a reason")
    return Plan(requirements, found[1], found[2])


def read(run: core.Run) -> Plan | None:
    """The saved plan of the run's branch, or None when no plan is saved."""
    path = core.records_dir(run.common_dir, run.mark["branch"]) / "plan.md"
    if not path.is_file():
        return None
    return parse(path.read_text(encoding="utf-8"))
