#!/usr/bin/env python3
"""PreToolUse hook: refuse direct `snow` and `snowsql` calls.

Runs on Claude Code, Codex and Cortex Code, which all pass the shell command as
a string in `tool_input.command` and block on exit 2. The registration's
matcher picks the shell tool (`Bash`, or `bash` on Cortex), so the tool name is
not checked here.

Snowflake work goes through scripts/snowman.py. This hook reads the shell tool
call on stdin and exits 2, with the reason on stderr, when the command runs
`snow` or `snowsql` itself. Allowed: `snow connection list`, `snow connection
test`, `snow --version` and `snow --help`/`-h`. The wrapper's own `snow`
subprocess is not a tool call, so the hook never sees it.

It catches an agent that runs the printed staged command or reaches for the
CLI out of habit. It does not stop a deliberate bypass, such as Python with
the Snowflake connector; see references/guardrails.md#direct-snow-calls.

Malformed hook input exits 0: a harness bug should not block every Bash call.
Hooks run under plain `python3` on every Bash call, so this file avoids syntax
newer than Python 3.9 and imports only the standard library.
"""
from __future__ import annotations

import json
import os
import re
import sys

BLOCKED = {"snow", "snowsql", "snowflake-cli"}  # the last via pipx run or uvx
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
SHELL_OPTIONS_WITH_VALUE = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
RESERVED = {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done",
            "while", "until", "for", "case", "esac", "time"}
# Wrappers that run their arguments as a command. Values name the options that
# take a separate argument, which must be skipped with the option.
WRAPPERS = {
    "command": set(), "exec": {"-a"}, "builtin": set(), "nohup": set(),
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"},
    "nice": {"-n", "--adjustment"}, "xargs": {"-I", "-L", "-n", "-P", "-d", "-E", "-s"},
    "uvx": {"--from", "--with", "--python", "-p", "--index", "--index-url"},
    "pipx": {"--spec", "--python", "--pip-args", "--index-url"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SUBSTITUTED = "\0"  # stands in for a $(...) or backtick result inside a word
REASON = (
    "BLOCKED: direct `{cmd}` call. Every Snowflake call goes through the snowman "
    "wrapper (scripts/snowman.py). The user runs staged scripts. Follow "
    "\"Stage requested changes\" in snowman's SKILL.md. Allowed direct calls: `snow "
    "connection list`, `snow connection test`, `snow --version`, `snow --help`."
)


class Parser:
    """Split shell text into simple commands, following its quoting rules.

    Each segment is (words, heredoc bodies fed to it). Commands inside $(...),
    backticks and unquoted heredoc bodies become segments of their own, since
    the shell runs them too. Raises ValueError on an unterminated quote or
    substitution.
    """

    def __init__(self, text: str, start: int = 0, closing: bool = False):
        self.s, self.i, self.closing = text, start, closing
        self.segments: list[tuple[list[str], list[str]]] = []
        self.words: list[str] = []
        self.bodies: list[str] = []
        self.chars: list[str] = []
        self.in_word = self.quoted = False
        self.target = None  # None, "redirect", or ("heredoc", strip_tabs)
        self.pending: list[tuple[str, bool, bool, list[str]]] = []
        self.parens = 0

    def parse(self) -> Parser:
        s = self.s
        while self.i < len(s):
            c, nxt = s[self.i], s[self.i + 1:self.i + 2]
            if c == "\\":
                self.i += 2
                if nxt != "\n":  # backslash-newline joins the lines
                    self.add(nxt, quoted=True)
            elif c == "'":
                end = s.find("'", self.i + 1)
                if end < 0:
                    raise ValueError("unterminated single quote")
                self.add(s[self.i + 1:end], quoted=True)
                self.i = end + 1
            elif c == "$" and nxt == "'":
                self.ansi_quote()
            elif c == '"':
                self.double_quote()
            elif c == "$" and nxt == "(":
                self.substitution()
            elif c == "`":
                self.backtick()
            elif c == "#" and not self.in_word:
                end = s.find("\n", self.i)
                self.i = len(s) if end < 0 else end
            elif c in " \t\r":
                self.end_word()
                self.i += 1
            elif c == "\n":
                self.end_segment()
                self.i += 1
                self.read_heredocs()
            elif c in "<>" or (c == "&" and nxt == ">"):
                self.redirect()
            elif c in ";&|()":
                if c == ")" and self.closing and self.parens == 0:
                    self.end_segment()
                    self.i += 1
                    return self
                self.parens += {"(": 1, ")": -1}.get(c, 0)
                self.end_segment()
                self.i += 1
            else:
                self.add(c)
                self.i += 1
        if self.closing:
            raise ValueError("unterminated $(")
        self.end_segment()
        return self

    def add(self, text: str, quoted: bool = False) -> None:
        self.chars.append(text)
        self.in_word = True
        self.quoted = self.quoted or quoted

    def end_word(self) -> None:
        if not self.in_word:
            return
        word, target = "".join(self.chars), self.target
        if target is None:
            self.words.append(word)
        elif target != "redirect":
            self.pending.append((word, self.quoted, target[1], self.bodies))
        self.chars, self.in_word, self.quoted, self.target = [], False, False, None

    def end_segment(self) -> None:
        self.end_word()
        self.target = None
        if self.words or self.bodies:
            self.segments.append((self.words, self.bodies))
        self.words, self.bodies = [], []

    def redirect(self) -> None:
        s = self.s
        if self.in_word and not self.quoted and "".join(self.chars).isdigit():
            self.chars, self.in_word = [], False  # a file descriptor, as in 2>
        self.end_word()
        if s.startswith("<<<", self.i):  # here-string: one word, no body
            self.i += 3
            self.target = "redirect"
        elif s.startswith("<<", self.i):
            strip = s.startswith("<<-", self.i)
            self.i += 3 if strip else 2
            self.target = ("heredoc", strip)
        else:
            self.i += 1
            while self.i < len(s) and s[self.i] in "<>&|":
                self.i += 1
            self.target = "redirect"

    def read_heredocs(self) -> None:
        s = self.s
        for delimiter, quoted, strip, bodies in self.pending:
            lines = []
            while self.i < len(s):
                end = s.find("\n", self.i)
                end = len(s) if end < 0 else end
                line, self.i = s[self.i:end], end + 1
                if (line.lstrip("\t") if strip else line) == delimiter:
                    break
                lines.append(line)
            body = "\n".join(lines)
            bodies.append(body)
            if not quoted:  # the shell expands $(...) in an unquoted body
                self.segments += Expansions(body).parse().segments
        self.pending = []

    def double_quote(self) -> None:
        s = self.s
        self.add("", quoted=True)
        self.i += 1
        while self.i < len(s):
            c, nxt = s[self.i], s[self.i + 1:self.i + 2]
            if c == '"':
                self.i += 1
                return
            if c == "\\" and nxt in ("$", "`", '"', "\\", "\n"):
                if nxt != "\n":
                    self.chars.append(nxt)
                self.i += 2
            elif c == "$" and nxt == "(":
                self.substitution()
            elif c == "`":
                self.backtick()
            else:
                self.chars.append(c)
                self.i += 1
        raise ValueError("unterminated double quote")

    def ansi_quote(self) -> None:
        s, j = self.s, self.i + 2
        while j < len(s) and s[j] != "'":
            j += 2 if s[j] == "\\" else 1
        if j >= len(s):
            raise ValueError("unterminated $' quote")
        self.add(s[self.i + 2:j], quoted=True)
        self.i = j + 1

    def substitution(self) -> None:
        inner = Parser(self.s, self.i + 2, closing=True).parse()
        self.segments += inner.segments
        self.i = inner.i
        self.add(SUBSTITUTED)

    def backtick(self) -> None:
        s, j, inner = self.s, self.i + 1, []
        while j < len(s) and s[j] != "`":
            if s[j] == "\\" and s[j + 1:j + 2] in ("`", "\\", "$"):
                j += 1
            inner.append(s[j])
            j += 1
        if j >= len(s):
            raise ValueError("unterminated backtick")
        self.segments += Parser("".join(inner)).parse().segments
        self.i = j + 1
        self.add(SUBSTITUTED)


class Expansions(Parser):
    """Find the substitutions in text the shell expands but does not split,
    such as an unquoted heredoc body."""

    def parse(self) -> Expansions:
        s = self.s
        while self.i < len(s):
            c, nxt = s[self.i], s[self.i + 1:self.i + 2]
            if c == "\\":
                self.i += 2
            elif c == "$" and nxt == "(":
                self.substitution()
            elif c == "`":
                self.backtick()
            else:
                self.i += 1
        return self


def skip_options(args: list[str], with_value: set[str]) -> list[str]:
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        i += 2 if args[i] in with_value else 1
    if i < len(args) and args[i] == "--":
        i += 1
    return args[i:]


def unwrap(words: list[str]) -> list[str]:
    """Strip reserved words, assignments and wrappers down to the real command."""
    while words:
        head = os.path.basename(words[0])
        if words[0] in RESERVED or ASSIGNMENT.match(words[0]):
            words = words[1:]
        elif head == "command" and any(
                "v" in w or "V" in w for w in words[1:len(words) - len(skip_options(words[1:], set()))]):
            return []  # `command -v snow` looks the program up; it runs nothing
        elif head == "uv" and words[1:2] == ["run"]:
            words = skip_options(words[2:], WRAPPERS["uvx"] | {"--project", "--directory"})
        elif head == "uv" and words[1:3] == ["tool", "run"]:
            words = skip_options(words[3:], WRAPPERS["uvx"])
        elif head == "pipx" and words[1:2] == ["run"]:
            words = skip_options(words[2:], WRAPPERS["pipx"])
        elif head in WRAPPERS and head != "pipx":
            words = skip_options(words[1:], WRAPPERS[head])
            if head == "timeout" and words:
                words = words[1:]
        else:
            return words
    return words


def shell_script(args: list[str]) -> str | None:
    """The script a shell runs from `-c`, or None when it reads stdin or a file."""
    has_c, i = False, 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            i += 1
            break
        if not arg.startswith(("-", "+")):
            break
        if arg in SHELL_OPTIONS_WITH_VALUE:
            i += 1
        elif not arg.startswith("--") and "c" in arg[1:]:
            has_c = True
        i += 1
    return args[i] if has_c and i < len(args) else None


def allowed(args: list[str]) -> bool:
    if args[:1] in (["--version"], ["--help"], ["-h"]):
        return True
    return args[:1] == ["connection"] and args[1:2] in (["list"], ["test"])


def blocked_call(command: str, depth: int = 0) -> str | None:
    """Return the blocked program a shell command would run, or None."""
    if depth > 5:
        return None
    try:
        segments = Parser(command).parse().segments
    except ValueError:
        # The shell runs the lines before a syntax error, so judge the raw text.
        match = re.search(r"(?:^|[\s;&|(`])(?:\S*/)?(snow(?:sql)?)(?=\s|$)", command)
        return match.group(1) if match else None
    for words, bodies in segments:
        words = unwrap(words)
        if not words:
            continue
        head = os.path.basename(words[0])
        if head in BLOCKED and not (head == "snow" and allowed(words[1:])):
            return head
        if head in SHELLS:
            script = shell_script(words[1:])
            scripts = [script] if script is not None else bodies
        elif head == "eval":
            scripts = [" ".join(words[1:])]
        else:
            scripts = []
        for script in scripts:
            found = blocked_call(script, depth + 1)
            if found:
                return found
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = payload["tool_input"]["command"]
    except (ValueError, KeyError, TypeError):
        return 0
    if not isinstance(command, str):
        return 0
    found = blocked_call(command)
    if found:
        print(REASON.format(cmd=found), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
