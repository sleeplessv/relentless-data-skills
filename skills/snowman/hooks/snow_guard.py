#!/usr/bin/env python3
"""Claude Code PreToolUse hook: refuse direct `snow` and `snowsql` calls.

Snowflake work goes through scripts/snowman.py. This hook reads the Bash tool
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
import shlex
import sys

BLOCKED = {"snow", "snowsql", "snowflake-cli"}  # the last via pipx run or uvx
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
SEPARATOR_CHARS = set(";&|()\n")
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
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SUBSTITUTION = re.compile(r"\$\(((?:[^()]|\([^()]*\))*)\)|`([^`]*)`")
REASON = (
    "BLOCKED: direct `{cmd}` call. Every Snowflake call goes through the snowman "
    "wrapper (scripts/snowman.py). To run a staged script, give the user its "
    "path and manual command; they run it. Allowed direct calls: `snow "
    "connection list`, `snow connection test`, `snow --version`, `snow --help`."
)


def strip_heredocs(command: str) -> tuple[str, list[str]]:
    """Drop heredoc bodies. Return the rest and the bodies the shell expands."""
    lines = command.split("\n")
    kept, expanded, pending = [], [], []
    for line in lines:
        if pending:
            quoted, delimiter, body = pending[0]
            if line.lstrip("\t") == delimiter:
                if not quoted:
                    expanded.append("\n".join(body))
                pending.pop(0)
            else:
                body.append(line)
            continue
        kept.append(line)
        for match in HEREDOC.finditer(line):
            pending.append((bool(match.group(1)), match.group(2), []))
    return "\n".join(kept), expanded


def tokens(command: str) -> list[str]:
    # Newlines separate commands, so they are punctuation, not whitespace.
    # Comments stay words: a commented-out `snow` is never at command position
    # unless it follows a separator, and a false refusal there is harmless.
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def segments(words: list[str]) -> list[list[str]]:
    out, current = [], []
    for word in words:
        if word and set(word) <= SEPARATOR_CHARS:
            if current:
                out.append(current)
            current = []
        else:
            current.append(word)
    if current:
        out.append(current)
    return out


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


def allowed(args: list[str]) -> bool:
    if args[:1] in (["--version"], ["--help"], ["-h"]):
        return True
    return args[:1] == ["connection"] and args[1:2] in (["list"], ["test"])


def blocked_call(command: str, depth: int = 0) -> str | None:
    """Return the blocked program a shell command would run, or None."""
    if depth > 5:
        return None
    command, expanded = strip_heredocs(command)
    # Substitutions run even inside double quotes and unquoted heredocs.
    for text in [command, *expanded]:
        for paren, tick in SUBSTITUTION.findall(text):
            found = blocked_call(paren or tick, depth + 1)
            if found:
                return found
    try:
        words = tokens(command)
    except ValueError:
        match = re.search(r"(?:^|[\s;&|(`])(?:\S*/)?(snow(?:sql)?)(?=\s|$)", command)
        return match.group(1) if match else None
    for segment in segments(words):
        words = unwrap([w.lstrip("`$") for w in segment])
        if not words:
            continue
        head = os.path.basename(words[0])
        if head in BLOCKED and not (head == "snow" and allowed(words[1:])):
            return head
        if head in SHELLS and "-c" in words[1:]:
            script = words[words.index("-c") + 1:words.index("-c") + 2]
            found = blocked_call(script[0], depth + 1) if script else None
        elif head == "eval":
            found = blocked_call(" ".join(words[1:]), depth + 1)
        else:
            found = None
        if found:
            return found
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = payload["tool_input"]["command"]
    except (ValueError, KeyError, TypeError):
        return 0
    if payload.get("tool_name") != "Bash" or not isinstance(command, str):
        return 0
    found = blocked_call(command)
    if found:
        print(REASON.format(cmd=found), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
