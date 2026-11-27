"""The mask every PR description passes through (#231 rules 45 to 47).

`mask(text)` replaces each `@` mention with `[mention]` and each private path with
`[private path]`, and returns the masked text with the kinds it masked. A mention after a diff's
`+`, a path in a `file://` link, and a path stuck to a short option such as `-I` are masked too. A
private path is one under a home or per-user folder: `/Users/<name>`, `/home/<name>`, `/root`, `~`, `C:\\Users\\<name>`,
and macOS's per-user temp folders under `/var/folders` and `/private/var/folders`. Code spans and
fenced blocks get no exemption. An email address is not a mention, and issue-closing words such as
`Closes #415` pass unchanged.

A value assigned to a secret name counts from 8 characters; a quoted value is measured whole,
spaces included. A value that starts with `$`, `{`, `<` or `%` is a template reference, not a secret.

`find_secret(text)` returns the kind and line number of the first text that looks like a secret,
or None. The caller stops with a question and never prints the text.

The cases both are held to are the run's mask measure; a new case is one pattern here and its test
in `tests/test_deliver_render.py`. Masking a harmless string is acceptable; letting a listed kind
through is not.
"""
from __future__ import annotations

import re

MENTION = re.compile(r"(?<![\w.@-])@[A-Za-z0-9_][\w-]*(?:/[\w.-]+)?")
_REST = r"[^\s`'\"()<>\[\]|]*"
PRIVATE_PATH = re.compile(
    r"(?:(?<![\w.~])|(?<=-[A-Za-z]))(?:/Users|/home|/root|/private/var/folders|/var/folders)(?![\w.-])" + _REST
    + r"|(?<![\w~/-])~[\w.-]*/" + _REST
    + r"|(?i:\b[a-z]:[\\/]+users[\\/])" + _REST
)
KINDS = (("@ mentions", MENTION, "[mention]"), ("private paths", PRIVATE_PATH, "[private path]"))

SECRETS = (
    ("an AWS key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_\w{20,}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("a Slack token", re.compile(r"\bxox[baps]-[A-Za-z0-9-]+")),
    ("an API key", re.compile(r"(?<![A-Za-z0-9])sk-[\w-]{20,}")),
    ("a password or token assignment", re.compile(
        r"(?i)(?:password|passwd|secret|token|api_?key)[\w-]*[\"']?\s*[:=]\s*"
        r"(?:\"[^\"\s${<%][^\"]{7,}|'[^'\s${<%][^']{7,}|[^\s\"'${<%][^\s\"']{7,})")),
)


def mask(text: str) -> tuple[str, list[str]]:
    """The text with every mention and private path masked, and the kinds that were masked."""
    kinds = []
    for kind, pattern, replacement in KINDS:
        text, count = pattern.subn(replacement, text)
        if count:
            kinds.append(kind)
    return text, kinds


def find_secret(text: str) -> tuple[str, int] | None:
    """The kind and 1-based line of the first secret-shaped text, or None."""
    for number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in SECRETS:
            if pattern.search(line):
                return kind, number
    return None
