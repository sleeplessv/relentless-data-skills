#!/usr/bin/env python3
"""The rule gate's CI check: a PR that changes skills/deliver/ carries its evidence.

The check acts only on a PR whose base is the default branch, whose base commit
(--base-rev) already holds skills/deliver/, and which changes a file under it
(#407 reading 10). Any other PR is not checked.

The PR body must hold one `## Change kind` heading. The block is the lines under it
up to the next `## ` heading. `kind:` names one of the four kinds of #180 rule 1, and
the block holds the lines that kind needs, in #231 rule 40's form:

  repair                 repair: <test> fails at <sha>, passes at <sha>
  code change            tests: <n> of <n> pass
  text rule              lesson: #<n>, <n> sightings
                         cases: <n> replayed; failed without the rule <n>; failed with it <n>
                         harm test: <n> of 3 right, was <n>; median tokens <+n or -n>%
  step or figure change  replay: <n> of 12 right, was <n>; tokens <+n or -n>%

A count the check cannot read is refused, never guessed. The lines are #180 rules 11
to 15, scaled by #407 reading 11: the harm test gets no fewer right and its median
tokens rise 10% at most; a replay gets no fewer right, and a tie (as many right and
no fewer tokens) fails. No line or flag waives the check (#180 rule 17).

Exit status: 0 when the PR passes or is not checked, with one line on stdout; 1 when
it is refused, with one line on stderr naming what is missing or below the line;
2 for bad usage.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

DELIVER = "skills/deliver/"
HEADING = "## Change kind"
# #407 reading 11 scales #180's lines to the replay set: the small edit's bucket holds 3
# tickets and the whole set 12. Starting figures; the owner moves one in a PR of its own.
HARM_TICKETS = 3
HARM_TOKENS = 10  # the most, in percent, the harm test's median tokens may rise
REPLAY_TICKETS = 12


def base_holds_deliver(rev: str) -> bool:
    """Whether the base commit's tree has a skills/deliver/ folder; a revision git cannot read is refused."""
    listed = subprocess.run(["git", "ls-tree", "-d", rev, DELIVER.rstrip("/")], capture_output=True, text=True)
    if listed.returncode:
        sys.exit(f"gate_check: refused: git cannot read the base {rev}: {' '.join(listed.stderr.split())}")
    return bool(listed.stdout.strip())


def block(body: str) -> list[str] | str:
    """The lines under the one ## Change kind heading, or the reason they cannot be read."""
    lines = [line.strip() for line in body.splitlines()]
    starts = [n for n, line in enumerate(lines) if line == HEADING]
    if not starts:
        return f"the PR body has no {HEADING} heading"
    if len(starts) > 1:
        return f"the PR body has {len(starts)} {HEADING} headings"
    taken = []
    for line in lines[starts[0] + 1:]:
        if line.startswith("## "):
            break
        taken.append(line)
    return taken


def repair(test: str, failed_at: str, passed_at: str) -> str | None:
    if failed_at.startswith(passed_at) or passed_at.startswith(failed_at):
        return "repair: the test fails and passes at the same commit"
    return None


def tests(passed: str, ran: str) -> str | None:
    if int(ran) == 0:
        return "tests: no test ran"
    if int(passed) > int(ran):
        return f"tests: {passed} pass of {ran} run"
    if int(passed) < int(ran):
        return f"tests: {int(ran) - int(passed)} of {ran} fail"
    return None


def lesson(number: str, sightings: str) -> str | None:
    return "lesson: no sighting" if int(sightings) == 0 else None


def cases(replayed: str, without: str, with_rule: str) -> str | None:
    if max(int(without), int(with_rule)) > int(replayed):
        return f"cases: more failures than the {replayed} cases replayed"
    if int(without) == 0:
        return "cases: the failure never reproduced without the rule"
    if int(with_rule) > 0:
        return f"cases: the failure came back with the rule in {with_rule} of {replayed}"
    return None


def replayed(key: str, line_tickets: int, right: str, tickets: str, was: str) -> str | None:
    """What is wrong with a replay's right count against the current version's, if anything."""
    if int(tickets) != line_tickets:
        where = "bucket" if key == "harm test" else "set"
        return f"{key}: {tickets} tickets replayed; the line is the {where}'s {line_tickets}"
    if max(int(right), int(was)) > int(tickets):
        return f"{key}: {max(int(right), int(was))} right of {tickets} tickets"
    if int(right) < int(was):
        return f"{key}: {right} right, fewer than the {was} the current version got"
    return None


def harm_test(right: str, tickets: str, was: str, tokens: str) -> str | None:
    problem = replayed("harm test", HARM_TICKETS, right, tickets, was)
    if not problem and float(tokens) > HARM_TOKENS:
        problem = f"harm test: median tokens {tokens}%, more than +{HARM_TOKENS}%"
    return problem


def replay(right: str, tickets: str, was: str, tokens: str) -> str | None:
    problem = replayed("replay", REPLAY_TICKETS, right, tickets, was)
    if not problem and int(right) == int(was) and float(tokens) >= 0:
        problem = f"replay: a tie, {right} right as before and tokens {tokens}%, not fewer"
    return problem


TOKENS = r"([+-]\d+(?:\.\d+)?|0)%"
# Each line a kind needs: the form #231 rule 40 gives it, the pattern that reads it, and its judge.
LINES = {
    "repair": ("<test> fails at <sha>, passes at <sha>",
               r"(\S.*) fails at ([0-9a-f]{7,40}), passes at ([0-9a-f]{7,40})", repair),
    "tests": ("<n> of <n> pass", r"(\d+) of (\d+) pass", tests),
    "lesson": ("#<n>, <n> sightings", r"#(\d+), (\d+) sightings?", lesson),
    "cases": ("<n> replayed; failed without the rule <n>; failed with it <n>",
              r"(\d+) replayed; failed without the rule (\d+); failed with it (\d+)", cases),
    "harm test": ("<n> of <n> right, was <n>; median tokens <+n or -n>%",
                  r"(\d+) of (\d+) right, was (\d+); median tokens " + TOKENS, harm_test),
    "replay": ("<n> of <n> right, was <n>; tokens <+n or -n>%",
               r"(\d+) of (\d+) right, was (\d+); tokens " + TOKENS, replay),
}
NEEDS = {
    "repair": ("repair",),
    "code change": ("tests",),
    "text rule": ("lesson", "cases", "harm test"),
    "step or figure change": ("replay",),
}


def check(body: str) -> tuple[bool, str]:
    """Whether the body's block carries the evidence its kind needs, with the kind or what is missing."""
    lines = block(body)
    if isinstance(lines, str):
        return False, lines
    fields: dict[str, str] = {}
    for line in lines:
        found = re.fullmatch(r"([a-z][a-z ]*):\s*(.*)", line, re.ASCII)
        if not found:
            continue
        if found[1] in fields:
            return False, f"the {HEADING} block has {found[1]}: twice"
        fields[found[1]] = found[2]
    if "kind" not in fields:
        return False, f"the {HEADING} block has no kind: line"
    kind = fields["kind"]
    if kind not in NEEDS:
        return False, f'kind: "{kind}" is not one of {", ".join(NEEDS)}'
    for key in NEEDS[kind]:
        if key not in fields:
            return False, f"a {kind} needs a {key}: line"
        form, pattern, judge = LINES[key]
        counts = re.fullmatch(pattern, fields[key], re.ASCII)
        if not counts:
            return False, f'cannot read "{key}: {fields[key]}"; write it as {key}: {form}'
        problem = judge(*counts.groups())
        if problem:
            return False, problem
    return True, kind


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--body", required=True, help="a file holding the PR body")
    parser.add_argument("--base", required=True, help="the branch the PR targets")
    parser.add_argument("--default-branch", required=True, help="the repository's default branch")
    parser.add_argument("--base-rev", required=True, help="the base commit, read with git in the current folder")
    parser.add_argument("--changed", required=True,
                        help="a file of the changed paths, each ended by a NUL, as git diff -z --name-only writes")
    args = parser.parse_args(argv)
    with open(args.changed, "rb") as f:
        changed = f.read().decode(errors="surrogateescape").split("\0")
    if args.base != args.default_branch:
        reason = f"the base {args.base} is not the default branch {args.default_branch}"
    elif not any(path.startswith(DELIVER) for path in changed):
        reason = f"no changed file is under {DELIVER}"
    elif not base_holds_deliver(args.base_rev):
        reason = f"the base has no {DELIVER}"
    else:
        with open(args.body, encoding="utf-8") as f:
            passed, line = check(f.read())
        if not passed:
            print(f"gate_check: refused: {line}.", file=sys.stderr)
            return 1
        print(f"gate_check: passed: {line}.")
        return 0
    print(f"gate_check: not checked: {reason}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
