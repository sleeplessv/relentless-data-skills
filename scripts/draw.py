#!/usr/bin/env python3
"""Draw the replay set. `--help` gives the rules and the files the draw reads and writes."""
from __future__ import annotations

import fcntl
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
HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*(['\"]?)([\w.-]+)\2")
OPERATORS = sorted([";;&", ";;", ";&", "&&", "||", "|&", "&>>", "&>", ">>", "<<-", "<<<", "<<", "<&", ">&", "<>",
                    ">|", ";", "&", "|", "(", ")", "<", ">", "\n"], key=len, reverse=True)
REDIRECTS = {"<", ">", ">>", "<<", "<<-", "<<<", "<&", ">&", "&>", "&>>", "<>", ">|"}
# Reserved words that put the command after them in a branch, a loop or a group.
COMPOUND = {"if", "then", "else", "elif", "while", "until", "do", "{", "for", "case", "select", "function"}
# Each prefix that runs the command after it, with its options that take a value.
PREFIXES = {"!": (), "time": (), "nohup": (), "command": (), "exec": ("-a",), "env": ("-u", "-C", "-P")}
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
# Kind 7: one whole open or closing tag alone on its line.
TAG_LINE = re.compile(r"(?:<[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[A-Za-z_:][\w.:-]*(?:[ \t]*=[ \t]*(?:[^ \t\"'=<>`]+|'[^']*'"
                      r"|\"[^\"]*\"))?)*[ \t]*/?>|</[A-Za-z][A-Za-z0-9-]*[ \t]*>)[ \t]*")


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
- A call runs `gh pr create` for certain when, read as shell words, it is the
  command's first command, or comes after only `cd` commands each followed by
  &&, ; or a new line, and no pipe or & follows it. Assignments and the
  prefixes !, time, command, exec, env and nohup may come before it, and gh
  may be named by its path. A call that runs it anywhere else, as in a branch,
  a loop, a group, a pipeline, the background or a command substitution, or
  that cannot be read, may have opened the PR its result names, if GitHub's
  time falls in its span. So may a call whose line or whose result's line
  has a time that is missing, has no zone or is at an end of the calendar.
  A PR in a repo outside repos.json counts on the command alone: opened or
  may have opened. A command run by another program, as with bash -c, does
  not count. Lines in the session's log or a helper's that carry another
  session's id, as lines a resumed session copied do, are left out of this
  reading of the session and credited to no other.
- The session's own responses name the model it ran on: a name that starts
  with a letter and holds only letters, digits and . _ : @ / -. A helper's
  copy of one of those responses, with the same message id, counts too; a
  helper's own response does not.
- That session loaded a generation-one skill:
  {one_of(list(GENERATION_ONE))}.
- The PR is merged and closes one issue, the ticket, in the PR's own repo. No
  other PR in the pool closes it.
- The ticket's body holds an item of a list under
  {one_of([f'"## {heading}"' for heading in CRITERIA_HEADINGS])}, read as Markdown:
  a list in code or in an HTML block does not count, nor does one in a
  blockquote, and any heading of level one or two ends the section.
- The PR's repo is in repos.json, and the ticket is in no earlier set, kept or
  set aside.

A ticket's size is its PR's additions plus deletions. The buckets are
{one_of(list(BUCKETS)).replace(" or ", " and ")} changed lines. A larger PR is in no bucket.
Each bucket's pool is sorted by repo and ticket number, then shuffled by
random.Random seeded with "<seed>:<bucket>". The draw tries the tickets in that
order until {PER_BUCKET} pass. A try runs the repo's setup command, where it has one,
and then its check command, each with sh, in a clean checkout of the commit
before the merged PR: the first parent of the PR's merge commit. A step that
runs for more than {CHECK_TIMEOUT // 60} minutes is stopped. Setup and check run in one process
group, made for the try, so what setup starts runs on through the check. When
the try ends, however it ends, whatever is still running in that group is
stopped; a process that starts its own group or session is not followed. A
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
                        bucket, size, title, body, base_commit, ready_commit,
                        model, pr, session, log and check_output. A set-aside
                        entry holds label, ticket, bucket, reason and
                        check_output. Paths are relative to the machine
                        directory.
  checks/<label>-<ticket>.txt
                        The output of each try: its setup and check, or what
                        the clone, checkout or gh call that failed printed on
                        both streams, or gh's answer that could not be read,
                        or why it was not run.
  logs/<session>.jsonl and logs/<session>/
                        A copy of each kept ticket's session log and the
                        session's folder, scanned into scan-rows.jsonl. Each
                        transcript, the log's and each helper's, is as the
                        draw read it when the session qualified, whole; a
                        helper transcript that appeared later is left out,
                        and a copy from an earlier draw is replaced.
  draw-work/            Clones and checkouts, removed when the draw ends.

Output names projects by label only. A session log and its helpers' logs are
read as a session only when the text of one of them holds github.com or a \\u
escape, as one must that holds a PR's URL. A log adds one to the count of
skipped logs when an error arises while reading it or its helpers' logs, such
as a helper folder that cannot be listed; the draw then skips it. A log also
adds one, once, when an error arises while reading its model or skills or
scanning it, or when a call in it printed the URL of a PR the draw asked GitHub
about and the call's time or its result's is missing or cannot be read. Such a
session puts no ticket in the pool, but its calls still count against other
sessions.

Exit 0: a set was written. Exit 1: an error; no set was written. Exit 2: bad
usage. Exit {EXIT_SHORT}: a bucket holds fewer than {PER_BUCKET} tickets, or cannot reach {PER_BUCKET} once
tickets are set aside; no set was written, and the count per bucket is printed."""


class DrawError(Exception):
    """Ends the draw with exit 1 and no set written."""


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


def quote_end(text: str, at: int, mark: str) -> int:
    """Where the quote or backtick that opens before `at` closes; -1 when it does not."""
    while at < len(text):
        if text[at] == "\\":
            at += 1
        elif text[at] == mark:
            return at
        at += 1
    return -1


def closing(text: str, at: int, opener: str = "(", closer: str = ")") -> int:
    """Where the bracket that opens before `at` closes, past quotes and nested brackets; -1 when it does not."""
    depth = 1
    while 0 <= at < len(text):
        char = text[at]
        if char == "\\":
            at += 1
        elif char == "'":
            at = text.find("'", at + 1)
        elif char in "\"`":
            at = quote_end(text, at + 1, char)
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if not depth:
                return at
        if at >= 0:
            at += 1
    return -1


def shell_tokens(command: str) -> tuple[list[tuple], list[str]] | None:
    """A command's tokens, and the text of each command it substitutes; None when it does not parse.

    A token is ("op", operator) or ("word", text, exact, quoted, assignment). Quotes and escapes are
    decoded. A word that holds an expansion is not exact, and holds "\\0" where the expansion stands."""
    tokens: list[tuple] = []
    inner: list[str] = []
    word: list | None = None  # [text, exact, quoted, assignment]

    def add(text: str, quoted: bool = False, exact: bool = True) -> None:
        nonlocal word
        if word is None:
            word = ["", True, False, False]
        if text == "=" and not quoted and not word[2] and word[1] and re.fullmatch(r"[A-Za-z_]\w*", word[0]):
            word[3] = True
        word[0] += text
        word[1] = word[1] and exact
        word[2] = word[2] or quoted

    def substitution(start: int, end: int, quoted: bool) -> int:
        if end < 0:
            raise ValueError("unclosed substitution")
        inner.append(command[start:end])
        add("\0", quoted, exact=False)
        return end + 1

    def dollar(at: int, quoted: bool) -> int:
        """Read the expansion at `at`, a "$"; return where reading goes on."""
        following = command[at + 1:at + 2]
        if following == "(":
            return substitution(at + 2, closing(command, at + 2), quoted)
        end = at + 2
        if following == "{":
            end = closing(command, at + 2, "{", "}") + 1
            if not end:
                raise ValueError("unclosed expansion")
        elif following.isalpha() or following == "_":
            while end < len(command) and (command[end].isalnum() or command[end] == "_"):
                end += 1
        elif not following or following not in "0123456789@*#?$!-":
            add("$", quoted)
            return at + 1
        add("\0", quoted, exact=False)
        return end

    at = 0
    try:
        while at < len(command):
            char = command[at]
            if char == "\\":
                if command[at + 1:at + 2] != "\n":  # a backslash before a new line joins the two lines
                    add(command[at + 1:at + 2], quoted=True)
                at += 2
            elif char == "'":
                end = command.find("'", at + 1)
                if end < 0:
                    raise ValueError("unclosed quote")
                add(command[at + 1:end], quoted=True)
                at = end + 1
            elif char == "$" and command[at + 1:at + 2] == "'":  # $'...' decodes escapes; only \' and \\ matter here
                at += 2
                while command[at:at + 1] != "'":
                    if at >= len(command):
                        raise ValueError("unclosed quote")
                    if command[at] == "\\":
                        at += 1
                    add(command[at:at + 1], quoted=True)
                    at += 1
                at += 1
            elif char == '"' or char == "$" and command[at + 1:at + 2] == '"':
                at += 1 if char == '"' else 2
                add("", quoted=True)
                while command[at:at + 1] != '"':
                    if at >= len(command):
                        raise ValueError("unclosed quote")
                    if command[at] == "\\" and command[at + 1:at + 2] in ("$", "`", '"', "\\", "\n"):
                        if command[at + 1] != "\n":
                            add(command[at + 1], quoted=True)
                        at += 2
                    elif command[at] == "$":
                        at = dollar(at, quoted=True)
                    elif command[at] == "`":
                        at = substitution(at + 1, quote_end(command, at + 1, "`"), quoted=True)
                    else:
                        add(command[at], quoted=True)
                        at += 1
                at += 1
            elif char == "`":
                at = substitution(at + 1, quote_end(command, at + 1, "`"), quoted=False)
            elif char == "$":
                at = dollar(at, quoted=False)
            elif char in "<>" and command[at + 1:at + 2] == "(":  # a process substitution is a word
                at = substitution(at + 2, closing(command, at + 2), quoted=False)
            elif char in " \t\r":
                if word is not None:
                    tokens.append(("word", *word))
                    word = None
                at += 1
            elif char == "#" and word is None:  # a comment runs to the end of its line
                end = command.find("\n", at)
                at = len(command) if end < 0 else end
            elif operator := next((op for op in OPERATORS if command.startswith(op, at)), None):
                if word is not None and not (operator[0] in "<>" and word[0].isdigit() and not word[2]):
                    tokens.append(("word", *word))  # digits right before a redirection name a file descriptor
                word = None
                tokens.append(("op", operator))
                at += len(operator)
            else:
                add(char)
                at += 1
    except ValueError:
        return None
    if word is not None:
        tokens.append(("word", *word))
    return tokens, inner


def strip_here_documents(command: str) -> tuple[str, list[str]]:
    """The command less its here-documents' bodies, which are input, not commands; and the bodies the shell
    expands, since a command substitution in one runs."""
    kept, expanded, ends = [], [], []
    for text in command.split("\n"):
        if ends:
            strip, quote, end, body = ends[0]
            if (text.lstrip("\t") if strip else text) == end:
                ends.pop(0)
                if not quote:
                    expanded.append("\n".join(body))
            else:
                body.append(text)
            continue
        kept.append(text)
        ends = [(strip, quote, end, []) for strip, quote, end in HEREDOC.findall(text)]
    expanded += ["\n".join(body) for strip, quote, end, body in ends if not quote]
    return "\n".join(kept), expanded


def runs_gh_pr_create(command: str) -> str | None:
    """Whether a Bash command runs `gh pr create`: "opens" when it does for certain, "maybe" when it may or
    when the command cannot be read, None when it does not, as when it only holds the words as text.

    For certain means, read as shell words: the first command, or one after only `cd` commands each
    followed by &&, ; or a new line, and itself followed by no pipe and no &. Assignments and the
    prefixes in PREFIXES may come before `gh`, and `gh` may be named by a path. Anywhere else, inside a
    branch, a loop, a group, a pipeline, the background or a command substitution, it may run."""
    command, expanded = strip_here_documents(command)
    read = shell_tokens(command)
    if read is None:
        return "maybe"
    tokens, inner = read
    commands: list[tuple[list[tuple], str]] = []  # each simple command's words, and the operator after it
    words: list[tuple] = []
    target = False  # the next word names a redirection's file
    for token in [*tokens, ("op", "\n")]:
        if token[0] == "word":
            if not target:
                words.append(token)
            target = False
        elif token[1] in REDIRECTS:
            target = True
        else:
            commands.append((words, token[1]))
            words, target = [], False
    found = None
    for number, (words, after) in enumerate(commands):
        kind = gh_pr_create(words)
        if kind == "opens" and after not in ("|", "|&", "&") and all(
                (not earlier or earlier[0][1] == "cd" and earlier[0][2] and not earlier[0][4]) and (
                    op in ("&&", ";", "\n") if earlier else op == "\n") for earlier, op in commands[:number]):
            return "opens"
        found = found or kind
    if found or any(runs_gh_pr_create(text) for text in inner + expanded):
        return "maybe"
    return None


def gh_pr_create(words: list[tuple]) -> str | None:
    """Whether one simple command runs `gh pr create`: "opens" when it does, "maybe" when it may: after a
    reserved word such as `then`, or with an expansion where a word would decide; None when it does not."""
    plain, at = True, 0
    while at < len(words):
        _, text, exact, quoted, assignment = words[at]
        if assignment:
            at += 1
        elif text in COMPOUND and not quoted:
            plain = False
            at += 1
        elif text in PREFIXES:
            at += 1
            while at < len(words) and words[at][1].startswith("-") or text == "env" and at < len(words) and \
                    "=" in words[at][1]:
                option = words[at][1]
                at += 1
                if option == "--":
                    break
                if text == "command" and re.fullmatch(r"-[pvV]*[vV][pvV]*", option):
                    return None  # command -v and -V only name the command
                if option in PREFIXES[text]:
                    at += 1
        else:
            break
    rest = words[at:at + 3]
    if len(rest) < 3:
        return None
    wanted = [rest[0][1].rsplit("/", 1)[-1] == "gh", rest[1][1] == "pr", rest[2][1] == "create"]
    if all(wanted) and all(word[2] for word in rest):
        return "opens" if plain else "maybe"
    if all(found or not word[2] for found, word in zip(wanted, rest)):
        return "maybe"
    return None


def own_lines(log: Path, helpers: list[Path]) -> tuple[list[dict], list[dict]]:
    """The session's own lines, its log's and then its helpers', less those copied from an earlier session.

    A helper's lines carry its session's id, so one rule holds for both."""
    def own(path: Path) -> list[dict]:
        return [line for line in scan.read_lines(path) if line.get("sessionId") in (None, log.stem)]
    return own(log), [line for path in helpers for line in own(path)]


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
    """The model the session's own responses name most: the main log's copies, and a helper's copy of a
    response the main log holds, by the same API message id. A helper's own responses do not count."""
    def message(line: dict) -> dict:
        found = line.get("message") if line.get("type") == "assistant" else None
        return found if isinstance(found, dict) else {}
    ids = {message(line).get("id") for line in main} - {None, ""}
    counts: dict[str, int] = {}
    for line in main + [line for line in helpers if message(line).get("id") in ids]:
        name = message(line).get("model")
        if isinstance(name, str) and MODEL_NAME.fullmatch(name):  # "<synthetic>" is no model
            counts[name] = counts.get(name, 0) + 1
    return max(counts, key=counts.get) if counts else None


def has_criteria(body: str | None) -> bool:
    """True when the body holds an item of a list under a "## " heading among the CRITERIA_HEADINGS.

    The body is read as CommonMark's blocks: code, fenced or indented, and HTML blocks hide what they
    hold; one of those ATX headings opens the section, and any heading of level one or two, ATX or
    setext, ends it. A list inside a blockquote is not read."""
    headings = {heading.lower() for heading in CRITERIA_HEADINGS}
    under = paragraph = False  # paragraph: the line before continues a paragraph
    fence, html = "", None  # the open code fence; the pattern that ends the open HTML block
    for text in (body or "").expandtabs(4).splitlines():
        if fence:  # a fence ends at a line of at least as many of its own character
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", text):
                fence = ""
            continue
        if html:
            if html.search(text):
                html = None
            continue
        line = text.lstrip(" ")
        if not line:
            paragraph = False
            continue
        if len(text) - len(line) >= 4:  # indented code, or a line that continues a paragraph
            continue
        if opening := re.match(r"`{3,}(?!.*`)|~{3,}", line):
            fence, paragraph = opening.group(), False
            continue
        if paragraph and re.fullmatch(r"(?:=+|-+)[ \t]*", line):  # the paragraph above is a setext heading
            under = paragraph = False
            continue
        start = next(((begin, end) for begin, end in HTML_BLOCKS if begin.match(line)), None)
        if start is None and not paragraph and TAG_LINE.fullmatch(line):
            start = (None, BLANK)
        if start:
            begin, end = start
            html = None if begin and end is not BLANK and end.search(line, begin.match(line).end()) else end
            paragraph = False
            continue
        if heading := re.fullmatch(r"(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*", line):
            if len(heading.group(1)) <= 2:  # a deeper heading stays in the section
                under = heading.group(1) == "##" and (heading.group(2) or "").strip().lower() in headings
            paragraph = False
            continue
        if re.fullmatch(r"([-*_])(?:[ \t]*\1){2,}[ \t]*", line):  # - - - is a break, not an item
            paragraph = False
            continue
        if (item := re.match(r"(?:[-*+]|(\d{1,9})[.)])[ \t]+\S", line)) and (
                not paragraph or item.group(1) in (None, "1")):  # only 1. starts a list inside a paragraph
            if under:
                return True
            paragraph = False
            continue
        paragraph = True
    return False


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
        if not has_criteria(issue.get("body")):
            return None
        return {"label": label, "ticket": number, "bucket": bucket, "size": size, "title": issue["title"],
                "body": issue["body"], "pr": pr, "session": opener["log"].stem, "model": opener["model"],
                "repo": repo, "merge": view["mergeCommit"]["oid"], "created": view["createdAt"],
                "branch": view["headRefName"], "fork": view["isCrossRepository"], "source": opener["log"],
                "transcripts": opener["transcripts"]}

    def sessions(self) -> tuple[list[dict], int]:
        """Each session with a run that runs or may run `gh pr create` and prints a PR's URL, and how many
        session logs could not be read. A session whose eligibility cannot be read is kept, not eligible,
        and counted: its runs still count against other sessions."""
        sessions, unreadable = [], 0
        for log in sorted((scan.config_dir() / "projects").glob("*/*.jsonl")):
            try:
                helpers = scan.helper_logs(log)
                # The transcripts as the draw reads them; a kept session's archive holds just these, whole.
                sizes = {path: path.stat().st_size for path in [log, *helpers]}
                # A cheap filter: a PR's URL holds github.com, or a JSON escape stands for some of its letters.
                if not any("github.com" in text or "\\u" in text
                           for text in (path.read_text(errors="replace") for path in sizes)):
                    continue
                main, own_helpers = own_lines(log, helpers)
                prs = opened_prs(main + own_helpers)
            except (Exception, SystemExit):  # whatever the cause, it is not a session the draw can read
                unreadable += 1
                continue
            if not prs:
                continue
            session = {"log": log, "prs": prs, "eligible": False, "counted": False,
                       "transcripts": {path.relative_to(log.parent): size for path, size in sizes.items()}}
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
        tickets: dict[tuple[str, int], dict | None] = {}
        for (repo, pr), found in sorted(touched.items()):
            if repo not in repos or len(found) != 1 or not found[0]["eligible"] \
                    or found[0]["opened"] != {(repo, pr): "opened"}:
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

        def stop() -> None:
            """Stop every process left in the try's group, once."""
            if started and started[0].returncode is None:
                try:  # the keeper is not reaped yet, so the group's id is still its own
                    os.killpg(started[0].pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                for process in started:
                    process.wait()
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
        finally:  # on success, failure, timeout or interrupt alike
            stop()
            self.git("-C", str(clone), "worktree", "remove", "--force", str(tree))
            self.git("-C", str(clone), "worktree", "prune")
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
        """Copy the session's log and its folder, and scan the copy. Each transcript, the log's and each
        helper's, is copied as the draw read it when the session qualified, whole; a helper transcript
        that appeared later is left out, and a copy from an earlier attempt is replaced."""
        source = candidate["source"]
        copy = self.state / "logs" / source.name
        try:
            copy.parent.mkdir(exist_ok=True)
            copy.unlink(missing_ok=True)
            if copy.with_suffix("").exists():
                shutil.rmtree(copy.with_suffix(""))
            if source.with_suffix("").is_dir():
                try:  # the folder's other files where they can be read; the transcripts follow
                    shutil.copytree(source.with_suffix(""), copy.with_suffix(""),
                                    ignore=shutil.ignore_patterns("agent-*.jsonl"))
                except shutil.Error:  # a file it cannot read stays behind
                    pass
            for relative, size in candidate["transcripts"].items():
                target = copy.parent / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source.parent / relative, target)
                if target.stat().st_size < size:
                    raise OSError(f"{target.name} did not copy whole")
                os.truncate(target, size)  # what a running session wrote after the draw read it
            scan.write_row(scan.scan(source.stem, copy))
        except (Exception, SystemExit) as error:  # its message can name the project's folder
            raise DrawError(f"could not save the session log of project {candidate['label']} ticket "
                            f"{candidate['ticket']} ({type(error).__name__}).")
        return str(copy.relative_to(self.state))

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
            fields = ("label", "ticket", "bucket", "size", "title", "body", "base_commit", "ready_commit", "model",
                      "pr", "session", "log", "check_output")
            number = 1 + max(self.sets(), default=0)
            path = self.state / f"replay-set-{number}.json"
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
    try:
        return Draw(seed).run()
    except DrawError as error:
        print(f"draw: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
