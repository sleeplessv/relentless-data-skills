"""The reviewers' reports and their findings: the report form, each finding's number, scope, proof and state.

`brief`, `save` and `render` call this module, and none of them works out a finding's scope,
proof or state itself (spec #479, Layout).

The report form (#231 rule 29). A reviewer's final message is its report, one line per
requirement and one per finding; blank lines are allowed, and any other line is outside the form:

    R1: met | not met | cannot tell: <check or file:line>
    F1: <file:line or R<n>>: <what is wrong>. Evidence: <failing command and output | rule or requirement broken | none>

The text after the answer of a requirement line is optional. A finding's place may be in one code
span, and its line may be a range (`calc.py:3-5`). The defect reviewer writes finding lines
only. A requirement line that says `not met` or `cannot tell` becomes a finding on that
requirement, whose Evidence is the answer (#256 rule 37).

Numbers (#256 rule 35). Findings are numbered F1… across both reviewers in the order their reports
are saved; the reviewer's own numbers are not kept. `save review` writes each number into its
`review` record, and `all_findings` reads them back from the records in order.

Scope (#256 rule 36). A finding is in scope when it names a requirement (`R2`), or when its line,
or any line of its range, is one the branch diff from the fixed point to the reviewed commit
added or changed; otherwise it is out of scope. A finding is proven when its Evidence is
anything but `none` (#256 rule 37).
"""
from __future__ import annotations

import re

REPORTERS = {"requirements": "requirements review", "defect": "defect review"}
FINDING_FORM = ("F1: <file:line or R<n>>: <what is wrong>. Evidence: "
                "<failing command and output | rule or requirement broken | none>")
# The report form each brief gives, and `parse` reads.
FORMS = {
    "requirements": (
        "Your final message is the report: one line per requirement of the check plan, then one line per "
        "finding, and nothing else. Blank lines are allowed.",
        "",
        "R1: met | not met | cannot tell: <check or file:line>",
        FINDING_FORM,
    ),
    "defect": (
        "Your final message is the report: one line per finding, and nothing else. Blank lines are allowed.",
        "",
        FINDING_FORM,
    ),
}
ANSWER = re.compile(r"(R\d+): (met|not met|cannot tell)(?:: (\S.*))?")
FINDING = re.compile(r"F\d+: (`?)(R\d+|[^\s`]+:\d+(?:-\d+)?)\1: (\S.*?)\.? Evidence: (\S.*)")
REQUIREMENT = re.compile(r"R\d+")
HUNK = re.compile(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@")


class BadLine(Exception):
    """A report line outside the fixed form; `number` counts from 1."""

    def __init__(self, number: int, line: str):
        self.number = number
        self.line = line
        super().__init__(f"line {number} is outside the report's form: {line!r}")


def parse(text: str, role: str) -> tuple[dict[str, str], list[dict]]:
    """The requirement answers and the findings of a report, in the report's order.

    Raises `BadLine` for the first line outside the form: a requirement line in a defect report is one.
    """
    answers, found = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if role == "requirements" and (answer := ANSWER.fullmatch(line)):
            rid, said, detail = answer.groups()
            answers[rid] = said
            if said != "met":
                found.append({"where": rid, "text": f"{said}: {detail}" if detail else said,
                              "evidence": f"{rid} {said}"})
        elif finding := FINDING.fullmatch(line):
            _, where, what, evidence = finding.groups()
            found.append({"where": where, "text": what, "evidence": evidence})
        else:
            raise BadLine(number, line)
    return answers, found


def changed_lines(diff: str) -> dict[str, set[int]]:
    """The lines each file's new side added or changed, from `git diff --unified=0` output."""
    changed: dict[str, set[int]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif path and (hunk := HUNK.match(line)):
            start, count = int(hunk[1]), int(hunk[2] if hunk[2] is not None else 1)
            changed.setdefault(path, set()).update(range(start, start + count))
    return changed


def scope(where: str, changed: dict[str, set[int]]) -> str:
    """`in` for a requirement or a line the branch changed, `out` otherwise."""
    if REQUIREMENT.fullmatch(where):
        return "in"
    path, _, lines = where.rpartition(":")
    first, _, last = lines.partition("-")
    touched = changed.get(path.removeprefix("./"), set())
    return "in" if any(n in touched for n in range(int(first), int(last or first) + 1)) else "out"


def proven(evidence: str) -> bool:
    return evidence.strip().rstrip(".").lower() != "none"


def all_findings(records: list[dict]) -> list[dict]:
    """Every saved finding, numbered, in save order, from the branch's `review` records."""
    return [finding for record in records if record.get("event") == "review" for finding in record["findings"]]


def number(found: list[dict], records: list[dict], role: str, changed: dict[str, set[int]]) -> list[dict]:
    """Findings parsed from one report, numbered after those already saved, with reviewer, scope and proof."""
    start = len(all_findings(records)) + 1
    return [{"number": f"F{start + i}", "reviewer": role, **finding, "scope": scope(finding["where"], changed),
             "proven": proven(finding["evidence"])} for i, finding in enumerate(found)]


def state(finding: dict) -> str:
    """The Findings table's state (#231 rule 22). Out of scope and not proven is listed only (#256 rule 38);
    every other finding is open until a later stage's fix, settle or follow-up records a state for it."""
    return "listed, not proven" if finding["scope"] == "out" and not finding["proven"] else "open"


def next_step(finding: dict) -> str:
    """What a saved finding needs next: fix it, settle it, file a follow-up, or nothing (#256 rule 38)."""
    n = finding["number"]
    if finding["scope"] == "in":
        if finding["proven"]:
            return "fix it in a commit"
        return f"settle it: deliver.py settle {n} --check <command>, or deliver.py settle {n} --unsettled"
    return f"file a follow-up: deliver.py follow-up {n}" if finding["proven"] else "nothing; it is listed, not proven"
