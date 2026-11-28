#!/usr/bin/env python3
"""Print the comparison between versions on the replay set and the verdicts on warning signs 1 and 2. `--help` gives
the figures and the files the report reads."""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
import textwrap
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True  # importing the siblings would otherwise write __pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
# The replay scripts stay in this repo's scripts/, so the report runs from this repo's tree only.
sys.path.insert(1, str(Path(__file__).resolve().parents[3] / "scripts"))
import core  # noqa: E402
import draw  # noqa: E402  (a replay script, not an installed package)
import judge  # noqa: E402
import replay  # noqa: E402
import scan  # noqa: E402

GENERATION_ONE, DIRECT, DELIVER = judge.GENERATION_ONE, replay.VERSION, replay.VERSIONS[1]
# Where a deliver replay ended, as ending() reads it from the clone.
MERGED, READY, HANDED, REVIEW, NO_PR, OTHER = ("merged", "ready", "handed to the owner", "draft needing a review",
                                              "stopped before the PR", "other or not read")
RATE_FLOOR = 20  # a count out of fewer tickets than this is never given as a rate
# Warning sign 1: the shares of the tickets judged that the difference is held against, each rounded up, and the
# words both the help and the verdict take from them; the help states the rule.
APPEARS, UNDECIDED, TOGETHER = Fraction(1, 6), Fraction(1, 10), Fraction(2, 15)
SECOND_SET = "the rest of the pool: every remaining pool ticket whose check passes, with no limit per bucket"
SETS_TOGETHER = (f"the sign appears at a difference of at least {TOGETHER} of the tickets judged, rounded up, and does "
                 "not appear below that")
TEXT, COUNT, FLAG = (str,), (int,), (bool,)  # JSON types by Python type; a bool is not a COUNT
# Why a version of a ticket is left out of every figure, as the report counts it.
NOT_RUNNABLE, NOT_DIRECT, NO_VERDICT, OTHER_COMMIT = ("not runnable", "not direct", "with no verdict",
                                                     "judged at a commit the version does not record")
# Warning sign 2: generation one's steps and the words that name each, as named() reads them. A bare "fix" names no
# step, since a ticket's own title may hold it. "Read" names none, since a brief opens its instructions with it, and
# "findings" names no search, since a re-check's brief speaks of them.
STEPS = tuple((name, re.compile(rf"\b(?:{words})", re.IGNORECASE)) for name, words in (
    ("re-check", r"re-?check|re-?verif|fix head\b"),
    ("closing verification", r"verif(?:y|ier|ication)\b"),
    ("fix", r"(?:fix|address)(?:es|ing)?\b[^.:;\n]*\b(?:finding|comment|review)|fix(?:es)? (?:round|worker|brief)"
            r"|(?:late|class) fix"),
    ("review", r"review|ponytail|audit"),
    ("implement", r"implement|build|integrat"),
    ("publish", r"publish|ready\b|pr body|merge|push|(?:start|stop) comment|tracker|claim"),
    ("explore", r"explor|research|find(?!ing)|search|investigat|locate|survey|look up"),
))
CUT = ("closing verification", "fix", "re-check")  # the steps the small cut takes out
# Text that names no role of its own, so named() reads the text without it: a generation-one skill's name names the
# whole run, every step at once, a ticket's title after its number ("#12: Verify CSV headers") names its subject, and
# the words after "by" are read past, since they often name who acted, not the helper ("the errors flagged by the
# reviewer"), though not always ("Start by implementing").
NO_ROLE = re.compile("|".join([*map(re.escape, draw.GENERATION_ONE), r"#\d+:[^.\n]*", r"\bby\b[^.,;:\n]*"]),
                     re.IGNORECASE)
AGAIN = re.compile(r"\b(?:follow-?up|round \d|fix(?:es)? round)", re.IGNORECASE)  # words that make a review a re-check


def listed(items: list) -> str:
    """1, 2 and 3."""
    return " and ".join([", ".join(map(str, items[:-1])), str(items[-1])] if len(items) > 1 else map(str, items))


def named(text: str | None) -> list[str]:
    """The steps a text names, read without NO_ROLE, in the order their words come, on a tie in the order of STEPS.
    Words inside another step's words are that step's: "address what the final reviewer identified" is a fix, not a
    review. A text whose first step is a review and that holds AGAIN's words names a re-check first, and a text that
    names a re-check names no review: a re-check is a review of a fix, so its review words are the re-check's."""
    text = NO_ROLE.sub(" ", text or "")
    found = [(match.start(), at, match.end(), name)
             for at, (name, words) in enumerate(STEPS) if (match := words.search(text))]
    found = [name for start, _, _, name in sorted(found) if not any(other < start < end for other, _, end, _ in found)]
    if found[:1] == ["review"] and AGAIN.search(text):
        found[0] = "re-check"
    return [name for name in found if name != "review"] if "re-check" in found else found


def step(description: str | None, brief_head: str | None) -> str | None:
    """The step of generation one a helper took, or None to leave it not sorted. A text that names steps on both
    sides of the cut is read as naming none; the helper takes the first step its description names or, when that
    names none, its brief, unless the two name steps on different sides of the cut. A brief that opens with a heading
    naming a step ("# Publish brief") is read by that heading alone, and a description that names a review with a
    brief that names a re-check make a re-check: the description names the reviewer, the brief the pass it makes.

    The sort can still be wrong, in ways these are examples of. Between two steps on one side of the cut it takes
    the first named, which may be a step the text only mentions; that changes no verdict. When every step a helper's
    texts name is one it only mentions, on the other side of the cut from its own, it is sorted across the cut:
    "Correct the errors the reviewer flagged", a fix, is sorted as a review. And a word rule can misread a text: a
    brief opening "#12 passed closing verification" is read by that "heading" alone, and "Start by implementing"
    is read past as if it named who acted."""
    heading = re.match(r"#[^.:\n]*", brief_head or "")
    texts = [named(description), heading and named(heading[0]) or named(brief_head)]
    texts = [steps for steps in texts if len({name in CUT for name in steps}) == 1]
    if [steps[0] for steps in texts] == ["review", "re-check"]:
        return "re-check"
    return texts[0][0] if texts and len({steps[0] in CUT for steps in texts}) == 1 else None


HELP = f"""\
Print the comparison between versions on the replay set and the verdicts on
warning sign 1, one agent alone makes more mistakes, and warning sign 2, a
small cut fixes the cost.

Usage: deliver.py report

The report reads the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver), and writes nothing: it makes no folder and takes no
lock, and reads each file once, as it stands. It covers every ticket of every
replay-set-<n>.json there, the sets taken together. It names each project by
the label the draw gave it, and prints counts, medians and sums only, with no
ticket, session, commit or helper and no figure per project.

A version is a name and a commit. {GENERATION_ONE}'s commit is the ready_commit its
set records, and its session the set's session. {DIRECT} has its commit and
session in its line in versions.jsonl. Any other version has them there too,
or, with no line there, the commit its verdict names and no session. For each
version, per size bucket and over the sets, the report prints the tickets
judged, the tickets right first time, the median total tokens and the median
active minutes. A version of a ticket is judged when verdicts.jsonl holds
true or false for it at its commit. Each median covers the judged tickets
whose scan row holds that figure. It is printed to at most three decimal
places, which is exact for whole token counts below 2**52 and for minutes to
two places, as scan.py rounds them. Tickets right first time out of fewer
than {RATE_FLOOR} judged are printed as a count, such as 8 of 10; out of {RATE_FLOOR} or
more judged, the count is followed by its rate, such as 20 of 30 (67%).

Left out of every figure, and counted: any version but {GENERATION_ONE} of a
ticket whose set entry has "browser": true, which the chief of staff sets by
hand and replay.py refuses to replay, counted as not runnable; a replay
versions.jsonl marks not direct; a version with no verdict, a null verdict or
no line at all; and a verdict on a commit other than the one the set or
versions.jsonl records, or for {DIRECT} with no line in versions.jsonl, since
replay.py writes that line and may mark the replay not direct. The figures of
{GENERATION_ONE} keep a marked ticket: its result is the original session's.
Left out of the token figures, and counted: a judged version whose session or
scan row is missing or has a blank total_tokens. Active minutes are left out
the same way. Lines in versions.jsonl or verdicts.jsonl for a ticket in no set
are left out and counted.

A nonblank line of scan-rows.jsonl is no row when the scan would not read it as a
JSON object (json_object in scan.py says which) or when it is an object
whose session is not text. The scan keeps such a line, and the report leaves it
out: it names the line once on standard error, with the file, the line number and
the reason, as it reads the file, and prints on standard output how many lines it
left out when it prints the report. A line of nothing but whitespace is blank,
and is passed over and not counted. A session whose row was such a line is left
out of the token figures and counted, like one with no row.

Every token figure includes the tokens a resumed session copied: the report
takes none out of a figure or a verdict. deliver.py scan --help says
which lines are copied and what copied_tokens holds. A copied response counts
in total_tokens and, wherever the scan puts it, in a helper's tokens or in the
session's own. Each version's block ends with the copied_tokens of the tickets
in its token figures, summed, out of the total_tokens of those of them with a
copied_tokens, and that share as a percent. Warning sign 2 gives the same for
each side, over the tickets it counts. Where those total_tokens sum to 0, no
share is printed. A copied_tokens that is null, or absent from a row the scan
wrote before it had that column, is blank: its ticket is left out of the copied
tokens and counted.

The {DELIVER} block then counts, per size bucket and over the sets, where each
{DELIVER} replay of a ticket in the sets ended, read from its clone as the
replay left it. The last PR the stand-in gh holds says it: merged; open and
not a draft, which is ready, or handed to the owner when the newest ready or
merge record of the PR's branch is a merge record; a draft whose newest such
record is a ready record with result "needs review", a draft needing a review.
A replay with no PR stopped before the PR. A clone that is gone, a clone file
that cannot be read, a closed PR, and any other draft count as other or not
read, and do not stop the report.


{textwrap.fill(
    f"Warning sign 1 is {GENERATION_ONE}'s right-first-time count minus {DIRECT}'s, over every ticket of the sets. "
    "It is printed only when every ticket has both versions judged; otherwise the report says how many tickets do "
    "not. Each line the difference is held against is a share of the tickets judged, rounded up. Over one set, the "
    f"sign appears at a difference of at least {APPEARS} of the tickets and does not appear below {UNDECIDED} of "
    "them. Between the two it is not decided, and a second set is needed, "
    f"{SECOND_SET}. Over two sets or more, taken together, {SETS_TOGETHER}. One set of 30 tickets gives "
    f"{math.ceil(APPEARS * 30)} and {math.ceil(UNDECIDED * 30)}; 60 tickets over two sets give "
    f"{math.ceil(TOGETHER * 60)}. Sets that hold no "
    "ticket the replay can run give no verdict.", 78, break_on_hyphens=False)}

Warning sign 2 is answered from the scan rows of {GENERATION_ONE}'s sessions,
over every ticket of the sets. The extra cost is the total_tokens
{GENERATION_ONE} spent minus those {DIRECT} spent. A ticket is left out of both
sides, and counted, when it lacks either version judged or either version
has a blank total_tokens. The figures cover the tickets left; the verdict
waits, as for warning sign 1, until every ticket has both versions judged.

Both warning signs leave a marked ticket out of their count of tickets, so it
holds back neither verdict. Each sign prints how many tickets it left out as
not runnable.

The report reads each helper's description and the head of its brief, and
puts the helper in a step of generation one or leaves it not sorted. How it
chooses, and where it can sort wrong, are in step() and named() in
report.py, with each step's words in STEPS, the words read past in
NO_ROLE and those that make a review a re-check in AGAIN. A helper sorted
into the wrong step can move the cut either way. The steps:

  {listed([name for name, _ in STEPS])}.

The cut is the helpers' tokens in {listed(list(CUT))}.
Not sorted are the tokens of helpers that name no step and the sessions' own
tokens, in no helper: a session's own turns serve every step, and the rows
cannot split them. A row with no list of helpers (null) counts all its
tokens as the session's own. The sign appears when the cut is more than half
the extra cost, and not at half or below. The report gives the verdict
without the tokens not sorted, and with them counted as cut, and says when
the two differ. With no extra cost, or no ticket left, it gives none.

A row lists a helper once, under the description and brief it started with,
so a helper resumed for a fix round counts under the step it started as, and
the cut can be smaller than generation one's real spend on those steps. A
helper with a blank total_tokens has no tokens of its own: its responses are
in another helper's or the session's, and it adds nothing to a step; the
report prints how many there are. A share of tokens is not a count of
tickets, so the report gives every share as a percent at any number of
tickets. The cut and the tokens not sorted are percents of {GENERATION_ONE}'s
tokens. Each copied share is of the total printed beside it.

Files read, all written by the other scripts:

  replay-set-<n>.json   label, ticket, bucket, session and ready_commit of
                        each entry under "tickets" (scripts/draw.py), and
                        browser where an entry has it.
  versions.jsonl        label, ticket, version, commit, session and
                        not_direct of each line, and clone of each {DELIVER}
                        line (scripts/replay.py).
  <clone>/.git/{replay.STAND_IN}/prs.json
                        state, isDraft and headRefName of the last PR
                        (scripts/replay_gh.py).
  <clone>/.git/deliver/branches/<branch>/{core.RECORDS}
                        event and result of each record (deliver.py).
  verdicts.jsonl        label, ticket, version, commit and right_first_time
                        of each line (scripts/judge.py).
  scan-rows.jsonl       session, total_tokens, copied_tokens, active_minutes
                        and helpers of each row, and description, brief_head
                        and total_tokens of each helper (deliver.py scan).

A missing versions.jsonl, verdicts.jsonl or scan-rows.jsonl holds nothing
yet. A folder or file that cannot be read, a line of versions.jsonl or
verdicts.jsonl that is not a JSON object, a field missing or of the wrong type
(but not the session of a line of scan-rows.jsonl, above, or a missing
copied_tokens), a set entry's label the draw would not give or bucket it does
not use, a version name in versions.jsonl or verdicts.jsonl the judge would
not take, a total_tokens or copied_tokens that is negative, infinite or not a
number, helpers that hold more tokens than their row's total_tokens, a
copied_tokens more than its row's total_tokens or beside a blank one, or a
second line for one ticket and version, one session or
one ticket of the sets stops the report. The error goes on standard error and
names the folder or file, and the ledger line, helper or set ticket entry that
fails a check. A set file that is not JSON, or not an object holding a list of
tickets, and a versions.jsonl or verdicts.jsonl that is not UTF-8 are named by
file alone. It never prints a refused label or version name, and prints nothing
on standard output.

Exit 0: the report was printed, with or without a verdict. Exit 1: an error;
no set, or a folder or file the report cannot read with certainty. Exit 2:
bad usage."""


class Unreadable(Exception):
    """Ends the report with exit 1: the error goes to standard error and nothing to standard output. Lines of
    scan-rows.jsonl already named on standard error stay named."""


def checked(where: str, line: object, **wanted: tuple) -> dict:
    """The line, once each wanted field is present with a value of one of its types."""
    if not isinstance(line, dict):
        raise Unreadable(f"{where}: not a JSON object.")
    for name, types in wanted.items():
        if name not in line or type(line[name]) not in types:
            raise Unreadable(f"{where}: {name} is missing or of the wrong type.")
    return line


def json_lines(path: Path) -> list[tuple[str, object]]:
    """Each line of a JSON-lines file with where it is; none for a file that does not exist."""
    try:
        text = path.read_text()
    except FileNotFoundError:  # any other OSError reaches main()
        return []
    except UnicodeDecodeError as error:
        raise Unreadable(f"{path} cannot be read ({type(error).__name__}).")
    lines = []
    for number, line in enumerate(text.split("\n"), 1):  # splitlines() would also split on U+2028
        if line.strip():
            try:
                lines.append((f"{path}:{number}", json.loads(line)))
            except ValueError:
                raise Unreadable(f"{path}:{number}: not a JSON line.")
    return lines


def blank(line: bytes) -> bool:
    """A line of nothing but whitespace, as str.strip() reads it; bytes that are not UTF-8 are not blank."""
    try:
        return not line.decode().strip()
    except UnicodeDecodeError:
        return False


def row_lines(path: Path) -> tuple[list[tuple[str, dict]], int]:
    """The lines of scan-rows.jsonl that can be rows, each with where it is, and how many nonblank lines are left out;
    none of either for a file that does not exist."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:  # any other OSError reaches main()
        return [], 0
    rows, skipped = [], 0
    for number, line in enumerate(data.split(b"\n"), 1):  # as the scan splits it
        if blank(line):
            continue
        where, row = f"{path}:{number}", scan.json_object(line)
        if row is not None and type(row.get("session")) in TEXT:
            rows.append((where, row))
            continue
        why = "not a JSON object" if row is None else "session is missing or of the wrong type"
        print(f"report: {where}: {why}, left out.", file=sys.stderr)
        skipped += 1
    return rows, skipped


def by_key(lines: list[tuple[str, dict]], *key: str) -> dict[tuple, dict]:
    found: dict[tuple, dict] = {}
    for where, line in lines:
        if tuple(line[name] for name in key) in found:
            raise Unreadable(f"{where}: a second line for the same {', '.join(key)}.")
        found[tuple(line[name] for name in key)] = line
    return found


def load_sets(state: Path) -> tuple[list[int], dict[tuple[str, int], dict]]:
    """The set numbers, and every ticket of the sets by (label, ticket)."""
    try:
        listing = list(state.iterdir())
    except FileNotFoundError:  # any other OSError reaches main()
        listing = []
    paths = sorted((int(found.group(1)), path) for path in listing
                   if (found := re.fullmatch(r"replay-set-(\d+)\.json", path.name)))
    if not paths:
        raise Unreadable(f"no replay set in {state}.")
    entries = []
    for _, path in paths:
        try:
            saved = json.loads(path.read_text())
        except ValueError as error:
            raise Unreadable(f"{path} cannot be read as JSON ({type(error).__name__}).")
        for at, entry in enumerate(checked(str(path), saved, tickets=(list,))["tickets"], 1):
            where = f"{path}: ticket entry {at}"
            checked(where, entry, label=TEXT, ticket=COUNT, bucket=TEXT, session=TEXT, ready_commit=TEXT,
                    **({"browser": FLAG} if "browser" in entry else {}))
            if not draw.LABEL.fullmatch(entry["label"]):  # an invalid label is never printed: it may name the project
                raise Unreadable(f"{where}: label is not a label the draw gives.")
            if entry["bucket"] not in draw.BUCKETS:
                raise Unreadable(f"{where}: bucket is not one the draw uses.")
            entries.append((where, entry))
    return [number for number, _ in paths], by_key(entries, "label", "ticket")


def versioned(where: str, line: object, **wanted: tuple) -> dict:
    """The line, checked, once its version is a name the judge would take; an invalid name is never printed."""
    checked(where, line, label=TEXT, ticket=COUNT, version=TEXT, commit=TEXT, **wanted)
    if not judge.VERSION_NAME.fullmatch(line["version"]):
        raise Unreadable(f"{where}: version is not a version name.")
    return line


def load_versions(state: Path) -> dict[tuple[str, int, str], dict]:
    """Each replayed version by (label, ticket, version)."""
    return by_key([(where, versioned(where, line, session=TEXT, not_direct=FLAG))
                   for where, line in json_lines(state / "versions.jsonl")], "label", "ticket", "version")


def load_verdicts(state: Path) -> dict[tuple[str, int, str], dict]:
    """Each verdict by (label, ticket, version)."""
    return by_key([(where, versioned(where, line, right_first_time=(bool, type(None))))
                   for where, line in json_lines(state / "verdicts.jsonl")], "label", "ticket", "version")


def tokens_of(where: str, line: dict, name: str = "total_tokens") -> int | float | None:
    """The line's figure, once it is blank or a count: a negative or infinite figure, or NaN, is none. A figure the
    line does not hold is blank."""
    value = line.get(name)
    if value is not None and not 0 <= value < math.inf:
        raise Unreadable(f"{where}: {name} is not a count of tokens.")
    return value


def scan_row(where: str, line: object) -> dict:
    """The row, once its figures and each helper's description, brief head and tokens can be read with certainty."""
    figure, text = (int, float, type(None)), (str, type(None))
    row = checked(where, line, total_tokens=figure, active_minutes=figure, helpers=(list, type(None)))
    total, held = tokens_of(where, row), 0
    for number, helper in enumerate(row["helpers"] or [], 1):
        at = f"{where}: helper {number}"
        held += tokens_of(at, checked(at, helper, description=text, brief_head=text, total_tokens=figure)) or 0
    if total is not None and held > total:  # scan.py gives each response to one helper or to the session
        raise Unreadable(f"{where}: its helpers hold more tokens than its total_tokens.")
    if type(row.get("copied_tokens")) not in figure:  # a row the scan wrote before the column has none: a blank
        raise Unreadable(f"{where}: copied_tokens is of the wrong type.")
    copied = tokens_of(where, row, "copied_tokens")
    if copied is not None and (total is None or copied > total):
        raise Unreadable(f"{where}: copied_tokens is more than its total_tokens or beside a blank one.")
    return row


def load_rows(state: Path) -> tuple[dict[str, dict], int]:
    """Each scan row, whole, by session, and how many lines of scan-rows.jsonl were left out."""
    lines, skipped = row_lines(state / "scan-rows.jsonl")
    return {key[0]: row for key, row in by_key([(where, scan_row(where, line)) for where, line in lines],
                                               "session").items()}, skipped


def outcome(ticket: dict, version: str, versions: dict, verdicts: dict, rows: dict) -> str | dict:
    """Why the version of the ticket is left out of every figure, or, judged, its result and its scan row's figures."""
    key = (ticket["label"], ticket["ticket"], version)
    replayed, verdict = versions.get(key), verdicts.get(key)
    if ticket.get("browser") and version != GENERATION_ONE:  # replay.py refuses it; generation one's is the original
        return NOT_RUNNABLE
    if replayed and replayed["not_direct"]:
        return NOT_DIRECT
    if verdict is None or verdict["right_first_time"] is None:
        return NO_VERDICT
    # Generation one has its commit and session in the set; a replay, in its versions.jsonl line. A version neither
    # gives, such as one judged with --commit and --from, has the commit its verdict names and no session. A direct
    # replay with no line has no commit of record: replay.py writes that line, and it may mark the replay not direct.
    commit, session = ((ticket["ready_commit"], ticket["session"]) if version == GENERATION_ONE
                       else (replayed["commit"], replayed["session"]) if replayed
                       else (None, None) if version == DIRECT else (verdict["commit"], None))
    if verdict["commit"] != commit:
        return OTHER_COMMIT
    row = rows.get(session, {})
    return {"right": verdict["right_first_time"], "tokens": row.get("total_tokens"), "copied": row.get("copied_tokens"),
            "minutes": row.get("active_minutes"), "helpers": row.get("helpers")}


def ending(clone: Path) -> str:
    """Where the deliver replay in `clone` ended: from the stand-in gh's PRs, then the records of the last PR's branch,
    read as `deliver.py finish` reads its state line. A clone or file that cannot be read is OTHER."""
    try:
        if not clone.is_dir():
            return OTHER
        path = clone / ".git" / replay.STAND_IN / "prs.json"  # the stand-in writes it on every call
        prs = json.loads(path.read_text()) if path.is_file() else []
        if not prs:
            return NO_PR
        pr = prs[-1]
        if pr["state"] != "OPEN":
            return MERGED if pr["state"] == "MERGED" else OTHER
        log = core.records_dir(clone / ".git", pr["headRefName"]) / core.RECORDS
        records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()] if log.is_file() else []
        newest = ([record for record in records if record.get("event") in ("ready", "merge")] or [{}])[-1]
        if not pr["isDraft"]:  # merge writes its record when it leaves the PR to the owner
            return HANDED if newest.get("event") == "merge" else READY
        return REVIEW if newest.get("result") == "needs review" else OTHER
    except (OSError, ValueError, LookupError, TypeError, AttributeError):
        return OTHER


def endings_line(bucket: str, found: list[str]) -> str:
    return (f"  Where the replays ended, {bucket}: "
            + ", ".join(f"{found.count(end)} {end}" for end in (MERGED, READY, HANDED, REVIEW, NO_PR, OTHER)) + ".")


def count(part: int, whole: int) -> str:
    return f"{part} of {whole}" + (f" ({part / whole:.0%})" if whole >= RATE_FLOOR else "")


def number(value: int | float) -> str:
    """A whole number as it is, any other to at most three decimal places; --help states where that is exact."""
    return str(value) if isinstance(value, int) else f"{value:.3f}".rstrip("0").rstrip(".")


def median(values: list) -> str:
    return number(statistics.median(values)) if values else "none"


def figures(results: list[str | dict]) -> str:
    judged = [result for result in results if isinstance(result, dict)]
    right = sum(result["right"] for result in judged)
    tokens = [result["tokens"] for result in judged if result["tokens"] is not None]
    minutes = [result["minutes"] for result in judged if result["minutes"] is not None]
    return (f"{len(judged)} judged, {count(right, len(judged))} right first time, "
            f"median total tokens {median(tokens)}, median active minutes {median(minutes)}.")


def copied_of(results: list[dict], whose: str) -> tuple[str, int]:
    """Of the results whose row gives a copied count, "<copied> of the <total> total tokens of <whose> tickets with a
    copied count", then ", <share>", or nothing when that total is 0; and how many results have a blank copied
    count."""
    known = [result for result in results if result["copied"] is not None]
    copied, total = sum(result["copied"] for result in known), sum(result["tokens"] for result in known)
    return (f"{number(copied)} of the {number(total)} total tokens of {whose} tickets with a copied count"
            + (f", {copied / total:.1%}" if total else ""), len(results) - len(known))


def copied_line(counted: list[dict]) -> str:
    """The copied tokens of the tickets in a version's token figures whose row gives them, out of the same tickets'
    total tokens; a blank copied count is left out and counted."""
    copied_of_total, blank = copied_of(counted, "the")
    return f"  Copied tokens: {copied_of_total}. Left out of the copied tokens: {blank} with a blank copied count."


def report(sets: list[int], tickets: dict, versions: dict, verdicts: dict, rows: dict, skipped_scan_lines: int = 0,
           ended: dict[tuple, str] | None = None) -> list[str]:
    """The report's lines; `ended` holds where each deliver replay of a ticket in the sets ended, by its key."""
    ended = ended or {}
    names = [GENERATION_ONE, DIRECT, *sorted({key[2] for key in [*versions, *verdicts] if key[:2] in tickets}
                                            - {GENERATION_ONE, DIRECT})]
    results = {name: {key: outcome(ticket, name, versions, verdicts, rows) for key, ticket in tickets.items()}
               for name in names}
    labels = sorted({label for label, _ in tickets}, key=lambda label: (len(label), label))
    lines = [f"Replay set{'s' if len(sets) > 1 else ''} {listed(sets)}: {len(tickets)} tickets, of "
             f"project{'s' if len(labels) > 1 else ''} {listed(labels)}."]
    outside = sum(key[:2] not in tickets for key in [*versions, *verdicts])
    if outside:
        lines.append(f"Left out: {outside} lines of versions.jsonl and verdicts.jsonl name a ticket in no set.")
    if skipped_scan_lines:
        lines.append(f"Left out: scan-rows.jsonl lines that are no scan row: {skipped_scan_lines}.")
    for name in names:
        found = list(results[name].values())
        judged = [result for result in found if isinstance(result, dict)]
        lines += ["", name, *(f"  {bucket}: " + figures([result for key, result in results[name].items()
                                                          if tickets[key]["bucket"] == bucket])
                              for bucket in draw.BUCKETS)]
        lines.append(f"  All: {figures(found)}")
        lines.append("  Left out of every figure: " + ", ".join(
            f"{found.count(why)} {why}" for why in (NOT_RUNNABLE, NOT_DIRECT, NO_VERDICT, OTHER_COMMIT)) + ".")
        lines.append(f"  Left out of the token figures: {sum(result['tokens'] is None for result in judged)} with a "
                     f"blank token count. Left out of the active minutes: "
                     f"{sum(result['minutes'] is None for result in judged)} blank.")
        lines.append(copied_line([result for result in judged if result["tokens"] is not None]))
        if name == DELIVER:
            lines += [endings_line(bucket, [end for key, end in ended.items() if bucket in ("All",
                                                                                           tickets[key[:2]]["bucket"])])
                      for bucket in (*draw.BUCKETS, "All")]
    runnable = [key for key, ticket in tickets.items() if not ticket.get("browser")]  # the signs count no other
    pairs = [(results[GENERATION_ONE][key], results[DIRECT][key]) for key in runnable]
    judged_pairs = [pair for pair in pairs if all(isinstance(side, dict) for side in pair)]
    one, not_runnable = sign_one(judged_pairs, len(runnable), set_count=len(sets)), len(tickets) - len(runnable)
    return [*lines, "", one[0], f"  Left out: {not_runnable} {NOT_RUNNABLE}.", *one[1:], "",
            *sign_two(judged_pairs, len(runnable), not_runnable)]


def unjudged(judged: list[tuple[dict, dict]], total: int) -> str:
    return f"without both {GENERATION_ONE} and {DIRECT} judged: {total - len(judged)} of {total}."


def sign_one(judged: list[tuple[dict, dict]], total: int, set_count: int) -> list[str]:
    """Warning sign 1 over the tickets with both versions judged; a verdict only when that is every ticket and there
    is at least one. One set gives the line of one set; two or more, the line of the sets together."""
    if len(judged) < total:
        return [f"Warning sign 1: no verdict. Tickets {unjudged(judged, total)}"]
    if not total:
        return ["Warning sign 1: no verdict. The sets hold no ticket the replay can run."]
    first, second = (sum(pair[side]["right"] for pair in judged) for side in (0, 1))
    difference = first - second
    lines = [f"Warning sign 1: {GENERATION_ONE} was right first time on {count(first, total)} tickets, {DIRECT} on "
             f"{count(second, total)}, a difference of {difference}."]
    # A Fraction keeps math.ceil exact for every count.
    appears, below = ((math.ceil(TOGETHER * total),) * 2 if set_count > 1
                      else (math.ceil(APPEARS * total), math.ceil(UNDECIDED * total)))
    return [*lines, "The sign appears." if difference >= appears else "The sign does not appear." if difference < below
            else f"Not decided: a second set is needed, {SECOND_SET}. Over both sets together, {SETS_TOGETHER}."]


def sign_two(judged: list[tuple[dict, dict]], total: int, not_runnable: int) -> list[str]:
    """Warning sign 2 over the tickets with both versions judged and both token counts; a verdict only when every
    ticket has both versions judged. The `not_runnable` tickets are in none of these counts."""
    counted = [pair for pair in judged if pair[0]["tokens"] is not None and pair[1]["tokens"] is not None]
    left = (f"  Left out of both sides: {not_runnable} {NOT_RUNNABLE}, {total - len(judged)} without both versions "
            f"judged, {len(judged) - len(counted)} with a blank token count.")
    if not counted:
        return ["Warning sign 2: no verdict. No ticket has both versions judged and both token counts.", left]
    spend, ownless = dict.fromkeys([*(name for name, _ in STEPS), None], 0), 0
    for first, _ in counted:
        for helper in first["helpers"] or []:
            spend[step(helper["description"], helper["brief_head"])] += helper["total_tokens"] or 0
            ownless += helper["total_tokens"] is None
    first, second = (sum(pair[side]["tokens"] for pair in counted) for side in (0, 1))
    own = first - sum(spend.values())
    (first_copied_of_total, first_blank), (second_copied_of_total, second_blank) = (
        copied_of([pair[side] for pair in counted], f"{name}'s") for side, name in ((0, GENERATION_ONE), (1, DIRECT)))
    extra, cut, unsorted = first - second, sum(spend[name] for name in CUT), spend[None] + own

    def share(part: int | float) -> str:
        return f"{number(part)} tokens, {part / first:.1%} of {GENERATION_ONE}'s" if first else f"{number(part)} tokens"

    lines = [f"Warning sign 2: on {len(counted)} of {total} tickets, {GENERATION_ONE} spent {number(first)} tokens "
             f"and {DIRECT} {number(second)}, an extra cost of {number(extra)}.", left,
             f"  {GENERATION_ONE}'s helpers by step: " + ", ".join(f"{name} {number(spend[name])}" for name, _ in STEPS)
             + f". {ownless} helpers have no tokens of their own.",
             f"  The cut, {listed(list(CUT))}: {share(cut)}.",
             f"  Not sorted into a step: {share(unsorted)}: {number(spend[None])} in helpers that name no step, "
             f"{number(own)} the sessions' own, in no helper.",
             "  A helper resumed for a fix round counts under the step it started as.",
             f"  Copied tokens in these sums: {first_copied_of_total}, and {second_copied_of_total}. Left out of the "
             f"copied tokens: {first_blank} of {GENERATION_ONE}'s tickets and {second_blank} of {DIRECT}'s, with a "
             "blank copied count."]
    if len(judged) < total:
        return [*lines, f"No verdict: tickets {unjudged(judged, total)}"]
    if extra <= 0:
        return [*lines, f"No verdict: {GENERATION_ONE} cost no more than {DIRECT}, so there is no extra cost to cut."]
    verdict_without_unsorted, verdict_with_unsorted = (
        "The sign appears." if 2 * part > extra else "The sign does not appear." for part in (cut, cut + unsorted))
    lines += [f"Without the spend not sorted, the cut is {number(cut)} tokens against half the extra cost, "
              f"{number(extra / 2)}. {verdict_without_unsorted}",
              f"With it counted as cut, the cut is {number(cut + unsorted)} tokens. {verdict_with_unsorted}"]
    if verdict_without_unsorted == verdict_with_unsorted:
        return lines
    return [*lines, "The two verdicts differ: the spend not sorted decides the sign."]


def cli(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(HELP)
        return 0
    if argv:
        print(HELP, file=sys.stderr)
        return 2
    # scan.state_dir() would make the folder; the report only reads it.
    state = Path(os.environ.get("DELIVER_STATE_DIR") or Path.home() / ".local" / "state" / "deliver")
    try:
        sets, tickets = load_sets(state)
        # Verdicts first, so a replay recorded before its verdict was saved has its line in the versions.jsonl read
        # here; read the other way, one recorded and judged between the two reads would count as having no line.
        verdicts = load_verdicts(state)
        versions = load_versions(state)
        rows, skipped = load_rows(state)
        ended = {key: ending(state / line["clone"]) if isinstance(line.get("clone"), str) else OTHER
                 for key, line in versions.items() if key[2] == DELIVER and key[:2] in tickets}
        lines = report(sets, tickets, versions, verdicts, rows, skipped, ended)
    except Unreadable as error:
        print(f"report: {error}", file=sys.stderr)
        return 1
    except OSError as error:  # any folder or file the report lists, tests or reads
        print(f"report: {error.filename or state} cannot be read ({type(error).__name__}).", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


def main(args: list[str], run: object = None) -> None:
    """deliver.py's entry: `run` is unused, since the report reads the machine directory, not a checkout."""
    code = cli(args)
    if code:
        raise SystemExit(code)
