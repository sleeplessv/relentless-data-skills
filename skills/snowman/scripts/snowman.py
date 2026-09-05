#!/usr/bin/env python3
"""Snowflake query previews and SQL staging using the named-connection snow CLI.

A best-effort lexical filter rejects writes, SYSTEM$ calls and sequence
advancement. It cannot prove UDFs or external functions have no side effects;
use a least-privilege connection and only trusted read functions.

Stdout contains CSV or a compact JSON array; notes go to stderr. Truncated
previews save complete rows and schema for local inspection. See SKILL.md
and references/guardrails.md for the usage and limits. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

# Leading keyword must be one of these (read-only statements only).
ALLOWED_LEADING = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}

# Belt-and-braces: if any of these appears as a bare word anywhere in the
# comment-stripped and string-stripped SQL, refuse. Catches `WITH ... INSERT`
# and similar.
WRITE_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "TRUNCATE", "DROP",
    "CREATE", "ALTER", "REPLACE", "RENAME", "GRANT", "REVOKE", "CALL",
    "EXECUTE", "COPY", "PUT", "GET", "REMOVE", "UNDROP", "USE", "SET",
    "UNSET", "BEGIN", "COMMIT", "ROLLBACK",
}

# Stage mode only warns (never blocks) when one of these appears. The human
# reviewing the staged file should have the destructive bits flagged.
DESTRUCTIVE_KEYWORDS = {
    "DROP", "TRUNCATE", "DELETE", "REPLACE", "GRANT", "REVOKE", "REMOVE",
}

BLOCK = 2  # exit code for a guardrail refusal

# A snow failure matching this is likely an auth problem, worth a hint but not
# worth debugging the connection config. Deliberately broad (it only ever
# adds a line to an already-failed query) but avoids bare "token", which
# parser errors use. The hint itself is matched to the connection's real
# authenticator, so a false trigger still prints true advice.
AUTH_ERROR_RE = re.compile(
    r"private[ _]?key|passphrase|decrypt|jwt|oauth|access token|authenticat", re.I
)

# Authenticators whose remedy is a human completing a browser login once.
# snow caches the token afterwards. Error text alone can't discriminate
# (key-pair auth is itself JWT-based and OAuth failures also mention tokens),
# hence the authenticator lookup.
BROWSER_AUTHENTICATORS = {"OAUTH_AUTHORIZATION_CODE", "EXTERNALBROWSER"}
ANALYSIS_TOKEN_RE = re.compile(
    r"/\*.*?\*/|--[^\n]*|//[^\n]*|\$\$.*?\$\$|'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"",
    flags=re.S,
)


class Blocked(Exception):
    """A guardrail refusal. ``str(exc)`` is the reason.

    Raised anywhere the wrapper refuses to proceed and rendered once, in
    ``main``, as ``BLOCKED: <reason>`` on stderr with exit code ``BLOCK``.
    """


class ResultProcessingError(Exception):
    """Snow succeeded, but its result could not be decoded or preserved."""


def find_context(start: Path) -> Path:
    """Walk up from `start` to find .snowman/context.md."""
    here = start.resolve()
    for d in (here, *here.parents):
        candidate = d / ".snowman" / "context.md"
        if candidate.is_file():
            return candidate
    raise Blocked(
        "no .snowman/context.md found in this project. Run the snowman "
        "bootstrap first (see references/install.md)."
    )


def parse_frontmatter(context: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Parse the context file's YAML frontmatter (stdlib, schema-specific).

    Returns ``(top, environments)``: top-level scalar keys, and the
    ``environments:`` map of env name -> {key: value}. Only the shapes the
    snowman templates produce are understood. Anything nested deeper is
    ignored.
    """
    text = context.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise Blocked(f"{context} has no YAML frontmatter, so the wrapper cannot find the connection.")
    _, _, rest = text.partition("---")
    front, _, _ = rest.partition("---")

    top: dict[str, str] = {}
    environments: dict[str, dict[str, str]] = {}
    in_environments = False
    current_env: str | None = None
    env_indent: int | None = None

    for raw in front.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, sep, value = raw.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        # YAML inline comments: `#` at the start of the value or after
        # whitespace ends it. Values here are bare names, never contain `#`.
        value = re.sub(r"(?:^|\s)#.*$", "", value.strip()).strip().strip("'\"")
        if indent == 0:
            in_environments = key == "environments" and not value
            current_env = None
            env_indent = None
            if not in_environments and value:
                top[key] = value
        elif in_environments:
            if not value and (env_indent is None or indent <= env_indent):
                env_indent = indent
                current_env = key
                environments[key] = {}
            elif value and current_env is not None and env_indent is not None and indent > env_indent:
                environments[current_env][key] = value
    return top, environments


def resolve_connection(
    context: Path, env: str | None, *, for_stage: bool = False
) -> tuple[str, str | None]:
    """Resolve ``(connection, environment-or-None)`` from the frontmatter.

    Legacy form (single ``connection:``): ``--env`` is rejected. Multi-env
    form (``environments:``): queries fall back to ``default_env``. Staging
    always needs an explicit ``--env`` because the staged file's run command
    targets a real account.
    """
    top, environments = parse_frontmatter(context)

    if environments:
        if top.get("connection"):
            raise Blocked(
                f"{context} defines both `connection:` and `environments:`. "
                "Keep exactly one form."
            )
        if for_stage and not env:
            raise Blocked(
                "staging in a multi-environment project requires --env <name>. "
                "The staged file's run command targets a real account, so "
                f"the environment must be explicit. Defined: {', '.join(environments)}."
            )
        chosen = env or top.get("default_env")
        if not chosen:
            raise Blocked(
                f"{context} has `environments:` but no `default_env:`. Add "
                "one to the frontmatter, or pass --env <name>."
            )
        if chosen not in environments:
            raise Blocked(
                f"unknown environment {chosen!r}. {context} defines: "
                f"{', '.join(environments)}."
            )
        connection = environments[chosen].get("connection")
        if not connection:
            raise Blocked(f"environment {chosen!r} in {context} has no `connection:` value.")
        return connection, chosen

    if env:
        raise Blocked(
            f"--env was given but {context} defines a single `connection:` "
            "with no `environments:` map. Drop --env, or convert the "
            "frontmatter to the multi-environment form."
        )
    connection = top.get("connection")
    if not connection:
        raise Blocked(f"{context} frontmatter has no `connection:` value.")
    return connection, None


def find_env_file(start: Path) -> Path | None:
    """Walk up from `start` to find a .env file (nearest wins)."""
    start = start.resolve()
    for d in (start, *start.parents):
        candidate = d / ".env"
        if candidate.is_file():
            return candidate
    return None


class Target(NamedTuple):
    """The resolved connection, environment, and paths for one run.

    In bootstrap mode (``--connection`` given) there is no context file yet,
    so ``project_root`` and ``snowman_dir`` are ``None``.
    """

    connection: str
    environment: str | None
    project_root: Path | None
    snowman_dir: Path | None
    env_file: Path | None
    warehouse: str | None = None


def resolve_target(
    start: Path, connection: str | None, env: str | None, *, for_stage: bool = False
) -> Target:
    """Resolve where one run goes, walking up from `start`.

    A ``connection`` override skips the context file (bootstrap mode).
    Otherwise the nearest ``.snowman/context.md`` supplies the connection,
    with ``env`` choosing among its environments. The ``.env`` is the nearest
    one at or above the project root, or above ``start`` in bootstrap mode.
    Raises ``Blocked`` for a missing context file or a bad frontmatter.
    """
    warehouse = None
    if connection:
        environment = project_root = snowman_dir = None
    else:
        context = find_context(start)
        connection, environment = resolve_connection(context, env, for_stage=for_stage)
        top, environments = parse_frontmatter(context)
        settings = environments[environment] if environment else top
        warehouse = settings.get("default_warehouse")
        snowman_dir = context.parent
        project_root = snowman_dir.parent
    return Target(
        connection, environment, project_root, snowman_dir,
        find_env_file(project_root or start), warehouse,
    )


def load_dotenv(path: Path) -> dict[str, str]:
    """Tolerant stdlib .env parser: comments, blanks, `export `, quotes.

    Malformed lines are skipped silently. This is a relay, not a linter.
    """
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key] = value
    return out


def snow_env(env_file: Path | None) -> dict[str, str]:
    """Process env merged over .env. Existing env always wins.

    The .env vars exist only in the snow subprocess. Their names and values
    are never printed.
    """
    merged = dict(os.environ)
    if env_file is not None:
        for key, value in load_dotenv(env_file).items():
            merged.setdefault(key, value)
    return merged


class SnowResult(NamedTuple):
    """Decoded CLI result plus original stdout bytes for lossless recovery."""

    returncode: int
    stdout: str
    stderr: str
    stdout_bytes: bytes | None = None


def run_snow(
    args: list[str], env: dict[str, str], *, timeout: float | None = None
) -> SnowResult:
    """Run ``snow <args>`` and return its decoded result.

    ``args`` is the argv after the binary name, so ``args[0]`` is the snow
    subcommand. This is the only place the wrapper touches ``subprocess``,
    and the one name tests patch to keep Snowflake out of the picture.
    Raises ``Blocked`` when the ``snow`` binary is not on PATH.
    """
    try:
        result = subprocess.run(
            ["snow", *args], capture_output=True, env=env, timeout=timeout
        )
    except FileNotFoundError:
        raise Blocked("`snow` CLI not found on PATH.")
    return SnowResult(
        result.returncode,
        result.stdout.decode(errors="replace"),
        result.stderr.decode(errors="replace"),
        result.stdout,
    )


def connection_params(connection: str, env: dict[str, str]) -> dict | None:
    """Look up a connection's parameters through ``snow connection list``.

    Reads local snow config only. Never reaches Snowflake, and the listing
    shows names and paths, not key material. Returns None when the lookup
    fails or the connection isn't listed. Callers fall back to generic guidance.
    """
    try:
        result = run_snow(["connection", "list", "--format", "JSON"], env, timeout=30)
        for item in json.loads(result.stdout):
            if item.get("connection_name") == connection:
                params = item.get("parameters")
                return params if isinstance(params, dict) else {}
    except Exception:
        pass
    return None


def classify_auth(params: dict | None) -> str:
    """Map a connection's parameters to 'browser', 'keypair', or 'unknown'."""
    if params is None:
        return "unknown"
    authenticator = str(params.get("authenticator", "")).upper()
    if authenticator in BROWSER_AUTHENTICATORS:
        return "browser"
    if authenticator == "SNOWFLAKE_JWT" or params.get("private_key_file"):
        return "keypair"
    return "unknown"


def auth_hint(kind: str, connection: str, env_file: Path | None) -> str:
    env_note = (
        f"a .env was loaded from {env_file}" if env_file is not None
        else "no .env file was found"
    )
    browser = (
        f"run `snow connection test -c {connection}` in your own terminal to "
        "complete the browser login (snow caches the token), then retry"
    )
    keypair = (
        "if its private key is encrypted, the passphrase belongs in the "
        "project root .env (e.g. PRIVATE_KEY_PASSPHRASE=...). snowman passes "
        f".env to snow automatically. This run: {env_note}. If a .env was "
        "loaded and it still fails, the variable name is probably wrong for "
        "this connection"
    )
    if kind == "browser":
        return (
            f"hint: connection {connection!r} authenticates in a browser "
            f"(OAuth or SSO). {browser}."
        )
    if kind == "keypair":
        return f"hint: this looks like a key-pair auth failure. {keypair}."
    return (
        "hint: this looks like an auth failure. If the connection uses "
        f"key-pair auth: {keypair}. If it authenticates in a browser "
        f"(OAuth or SSO): {browser}."
    )


def auth_hint_for(
    stderr: str, connection: str, env_file: Path | None, env: dict[str, str]
) -> str | None:
    """The one-line auth hint for a failed snow call, or None if it does
    not look like an auth failure.

    Wraps the trigger regex, the ``snow connection list`` lookup, the
    authenticator classification, and the wording. A lookup that fails for
    any reason (including a missing ``snow`` binary) yields the combined
    hint rather than no hint.
    """
    if not AUTH_ERROR_RE.search(stderr):
        return None
    kind = classify_auth(connection_params(connection, env))
    return auth_hint(kind, connection, env_file)


def strip_for_analysis(sql: str) -> str:
    """Remove comments, string literals, and quoted identifiers.

    The result is used ONLY for the read-only checks. The original SQL is
    what actually runs. Matching every ignored token in one leftmost-first
    pass stops quote or comment markers inside one token from starting
    another token that swallows executable SQL.
    """
    return ANALYSIS_TOKEN_RE.sub(" ", sql)


def keywords_in(sql: str, words: set[str]) -> set[str]:
    """Return the members of ``words`` present as bare words in ``sql``.

    ``sql`` should already be through ``strip_for_analysis``. The match is
    case-insensitive and the result uses the spelling from ``words``.
    """
    return {kw for kw in words if re.search(rf"\b{kw}\b", sql, flags=re.I)}


def enforce_read_only(sql: str) -> None:
    cleaned = strip_for_analysis(sql)

    statements = [s for s in cleaned.split(";") if s.strip()]
    if len(statements) > 1:
        raise Blocked("multiple statements detected. Submit one statement at a time.")
    if not statements:
        raise Blocked("empty query.")

    first = statements[0].strip()
    leading = re.match(r"[A-Za-z_]+", first)
    if not leading:
        raise Blocked("could not identify a leading SQL keyword.")
    word = leading.group(0).upper()
    if word not in ALLOWED_LEADING:
        raise Blocked(f"non-read-only statement (leading keyword: {word}).")

    # REPLACE and GET are also read functions. Only exempt call syntax;
    # their statement forms still fail the leading-keyword/write checks.
    write_scan = re.sub(r"\b(?:REPLACE|GET)\s*(?=\()", " ", cleaned, flags=re.I)
    found = keywords_in(write_scan, WRITE_KEYWORDS)
    if found:
        raise Blocked(f"write or DDL keyword present: {', '.join(sorted(found))}.")

    # Retain quoted identifiers for this check, but still discard literals
    # and comments. Quoting a system function must not bypass the filter.
    callable_sql = ANALYSIS_TOKEN_RE.sub(
        lambda match: match.group(0) if match.group(0).startswith('"') else " ", sql
    )
    if re.search(r'(?<![\w$])"?SYSTEM\$[\w$]+"?\s*\(', callable_sql, re.I):
        raise Blocked("SYSTEM$ function calls are outside supported read queries.")
    if re.search(r'\.\s*"?NEXTVAL"?(?![\w$])|(?<![\w$])"?GETNEXTVAL"?\s*\(', callable_sql, re.I):
        raise Blocked("sequence advancement is outside supported read queries.")


DEFAULT_MAX_ROWS = 50
DEFAULT_MAX_CELL = 200
DEFAULT_MAX_OUTPUT = 16000
MAX_TYPE_NOTE_BYTES = 1024


def render_cell(value) -> str | None:
    """CSV cell text: None stays None, bool -> true/false, nested -> compact JSON."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def truncate_cell(text: str, max_cell: int) -> tuple[str, bool]:
    """Cut `text` to `max_cell` chars plus an `…(+K chars)` tail. 0 = unlimited."""
    if max_cell and len(text) > max_cell:
        return f"{text[:max_cell]}…(+{len(text) - max_cell} chars)", True
    return text, False


def csv_field(text: str | None, *, force_quote: bool = False) -> str:
    """One RFC 4180 field. ``None`` (NULL) is an empty field, ``""`` (empty
    string) is a quoted empty field so a reader can tell the two apart, and
    anything else is quoted only when it holds a comma, quote or newline."""
    if text is None:
        return ""
    if force_quote or text == "" or any(c in text for c in ',"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def write_csv_row(out: io.StringIO, cells: list[str | None]) -> None:
    """Write one CSV record, quoting leading hashes for human readability."""
    fields = [csv_field(cell) for cell in cells]
    if cells and cells[0] is not None and cells[0].startswith("#"):
        fields[0] = csv_field(cells[0], force_quote=True)
    out.write(",".join(fields) + "\n")


PLAIN_TYPES = {"VARCHAR", "TEXT", "STRING", "CHAR", "CHARACTER", "BOOLEAN"}
INTEGER_TYPES = {"NUMBER", "DECIMAL", "NUMERIC", "INT", "INTEGER", "BIGINT",
                 "SMALLINT", "TINYINT", "BYTEINT"}


def type_is_plain(sql_type: str) -> bool:
    """True for types CSV text already conveys: strings, booleans, and
    integers (NUMBER with scale 0). Everything else deserves a footer note."""
    base, _, rest = sql_type.partition("(")
    base = base.strip().upper()
    if base in PLAIN_TYPES:
        return True
    if base in INTEGER_TYPES:
        scale = rest.rstrip(")").partition(",")[2].strip()
        return scale in ("", "0")
    return False


def types_footer(describe_rows: list[dict] | None, *, include_plain: bool = False) -> str | None:
    """``# types: COL TYPE, ...`` for the columns whose Snowflake type the CSV
    text cannot show (scaled NUMBER, FLOAT, DATE/TIME/TIMESTAMP, VARIANT,
    OBJECT, ARRAY, ...). ``describe_rows`` is the ``DESCRIBE RESULT`` output
    that the wrapper fetches with the query. None when nothing is notable."""
    notable = [
        f"{row['name']} {row['type']}"
        for row in describe_rows or []
        if isinstance(row, dict) and row.get("name") and row.get("type")
        and (include_plain or not type_is_plain(str(row["type"])))
    ]
    return f"# types: {', '.join(notable)}" if notable else None


def validate_limits(fmt: str, max_rows: int, max_cell: int, max_output: int) -> None:
    for name, value in (("max-rows", max_rows), ("max-cell", max_cell), ("max-output", max_output)):
        if value < 0:
            raise Blocked(f"--{name} must be nonnegative; 0 means unlimited.")
    if fmt == "json" and 0 < max_output < 3:
        raise Blocked("--max-output must be 0 or at least 3 bytes for JSON ([] plus newline).")


def render_rows(
    rows: list[dict],
    *,
    fmt: str = "csv",
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cell: int = DEFAULT_MAX_CELL,
    max_output: int = DEFAULT_MAX_OUTPUT,
    full_note: str | None = None,
    types: list[dict] | None = None,
) -> tuple[str, list[str], bool]:
    """Return data text, stderr notes, and whether any result detail was cut.

    Limits apply to rows, cell characters and UTF-8 data bytes. Zero lifts
    that limit. Oversized nested JSON cells become truncated JSON text;
    complete nested values retain their types. Whole rows are omitted when
    the byte budget runs out. Type notes have a separate 1024-byte ceiling.
    """
    validate_limits(fmt, max_rows, max_cell, max_output)
    total = len(rows)
    columns = list(rows[0]) if rows else [row["name"] for row in types or [] if row.get("name")]
    header = io.StringIO()
    if fmt == "csv" and columns:
        write_csv_row(header, columns)
    prefix = "[" if fmt == "json" else header.getvalue()
    suffix = "]\n" if fmt == "json" else ""
    used = len((prefix + suffix).encode("utf-8"))
    budget_cut = bool(max_output and used > max_output)
    if budget_cut:
        prefix = ""  # A CSV header can exceed the budget by itself.
    pieces: list[str] = []
    had_null = had_empty = cell_cut = nested_cut = False
    candidates = rows[:max_rows] if max_rows else rows
    for row in candidates:
        if budget_cut:
            break
        csv_cells: list[str | None] = []
        json_cells: dict = {}
        row_null = row_empty = row_cut = row_nested_cut = False
        for col in columns:
            value = row.get(col)
            text = render_cell(value)
            cut = False
            if text is not None:
                text, cut = truncate_cell(text, max_cell)
            row_cut |= cut
            if fmt == "json":
                json_cells[col] = text if cut else value
                row_nested_cut |= cut and isinstance(value, (dict, list))
            else:
                row_null |= value is None
                row_empty |= value == ""
                csv_cells.append(text)
        if fmt == "json":
            piece = ("," if pieces else "") + json.dumps(json_cells, separators=(",", ":"), ensure_ascii=False)
        else:
            line = io.StringIO()
            write_csv_row(line, csv_cells)
            piece = line.getvalue()
        size = len(piece.encode("utf-8"))
        if max_output and used + size > max_output:
            budget_cut = True
            break
        pieces.append(piece)
        used += size
        had_null |= row_null
        had_empty |= row_empty
        cell_cut |= row_cut
        nested_cut |= row_nested_cut

    notes = []
    type_cut = False
    if (note := types_footer(types, include_plain=not rows)):
        encoded = note.encode("utf-8")
        if len(encoded) > MAX_TYPE_NOTE_BYTES:
            ending = "... [type notes shortened]"
            note = encoded[:MAX_TYPE_NOTE_BYTES - len(ending)].decode("utf-8", errors="ignore") + ending
            type_cut = True
        notes.append(note)
    if not rows:
        notes.append("# 0 rows")
    if had_null and had_empty:
        notes.append('# empty cells are NULL; "" is an empty string')
    elif had_null:
        notes.append("# empty cells are NULL")
    elif had_empty:
        notes.append('# "" is an empty string')
    if cell_cut:
        notes.append(f"# some cells truncated to {max_cell} chars; pass --max-cell 0 for full values")
    if nested_cut:
        notes.append("# truncated nested JSON cells are shown as JSON text strings")
    if len(pieces) < total:
        note = f"# showing {len(pieces)} of {total} rows"
        if full_note:
            note += f"; {full_note}"
        notes.append(note + "; narrow the query or raise --max-rows/--max-output")
    if budget_cut:
        notes.append(f"# data preview limited to {max_output} UTF-8 bytes; pass --max-output 0 for unlimited")
    truncated = cell_cut or type_cut or budget_cut or len(pieces) < total
    return prefix + "".join(pieces) + suffix, notes, truncated


def clean_snow_stderr(text: str) -> str:
    """Flatten snow's Rich error panel into one ``ERROR: ...`` line.

    Border-only lines are dropped, the ``│`` gutters removed, and the
    wrapped lines of one panel re-joined with single spaces (blank panel
    lines are skipped). Each panel becomes its own line. Lines outside a
    panel pass through untouched.
    """
    out: list[str] = []
    panel: list[str] = []

    def flush() -> None:
        if panel:
            out.append("ERROR: " + " ".join(panel))
            panel.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("╭"):
            continue
        if stripped.startswith("╰"):
            flush()
            continue
        if stripped.startswith("│"):
            inner = stripped.strip("│").strip()
            if inner:
                panel.append(inner)
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out) + ("\n" if out else "")


def gitignored_dir(path: Path) -> Path:
    """Create `path` (if needed) with a `.gitignore` ignoring everything in it."""
    path.mkdir(exist_ok=True)
    gitignore = path / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text("*\n", encoding="utf-8")
    return path


def unique_path(directory: Path, base: str, suffix: str, now: datetime) -> Path:
    """``<directory>/<timestamp>__<base><suffix>`` that does not exist yet.

    The timestamp is ``now`` to the second. A clash appends ``-1``, ``-2``
    and so on to ``base`` until the name is free.
    """
    stem = f"{now:%Y%m%d-%H%M%S}__{base}"
    path = directory / f"{stem}{suffix}"
    bump = 1
    while path.exists():
        path = directory / f"{stem}-{bump}{suffix}"
        bump += 1
    return path


def spill_full_result(
    rows: list[dict], sql: str, snowman_dir: Path | None, *,
    types: list[dict] | None = None, now: datetime | None = None,
) -> Path:
    """Save lossless rows and DESCRIBE schema. Bootstrap uses a private temp dir."""
    results_dir = (gitignored_dir(snowman_dir / "results") if snowman_dir
                   else Path(tempfile.mkdtemp(prefix="snowman-results-")))
    digest = hashlib.sha1(sql.encode("utf-8")).hexdigest()[:8]
    path = unique_path(results_dir, digest, ".json", now or datetime.now())
    with path.open("x", encoding="utf-8") as out:
        json.dump({"rows": rows, "types": types or []}, out, separators=(",", ":"), ensure_ascii=False)
        out.write("\n")
    return path


def stage(sql: str, name: str, env: str | None, *, now: datetime | None = None) -> int:
    """Write the SQL to .snowman/staged/ for manual execution. Never runs it."""
    if not sql.strip():
        raise Blocked("empty script. Nothing to stage.")

    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", name.lower())).strip("-")
    if not slug:
        raise Blocked(f"--name {name!r} reduces to an empty slug. Use letters, digits, hyphens.")

    target = resolve_target(Path.cwd(), None, env, for_stage=True)
    connection, env_name = target.connection, target.environment
    assert target.snowman_dir is not None and target.project_root is not None
    staged_dir = gitignored_dir(target.snowman_dir / "staged")

    now = now or datetime.now()
    env_part = f"{env_name}__" if env_name else ""
    path = unique_path(staged_dir, f"{env_part}{slug}", ".sql", now)
    rel = path.relative_to(target.project_root)

    run_args = ["snow", "sql", "-f", str(rel), "--connection", connection]
    if target.warehouse:
        run_args += ["--warehouse", target.warehouse]
    run_cmd = shlex.join(run_args)
    destructive = sorted(keywords_in(strip_for_analysis(sql), DESTRUCTIVE_KEYWORDS))
    header = [
        "-- staged by snowman, NOT executed",
        f"-- purpose: {slug}",
    ]
    if env_name:
        header.append(f"-- target environment: {env_name} (connection: {connection})")
    header += [
        f"-- staged at: {now:%Y-%m-%d %H:%M:%S}",
        f"-- run with: {run_cmd}",
    ]
    if destructive:
        header.append(
            f"-- WARNING: contains {', '.join(destructive)}. Review carefully before running"
        )
    path.write_text("\n".join(header) + "\n\n" + sql.strip() + "\n", encoding="utf-8")

    print(f"STAGED (not executed): {rel}")
    print(f"run with: {run_cmd}")
    return 0


DESCRIBE_RESULT = "DESCRIBE RESULT LAST_QUERY_ID()"


def mask_for_trim(match: re.Match) -> str:
    """Same-length stand-in for a comment or literal. Comments become spaces
    so a trailing one is trimmed; literals and quoted identifiers become
    ``x`` so the trim stops at their closing quote instead of eating them.
    Deliberately differs from ``strip_for_analysis``, which blanks literals
    too: here their length and non-whitespace content must survive."""
    token = match.group(0)
    if token.startswith(("--", "//", "/*")):
        return " " * len(token)
    return "x" * len(token)


def with_describe(sql: str) -> str:
    """Append ``DESCRIBE RESULT LAST_QUERY_ID()`` as a second statement so one
    ``snow`` session returns the rows and their column types. The ``;`` goes
    on its own line so a trailing ``--`` comment cannot swallow it. Any
    trailing ``;`` on the query (even one followed by a comment) is cut so no
    empty statement sits between, which Snowflake would reject."""
    masked = ANALYSIS_TOKEN_RE.sub(mask_for_trim, sql)
    body = masked.rstrip()
    while body.endswith(";"):
        body = body[:-1].rstrip()
    return f"{sql[:len(body)]}\n;{DESCRIBE_RESULT}"


def split_result(parsed) -> tuple[list | None, list[dict] | None]:
    """``(rows, describe_rows)`` from snow's JSON_EXT stdout. Two statements
    come back as ``[[rows...], [describe rows...]]``; a lone ``[rows...]``
    (or the ``[]`` snow prints on failure) has no types. Anything else is
    ``(None, None)`` so the caller refuses an unexpected output format."""
    if not isinstance(parsed, list):
        return None, None
    if len(parsed) == 2 and all(isinstance(part, list) for part in parsed):
        if all(isinstance(row, dict) for part in parsed for row in part):
            return parsed[0], parsed[1]
        return None, None
    if all(isinstance(row, dict) for row in parsed):
        return parsed, None
    return None, None


def preserve_failed_result(raw: str | bytes, reason: str) -> ResultProcessingError:
    """Keep received CLI stdout privately when parsing, rendering or spilling fails."""
    if not raw.strip():
        return ResultProcessingError(f"{reason} no result output received; nothing to recover.")
    path: str | None = None
    try:
        fd, path = tempfile.mkstemp(prefix="snowman-recovery-", suffix=".txt")
        with os.fdopen(fd, "wb") as out:
            out.write(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
    except OSError:
        if path is not None:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return ResultProcessingError(f"{reason} could not save recovery copy; no complete artifact available.")
    return ResultProcessingError(
        f"{reason}\n# raw CLI stdout: {path}\n"
        "# Inspect this file locally; JSON_EXT rows/schema if valid, otherwise unparsed output."
    )


def execute(
    sql: str,
    connection_override: str | None = None,
    env: str | None = None,
    *,
    fmt: str = "csv",
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cell: int = DEFAULT_MAX_CELL,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> int:
    validate_limits(fmt, max_rows, max_cell, max_output)
    if not sql.strip():
        raise Blocked("empty query.")
    enforce_read_only(sql)

    target = resolve_target(Path.cwd(), connection_override, env)
    connection, env_file = target.connection, target.env_file

    sub_env = snow_env(env_file)
    query_args = ["sql", "-q", with_describe(sql), "--connection", connection,
                  "--format", "JSON_EXT", "--enhanced-exit-codes"]
    if target.warehouse:
        query_args += ["--warehouse", target.warehouse]
    result = run_snow(query_args, sub_env)

    if result.stderr:
        sys.stderr.write(clean_snow_stderr(result.stderr))
    if result.returncode != 0:
        hint = auth_hint_for(result.stderr, connection, env_file, sub_env)
        if hint:
            print(hint, file=sys.stderr)
        return result.returncode

    raw = result.stdout_bytes if result.stdout_bytes is not None else result.stdout
    try:
        rows, types = split_result(json.loads(result.stdout))
    except (ValueError, RecursionError):
        rows = types = None
    if not isinstance(rows, list):
        raise preserve_failed_result(raw, "unexpected snow output; expected JSON row arrays.")
    if rows and any(row.keys() != rows[0].keys() for row in rows[1:]):
        raise preserve_failed_result(raw, "inconsistent result columns; cannot safely render these rows.")
    if types is not None and any(
        not isinstance(row.get("name"), str) or not isinstance(row.get("type"), str)
        for row in types
    ):
        raise preserve_failed_result(raw, "invalid DESCRIBE schema; expected string names and types.")
    try:
        text, notes, truncated = render_rows(
            rows, fmt=fmt, max_rows=max_rows, max_cell=max_cell,
            max_output=max_output, types=types,
        )
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise preserve_failed_result(raw, "cannot render result preview.") from None
    if truncated:
        try:
            spilled = spill_full_result(rows, sql, target.snowman_dir, types=types)
        except (OSError, ValueError, TypeError, RecursionError, OverflowError):
            raise preserve_failed_result(raw, "cannot save full result.") from None
        location = os.path.relpath(spilled, Path.cwd()) if target.snowman_dir else str(spilled)
        notes.append(f"# full result: {location}")
    sys.stdout.write(text)
    for line in notes:
        print(line, file=sys.stderr)
    return result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="snowman.py",
        description="Read-only Snowflake query wrapper. --stage writes DML or DDL "
        "to .snowman/staged/ for manual execution instead of running anything.",
    )
    parser.add_argument("sql", help="the SQL to run (read-only) or stage")
    parser.add_argument(
        "--stage", action="store_true",
        help="write the SQL to .snowman/staged/ instead of executing it",
    )
    parser.add_argument(
        "--name", metavar="PURPOSE-SLUG",
        help="kebab-case purpose for the staged file (required with --stage)",
    )
    parser.add_argument(
        "--connection", metavar="NAME",
        help="connection name override for bootstrap, before "
        ".snowman/context.md exists (execute mode only)",
    )
    parser.add_argument(
        "--env", metavar="NAME",
        help="environment to target in a multi-environment project (falls "
        "back to default_env for queries). Required with --stage there",
    )
    parser.add_argument(
        "--max-rows", type=int, default=DEFAULT_MAX_ROWS, metavar="N",
        help="rows to print before spilling the full result to "
        f".snowman/results/ (default {DEFAULT_MAX_ROWS}, 0 = unlimited)",
    )
    parser.add_argument(
        "--max-cell", type=int, default=DEFAULT_MAX_CELL, metavar="N",
        help="characters to keep per cell before cutting with an "
        f"…(+K chars) tail (default {DEFAULT_MAX_CELL}, 0 = unlimited)",
    )
    parser.add_argument(
        "--max-output", type=int, default=DEFAULT_MAX_OUTPUT, metavar="BYTES",
        help=f"UTF-8 data bytes to print (default {DEFAULT_MAX_OUTPUT}, 0 = unlimited); notes go to stderr",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="print rows as a compact JSON array instead of CSV (nested "
        "VARIANT, OBJECT, and ARRAY values retain JSON types unless truncated)",
    )
    args = parser.parse_args(argv[1:])

    if args.stage:
        if not args.name:
            parser.error("--stage requires --name <purpose-slug>")
        if args.connection:
            parser.error("--connection is not valid with --stage")
        if args.json:
            parser.error("--json is only valid when executing")
    elif args.name:
        parser.error("--name is only valid with --stage")
    elif args.connection and args.env:
        parser.error("--env resolves via the context file and --connection bypasses it, so use one or the other")

    try:
        if args.stage:
            return stage(args.sql, args.name, args.env)
        return execute(
            args.sql,
            connection_override=args.connection,
            env=args.env,
            fmt="json" if args.json else "csv",
            max_rows=args.max_rows,
            max_cell=args.max_cell,
            max_output=args.max_output,
        )
    except Blocked as refusal:
        print(f"BLOCKED: {refusal}", file=sys.stderr)
        return BLOCK
    except ResultProcessingError as failure:
        print(f"ERROR: query already ran; {failure} Do not rerun automatically.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
