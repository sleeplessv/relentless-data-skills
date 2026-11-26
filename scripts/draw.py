#!/usr/bin/env python3
"""Draw the replay set. `--help` gives the rules and the files the draw reads and writes."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

sys.dont_write_bytecode = True  # importing the sibling would otherwise write scripts/__pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan  # noqa: E402  (a sibling script, not an installed package)

GENERATION_ONE = ("orchestrator-mode", "implement-ticket", "implement-feature", "implement-backlog")
CRITERIA_HEADINGS = ("Acceptance criteria", "Acceptance", "Done when")
BUCKETS = {f"{low}-{high}": range(low, high + 1) for low, high in ((0, 50), (51, 300), (301, 1500))}
PER_BUCKET = 10
CHECK_TIMEOUT = 3600  # seconds, for each of setup and check
CLOCK_SLACK = timedelta(minutes=1)  # between the machine's clock in the log and GitHub's
EXIT_SHORT = 3
NO_PUSH = "GitHub records no push to the PR's branch by the time it was first ready for review"
UNREAD = "GitHub's record of the PR's history or of the pushes to its branch could not be read"
PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
MODEL_NAME = re.compile(r"[A-Za-z][\w.:@/-]*")
# The commands an opening call may run besides gh pr create. Each is a program, or the builtin cd, that cannot end
# the shell or skip what follows it.
OTHERS = ("cd", "git", "cat", "tail")
# The longest opening call, in bytes of UTF-8. No piece of a call expands to more than its text in bash or zsh, as no
# word starts with a plain =, so this bounds the arguments of each command in it.
LONGEST = 64 * 1024
# The pieces an opening call is made of, tried in turn at each point. A call with any other text has no opening form.
# APART and AFTER hold a redirection to a word of its own.
APART = r"(?<![^ \t\n;|&])"
AFTER = r"(?=[ \t\n;|&]|\Z)"
PIECE = re.compile(rf"""
    (?P<blank>[ \t]+|(?<=[ \t])\\\n)
  | (?P<op>&&|\|(?![|&])|;(?!;)|\n)
  | (?P<errors>{APART}2>&1{AFTER})
  | (?P<to>{APART}>>?{AFTER})
  | (?P<here>{APART}<<'(?P<delimiter>\w+)'{AFTER})
  | (?P<body>"\$\(cat\ <<'(?P<inner>\w+)'\n(?P<lines>(?:.*\n)*?)(?P=inner)\n\)")
  | (?P<plain>[A-Za-z0-9_./,:=@%+-]+)
  | (?P<quoted>'[^']*'|"[^"\\$`]*"|\\[^\n])
""", re.X | re.A)
TAIL = re.compile(r"-[0-9]+|-n [0-9]+")  # what a tail that reads gh's pipe may take: a count of lines and no file
# CommonMark's HTML blocks of kinds 1 to 6: what starts one and what ends it; a blank line ends kinds 6 and 7.
BLANK = re.compile(r"\A[ \t]*\Z")
HTML_BLOCKS = [
    (re.compile(r"<(?:pre|script|style|textarea)(?:[ \t>]|$)", re.I), re.compile(r"</(?:pre|script|style|textarea)>", re.I)),
    (re.compile(r"<!--"), re.compile(r"-->")),
    (re.compile(r"<\?"), re.compile(r"\?>")),
    (re.compile(r"<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"<!\[CDATA\["), re.compile(r"\]\]>")),
    (re.compile(r"</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|"
                r"dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|"
                r"html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|"
                r"section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:[ \t>]|/>|$)", re.I), BLANK)]
# A list item's marker and the spaces after it; more than 4 spaces make the item open with code.
MARKER = re.compile(r"(?:[-*+]|([0-9]{1,9})[.)])(?: {1,4}|[ \t]*$)")
SETEXT = re.compile(r"(?:=+|-+)[ \t]*")  # the underline that makes the paragraph above it a heading
BREAK = re.compile(r"([-*_])(?:[ \t]*\1){2,}[ \t]*")  # - - - is a break, not an item
# The start of a block that is not a paragraph or a list: a quote, HTML, a fence, an ATX heading, an underline, a break.
OPENS = re.compile(rf"[<>]|`{{3}}|~{{3}}|#{{1,6}}(?:[ \t]|$)|(?:{SETEXT.pattern})$|(?:{BREAK.pattern})$")
# Kind 7: one whole open or closing tag alone on its line.
TAG_LINE = re.compile(r"(?:<[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[A-Za-z_:][\w.:-]*(?:[ \t]*=[ \t]*(?:[^ \t\"'=<>`]+|'[^']*'"
                      r"|\"[^\"]*\"))?)*[ \t]*/?>|</[A-Za-z][A-Za-z0-9-]*[ \t]*>)[ \t]*")
HEADING = re.compile(r"(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*")  # an ATX heading: its level and its text


def one_of(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " or " + items[-1]


HELP = f"""\
Draw the replay set: {PER_BUCKET * len(BUCKETS)} tickets generation one finished, {PER_BUCKET} per size bucket.

Usage: python3 scripts/draw.py [--seed N]

The pool is every ticket that meets all of these:
- One session under $CLAUDE_CONFIG_DIR/projects (default ~/.claude) opened the
  ticket's PR, itself or through a helper: a Bash call in its log runs
  `gh pr create` for certain, the call's result holds the PR's URL, and the
  time GitHub gives for the PR's opening falls between the call and its
  result, give or take {CLOCK_SLACK.seconds // 60} minute. No other session opened or may have opened
  the PR, and the session opened or may have opened no other PR.
- A call runs `gh pr create` for certain when it exited 0 and has this form,
  which shows that the shell started that command:
  - The call is commands joined by &&, |, ; and new lines. More new lines
    may start the call or follow any of these, and a ; may end it. The call
    is at most {LONGEST // 1024} KiB in UTF-8.
  - One command is gh pr create, its three words unquoted, with nothing
    before them and no redirection between them, as in
      gh pr create --title "t" --body "b"
  - That command comes after the last ; or new line that ends a command, and
    first in its pipeline. After its three words it may send its errors to
    its output with 2>&1.
  - Or the call is that command piped straight to one tail -N or tail -n N,
    with no redirection of its own, and nothing else, as in
      gh pr create --fill 2>&1 | tail -1
  - Every other command is {one_of(list(OTHERS))}, its name written plain and
    unquoted. Each but a tail that reads gh's pipe may, after its name,
    write its output to a file with > or >>, send its errors to its output
    with 2>&1, and read a here-document whose delimiter is letters, digits
    and _ in single quotes, as in
      cat > body.md <<'EOF'
      Body text.
      EOF
      git push -u origin b && gh pr create --body-file body.md
  - Each of those redirections is a word of its own, with a blank before it
    and a blank, an operator or the end of the call after it.
  - Each word is made of letters, digits and _ . / , : = @ % + -, of text in
    single quotes, of text in double quotes with no $, ` or \\, of a backslash
    and the character after it, and of a body in this form, with a delimiter
    of letters, digits and _ in place of EOF, whose lines are text and never
    commands, and none of which starts with the delimiter:
      --body "$(cat <<'EOF'
      Body text.
      EOF
      )"
    No word starts with a plain =. A backslash that ends a line, after a
    blank, joins the next line to it.
  The draw takes for granted that the call ran in bash 5.2 or later, or in
  zsh 5.9 or later, with its default options; that no alias, function,
  variable or option set before the call changes what a name in it runs;
  that gh names the GitHub CLI and {one_of(list(OTHERS)).replace(" or ", " and ")} the commands
  of those names, wherever the call runs them; and that the system can
  start a command whose arguments total {LONGEST // 1024} KiB.
  Any other call whose text holds gh, pr and create, in any order or case,
  with any text beside each, once its quotes, backslashes, $ signs and
  backslash-new lines are taken out, may have opened the PR its result
  names, if GitHub's time falls in its span. A call whose text does not hold
  the three words does not count. So a command that builds the words when it
  runs, or a script or program that runs gh pr create, leaves no evidence. A
  call may also have opened the PR when its line or its result's line has a
  time that is missing, has no zone or is at an end of the calendar. A PR in a
  repo outside repos.json counts on the command alone: opened or may have
  opened. Lines in the session's log or a helper's that carry another
  session's id, as lines a resumed session copied do, are left out of this
  reading of the session and credited to no other.
- The session's own responses name the model it ran on: the name most of
  them give, one vote per response, that starts with a letter and holds only
  letters, digits and . _ : @ / -. A helper's copy of one of those responses,
  with the same message id, supplies the name only when the session's log
  lacks one; a helper's own response does not count.
- That session loaded a generation-one skill:
  {one_of(list(GENERATION_ONE))}.
- The PR is merged and closes one issue, the ticket, in the PR's own repo. No
  other PR in the pool closes it.
- The ticket's body holds an item of a list under
  {one_of([f'"## {heading}"' for heading in CRITERIA_HEADINGS])}, read as Markdown:
  a list in code or in an HTML block does not count, and a "# " or "## "
  heading ends the section. A list the draw cannot read with certainty does
  not count either: the lists it reads are below.
- The PR's repo is in repos.json, and the ticket is in no earlier set, kept or
  set aside.

The draw reads the body as CommonMark's blocks, and a line ends only at a line
feed, a carriage return or both. Code, fenced or indented, and HTML blocks
hide what they hold. In the section the draw reads lists of items marked - * +
or ASCII digits and . or ), each with its text on its marker line. An item's
text can wrap onto the lines after it, however they are indented, until a
blank line or the next item. It is read without its marker or a task box. A
list nested in an item, its markers at most 3 columns past the item's text,
gives items of its own after their parent. Between lists stand paragraphs,
headings of level three and deeper, breaks such as * * *, and code and HTML
blocks. Any other line in the section is one the draw cannot read with
certainty: inside an item, a quote, code, a fence, HTML, a heading, a break or
a second paragraph; an item with nothing but white space after its marker and
any task box; an item with no task box whose text starts with < or >, three
backticks or three tildes, the one to six # of a heading, another marker, or
more than four spaces, or is a break or a line of = or -; a line indented into
an item that wraps its text and starts with < or >, three backticks or three
tildes, or the one to six # of a heading, or is a break or a line of = or -; a
quote; an underline below a line of text; and, right after a line of text, a
marker numbered other than 1 with no list open or indented at least to the
text of the last open item. Anywhere in the body but inside a fence or an HTML
block the draw holds open, which it opens only at a line indented at most 3
spaces, with no > or marker, that starts a fence or one of CommonMark's HTML
blocks of kinds 1 to 6, and holds until a later line ends it or its first line
does past the text that opens it, so is a line that is a "## " criteria
heading once its indent, the > of any quotes and any list markers are taken
off, when it had a > or a marker, or when it is indented and a line outside
such a block that starts, at most 3 spaces in, with a list marker came before
it, as it may stand inside a quote or an item; and a line indented at most 3
spaces that holds one HTML tag alone and starts none of those HTML blocks,
which may be text or an HTML block. Inside such a block, so is a non-blank
line indented less than the block's first line. Outside the criteria sections,
from a line outside such a block that starts, at most 3 spaces in, with a list
marker, that line included, to the next heading at the margin that starts with
#, so is a line outside such a block that starts with three backticks, three
tildes or < once its indent, any > and any list markers are taken off, unless
it starts at the margin with none of them, as it may open a block inside an
item. Outside the criteria sections such a line refuses the body only when it
or a line after it is a "## " criteria heading once its indent, any > and any
list markers are taken off; otherwise the list is the items read before it.
The items of the list are the ticket's requirements, in the order written, and
the draw stores them in its entry of the set.

A ticket's size is its PR's additions plus deletions. The buckets are
{one_of(list(BUCKETS)).replace(" or ", " and ")} changed lines. A larger PR is in no bucket.
Each bucket's pool is sorted by repo and ticket number, then shuffled by
random.Random seeded with "<seed>:<bucket>". The draw tries the tickets in that
order until {PER_BUCKET} pass. A try runs the repo's setup command, where it has one,
and then its check command, each with sh, in a clean checkout of the commit
before the merged PR: the first parent of the PR's merge commit. A step that
runs for more than {CHECK_TIMEOUT // 60} minutes is stopped. Setup and check run in one process
group, made for the try, so what setup starts runs on through the check. When
the try ends, whether it passes, fails, runs too long, or the draw gets Ctrl-C
or SIGTERM, whatever is still running in that group is stopped; SIGKILL to the
draw leaves it running, and a process that starts its own group or session is
not followed. A
ticket is set aside when its repo cannot be cloned, when that commit is missing
or cannot be checked out, when the PR came from a fork, when GitHub's record of
the PR's history or of its branch's pushes cannot be fetched or read, when that
record holds no push by the time the PR was first ready, or when its setup or
check exits non-zero or is stopped.

The commit first marked ready is the head of the PR's branch at the PR's first
ready_for_review event, or at its creation when it has none: the newest push
GitHub records for that branch at or before then.

Every file is in the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver):

  repos.json            The owner's repo list, written by hand. A JSON list of
                        {{"repo": "owner/name", "check": "<command>",
                        "setup": "<command>"}} objects. "setup" is optional.
  project-labels.json   The key from label to repo: {{"A": "owner/name", ...}}.
                        A repo keeps its label. A new repo takes the first
                        label not in use, in repos.json order: A to Z, then
                        AA, AB and on.
  replay-set-<n>.json   Set n, as {{"set", "seed", "drawn_at", "tickets",
                        "set_aside"}}. A ticket entry holds label, ticket,
                        bucket, size, title, body, requirements, base_commit,
                        ready_commit, model, pr, session, log and
                        check_output. Its requirements are a list of
                        strings. A set-aside entry holds label, ticket,
                        bucket, reason and check_output. Paths are relative
                        to the machine directory.
  checks/<label>-<ticket>.txt
                        The output of each try: its setup and check, or what
                        the clone, checkout or gh call that failed printed on
                        both streams, or gh's answer that could not be read,
                        or why it was not run.
  logs/<session>.jsonl and logs/<session>/
                        A copy of each kept ticket's session log and the
                        session's folder, scanned into scan-rows.jsonl. Each
                        transcript, the log's and each helper's, holds the
                        bytes the draw read when the session qualified,
                        checked by digest; a helper transcript that appeared
                        later is left out. A copy from an earlier draw is
                        replaced only once the new one is whole, checked and
                        scanned; until then it stays as it was.
  draw-work/            Clones and checkouts, removed when the draw ends.

Output names projects by label only. Before the count per bucket, the draw
prints how many PRs of the listed repos the first rule leaves out only
because a call may have opened a PR: a PR is counted when one session that
names its model, loaded a generation-one skill and could be scanned, with
every log of it read, opened or may have opened it, any other session only
may have opened it, and that session only may have opened any other PR. The
count is taken before the rules on the PR, its ticket and earlier sets, so it
is the most PRs the veto can have cost the pool. A session log and its helpers' logs are
read as a session only when the text of one of them holds github.com or a \\u
escape, as one must that holds a PR's URL. A log adds one, once, to the count
of skipped logs when an error arises while finding or reading its helpers'
logs or reading any one transcript, such as a helper folder that cannot be
listed, or while reading its model or skills or scanning it. Such a session
puts no ticket in the pool, but the calls in each transcript it could read
still count against other sessions. A log also adds one, once, when a call in
it printed the URL of a PR the draw asked GitHub about and the call's time or
its result's is missing or cannot be read. That call may have opened that PR,
so it counts against other sessions and against the session's other PRs; the
session can still put that PR's ticket in the pool through another call that
opened it.

After the count of vetoed PRs and before the count per bucket, the draw prints
how many tickets of the listed repos it left out because it refused their body
as above. A body is never refused when none of its lines is a "## " criteria
heading once its indent, any > and any list markers are taken off, or when
none of its lines starts with a list marker once its indent and any > are
taken off, as it then holds no item. That count is taken before the rules on a
ticket's other PRs and earlier sets, so it is the most tickets the reader can
have cost the pool.

Exit 0: a set was written. Exit 1: an error; no set was written. Exit 2: bad
usage. Exit {EXIT_SHORT}: a bucket holds fewer than {PER_BUCKET} tickets, or cannot reach {PER_BUCKET} once
tickets are set aside; no set was written, and the count per bucket is printed."""


class DrawError(Exception):
    """Ends the draw with exit 1 and no set written."""


class Unreadable(ValueError):
    """A line under a criteria heading that the requirements reader cannot read with certainty."""

    def __init__(self, number: int, line: str) -> None:
        super().__init__(f"line {number}, {line!r}")
        self.number, self.line = number, line


SIGNALS = (signal.SIGINT, signal.SIGTERM)  # what stops the draw, with one line that says so


class Stopped(BaseException):
    """SIGINT or SIGTERM, whose number it holds, raised where the draw is so that each cleanup runs; no handler for
    errors catches it."""


STOPPED_BY: list[int] = []  # the signal that stopped the draw; a later one does nothing, so the cleanups run whole


def stopped(number: int, frame: object) -> None:
    if not STOPPED_BY:
        STOPPED_BY.append(number)
        raise Stopped(number)


class GhFailed(DrawError):
    """A gh call that failed or gave an answer the draw cannot read; `output` holds the command, what gh
    printed on both streams, and its exit or why its answer cannot be read."""

    def __init__(self, message: str, output: str) -> None:
        super().__init__(message)
        self.output = output


def label_name(number: int) -> str:
    """1 is A, 26 is Z, 27 is AA."""
    label = ""
    while number:
        number, rest = divmod(number - 1, 26)
        label = chr(ord("A") + rest) + label
    return label


LABEL = re.compile(r"[A-Z]+")  # every name label_name gives, and nothing else


def generation_one(skills: list[str]) -> bool:
    # A plugin's skill may carry the plugin's name as a prefix, as in plugin:implement-ticket.
    return any(name.split(":")[-1] in GENERATION_ONE for name in skills)


def moment(text: str) -> datetime:
    """A time with its zone; a log's time without one cannot be set beside GitHub's."""
    found = datetime.fromisoformat(text)
    if found.tzinfo is None:
        raise ValueError(f"{text} has no time zone")
    return found


def log_time(text: object) -> datetime | None:
    """A log line's time, or None when it is missing or cannot be read."""
    try:
        return moment(text) if isinstance(text, str) else None
    except ValueError:
        return None


def parts(line: dict) -> list[dict]:
    content = (line.get("message") or {}).get("content")
    return [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []


def result_text(part: dict) -> str:
    content = part.get("content")
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content or "")


def runs_gh_pr_create(command: str, exited_zero: bool = True) -> str | None:
    """Whether a Bash call ran `gh pr create`: "opens" when it exited 0 and has an opening form, "maybe" when its
    text could spell the three words otherwise, None when it cannot. --help gives the forms and what they take for
    granted."""
    # With every quote, backslash, $ and backslash-newline taken out, text bash may join is joined. A word is matched
    # with any text on either side, since an expansion or a quote beside it may still leave it whole when bash runs.
    letters = re.sub(r"\\\n|[\\'\"$]", "", command).lower()
    if not all(word in letters for word in ("gh", "pr", "create")):
        return None
    return "opens" if exited_zero and opening_form(command) else "maybe"


def opening_form(command: str) -> bool:
    """Whether a call has the form --help gives for one whose exit of 0 shows bash started `gh pr create`."""
    if len(command.encode(errors="surrogatepass")) > LONGEST:
        return False

    def new(first: bool) -> dict:
        """A command: its words, each None unless plain; its redirections, each after how many words; its list;
        and whether it is first in its pipeline."""
        return {"words": [], "redirects": [], "list": lists, "first": first}
    lists = 0  # the lists a ; or new line has ended so far
    commands: list[dict] = []
    current = new(True)
    word: list[tuple[str, str]] = []  # the pieces of the word being read
    target = False  # a > or >> waits for its file's word
    here: list[str] = []  # the delimiters of here-documents whose bodies follow the next new line
    after, at = "\n", 0  # after: the operator that ended the last command

    def end_word() -> None:
        nonlocal word, target
        if word:
            text = "".join(piece for _, piece in word) if all(kind == "plain" for kind, _ in word) else None
            if not target:
                current["words"].append(text)
            word, target = [], False

    while at < len(command):
        found = PIECE.match(command, at)
        if not found:
            return False
        kind, text, at = found.lastgroup, found.group(), found.end()
        if kind in ("plain", "quoted", "body"):
            if here and "\n" in text or not word and text.startswith("=") or kind == "body" and any(
                    line.startswith(found["inner"]) for line in found["lines"].splitlines()):
                return False
            word.append((kind, text))
            continue
        end_word()
        if kind == "blank":
            continue
        if target or kind != "op" and not current["words"]:  # > waits for its file; a name comes before redirections
            return False
        if kind in ("errors", "to", "here"):
            current["redirects"].append((len(current["words"]), text if kind == "errors" else kind))
            target = kind == "to"
            if kind == "here":
                here.append(found["delimiter"])
        elif current["words"]:
            commands.append(current)
            lists += text in ";\n"
            current = new(text != "|")
            after = text
        elif text != "\n":
            return False
        if kind == "op" and text == "\n":
            for delimiter in here:
                while True:
                    end = command.find("\n", at)
                    line, at = (command[at:], len(command)) if end < 0 else (command[at:end], end + 1)
                    if line == delimiter:
                        break
                    if end < 0:
                        return False
            here = []
    end_word()
    if target or here or not current["words"] and after in ("&&", "|"):
        return False
    if current["words"]:
        commands.append(current)
    gh = [number for number, found in enumerate(commands) if found["words"][:3] == ["gh", "pr", "create"]]
    if len(gh) != 1:
        return False
    number = gh[0]
    opener, piped = commands[number], commands[number + 1:number + 3]
    if piped and not piped[0]["first"]:  # gh feeds a pipe: the call is gh and one tail that reads only it
        reader = piped[0]
        if (len(commands) != 2 or reader["words"][0] != "tail" or reader["redirects"]
                or None in reader["words"] or not TAIL.fullmatch(" ".join(reader["words"][1:]))):
            return False
    return (opener["first"] and opener["list"] == commands[-1]["list"]
            and all(words >= 3 and redirect == "2>&1" for words, redirect in opener["redirects"])
            and all(found["words"][0] in OTHERS for found in commands if found is not opener))


Run = tuple[datetime | None, datetime | None, bool]


def opened_prs(lines: list[dict]) -> dict[tuple[str, int], list[Run]]:
    """Each PR whose URL the result of a Bash call that runs or may run `gh pr create` prints, as
    (owner/name in lower case, number), with each such run as (the call's time, the result's time, whether
    the call runs it for certain). A time is None when its line has none, or one that cannot be read."""
    calls = {}
    for line in lines:
        for part in parts(line) if line.get("type") == "assistant" else []:
            if part.get("type") == "tool_use" and part.get("name") == "Bash":
                kind = runs_gh_pr_create(str((part.get("input") or {}).get("command")))
                if kind:
                    calls[part.get("id")] = (log_time(line.get("timestamp")), kind == "opens")
    found: dict[tuple[str, int], list[Run]] = {}
    for line in lines:
        for part in parts(line) if line.get("type") == "user" else []:
            call = calls.get(part.get("tool_use_id"))
            if call and part.get("type") == "tool_result" and not part.get("is_error"):
                for repo, number in PR_URL.findall(result_text(part)):
                    found.setdefault((repo.lower(), int(number)), []).append(
                        (call[0], log_time(line.get("timestamp")), call[1]))
    return found


def opened(runs: list[Run], created: datetime | None) -> tuple[str | None, bool]:
    """Whether a session's runs opened a PR: "opened", "maybe" or None; and whether a run could not be timed.

    `created` is GitHub's time for the PR's opening, None for a PR the draw does not ask about, whose
    runs count on their command alone. A run opened the PR when it ran `gh pr create` for certain and
    GitHub's time falls between its call and its result, give or take CLOCK_SLACK. A run that may
    have run it, inside that span, and a run whose times are missing or cannot be read, may have."""
    found, untimed = set(), False
    for start, end, certain in runs:
        if created is None:
            found.add("opened" if certain else "maybe")
            continue
        try:
            inside = start - CLOCK_SLACK <= created <= end + CLOCK_SLACK
        except (TypeError, OverflowError):  # a time missing, or at an end of the calendar
            untimed = True
            found.add("maybe")
        else:
            if inside:
                found.add("opened" if certain else "maybe")
    return next((state for state in ("opened", "maybe") if state in found), None), untimed


def parent_model(main: list[dict], helpers: list[dict]) -> str | None:
    """The model the session's own responses name most, one vote per response: a response is an API message
    id in the main log, or a main-log line without one. A helper's copy of a response, by the same id, only
    supplies a name the main log's copies lack. A helper's own responses do not count."""
    def message(line: dict) -> dict:
        found = line.get("message") if line.get("type") == "assistant" else None
        return found if isinstance(found, dict) else {}

    def name(line: dict) -> str | None:
        found = message(line).get("model")
        return found if isinstance(found, str) and MODEL_NAME.fullmatch(found) else None  # "<synthetic>" is no model
    votes: dict[object, str | None] = {}
    for number, line in enumerate(main):
        if message(line):
            key = message(line).get("id") or number
            votes[key] = votes.get(key) or name(line)
    for line in helpers:
        key = message(line).get("id")
        if key and key in votes and not votes[key]:
            votes[key] = name(line)
    counts: dict[str, int] = {}
    for found in votes.values():
        if found:
            counts[found] = counts.get(found, 0) + 1
    return max(counts, key=counts.get) if counts else None


def opens(line: str) -> bool:
    """True when an item's text, or a line inside an item, starts with what HELP says the reader refuses there."""
    return bool(OPENS.match(line) or MARKER.match(line))


def criteria(text: str) -> bool:
    """True when the line is what HELP calls a "## " criteria heading."""
    heading = HEADING.fullmatch(text.lstrip(" "))
    return bool(heading and len(text) - len(text.lstrip(" ")) < 4 and heading.group(1) == "##"
                and (heading.group(2) or "").lower() in {name.lower() for name in CRITERIA_HEADINGS})


def unquoted(line: str) -> str:
    """The line without its indent and the > of any quotes."""
    while (rest := line.lstrip(" ")).startswith(">"):
        line = rest[1:]
    return rest


def unmarked(line: str) -> str:
    """The line without its indent, the > of any quotes and the markers of any items."""
    while (marker := MARKER.match(rest := unquoted(line))) and rest:
        line = rest[marker.end():]
    return rest


def requirements(body: str | None) -> list[str]:
    """The text of each item of a list under a "## " heading among the CRITERIA_HEADINGS, in the order written.
    Unreadable names the first line the reader cannot read with certainty. HELP says which lists it reads."""
    # CommonMark ends a line only at \n, \r or both; str.splitlines also ends one at \v, \f, \x85 and others.
    lines = re.split(r"\r\n|\r|\n", (body or "").expandtabs(4))
    found: list[str] = []
    columns: list[int] = []  # the text column of each open item of the section, outermost first
    under = paragraph = False  # paragraph: the line before is text that a line of text continues
    after_item = False  # a line that starts with a list marker came before: an item may still be open
    loose = False  # such a line came outside the criteria sections since the last heading at the margin
    fence, html = "", None  # the open code fence; the pattern that ends the open HTML block
    block_indent = 0  # the indent of the open fence or HTML block's first line
    try:
        for number, text in enumerate(lines, 1):
            if (fence or html) and text.strip(" \t") and len(text) - len(text.lstrip(" ")) < block_indent:
                # Inside an item the block ends with the item, and at the top level it does not: no telling which.
                raise Unreadable(number, text)
            if fence:  # a fence ends at a line of at least as many of its own character
                if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", text):
                    fence = ""
                continue
            if html:
                if html.search(text):
                    html = None
                continue
            line = text.lstrip(" ")
            indent = len(text) - len(line)
            if not line:
                paragraph = False
                continue
            depth = sum(column <= indent for column in columns)  # the open items the line is indented into
            marker = MARKER.match(line) if indent - (columns[depth - 1] if depth else 0) < 4 else None
            marker = None if BREAK.fullmatch(line) else marker  # * * * is a break, not an item
            starts_item = bool(indent < 4 and MARKER.match(line) and not BREAK.fullmatch(line))
            after_item = after_item or starts_item
            loose = loose or starts_item and not under
            if loose and not under and (indent or line != unmarked(line)) and re.match(r"`{3}|~{3}|<", unmarked(line)):
                # A fence or HTML block that may open inside an item outside the sections: where it ends, no telling.
                raise Unreadable(number, text)
            if criteria(unmarked(line)) and (line != unmarked(line) or indent and after_item):
                raise Unreadable(number, text)  # a criteria heading in a quote or an item, or that may be in an item
            if under and (depth or marker or line.startswith(">") or paragraph and SETEXT.fullmatch(line)):
                content = line[marker.end():].rstrip(" \t") if marker else ""
                if marker and content and not content.startswith(" ") and not opens(content) and not (
                        depth == len(columns) and paragraph and int(marker.group(1) or 1) != 1):
                    del columns[depth:]
                    columns.append(indent + marker.end())
                    found.append(re.sub(r"\A\[[ xX]\](?:[ \t]+|\Z)", "", content))
                    if not found[-1].strip():  # no text, or a task box with none: the judge's test
                        raise Unreadable(number, text)
                    paragraph = True
                elif depth and paragraph and not opens(line):
                    found[-1] += " " + line.rstrip(" \t")
                else:
                    raise Unreadable(number, text)
                continue
            start = indent < 4 and next(((begin, end) for begin, end in HTML_BLOCKS if begin.match(line)), None)
            if indent < 4 and (opening := re.match(r"`{3,}(?!.*`)|~{3,}", line)):
                fence, block_indent = opening.group(), indent
            elif start:
                begin, end = start
                html = None if end is not BLANK and end.search(line, begin.match(line).end()) else end
                block_indent = indent
            elif indent < 4 and TAG_LINE.fullmatch(line):  # an HTML block, or a paragraph's text: the line above says
                raise Unreadable(number, text)
            elif indent < 4 and (heading := HEADING.fullmatch(line)):
                loose = loose and bool(indent)  # a heading at the margin ends every item
                if len(heading.group(1)) <= 2:  # a deeper heading stays in the section
                    under = criteria(text)
            elif not (indent < 4 and (BREAK.fullmatch(line) or paragraph and SETEXT.fullmatch(line))):
                # Text: it continues the paragraph above, or starts one; indented, after no paragraph, it is code.
                if paragraph and columns:
                    found[-1] += " " + line.rstrip(" \t")
                elif not paragraph:
                    columns.clear()
                paragraph = paragraph or indent < 4
                continue
            columns.clear()  # any other block ends the list and the paragraph
            paragraph = False
    except Unreadable as refusal:
        # Outside every criteria section, a line the reader cannot be sure of costs the list only when a criteria
        # heading may come at or after it; the items read before it stand.
        # A body with no line that may start an item has no list: no refusal can cost it one.
        if not any(MARKER.match(unquoted(text)) for text in lines):
            return found
        if under or any(criteria(unmarked(text)) for text in lines[refusal.number - 1:]):
            raise
    return found


def pages(text: str) -> list:
    """The items of every page `gh api --paginate` printed: one JSON list per page."""
    decoder, items, at = json.JSONDecoder(), [], 0
    text = text.strip()
    while at < len(text):
        page, at = decoder.raw_decode(text, at)
        if not isinstance(page, list):
            raise ValueError("a page is not a list")
        items += page
        at = len(text) - len(text[at:].lstrip())
    return items


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except ValueError:
        raise DrawError(f"{path} is not JSON.")


class Draw:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.state = scan.state_dir()
        self.work = self.state / "draw-work"
        self.clones: dict[str, Path] = {}  # label: the repo's clone, once one has worked

    def gh(self, label: str, read: Callable[[str], Any], *args: str) -> Any:
        """What `read` makes of the output of `gh <args>`. A call that fails, or whose output `read` cannot
        read, raises GhFailed, its output holding what gh printed on both streams."""
        result = subprocess.run(["gh", *args], text=True, capture_output=True)
        printed = f"$ gh {shlex.join(args)}\n{result.stdout}{result.stderr}".rstrip("\n")
        error = self.state / "draw-error.txt"
        if result.returncode:
            # gh's own message can name the repo, so it goes to a file, not to the output.
            scan.write_private(error, result.stdout + result.stderr)
            raise GhFailed(f"`gh {args[0]} {args[1]}` failed for project {label} with exit {result.returncode}. "
                           f"Its message is in {error}.", f"{printed}\ngh exit {result.returncode}\n")
        try:
            return read(result.stdout)
        except Exception as failure:  # whatever is wrong with the answer, it is the answer's
            scan.write_private(error, result.stdout)
            kind = type(failure).__name__
            raise GhFailed(f"`gh {args[0]} {args[1]}` gave an answer the draw cannot read for project {label} "
                           f"({kind}). The answer is in {error}.", f"{printed}\nthe draw cannot read the answer ({kind})\n")

    def repos(self) -> dict[str, dict]:
        path = self.state / "repos.json"
        if not path.is_file():
            raise DrawError(f"{path} does not exist. Write the repo list there first; --help gives its format.")
        entries = read_json(path)
        if not isinstance(entries, list) or not all(
                isinstance(entry, dict) and isinstance(entry.get("repo"), str)
                and re.fullmatch(r"[\w.-]+/[\w.-]+", entry["repo"])
                and isinstance(entry.get("check"), str) and entry["check"].strip()
                and isinstance(entry.get("setup", ""), str) for entry in entries):
            raise DrawError(f'{path} must be a list of {{"repo": "owner/name", "check": "...", "setup": "..."}} '
                            "objects, with setup optional.")
        return {entry["repo"].lower(): entry for entry in entries}

    def labels(self, repos: dict[str, dict]) -> dict[str, str]:
        """Each listed repo's label, from the key file; a new repo gets the next free label."""
        path = self.state / "project-labels.json"
        key = read_json(path) if path.is_file() else {}
        labels = {repo.lower(): label for label, repo in key.items()}
        new = [repo for repo in repos if repo not in labels]
        for repo in new:
            label = next(label for label in map(label_name, range(1, len(key) + 2)) if label not in key)
            labels[repo], key[label] = label, repos[repo]["repo"]
        if new:
            scan.write_private(path, json.dumps(key, indent=2) + "\n")
        return labels

    def sets(self) -> dict[int, Path]:
        """The sets earlier calls wrote, by number."""
        return {int(found.group(1)): path for path in self.state.iterdir()
                if (found := re.fullmatch(r"replay-set-(\d+)\.json", path.name))}

    def used(self) -> set[tuple[str, int]]:
        """Every (label, ticket) an earlier set kept or set aside."""
        used = set()
        for path in self.sets().values():
            earlier = read_json(path)
            used |= {(entry["label"], entry["ticket"]) for entry in earlier["tickets"] + earlier["set_aside"]}
        return used

    def view(self, repo: dict, label: str, pr: int) -> dict:
        def read(text: str) -> dict:
            view = json.loads(text)
            view["created"] = moment(view["createdAt"])
            return view
        return self.gh(label, read, "pr", "view", str(pr), "--repo", repo["repo"], "--json",
                       "state,additions,deletions,createdAt,mergeCommit,closingIssuesReferences,"
                       "headRefName,isCrossRepository")

    def candidate(self, repo: dict, label: str, pr: int, view: dict, opener: dict) -> dict | None:
        size = view["additions"] + view["deletions"]
        bucket = next((name for name, sizes in BUCKETS.items() if size in sizes), None)
        closes = view.get("closingIssuesReferences") or []
        if (view.get("state") != "MERGED" or bucket is None or len(closes) != 1
                or "/".join((closes[0]["repository"]["owner"]["login"], closes[0]["repository"]["name"])).lower()
                != repo["repo"].lower()):
            return None
        number = closes[0]["number"]
        issue = self.gh(label, json.loads, "issue", "view", str(number), "--repo", repo["repo"], "--json", "title,body")
        try:
            required = requirements(issue.get("body"))
        except Unreadable:
            self.refused.add((repo["repo"], number))
            return None
        if not required:
            return None
        return {"label": label, "ticket": number, "bucket": bucket, "size": size, "title": issue["title"],
                "body": issue["body"], "requirements": required, "pr": pr, "session": opener["log"].stem,
                "model": opener["model"],
                "repo": repo, "merge": view["mergeCommit"]["oid"], "created": view["createdAt"],
                "branch": view["headRefName"], "fork": view["isCrossRepository"], "source": opener["log"],
                "transcripts": opener["transcripts"]}

    def sessions(self) -> tuple[list[dict], int]:
        """Each session with a run that runs or may run `gh pr create` and prints a PR's URL, and how many
        session logs could not be read. Each transcript, the log's and each helper's, is read once, and its
        runs count whatever happens to another transcript of the session or to finding its helpers. A
        session with any failure is counted and not eligible, but its readable runs count against others."""
        sessions, unreadable = [], 0
        for log in sorted((scan.config_dir() / "projects").glob("*/*.jsonl")):
            failed = False
            try:
                helpers = scan.helper_logs(log)
            except (Exception, SystemExit):
                helpers, failed = [], True
            # The bytes the draw decides on: a kept session's archive holds just these, checked by digest.
            texts, transcripts = {}, {}
            for path in [log, *helpers]:
                try:
                    data = path.read_bytes()
                except (Exception, SystemExit):
                    failed = True
                    continue
                transcripts[path.relative_to(log.parent)] = (len(data), hashlib.sha256(data).hexdigest())
                texts[path] = data.decode(errors="replace")
            # A cheap filter: a PR's URL holds github.com, or a JSON escape stands for some of its letters.
            if not any("github.com" in text or "\\u" in text for text in texts.values()):
                unreadable += failed
                continue
            lines: dict[Path, list[dict]] = {}
            prs: dict[tuple[str, int], list[Run]] = {}
            for path, text in texts.items():
                try:  # a line copied from an earlier session is that session's, and no other's
                    lines[path] = [line for line in scan.parse_lines(text, path)
                                   if line.get("sessionId") in (None, log.stem)]
                    for key, runs in opened_prs(lines[path]).items():
                        prs.setdefault(key, []).extend(runs)
                except (Exception, SystemExit):
                    lines.pop(path, None)
                    failed = True
            unreadable += failed
            if not prs:
                continue
            main = lines.get(log, [])
            own_helpers = [line for path in helpers for line in lines.get(path, [])]
            session = {"log": log, "prs": prs, "eligible": False, "counted": failed, "transcripts": transcripts}
            if not failed:
                try:
                    session["model"] = parent_model(main, own_helpers)
                    if session["model"] and generation_one(scan.skills(main + own_helpers)):
                        scan.scan(log.stem, log)  # the draw saves the scan's row for a kept ticket
                        session["eligible"] = True
                except (Exception, SystemExit):
                    session["counted"] = True
                    unreadable += 1
            sessions.append(session)
        return sessions, unreadable

    def pool(self, repos: dict[str, dict], labels: dict[str, str]) -> dict[str, list[dict]]:
        sessions, unreadable = self.sessions()
        views = {key: self.view(repos[key[0]], labels[key[0]], key[1])
                 for key in sorted({key for session in sessions if session["eligible"] for key in session["prs"]})
                 if key[0] in repos}
        touched: dict[tuple[str, int], list[dict]] = {}  # the sessions that opened or may have opened each PR
        for session in sessions:
            session["opened"] = {}
            for key, runs in session["prs"].items():
                state, untimed = opened(runs, views[key]["created"] if key in views else None)
                if untimed and not session["counted"]:
                    session["counted"] = True
                    unreadable += 1
                if state:
                    session["opened"][key] = state
                    touched.setdefault(key, []).append(session)
        if unreadable:
            print(f"Skipped {unreadable} session logs that could not be read.")

        def alone(key: tuple[str, int], found: list[dict], maybe: tuple[str, ...]) -> bool:
            """Whether one eligible session opened the PR, or has a state in `maybe` for it, while every other
            session's state for the PR, and that session's state for each other PR, is in `maybe`."""
            return any(session["eligible"] and session["opened"][key] in ("opened", *maybe)
                       and all(other["opened"][key] in maybe for other in found if other is not session)
                       and all(state in maybe for each, state in session["opened"].items() if each != key)
                       for session in found)
        vetoed = sum(key[0] in repos and alone(key, found, ("maybe",)) and not alone(key, found, ())
                     for key, found in touched.items())
        print(f"Vetoed {vetoed} PRs of the listed repos: a call that may have opened each, or another PR of the "
              f"session that opened it, keeps it out of the pool.")
        tickets: dict[tuple[str, int], dict | None] = {}
        self.refused: set[tuple[str, int]] = set()  # the tickets whose list the reader refuses
        for (repo, pr), found in sorted(touched.items()):
            if repo not in repos or not alone((repo, pr), found, ()):
                continue
            try:
                candidate = self.candidate(repos[repo], labels[repo], pr, views[(repo, pr)], found[0])
            except DrawError:
                raise
            except Exception as error:  # a field missing from GitHub's answer, or of the wrong kind
                raise DrawError(f"GitHub's answer about a PR or issue of project {labels[repo]} could not be read "
                                f"({type(error).__name__}).")
            if candidate:
                key = (repo, candidate["ticket"])
                tickets[key] = None if key in tickets else candidate  # a ticket with two PRs has no PR of its own
        print(f"Refused {len(self.refused)} tickets of the listed repos: a list under a criteria heading that the draw "
              f"cannot read with certainty keeps each out of the pool.")
        used = self.used()
        buckets: dict[str, list[dict]] = {name: [] for name in BUCKETS}
        for _, found in sorted(tickets.items()):  # by repo and ticket, so the repo list's order changes nothing
            if found and (found["label"], found["ticket"]) not in used:
                buckets[found["bucket"]].append(found)
        return buckets

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], text=True, capture_output=True)

    def clone(self, candidate: dict) -> tuple[Path, str]:
        """The repo's clone, and the failed clone's output, or "" when it was cloned."""
        label, repo = candidate["label"], candidate["repo"]["repo"]
        if label not in self.clones:
            target = self.work / label
            shutil.rmtree(target, ignore_errors=True)  # what an earlier failed clone left would make this one fail
            result = subprocess.run(["gh", "repo", "clone", repo, str(target)], text=True, capture_output=True)
            if result.returncode:  # the repo's next ticket tries again
                return target, (f"$ gh repo clone {repo} {target}\n{result.stdout}{result.stderr}".rstrip("\n")
                                + f"\nclone exit {result.returncode}\n")
            self.clones[label] = target
        return self.clones[label], ""

    def ready_commit(self, candidate: dict) -> str | None:
        repo, label = candidate["repo"]["repo"], candidate["label"]

        def first_ready(text: str) -> datetime:
            return min((moment(event["created_at"]) for event in pages(text) if event.get("event") == "ready_for_review"),
                       default=moment(candidate["created"]))
        ready = self.gh(label, first_ready, "api", "--paginate", f"repos/{repo}/issues/{candidate['pr']}/timeline")

        def head_then(text: str) -> str:
            pushes = [push for push in pages(text) if moment(push["timestamp"]) <= ready]  # pushed seconds before
            head = max(pushes, key=lambda push: moment(push["timestamp"]), default={}).get("after", "")
            if not isinstance(head, str):
                raise TypeError("a push's after is not a commit")
            return head
        ref = quote(f"refs/heads/{candidate['branch']}", safe="/")
        head = self.gh(label, head_then, "api", "--paginate", f"repos/{repo}/activity?ref={ref}&per_page=100")
        return head if head.strip("0") else None  # a deleted branch's push leads to 000…

    def run_check(self, candidate: dict, clone: Path, base: str, output: Path) -> str | None:
        """Run setup and check in a clean checkout of `base`; None when both pass, else the reason."""
        tree = self.work / f"{candidate['label']}-{candidate['ticket']}"
        started: list[subprocess.Popen] = []  # the try's group keeper, then each step
        signalled: list[bool] = []

        def stop() -> None:
            """Signal the try's group once, then reap each process; a second call only finishes the reaping."""
            if started and not signalled:
                signalled.append(True)  # before the signal, so an interrupt after it cannot bring a second one
                try:  # the keeper is not reaped yet, so the group's id is still its own
                    os.killpg(started[0].pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for process in started:
                process.wait()
            if started:
                started[0].stdin.close()
        try:
            added = self.git("-C", str(clone), "worktree", "add", "--detach", "--quiet", str(tree), base)
            if added.returncode:
                output.write_text(f"$ git worktree add --detach {tree} {base}\n{added.stdout}{added.stderr}".rstrip("\n")
                                  + f"\ncheckout exit {added.returncode}\n")
                return "the commit before the merged PR cannot be checked out"
            # A process group for the whole try, held by a keeper that only waits, and ends if the draw dies. Setup
            # and check join it, so what setup starts runs on through the check, and what either leaves is stopped
            # when the try ends.
            started.append(subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, process_group=0))
            with open(output, "w") as out:
                for step in ("setup", "check"):
                    command = candidate["repo"].get(step)
                    if not command:
                        continue
                    out.write(f"$ {command}\n")
                    out.flush()
                    process = subprocess.Popen(command, shell=True, cwd=tree, stdin=subprocess.DEVNULL, stdout=out,
                                               stderr=subprocess.STDOUT, process_group=started[0].pid)
                    started.append(process)
                    try:
                        code = process.wait(timeout=CHECK_TIMEOUT)
                    except subprocess.TimeoutExpired:
                        stop()
                        out.write(f"\n{step} ran for more than {CHECK_TIMEOUT} seconds\n")
                        return f"{step} ran for more than {CHECK_TIMEOUT} seconds"
                    out.write(f"\n{step} exit {code}\n")
                    if code:
                        return f"{step} exited {code}"
        finally:  # on success, failure, timeout, interrupt or SIGTERM alike, with both held until it is done
            held = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
            try:
                stop()
                self.git("-C", str(clone), "worktree", "remove", "--force", str(tree))
                self.git("-C", str(clone), "worktree", "prune")
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, held)
        return None

    def try_ticket(self, candidate: dict) -> str | None:
        """Fill in the entry's commits and run its check; None when it is kept, else why it is set aside."""
        output = self.state / "checks" / f"{candidate['label']}-{candidate['ticket']}.txt"
        output.parent.mkdir(exist_ok=True)
        candidate["check_output"] = str(output.relative_to(self.state))
        clone, failure = self.clone(candidate)
        if failure:
            output.write_text(failure)
            return "the repo cannot be cloned"
        candidate["base_commit"] = self.git("-C", str(clone), "rev-parse", "--verify", "--quiet",
                                            candidate["merge"] + "^1").stdout.strip()
        if not candidate["base_commit"]:
            reason = "the commit before the merged PR is missing"
        elif candidate["fork"]:
            reason = "the PR came from a fork, whose pushes GitHub records in the fork"
        else:
            try:
                ready = self.ready_commit(candidate)
            except GhFailed as error:
                output.write_text(error.output)
                return UNREAD
            if not ready:
                reason = NO_PUSH
            else:
                candidate["ready_commit"] = ready
                return self.run_check(candidate, clone, candidate["base_commit"], output)
        output.write_text(reason + "\n")
        return reason

    def save_log(self, candidate: dict) -> str:
        """Copy the session's log and its folder, check and scan the copy, and only then put it in place.

        Each transcript, the log's and each helper's, is copied as the bytes the draw read when the session
        qualified, checked by their digest; a helper transcript that appeared later is left out. The copy is
        made in logs/.new-<session>; an earlier copy of the session moves to logs/.old-<session> only once
        the new one is whole and scanned, and is removed once the new one is in place. A signal holds off from that
        move until the scan row is written; before it, the earlier copy stays as it was and no .new- folder is
        left."""
        source = candidate["source"]
        logs = self.state / "logs"
        staged, old = logs / f".new-{source.stem}", logs / f".old-{source.stem}"
        names = (source.name, source.stem)  # the log and its folder
        try:
            logs.mkdir(exist_ok=True)
            if old.exists():  # an earlier draw stopped while it put a copy in place
                for name in names:
                    if (old / name).exists() and not (logs / name).exists():
                        os.replace(old / name, logs / name)
                shutil.rmtree(old)
            shutil.rmtree(staged, ignore_errors=True)
            staged.mkdir()
            if source.with_suffix("").is_dir():
                try:  # the folder's other files where they can be read; the transcripts follow
                    shutil.copytree(source.with_suffix(""), staged / source.stem,
                                    ignore=shutil.ignore_patterns("agent-*.jsonl"))
                except shutil.Error:  # a file it cannot read stays behind
                    pass
            for relative, (size, digest) in candidate["transcripts"].items():
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source.parent / relative, target)
                if target.stat().st_size < size:
                    raise OSError(f"{target.name} did not copy whole")
                os.truncate(target, size)  # what a running session wrote after the draw read it
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise OSError(f"{target.name} changed after the draw read it")
            row = scan.scan(source.stem, staged / source.name)
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            try:
                old.mkdir()
                for name in names:
                    if (logs / name).exists():
                        os.replace(logs / name, old / name)
                for name in names:
                    if (staged / name).exists():
                        os.replace(staged / name, logs / name)
                shutil.rmtree(old)
                shutil.rmtree(staged)
                scan.write_row(row)
            finally:  # a signal held off is raised here
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        except (Exception, SystemExit, Stopped) as error:  # its message can name the project's folder
            try:
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            except Stopped as late:  # a signal that came just before; the signals are held all the same
                error, mask = late, None
            for name in names if old.exists() else ():  # put back the earlier copy where it was moved
                if (old / name).exists():
                    if (logs / name).is_dir():
                        shutil.rmtree(logs / name)
                    elif (logs / name).exists():
                        (logs / name).unlink()
                    os.replace(old / name, logs / name)
            shutil.rmtree(old, ignore_errors=True)
            shutil.rmtree(staged, ignore_errors=True)
            if mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            if isinstance(error, Stopped):
                raise error
            raise DrawError(f"could not save the session log of project {candidate['label']} ticket "
                            f"{candidate['ticket']} ({type(error).__name__}).")
        return str((logs / source.name).relative_to(self.state))

    def run(self) -> int:
        with open(self.state / "draw.lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DrawError("another draw is running in this machine directory.")
            print(f"Seed {self.seed}.")
            repos = self.repos()
            buckets = self.pool(repos, self.labels(repos))
            kept: list[dict] = []
            aside: list[dict] = []
            if all(len(found) >= PER_BUCKET for found in buckets.values()):
                shutil.rmtree(self.work, ignore_errors=True)
                self.work.mkdir()
                try:
                    for name, found in buckets.items():
                        order = list(found)
                        random.Random(f"{self.seed}:{name}").shuffle(order)
                        for candidate in order:
                            if sum(entry["bucket"] == name for entry in kept) == PER_BUCKET:
                                break
                            reason = self.try_ticket(candidate)
                            if reason:
                                aside.append({**candidate, "reason": reason})
                            else:
                                kept.append(candidate)
                finally:
                    shutil.rmtree(self.work, ignore_errors=True)
            for name, found in buckets.items():
                print(f"{name}: pool {len(found)}, set aside {sum(entry['bucket'] == name for entry in aside)}, "
                      f"kept {sum(entry['bucket'] == name for entry in kept)}.")
            if len(kept) < PER_BUCKET * len(BUCKETS):
                print(f"No set written: a bucket cannot reach {PER_BUCKET} tickets.")
                return EXIT_SHORT
            for candidate in kept:
                candidate["log"] = self.save_log(candidate)
            fields = ("label", "ticket", "bucket", "size", "title", "body", "requirements", "base_commit",
                      "ready_commit", "model", "pr", "session", "log", "check_output")
            number = 1 + max(self.sets(), default=0)
            path = self.state / f"replay-set-{number}.json"
            # From here the draw ends with its set: a signal stays held past its exit, and a signal that came just
            # before is raised here, with no set written.
            signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            scan.write_private(path, json.dumps({
                "set": number, "seed": self.seed, "drawn_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "tickets": [{field: entry[field] for field in fields} for entry in kept],
                "set_aside": [{field: entry[field] for field in ("label", "ticket", "bucket", "reason", "check_output")}
                              for entry in aside]}, indent=2) + "\n")
            print(f"Wrote {path}.")
            return 0


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(HELP)
        return 0
    if argv == []:
        seed = random.SystemRandom().randrange(2**32)
    elif len(argv) == 2 and argv[0] == "--seed" and argv[1].isdecimal():
        seed = int(argv[1])
    else:
        print(HELP, file=sys.stderr)
        return 2
    for number in SIGNALS:  # a SIGINT the caller ignored stays ignored, as a job started with & expects
        if signal.getsignal(number) != signal.SIG_IGN:
            signal.signal(number, stopped)
    try:
        try:
            return Draw(seed).run()
        finally:  # the draw's last line is printed, or is printed below: no signal follows it
            signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    except Stopped as stop:
        number = signal.Signals(stop.args[0])
        print(f"draw: stopped by {number.name}; no set written.", file=sys.stderr)
        return 128 + number
    except DrawError as error:
        print(f"draw: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
