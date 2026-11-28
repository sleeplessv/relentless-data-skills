"""The reviewers' reports and their findings: the report form, each finding's number, scope, proof and state.

`brief`, `save`, `settle`, `follow-up` and `render` call this module, and none of them works out a finding's scope,
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

Call-backs (#231 rule 30; spec #479, The review steps, step 5). A fix round is a distinct commit
that one or more saved call-backs read; `fix_rounds` lists them in order. A call-back brief whose
report is never saved uses up no round. A call-back report
holds a resolution line per earlier finding of its reviewer, and new finding lines:

    F1: resolved | not resolved

New findings are numbered on and scoped like a review's. The call-back's `review` record holds
the round and `resolutions`, each finding's `resolved` or `not resolved` by number.

States (#231 rule 22; spec #479, Ready, render and merge). The newest record that decides a
finding sets its state: a call-back that names it, a `settle` or a `follow-up`. With none, a
finding out of scope and not proven is listed only and every other one is open. `resolved` fixes
a finding in the call-back's commit when its Evidence names no command, or when the command has
a counted pass on that commit; until then it stays open. The command is the text of the
Evidence's first code span. The failing run before is a saved check of that command that did not
exit 0, on the commit the finding's report read; without one the state says it was not saved.
"""
from __future__ import annotations

import re
import shlex

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
CALLBACK_FORM = (
    "Your final message is the report: one line for each of your findings above, then one line per new finding "
    "on a line the commits above changed, and nothing else. Blank lines are allowed.",
    "",
    "F1: resolved | not resolved",
    FINDING_FORM,
)
RESOLUTION = re.compile(r"(F\d+): (resolved|not resolved)")
CODE_SPAN = re.compile(r"`([^`]+)`")
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


def parse(text: str, role: str, callback: bool = False) -> tuple[dict[str, str], list[dict]]:
    """The requirement answers, or a call-back's resolutions, and the findings of a report, in its order.

    Raises `BadLine` for the first line outside the form: a requirement line in a defect report or
    in a call-back is one, and so is a resolution line in a review.
    """
    answers, found = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if callback and (resolution := RESOLUTION.fullmatch(line)):
            answers[resolution[1]] = resolution[2]
        elif not callback and role == "requirements" and (answer := ANSWER.fullmatch(line)):
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


def counted(record: dict, command: str) -> bool:
    """Whether a record is a counted pass of `command`: a check of that exact text that exited 0,
    is tied to a commit and selected something (#256 rules 29, 30). `ready` also wants the commit
    to be `HEAD`."""
    return (record.get("event") == "check" and record.get("command") == command and record.get("exit") == 0
            and bool(record.get("commit")) and not record.get("selected_nothing"))


def report_line(finding: dict) -> str:
    """A saved finding as a report line, under its saved number."""
    return f"{finding['number']}: {finding['where']}: {finding['text'].rstrip('.')}. Evidence: {finding['evidence']}"


def named_command(evidence: str) -> str | None:
    """The command a finding's Evidence names: the text of its first code span, if any."""
    span = CODE_SPAN.search(evidence)
    return span[1] if span else None


def fix_rounds(records: list[dict]) -> list[str]:
    """The fix rounds' commits in order: each distinct commit a saved call-back read."""
    return list(dict.fromkeys(r["commit"] for r in records if r.get("event") == "review" and r.get("round", 0) > 0))


def _decided(finding: dict, records: list[dict]) -> tuple[dict | None, str | None]:
    """The newest record that decides the finding, and the commit of the report that found it."""
    number, decider, read = finding["number"], None, None
    for record in records:
        event = record.get("event")
        if event == "review":
            if any(f["number"] == number for f in record["findings"]):
                read = record["commit"]
            if number in record.get("resolutions", {}):
                decider = record
        elif event in ("settle", "follow-up") and record.get("finding") == number:
            decider = record
    return decider, read


def _waits_for_pass(finding: dict, records: list[dict], decider: dict | None) -> str | None:
    """The command a resolved finding still needs a counted pass of on the call-back's commit, if any."""
    if not decider or decider["event"] != "review" or decider["resolutions"][finding["number"]] != "resolved":
        return None
    command = named_command(finding["evidence"])
    if command and not any(counted(r, command) and r["commit"] == decider["commit"] for r in records):
        return command
    return None


def state(finding: dict, records: list[dict]) -> str:
    """The Findings table's state of a saved finding, from the branch's records."""
    decider, read = _decided(finding, records)
    if decider is None:
        return "listed, not proven" if finding["scope"] == "out" and not finding["proven"] else "open"
    if decider["event"] == "settle":
        return f"disproven: `{decider['command']}` passes" if decider["state"] == "disproven" else "unsettled"
    if decider["event"] == "follow-up":
        return f"follow-up #{decider['issue']}" if decider["state"] == "filed" else \
            f"follow-up not filed ({decider['reason']})"
    if decider["resolutions"][finding["number"]] != "resolved" or _waits_for_pass(finding, records, decider):
        return "open"
    fixed = f"fixed in {decider['commit'][:7]}"
    command = named_command(finding["evidence"])
    if command is None:
        return fixed
    if any(r.get("event") == "check" and r.get("command") == command and r.get("commit") == read and r.get("exit") != 0
           for r in records):
        return f"{fixed}: `{command}` fails before, passes after"
    return f"{fixed}: `{command}` passes after; the failing run before the fix was not saved"


def next_step(finding: dict, records: list[dict]) -> str:
    """What a saved finding needs next: fix it, check it, settle it, file a follow-up, or nothing (#256 rule 38)."""
    n, now = finding["number"], state(finding, records)
    if now != "open":
        return f"nothing; it is {now}"
    decider, _ = _decided(finding, records)
    if command := _waits_for_pass(finding, records, decider):
        return f"deliver.py check -- {shlex.quote(command)} on {decider['commit'][:7]}, the call-back's commit"
    if finding["scope"] == "in":
        if finding["proven"]:
            return "fix it in a commit"
        return f"settle it: deliver.py settle {n} --check <command>, or deliver.py settle {n} --unsettled"
    return f"file a follow-up: deliver.py follow-up {n}"
