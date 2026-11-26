#!/usr/bin/env python3
"""Print the comparison between versions on the replay set and the verdict on warning sign 1. `--help` gives the
figures and the files the report reads."""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing the siblings would otherwise write scripts/__pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
import draw  # noqa: E402  (a sibling script, not an installed package)
import judge  # noqa: E402
import replay  # noqa: E402

GENERATION_ONE, DIRECT = judge.GENERATION_ONE, replay.VERSION
RATE_FLOOR = 20  # a count out of fewer tickets than this is never given as a rate
# Warning sign 1, by the tickets in the sets: the sign appears at the first difference or more, and does not appear
# below the second. A difference between the two needs a second set of SET_SIZE tickets.
SIGN_ONE = {30: (5, 3), 60: (8, 8)}
SET_SIZE, DECIDING = min(SIGN_ONE), max(SIGN_ONE)
TEXT, COUNT, FLAG = (str,), (int,), (bool,)  # JSON types by Python type; a bool is not a COUNT
# Why a version of a ticket is left out of every figure, as the report counts it.
NOT_DIRECT, NO_VERDICT, OTHER_COMMIT = ("not direct", "with no verdict",
                                       "judged at a commit the version does not record")


def table_line(tickets: int) -> str:
    appears, below = SIGN_ONE[tickets]
    undecided = f" not decided at {below} to {appears - 1}," if below < appears else ""
    return f"  {tickets} tickets: appears at {appears} or more,{undecided} not at {below - 1} or fewer."


def listed(items: list) -> str:
    """1, 2 and 3."""
    return " and ".join([", ".join(map(str, items[:-1])), str(items[-1])] if len(items) > 1 else map(str, items))


HELP = f"""\
Print the comparison between versions on the replay set and the verdict on
warning sign 1: one agent alone makes more mistakes.

Usage: python3 scripts/report.py

The report reads the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver), and writes nothing: it makes no folder and takes no
lock, and reads each file once, as it stands. It covers every ticket of every
replay-set-<n>.json there, the sets taken together. It names each project by
the label the draw gave it, and prints counts and medians only, with no
ticket, session or commit and no figure per project.

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

Left out of every figure, and counted: a replay versions.jsonl marks not
direct; a version with no verdict, a null verdict or no line at all; and a
verdict on a commit other than the one the set or versions.jsonl records,
or for {DIRECT} with no line in versions.jsonl, since replay.py writes that
line and may mark the replay not direct. Left out of the token figures, and
counted: a judged version whose session or scan row is missing or has a
blank total_tokens. Active minutes are left out the same way. Lines in
versions.jsonl or verdicts.jsonl for a ticket in no set are left out and
counted.

Warning sign 1 is {GENERATION_ONE}'s right-first-time count minus {DIRECT}'s,
over every ticket of the sets. It is printed only when every ticket has both
versions judged; otherwise the report says how many tickets do not. The sign
appears, is not decided (a second set of {SET_SIZE} is needed), or does not
appear, by the difference:

{chr(10).join(map(table_line, SIGN_ONE))}

Any other number of tickets gives no verdict.

Files read, all written by the other scripts:

  replay-set-<n>.json   label, ticket, bucket, session and ready_commit of
                        each entry under "tickets" (scripts/draw.py).
  versions.jsonl        label, ticket, version, commit, session and
                        not_direct of each line (scripts/replay.py).
  verdicts.jsonl        label, ticket, version, commit and right_first_time
                        of each line (scripts/judge.py).
  scan-rows.jsonl       session, total_tokens and active_minutes of each row
                        (scripts/scan.py).

A missing versions.jsonl, verdicts.jsonl or scan-rows.jsonl holds nothing
yet. A folder or file that cannot be read, a line that is not a JSON object,
a field missing or of the wrong type, a set entry's label the draw would not
give or bucket it does not use, a version name in versions.jsonl or
verdicts.jsonl the judge would not take, or a second line for one ticket and
version, one session or one ticket of the sets stops the report. The error
names the folder or file, and the line or ticket entry where there is one,
but not a refused label or version name; nothing else is printed.

Exit 0: the report was printed, with or without a verdict. Exit 1: an error;
no set, or a folder or file the report cannot read with certainty. Exit 2:
bad usage."""


class Unreadable(Exception):
    """Ends the report with exit 1 and nothing printed."""


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
            checked(where, entry, label=TEXT, ticket=COUNT, bucket=TEXT, session=TEXT, ready_commit=TEXT)
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


def load_rows(state: Path) -> dict[str, dict]:
    """Each scan row, whole, by session."""
    figure = (int, float, type(None))
    return {key[0]: row for key, row in by_key(
        [(where, checked(where, line, session=TEXT, total_tokens=figure, active_minutes=figure))
         for where, line in json_lines(state / "scan-rows.jsonl")], "session").items()}


def outcome(ticket: dict, version: str, versions: dict, verdicts: dict, rows: dict) -> str | dict:
    """Why the version of the ticket is left out of every figure, or, judged, its result and its scan row's figures."""
    key = (ticket["label"], ticket["ticket"], version)
    replayed, verdict = versions.get(key), verdicts.get(key)
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
    return {"right": verdict["right_first_time"], "tokens": row.get("total_tokens"),
            "minutes": row.get("active_minutes")}


def count(part: int, whole: int) -> str:
    return f"{part} of {whole}" + (f" ({part / whole:.0%})" if whole >= RATE_FLOOR else "")


def median(values: list) -> str:
    """To at most three places: exact for whole token counts below 2**52 and for minutes to two places, as scan.py
    rounds them."""
    return f"{statistics.median(values):.3f}".rstrip("0").rstrip(".") if values else "none"


def figures(results: list[str | dict]) -> str:
    judged = [result for result in results if isinstance(result, dict)]
    right = sum(result["right"] for result in judged)
    tokens = [result["tokens"] for result in judged if result["tokens"] is not None]
    minutes = [result["minutes"] for result in judged if result["minutes"] is not None]
    return (f"{len(judged)} judged, {count(right, len(judged))} right first time, "
            f"median total tokens {median(tokens)}, median active minutes {median(minutes)}.")


def report(sets: list[int], tickets: dict, versions: dict, verdicts: dict, rows: dict) -> list[str]:
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
    for name in names:
        found = list(results[name].values())
        judged = [result for result in found if isinstance(result, dict)]
        lines += ["", name, *(f"  {bucket}: " + figures([result for key, result in results[name].items()
                                                          if tickets[key]["bucket"] == bucket])
                              for bucket in draw.BUCKETS)]
        lines.append(f"  All: {figures(found)}")
        lines.append("  Left out of every figure: "
                     + ", ".join(f"{found.count(why)} {why}" for why in (NOT_DIRECT, NO_VERDICT, OTHER_COMMIT)) + ".")
        lines.append(f"  Left out of the token figures: {sum(result['tokens'] is None for result in judged)} with a "
                     f"blank token count. Left out of the active minutes: "
                     f"{sum(result['minutes'] is None for result in judged)} blank.")
    return [*lines, "", *sign_one(results, len(tickets))]


def sign_one(results: dict[str, dict], total: int) -> list[str]:
    pairs = [(results[GENERATION_ONE][key], results[DIRECT][key]) for key in results[GENERATION_ONE]]
    missing = sum(not (isinstance(first, dict) and isinstance(second, dict)) for first, second in pairs)
    if missing:
        return [f"Warning sign 1: no verdict. Tickets without both {GENERATION_ONE} and {DIRECT} judged: "
                f"{missing} of {total}."]
    first, second = (sum(pair[side]["right"] for pair in pairs) for side in (0, 1))
    difference = first - second
    lines = [f"Warning sign 1: {GENERATION_ONE} was right first time on {count(first, total)} tickets, {DIRECT} on "
             f"{count(second, total)}, a difference of {difference}."]
    if total not in SIGN_ONE:
        return [*lines, f"No verdict: the table of warning sign 1 has lines for {listed(list(SIGN_ONE))} tickets, "
                        f"not {total}."]
    appears, below = SIGN_ONE[total]
    return [*lines, "The sign appears." if difference >= appears else "The sign does not appear." if difference < below
            else f"Not decided: a second set of {SET_SIZE} is needed, and {DECIDING} tickets decide."]


def main(argv: list[str]) -> int:
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
        # Verdicts first: a verdict is saved after its replay's line, so a verdict read here has its line in place.
        verdicts = load_verdicts(state)
        lines = report(sets, tickets, load_versions(state), verdicts, load_rows(state))
    except Unreadable as error:
        print(f"report: {error}", file=sys.stderr)
        return 1
    except OSError as error:  # any folder or file the report lists, tests or reads
        print(f"report: {error.filename or state} cannot be read ({type(error).__name__}).", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
