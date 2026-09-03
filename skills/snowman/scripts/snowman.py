#!/usr/bin/env python3
"""snowman: read-only guardrail wrapper around the Snowflake ``snow`` CLI.

Every snowman query goes through here. The wrapper makes one ironclad
guarantee: **only read-only, single-statement SQL ever reaches Snowflake.**
Cost discipline (LIMIT or SAMPLE, full-scan avoidance) is taught in
``references/guardrails.md`` and is NOT enforced here. See that file.

Usage:
    python3 snowman.py "<SQL>"
    python3 snowman.py --env <name> "<SQL>"
    python3 snowman.py --connection <name> "<SQL>"
    python3 snowman.py [--max-rows N] [--max-cell N] [--json] "<SQL>"
    python3 snowman.py --stage "<SQL>" --name <purpose-slug> [--env <name>]

Execute mode (default):
  * resolves the project's ``.snowman/context.md`` (walks up from CWD) and
    reads the connection from its YAML frontmatter. Two frontmatter forms:
    a single ``connection:`` (one account), or an ``environments:`` map plus
    ``default_env:`` (dev and prod in separate accounts). With environments,
    ``--env <name>`` picks one per query and ``default_env`` is the fallback.
    Selection is stateless, never sticky;
  * refuses to run if no context file exists (bootstrap not done), unless
    ``--connection <name>`` overrides it, which is how the bootstrap routes
    its discovery queries through the guardrail before the context exists;
  * strips comments + string literals, then rejects anything that is not a
    single read-only statement;
  * loads the project's ``.env`` (if any) into the ``snow`` subprocess
    environment. Existing process env always wins. Values and var names are
    never printed. This is what makes key-pair connections with an encrypted
    private key work: the passphrase lives in ``.env``, not in any config
    snowman touches;
  * on success runs ``snow sql -q <SQL> --connection <conn> --format
    JSON_EXT --enhanced-exit-codes``, parses the JSON result and prints it
    as CSV (header row first, a NULL is an empty cell, and VARIANT, OBJECT,
    and ARRAY cells are compact JSON). CSV costs a third to a fifth of the
    tokens of snow's indented JSON. Output is capped: ``--max-rows N`` (default 50)
    rows are shown and, when a context file exists, the full result is
    written to ``.snowman/results/<timestamp>__<sha1-8 of SQL>.csv``
    (gitignored). ``--max-cell N`` (default 200) cuts longer string cells
    to ``<prefix>…(+K chars)``. ``0`` lifts either cap. ``--json`` prints a
    compact JSON array instead of CSV. Notes about NULLs, truncated cells
    and the row cap are appended as ``# ...`` footer lines, the only
    non-data lines on stdout;
  * relays snow's stderr with the Rich error panel flattened to one
    ``ERROR: ...`` line, and forwards snow's exit code (5 = SQL error, 2 =
    argument error, other snow errors keep snow's own code). If snow fails
    with an auth-looking error, looks up the connection's authenticator
    through ``snow connection list`` (local config read, no secrets) and
    appends a one-line hint matched to the auth method: complete the browser
    login (OAuth or SSO), or put the key-pair passphrase in ``.env``;
  * on refusal prints ``BLOCKED: <reason>`` to stderr and exits non-zero.

Stage mode (``--stage``):
  * never executes anything. Writes the SQL to
    ``.snowman/staged/<timestamp>__<slug>.sql`` for the user to review and
    run manually;
  * accepts any SQL, including DML or DDL and multi-statement scripts. The
    only check is non-emptiness. Destructive keywords add a warning line to
    the file header. They never block;
  * still requires ``.snowman/context.md`` (the header's run command needs
    the connection name). In a multi-environment project ``--env`` is
    REQUIRED. The run command targets a real account, so the environment
    must be explicit. It also lands in the filename and a header line;
  * keeps ``.snowman/staged/`` gitignored through a ``.gitignore`` it maintains.

Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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


class Blocked(Exception):
    """A guardrail refusal. ``str(exc)`` is the reason.

    Raised anywhere the wrapper refuses to proceed and rendered once, in
    ``main``, as ``BLOCKED: <reason>`` on stderr with exit code ``BLOCK``.
    """


def find_context() -> Path:
    """Walk up from CWD to find .snowman/context.md."""
    here = Path.cwd().resolve()
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


def connection_params(connection: str, env: dict[str, str]) -> dict | None:
    """Look up a connection's parameters through ``snow connection list``.

    Reads local snow config only. Never reaches Snowflake, and the listing
    shows names and paths, not key material. Returns None when the lookup
    fails or the connection isn't listed. Callers fall back to generic guidance.
    """
    try:
        result = subprocess.run(
            ["snow", "connection", "list", "--format", "JSON"],
            capture_output=True, env=env, timeout=30,
        )
        for item in json.loads(result.stdout.decode(errors="replace")):
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


def strip_for_analysis(sql: str) -> str:
    """Remove block comments, line comments, and string literals.

    The result is used ONLY for the read-only checks. The original SQL is
    what actually runs. Blanking string literals (single-quoted and
    dollar-quoted) stops semicolons and keywords inside quotes from
    triggering false rejects.
    """
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)        # /* block */
    sql = re.sub(r"--[^\n]*", " ", sql)                       # -- line
    sql = re.sub(r"//[^\n]*", " ", sql)                       # // line (Snowflake)
    sql = re.sub(r"\$\$.*?\$\$", " '' ", sql, flags=re.S)     # $$dollar quoted$$
    sql = re.sub(r"'(?:[^']|'')*'", " '' ", sql)             # 'string literals'
    return sql


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

    found = keywords_in(cleaned, WRITE_KEYWORDS)
    if found:
        raise Blocked(f"write or DDL keyword present: {', '.join(sorted(found))}.")


DEFAULT_MAX_ROWS = 50
DEFAULT_MAX_CELL = 200


def render_cell(value) -> str:
    """CSV cell text: None -> empty, bool -> true/false, nested -> compact JSON."""
    if value is None:
        return ""
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


def write_csv_row(out: io.StringIO, cells: list[str]) -> None:
    """Write one CSV line. A first cell starting with ``#`` is force-quoted so
    no data line can be mistaken for a ``# ...`` footer."""
    if cells and cells[0].startswith("#"):
        first = '"' + cells[0].replace('"', '""') + '"'
        if len(cells) == 1:
            out.write(first + "\n")
            return
        out.write(first + ",")
        cells = cells[1:]
    csv.writer(out, lineterminator="\n").writerow(cells)


def render_rows(
    rows: list[dict],
    *,
    fmt: str = "csv",
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cell: int = DEFAULT_MAX_CELL,
    full_note: str | None = None,
) -> tuple[str, list[str]]:
    """Shape a JSON_EXT result for the agent: ``(text, footer_lines)``.

    ``fmt`` is ``csv`` (header row, NULL as empty cell, nested values as
    compact JSON) or ``json`` (compact array, NULL stays ``null``). Rows past
    ``max_rows`` and characters past ``max_cell`` are cut (0 = unlimited).
    ``full_note`` is spliced into the row-cap footer to say where (or
    whether) the full result was saved. Footers all start with ``# ``.
    """
    total = len(rows)
    if total == 0:
        return "", ["# 0 rows"]
    shown = rows[:max_rows] if max_rows else rows
    columns = list(shown[0].keys())

    had_null = False
    truncated_any = False
    out = io.StringIO()
    if fmt == "json":
        shaped = []
        for row in shown:
            cells = {}
            for col in columns:
                value = row.get(col)
                if isinstance(value, str):
                    value, cut = truncate_cell(value, max_cell)
                    truncated_any |= cut
                cells[col] = value
            shaped.append(cells)
        out.write(json.dumps(shaped, separators=(",", ":"), ensure_ascii=False))
        out.write("\n")
    else:
        write_csv_row(out, columns)
        for row in shown:
            cells = []
            for col in columns:
                value = row.get(col)
                had_null |= value is None
                text, cut = truncate_cell(render_cell(value), max_cell)
                truncated_any |= cut
                cells.append(text)
            write_csv_row(out, cells)

    footers = []
    if had_null:
        footers.append("# empty cells are NULL")
    if truncated_any:
        footers.append(
            f"# some cells truncated to {max_cell} chars; pass --max-cell 0 for full values"
        )
    if len(shown) < total:
        footers.append(
            f"# showing {len(shown)} of {total} rows; {full_note}; add LIMIT or a "
            "WHERE filter to narrow, or pass --max-rows 0"
        )
    return out.getvalue(), footers


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


def spill_full_result(rows: list[dict], sql: str, context: Path) -> Path:
    """Write every row, untruncated, as CSV under ``.snowman/results/``."""
    results_dir = gitignored_dir(context.parent / "results")
    digest = hashlib.sha1(sql.encode("utf-8")).hexdigest()[:8]
    path = results_dir / f"{datetime.now():%Y%m%d-%H%M%S}__{digest}.csv"
    text, _ = render_rows(rows, fmt="csv", max_rows=0, max_cell=0)
    path.write_text(text, encoding="utf-8")
    return path


def stage(sql: str, name: str, env: str | None) -> int:
    """Write the SQL to .snowman/staged/ for manual execution. Never runs it."""
    if not sql.strip():
        raise Blocked("empty script. Nothing to stage.")

    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", name.lower())).strip("-")
    if not slug:
        raise Blocked(f"--name {name!r} reduces to an empty slug. Use letters, digits, hyphens.")

    context = find_context()
    connection, env_name = resolve_connection(context, env, for_stage=True)
    project_root = context.parent.parent

    staged_dir = gitignored_dir(context.parent / "staged")

    now = datetime.now()
    env_part = f"{env_name}__" if env_name else ""
    base = f"{now:%Y%m%d-%H%M%S}__{env_part}{slug}"
    path = staged_dir / f"{base}.sql"
    bump = 1
    while path.exists():
        path = staged_dir / f"{base}-{bump}.sql"
        bump += 1
    rel = path.relative_to(project_root)

    run_cmd = f"snow sql -f {rel} --connection {connection}"
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


def execute(
    sql: str,
    connection_override: str | None = None,
    env: str | None = None,
    *,
    fmt: str = "csv",
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cell: int = DEFAULT_MAX_CELL,
) -> int:
    if not sql.strip():
        raise Blocked("empty query.")
    enforce_read_only(sql)

    context: Path | None = None
    if connection_override:
        # Bootstrap mode: no context file yet, so search for .env from CWD.
        connection = connection_override
        env_file = find_env_file(Path.cwd())
    else:
        context = find_context()
        connection, _ = resolve_connection(context, env)
        project_env = context.parent.parent / ".env"
        env_file = project_env if project_env.is_file() else None

    cmd = [
        "snow", "sql", "-q", sql, "--connection", connection,
        "--format", "JSON_EXT", "--enhanced-exit-codes",
    ]
    sub_env = snow_env(env_file)
    try:
        result = subprocess.run(cmd, env=sub_env, capture_output=True)
    except FileNotFoundError:
        raise Blocked("`snow` CLI not found on PATH.")

    stderr = result.stderr.decode(errors="replace")
    if stderr:
        sys.stderr.write(clean_snow_stderr(stderr))
    if result.returncode != 0 and AUTH_ERROR_RE.search(stderr):
        kind = classify_auth(connection_params(connection, sub_env))
        print(auth_hint(kind, connection, env_file), file=sys.stderr)

    stdout = result.stdout.decode(errors="replace")
    if stdout.strip():
        try:
            rows = json.loads(stdout)
        except ValueError:
            rows = None
        if not isinstance(rows, list):
            sys.stdout.write(stdout)  # unexpected shape: relay raw
        else:
            full_note = None
            if max_rows and len(rows) > max_rows:
                if context is None:
                    full_note = "no context file yet so the full result was not saved"
                else:
                    spilled = spill_full_result(rows, sql, context)
                    rel = os.path.relpath(spilled, Path.cwd())
                    full_note = f"full result: {rel}"
            text, footers = render_rows(
                rows, fmt=fmt, max_rows=max_rows, max_cell=max_cell, full_note=full_note
            )
            sys.stdout.write(text)
            for line in footers:
                print(line)
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
        "--json", action="store_true",
        help="print rows as a compact JSON array instead of CSV (nested "
        "VARIANT, OBJECT, and ARRAY values stay real JSON)",
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
        )
    except Blocked as refusal:
        print(f"BLOCKED: {refusal}", file=sys.stderr)
        return BLOCK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
