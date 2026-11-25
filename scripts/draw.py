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
HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*(['\"]?)([\w.-]+)\2")
OPERATORS = sorted([";;&", ";;", ";&", "&&", "||", "|&", "&>>", "&>", ">>", "<<-", "<<<", "<<", "<&", ">&", "<>",
                    ">|", ";", "&", "|", "(", ")", "<", ">", "\n"], key=len, reverse=True)
REDIRECTS = {"<", ">", ">>", "<<", "<<-", "<<<", "<&", ">&", "&>", "&>>", "<>", ">|"}
# Bash's reserved words. The reader models if, while, until, for, { } and the ! and time that start a pipeline;
# any other one in a command's place makes the whole call one it cannot read.
RESERVED = {"if", "then", "else", "elif", "fi", "while", "until", "for", "do", "done", "{", "}", "!", "time",
            "case", "esac", "select", "function", "coproc", "[[", "]]"}
# Commands that can end the shell, skip what follows, run text as commands, or change what a later name runs.
STOPPERS = {"exit", "exec", "return", "logout", "set", "trap", "kill", "source", ".", "eval", "break", "continue",
            "builtin", "alias", "shopt", "enable", "hash", "suspend"}
# Each prefix that runs the command after it, with the options the reader knows: True for one that takes a
# value. Any other option leaves the command one the reader cannot name.
PREFIXES: dict[str, dict[str, bool]] = {"command": {"--": False}, "exec": {"-a": True, "--": False},
                                        "env": {"-u": True, "--": False}, "nohup": {"--": False}}
FAILS = "\x01"  # stands in a word for an expansion that can end the shell or abandon the rest of its line
# Redirections that cannot fail: duplicating standard output or error, here-documents and strings, /dev/null.
SAFE_REDIRECTS = {(">&", "1"), (">&", "2"), (">", "/dev/null"), (">>", "/dev/null"), ("&>", "/dev/null"),
                  ("&>>", "/dev/null")}
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
- A call runs `gh pr create` for certain when the draw proves from its words,
  and from its exit of 0, that bash started that command. The draw reads the
  call as bash's lists, pipelines, simple commands, functions, if, while,
  until and for loops, groups and subshells; any other grammar, such as case
  or [[, makes the call one it cannot read. It proves a start when gh pr
  create is a simple command outside any compound command; its three words
  are exact, with no expansion, glob or escape in $'...'; the prefixes before
  it are assignments, !, time, command, exec, env and nohup with options the
  draw knows; its redirections cannot fail; no command before it can end the
  shell or skip what follows, such as exit, exec, set, trap, eval or a name
  given by an expansion; and its pipeline comes first in its list, the
  commands up to the next ;, & or new line, or its list is the last, not run
  with &, and && joins every pipeline from just before it to the end. A
  command substitution in a command proved to start counts the same way. The
  draw takes for granted that the call ran in bash, and that gh names the
  GitHub CLI: no alias, function or PATH set before the call changes it.
  A call that may run it anywhere else, as after || or in a branch, or that
  cannot be read, may have opened the PR its result names, if GitHub's
  time falls in its span. So may a call whose line or whose result's line
  has a time that is missing, has no zone or is at an end of the calendar.
  A PR in a repo outside repos.json counts on the command alone: opened or
  may have opened. A command run by another program, as with bash -c, does
  not count. Lines in the session's log or a helper's that carry another
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
                        transcript, the log's and each helper's, holds the
                        bytes the draw read when the session qualified,
                        checked by digest; a helper transcript that appeared
                        later is left out. A copy from an earlier draw is
                        replaced only once the new one is whole, checked and
                        scanned; until then it stays as it was.
  draw-work/            Clones and checkouts, removed when the draw ends.

Output names projects by label only. A session log and its helpers' logs are
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

Exit 0: a set was written. Exit 1: an error; no set was written. Exit 2: bad
usage. Exit {EXIT_SHORT}: a bucket holds fewer than {PER_BUCKET} tickets, or cannot reach {PER_BUCKET} once
tickets are set aside; no set was written, and the count per bucket is printed."""


class DrawError(Exception):
    """Ends the draw with exit 1 and no set written."""


class Terminated(BaseException):
    """SIGTERM, raised where the draw is so that each cleanup runs; no handler for errors catches it."""


def terminated(number: int, frame: object) -> None:
    raise Terminated


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


def shell_tokens(command: str) -> tuple[list[tuple], list[tuple[str, int, bool]]] | None:
    """A command's tokens, and each command it substitutes; None when it does not parse.

    A token is ("op", operator) or ("word", text, exact, quoted, assignment). Quotes and backslashes are
    removed. A word is exact only when its text is surely what bash passes on: one that holds an expansion
    (and holds "\\0" where it stands), an escape in $'...', a $"..." string, a glob, a brace expansion or a
    leading ~ is not. A word also holds FAILS where an expansion can end the shell or abandon its line: any
    ${...} but ${name}, and arithmetic. A substitution is (its text, the index of the token that holds it, whether it runs
    whenever its word is expanded); one inside ${...} may not run."""
    tokens: list[tuple] = []
    inner: list[tuple[str, int, bool]] = []
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
        inner.append((command[start:end], len(tokens), True))
        add("\0", quoted, exact=False)
        return end + 1

    def dollar(at: int, quoted: bool) -> int:
        """Read the expansion at `at`, a "$"; return where reading goes on."""
        following = command[at + 1:at + 2]
        if following == "(":
            if command[at + 2:at + 3] == "(":  # arithmetic, whose error abandons the line
                add(FAILS, quoted, exact=False)
            return substitution(at + 2, closing(command, at + 2), quoted)
        end = at + 2
        if following == "{":
            end = closing(command, at + 2, "{", "}") + 1
            if not end:
                raise ValueError("unclosed expansion")
            if found := re.search(r"\$\(|`", command[at:end]):  # as in ${name:-$(command)}, which may run
                inner.append((command[at + found.end():end - 1], len(tokens), False))
            if not re.fullmatch(r"\$\{([A-Za-z_]\w*|\d+|[@*#?$!-])\}", command[at:end]):
                add(FAILS, quoted, exact=False)  # ${x:?} ends the shell; a bad substitution abandons the line
        elif following.isalpha() or following == "_":
            while end < len(command) and (command[end].isalnum() or command[end] == "_"):
                end += 1
        elif following == "[":  # an old arithmetic expansion
            end = closing(command, at + 2, "[", "]") + 1
            if not end:
                raise ValueError("unclosed expansion")
            add(FAILS, quoted, exact=False)
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
            elif char == "$" and command[at + 1:at + 2] == "'":  # $'...': the reader finds its end, not its bytes
                at += 2
                while command[at:at + 1] != "'":
                    if at >= len(command):
                        raise ValueError("unclosed quote")
                    escaped = command[at] == "\\"
                    at += escaped
                    add(command[at:at + 1], quoted=True, exact=not escaped)
                    at += 1
                at += 1
            elif char == '"' or char == "$" and command[at + 1:at + 2] == '"':
                add("", quoted=True, exact=char == '"')  # $"..." may be translated
                at += 1 if char == '"' else 2
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
            else:  # a glob, a brace expansion or a leading ~ may change the word
                add(char, exact=char not in "*?[{~" or char == "~" and word is not None and word[0] != ""
                    or char == "[" and "]" not in command[at:at + 200].split()[0]
                    or char == "{" and not re.match(r"\{[^\s{}]*(,|\.\.)[^\s{}]*\}", command[at:]))
                at += 1
    except ValueError:
        return None
    if word is not None:
        tokens.append(("word", *word))
    return tokens, inner


def strip_here_documents(command: str) -> tuple[str, list[str], int]:
    """The command less its here-documents' bodies, which are input, not commands; the bodies the shell
    expands, since a command substitution in one runs; and how many here-documents it found. It finds them
    in the text, quotes aside, so the caller checks that count against the operators the shell reads."""
    kept, expanded, ends, found = [], [], [], 0
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
        found += len(ends)
    expanded += ["\n".join(body) for strip, quote, end, body in ends if not quote]
    return "\n".join(kept), expanded, found


def runs_gh_pr_create(command: str, exited_zero: bool = True) -> str | None:
    """Whether a Bash command runs `gh pr create`: "opens" when the reader proves bash started it, "maybe"
    when it may have, or when the call holds anything the reader does not model; None when it does not.
    `exited_zero` says the call is known to have exited 0.

    The reader parses the call as bash's lists, and-or lists, pipelines, simple commands, functions, if,
    while, until and for loops, groups and subshells, and fails closed on any other grammar (`case`, `[[`,
    `((`, `select`, `coproc`, `function`) and on a here-document it cannot match to its operator. It proves
    a start when `gh pr create` is a simple command at the top level, outside any compound command; its
    three words are exact; its prefixes and their options are ones it knows; its redirections cannot fail;
    no simple command before it, at any depth, is one that `stops`; no function anywhere in the call is
    named gh, a prefix or a STOPPER; and either its
    pipeline is the first of its and-or list, or that list ends the call, is not run in the background,
    and && joins every pipeline from just before it to the end, so an exit of 0 means each ran. A command
    substitution in a word of a command proved to start counts when its own command is proved to start
    `gh pr create`, its exit unknown. It takes for granted that the call runs in bash, that gh, env and
    nohup name the programs their names give, and that nothing outside the call, such as an alias, a
    function or PATH set before it, changes that."""
    command, expanded, heres = strip_here_documents(command)
    read = shell_tokens(command)
    if read is None:
        return "maybe"
    tokens, inner = read
    if heres != here_operators(tokens, inner):  # a << the text shows that the shell does not read, or the reverse
        return "maybe"
    try:
        top = Grammar(tokens).program()
    except ValueError:  # grammar the reader does not model
        return "maybe"
    surely, found = True, None  # surely: no command so far can stop the ones after it
    for number, (pipelines, ending) in enumerate(top):
        last = number == len(top) - 1 and ending != "&"
        for place, (pipeline, _) in enumerate(pipelines):
            joined = [after for _, after in pipelines[max(place - 1, 0):-1]] if place else []
            started = surely and (place == 0 or exited_zero and last and all(op == "&&" for op in joined))
            for item in pipeline:
                nested = item["compound"]
                for simple in item["simple"]:
                    kind = gh_pr_create(simple["words"], simple["redirects"])
                    if kind == "opens" and started and not nested:
                        return "opens"
                    found = found or kind
                    for text, at, runs in inner:
                        if at in simple["span"]:
                            within = runs_gh_pr_create(text, exited_zero=False)
                            if within == "opens" and runs and started and not nested:
                                return "opens"
                            found = found or within
            if any(stops(simple["words"], simple["redirects"]) for item in pipeline for simple in item["simple"]):
                surely = False
    if found or any(runs_gh_pr_create(text) for text in expanded):
        return "maybe"
    return None


def here_operators(tokens: list[tuple], inner: list[tuple[str, int, bool]]) -> int:
    """How many here-document operators the shell reads in the tokens and in the commands they substitute."""
    count = sum(token == ("op", "<<") or token == ("op", "<<-") for token in tokens)
    for text, _, _ in inner:
        read = shell_tokens(text)
        count += here_operators(*read) if read else 0
    return count


class Grammar:
    """Bash's grammar over a call's tokens, as far as the reader models it; ValueError beyond that.

    `program` gives the call's lists, each as (its and-or list, the operator that ends it). An and-or list
    is [(pipeline, the operator after it)], and a pipeline is a list of commands. A command is
    {"compound": whether it is a compound command or a function, "simple": every simple command in it}, and
    a simple command is {"words", "redirects": [(operator, target)], "span": its tokens' indices}."""

    def __init__(self, tokens: list[tuple]) -> None:
        self.tokens = tokens
        self.at = 0

    def peek(self, ahead: int = 0) -> tuple | None:
        return self.tokens[self.at + ahead] if self.at + ahead < len(self.tokens) else None

    def reserved(self, *names: str) -> bool:
        """Whether the next token is a reserved word, one of `names` when they are given."""
        token = self.peek()
        return (token is not None and token[0] == "word" and token[2] and not token[3] and token[1] in RESERVED
                and (not names or token[1] in names))

    def op(self, *names: str) -> bool:
        token = self.peek()
        return token is not None and token[0] == "op" and token[1] in names

    def expect(self, name: str) -> None:
        if not (self.reserved(name) or self.op(name)):
            raise ValueError(f"expected {name}")
        self.at += 1

    def newlines(self) -> None:
        while self.op("\n"):
            self.at += 1

    def program(self) -> list:
        found = self.lists(())
        if self.at < len(self.tokens):
            raise ValueError("unexpected token")
        return found

    def lists(self, ends: tuple[str, ...]) -> list:
        """And-or lists up to one of the reserved words `ends`, or a closing parenthesis."""
        found = []
        self.newlines()
        while self.peek() is not None and not (ends and self.reserved(*ends)) and not self.op(")"):
            pipelines = [(self.pipeline(), None)]
            while self.op("&&", "||"):
                pipelines[-1] = (pipelines[-1][0], self.peek()[1])
                self.at += 1
                self.newlines()
                pipelines.append((self.pipeline(), None))
            ending = self.peek()[1] if self.op(";", "&", "\n") else None
            found.append((pipelines, ending))
            if ending is None:
                break
            self.at += 1
            self.newlines()
        return found

    def pipeline(self) -> list[dict]:
        while self.reserved("!", "time"):
            self.at += 1
            if self.tokens[self.at - 1][1] == "time" and self.peek() and self.peek()[1:3] == ("-p", True):
                self.at += 1
        commands = [self.command()]
        while self.op("|", "|&"):
            self.at += 1
            self.newlines()
            commands.append(self.command())
        return commands

    def command(self) -> dict:
        token = self.peek()
        if token is None:
            raise ValueError("a command is missing")
        if self.op("("):
            self.at += 1
            if self.op("("):
                raise ValueError("arithmetic")
            inside = self.lists(())
            self.expect(")")
            return self.compound(inside)
        if self.reserved("if"):
            self.at += 1
            inside = self.lists(("then",))
            self.expect("then")
            inside += self.lists(("elif", "else", "fi"))
            while self.reserved("elif"):
                self.at += 1
                inside += self.lists(("then",))
                self.expect("then")
                inside += self.lists(("elif", "else", "fi"))
            if self.reserved("else"):
                self.at += 1
                inside += self.lists(("fi",))
            self.expect("fi")
            return self.compound(inside)
        if self.reserved("while", "until"):
            self.at += 1
            inside = self.lists(("do",))
            self.expect("do")
            inside += self.lists(("done",))
            self.expect("done")
            return self.compound(inside)
        if self.reserved("for"):
            self.at += 1
            first = self.at
            if self.peek() is None or self.peek()[0] != "word" or not re.fullmatch(r"[A-Za-z_]\w*", self.peek()[1]):
                raise ValueError("a loop's name")
            self.at += 1
            self.newlines()
            words = []
            if self.peek() and self.peek()[0] == "word" and self.peek()[1] == "in" and not self.peek()[3]:
                self.at += 1
                while self.peek() and self.peek()[0] == "word":
                    words.append(self.peek())
                    self.at += 1
            header = {"words": words, "redirects": [], "span": range(first, self.at)}
            if self.op(";", "\n"):
                self.at += 1
            self.newlines()
            self.expect("do")
            inside = self.lists(("done",))
            self.expect("done")
            return self.compound(inside, [header])
        if self.reserved("{"):
            self.at += 1
            inside = self.lists(("}",))
            self.expect("}")
            return self.compound(inside)
        if self.reserved():
            raise ValueError(f"the reserved word {token[1]}")
        if token[0] == "word" and self.peek(1) == ("op", "(") and self.peek(2) == ("op", ")"):
            if not token[2] or token[1] == "gh" or token[1] in PREFIXES or token[1] in STOPPERS:
                raise ValueError("a function that changes what a name runs")
            self.at += 3
            self.newlines()
            body = self.command()
            if not body["compound"]:
                raise ValueError("a function's body")
            return {"compound": True, "simple": body["simple"]}
        return {"compound": False, "simple": [self.simple()]}

    def compound(self, inside: list, extra: list[dict] | None = None) -> dict:
        """A compound command, with its redirections, and every simple command in it."""
        simple = list(extra or [])
        for pipelines, _ in inside:
            for pipeline, _ in pipelines:
                for command in pipeline:
                    simple += command["simple"]
        self.redirects([])
        return {"compound": True, "simple": simple}

    def redirects(self, found: list) -> None:
        while self.op(*REDIRECTS):
            operator = self.peek()[1]
            self.at += 1
            if self.peek() is None or self.peek()[0] != "word":
                raise ValueError("a redirection's target")
            found.append((operator, self.peek()))
            self.at += 1

    def simple(self) -> dict:
        first, words, redirects = self.at, [], []
        while True:
            if self.peek() is not None and self.peek()[0] == "word":
                words.append(self.peek())
                self.at += 1
            elif self.op(*REDIRECTS):
                self.redirects(redirects)
            else:
                break
        if not words and not redirects:
            raise ValueError("a command is missing")
        return {"words": words, "redirects": redirects, "span": range(first, self.at)}


def command_name(words: list[tuple]) -> tuple[int, bool, bool]:
    """Where a simple command's name stands, past assignments and the prefixes that run it; whether every
    option given a prefix is one the reader knows; and whether a prefix only looks the name up."""
    at, known = 0, True
    while at < len(words):
        _, text, exact, quoted, assignment = words[at]
        if assignment:
            at += 1
        elif exact and text in PREFIXES:
            at += 1
            while at < len(words) and (words[at][1].startswith("-") or not words[at][2]
                                       or text == "env" and words[at][4]):
                option = words[at]
                at += 1
                if text == "env" and option[4]:
                    continue
                if text == "command" and re.fullmatch(r"-[pvV]*[vV][pvV]*", option[1]):
                    return at, known, True  # command -v and -V only name the command
                if not option[2] or option[1] not in PREFIXES[text]:
                    known = False
                elif option[1] == "--":
                    break
                else:
                    at += PREFIXES[text][option[1]]
        else:
            break
    return at, known, False


def stops(words: list[tuple], redirects: list[tuple] = []) -> bool:
    """Whether a simple command can end the shell or skip what follows it: one of the STOPPERS, any exec,
    a command named by a word that is not exact, one the reader cannot name, or one with an expansion
    that can fail (FAILS)."""
    if any(FAILS in word[1] for word in words + [target for _, target in redirects]):
        return True
    at, known, lookup = command_name(words)
    if any(word[2] and not word[4] and word[1] == "exec" for word in words[:at]):
        return True  # exec replaces the shell, and a failed redirection given to it can end the shell
    if lookup or at >= len(words):
        return not known
    return not known or not words[at][2] or words[at][1] in STOPPERS


def gh_pr_create(words: list[tuple], redirects: list[tuple] = []) -> str | None:
    """Whether one simple command runs `gh pr create`: "opens" when it surely does, "maybe" when it may, as
    when a word that is not exact could spell it or the reader does not know a prefix's option or that a
    redirection cannot fail; None when it does not."""
    at, known, lookup = command_name(words)
    if lookup:
        return None
    sure = known and not any(FAILS in word[1] for word in words + [target for _, target in redirects])
    for place, wanted in enumerate(("gh", "pr", "create")):
        if at + place >= len(words):
            return None
        _, text, exact, quoted, _ = words[at + place]
        if not exact:
            if not quoted:
                return "maybe"  # it may expand to any number of words
            sure = False
        elif (text.rsplit("/", 1)[-1] if place == 0 else text) != wanted:
            return None
    if not all((operator, target[1]) in SAFE_REDIRECTS and target[2] or operator in ("<<", "<<-", "<<<")
               for operator, target in redirects):
        sure = False
    return "opens" if sure else "maybe"


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


def has_criteria(body: str | None) -> bool:
    """True when the body holds an item of a list under a "## " heading among the CRITERIA_HEADINGS."""
    return bool(requirements(body))


def requirements(body: str | None) -> list[str]:
    """The text of each item of a list under a "## " heading among the CRITERIA_HEADINGS, in the order written.

    The body is read as CommonMark's blocks: code, fenced or indented, and HTML blocks hide what they
    hold; one of those ATX headings opens the section, and any heading of level one or two, ATX or
    setext, ends it. A list inside a blockquote is not read. A line belongs to the innermost open item
    whose text it is indented to; a line of text that follows a paragraph and starts no block continues
    that paragraph however far it is indented. An item's text is its paragraphs joined by spaces, without
    its marker or a task box. A list inside an item gives items of its own, after their parent; a quote,
    code or an HTML block inside an item is not its text and does not end it. In a paragraph only - * +
    and 1. start a list, so a wrapped line that begins "3." stays in its item."""
    headings = {heading.lower() for heading in CRITERIA_HEADINGS}
    found: list[str] = []
    under = False
    items: list[list] = []  # the open items, outermost first: [the column of the item's text, its index in found or None]
    owner: list | str | None = None  # the open paragraph: an item's, "quote", "text", or None
    fence, fence_column, html = "", 0, None  # the open code fence and its container's column; the end of an HTML block
    for text in (body or "").expandtabs(4).splitlines():
        line = text.lstrip(" ")
        indent = len(text) - len(line)
        if fence:
            if not line or indent >= fence_column:  # a line short of its item's column ends the item and the fence
                if indent - fence_column < 4 and re.fullmatch(rf"{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", line):
                    fence = ""
                continue
            fence = ""
        if html:
            if html.search(text):
                html = None
            continue
        if not line:
            owner = None
            continue
        depth = sum(column <= indent for column, _ in items)
        base = items[depth - 1][0] if depth else 0
        block = marker = opening = start = None
        if indent - base >= 4:
            block = None if owner else "code"  # indented code cannot interrupt a paragraph
        elif opening := re.match(r"`{3,}(?!.*`)|~{3,}", line):
            block = "fence"
        elif owner and depth == len(items) and re.fullmatch(r"(?:=+|-+)[ \t]*", line):
            block = "setext"  # the paragraph above is a heading
        elif start := (next(((begin, end) for begin, end in HTML_BLOCKS if begin.match(line)), None)
                       or ((None, BLANK) if not owner and TAG_LINE.fullmatch(line) else None)):
            block = "html"
        elif heading := re.fullmatch(r"(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*", line):
            block = "heading"
        elif re.fullmatch(r"([-*_])(?:[ \t]*\1){2,}[ \t]*", line):  # - - - is a break, not an item
            block = "break"
        elif (marker := re.match(r"(?:[-*+]|(\d{1,9})[.)])[ \t]+(?=\S)", line)) and (
                not owner or depth < len(items) or marker.group(1) in (None, "1")):
            block = "item"  # in a paragraph of the same item, only - * + and 1. start a list
        elif line.startswith(">"):
            block = "quote"
        if block is None:  # text: it continues the open paragraph, or starts one in the item it reaches
            if not owner:
                del items[depth:]
                owner = items[-1] if items else "text"
            if isinstance(owner, list) and owner[1] is not None:
                found[owner[1]] += " " + line.strip()
            continue
        del items[depth:]
        owner = None
        if block == "fence":
            fence, fence_column = opening.group(), base
        elif block == "setext" and not depth:
            under = False
        elif block == "html":
            begin, end = start
            html = None if begin and end is not BLANK and end.search(line, begin.match(line).end()) else end
        elif block == "heading" and not depth and len(heading.group(1)) <= 2:  # a deeper heading stays in the section
            under = heading.group(1) == "##" and (heading.group(2) or "").strip().lower() in headings
        elif block == "item":
            items.append([indent + marker.end(), len(found) if under else None])
            if under:
                found.append(re.sub(r"\A\[[ xX]\][ \t]+", "", line[marker.end():]).strip())
            owner = items[-1]
        elif block == "quote":
            owner = "quote"  # its lines, and the lines that lazily continue it, are not read
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
        if not has_criteria(issue.get("body")):
            return None
        return {"label": label, "ticket": number, "bucket": bucket, "size": size, "title": issue["title"],
                "body": issue["body"], "pr": pr, "session": opener["log"].stem, "model": opener["model"],
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
        the new one is whole and scanned, and is removed once the new one is in place."""
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
        except (Exception, SystemExit) as error:  # its message can name the project's folder
            for name in names if old.exists() else ():  # put back the earlier copy where it was moved
                if (old / name).exists():
                    if (logs / name).is_dir():
                        shutil.rmtree(logs / name)
                    elif (logs / name).exists():
                        (logs / name).unlink()
                    os.replace(old / name, logs / name)
            shutil.rmtree(old, ignore_errors=True)
            shutil.rmtree(staged, ignore_errors=True)
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
    signal.signal(signal.SIGTERM, terminated)
    try:
        return Draw(seed).run()
    except Terminated:
        print("draw: stopped by SIGTERM; no set written.", file=sys.stderr)
        return 128 + signal.SIGTERM
    except DrawError as error:
        print(f"draw: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
