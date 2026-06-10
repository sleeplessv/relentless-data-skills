#!/usr/bin/env python3
"""snowman — read-only guardrail wrapper around the Snowflake ``snow`` CLI.

Every snowman query goes through here. The wrapper makes one ironclad
guarantee: **only read-only, single-statement SQL ever reaches Snowflake.**
Cost discipline (LIMIT/SAMPLE, full-scan avoidance) is taught in
``references/guardrails.md`` and is NOT enforced here — see that file.

Usage:
    python3 snowman.py "<SQL>"
    python3 snowman.py --connection <name> "<SQL>"
    python3 snowman.py --stage "<SQL>" --name <purpose-slug>

Execute mode (default):
  * resolves the project's ``.snowman/context.md`` (walks up from CWD) and
    reads the ``connection`` from its YAML frontmatter;
  * refuses to run if no context file exists (bootstrap not done) — unless
    ``--connection <name>`` overrides it, which is how the bootstrap routes
    its discovery queries through the guardrail before the context exists;
  * strips comments + string literals, then rejects anything that is not a
    single read-only statement;
  * loads the project's ``.env`` (if any) into the ``snow`` subprocess
    environment — existing process env always wins; values and var names are
    never printed. This is what makes key-pair connections with an encrypted
    private key work: the passphrase lives in ``.env``, not in any config
    snowman touches;
  * on success runs ``snow sql -q <SQL> --connection <conn> --format JSON``
    and forwards snow's stdout/stderr/exit code; if snow fails with an error
    that looks key/passphrase-related, appends a one-line hint saying whether
    a ``.env`` was found;
  * on refusal prints ``BLOCKED: <reason>`` to stderr and exits non-zero.

Stage mode (``--stage``):
  * never executes anything — writes the SQL to
    ``.snowman/staged/<timestamp>__<slug>.sql`` for the user to review and
    run manually;
  * accepts any SQL, including DML/DDL and multi-statement scripts; the only
    check is non-emptiness. Destructive keywords add a warning line to the
    file header, they never block;
  * still requires ``.snowman/context.md`` (the header's run command needs
    the connection name);
  * keeps ``.snowman/staged/`` gitignored via a ``.gitignore`` it maintains.

Standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Leading keyword must be one of these (read-only statements only).
ALLOWED_LEADING = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}

# Belt-and-braces: if any of these appears as a bare word anywhere in the
# comment/string-stripped SQL, refuse — catches `WITH ... INSERT`, etc.
WRITE_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "TRUNCATE", "DROP",
    "CREATE", "ALTER", "REPLACE", "RENAME", "GRANT", "REVOKE", "CALL",
    "EXECUTE", "COPY", "PUT", "GET", "REMOVE", "UNDROP", "USE", "SET",
    "UNSET", "BEGIN", "COMMIT", "ROLLBACK",
}

# Stage mode only warns (never blocks) when one of these appears — the human
# reviewing the staged file should have the destructive bits flagged.
DESTRUCTIVE_KEYWORDS = {
    "DROP", "TRUNCATE", "DELETE", "REPLACE", "GRANT", "REVOKE", "REMOVE",
}

BLOCK = 2  # exit code for a guardrail refusal

# A snow failure matching this is likely a key-pair auth problem (encrypted
# private key, missing/wrong passphrase) — worth a hint, not worth debugging
# the connection config.
AUTH_ERROR_RE = re.compile(r"private[ _]?key|passphrase|decrypt|jwt", re.I)


def die(reason: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"BLOCKED: {reason}", file=sys.stderr)
    raise SystemExit(BLOCK)


def find_context() -> Path:
    """Walk up from CWD to find .snowman/context.md."""
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        candidate = d / ".snowman" / "context.md"
        if candidate.is_file():
            return candidate
    die(
        "no .snowman/context.md found in this project — run the snowman "
        "bootstrap first (see references/install.md)."
    )


def read_connection(context: Path) -> str:
    """Pull `connection:` from the context file's YAML frontmatter."""
    text = context.read_text(encoding="utf-8")
    if not text.startswith("---"):
        die(f"{context} has no YAML frontmatter — cannot find the connection.")
    _, _, rest = text.partition("---")
    front, _, _ = rest.partition("---")
    for line in front.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "connection":
            conn = value.strip().strip("'\"")
            if conn:
                return conn
    die(f"{context} frontmatter has no `connection:` value.")


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

    Malformed lines are skipped silently — this is a relay, not a linter.
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
    """Process env merged over .env — existing env always wins.

    The .env vars exist only in the snow subprocess; their names and values
    are never printed.
    """
    merged = dict(os.environ)
    if env_file is not None:
        for key, value in load_dotenv(env_file).items():
            merged.setdefault(key, value)
    return merged


def strip_for_analysis(sql: str) -> str:
    """Remove block comments, line comments, and string literals.

    The result is used ONLY for the read-only checks; the original SQL is
    what actually runs. Blanking string literals stops semicolons/keywords
    inside quotes from triggering false rejects.
    """
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)        # /* block */
    sql = re.sub(r"--[^\n]*", " ", sql)                       # -- line
    sql = re.sub(r"//[^\n]*", " ", sql)                       # // line (Snowflake)
    sql = re.sub(r"'(?:[^']|'')*'", " '' ", sql)             # 'string literals'
    return sql


def enforce_read_only(sql: str) -> None:
    cleaned = strip_for_analysis(sql)

    statements = [s for s in cleaned.split(";") if s.strip()]
    if len(statements) > 1:
        die("multiple statements detected — submit one statement at a time.")
    if not statements:
        die("empty query.")

    first = statements[0].strip()
    leading = re.match(r"[A-Za-z_]+", first)
    if not leading:
        die("could not identify a leading SQL keyword.")
    word = leading.group(0).upper()
    if word not in ALLOWED_LEADING:
        die(f"non-read-only statement (leading keyword: {word}).")

    found = {
        kw for kw in WRITE_KEYWORDS
        if re.search(rf"\b{kw}\b", cleaned, flags=re.I)
    }
    if found:
        die(f"write/DDL keyword(s) present: {', '.join(sorted(found))}.")


def stage(sql: str, name: str) -> int:
    """Write the SQL to .snowman/staged/ for manual execution. Never runs it."""
    if not sql.strip():
        die("empty script — nothing to stage.")

    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", name.lower())).strip("-")
    if not slug:
        die(f"--name {name!r} reduces to an empty slug — use letters, digits, hyphens.")

    context = find_context()
    connection = read_connection(context)
    project_root = context.parent.parent

    staged_dir = context.parent / "staged"
    staged_dir.mkdir(exist_ok=True)
    gitignore = staged_dir / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text("*\n", encoding="utf-8")

    now = datetime.now()
    base = f"{now:%Y%m%d-%H%M%S}__{slug}"
    path = staged_dir / f"{base}.sql"
    bump = 1
    while path.exists():
        path = staged_dir / f"{base}-{bump}.sql"
        bump += 1
    rel = path.relative_to(project_root)

    run_cmd = f"snow sql -f {rel} --connection {connection}"
    destructive = sorted(
        kw for kw in DESTRUCTIVE_KEYWORDS
        if re.search(rf"\b{kw}\b", strip_for_analysis(sql), flags=re.I)
    )
    header = [
        "-- staged by snowman — NOT executed",
        f"-- purpose: {slug}",
        f"-- staged at: {now:%Y-%m-%d %H:%M:%S}",
        f"-- run with: {run_cmd}",
    ]
    if destructive:
        header.append(
            f"-- WARNING: contains {', '.join(destructive)} — review carefully before running"
        )
    path.write_text("\n".join(header) + "\n\n" + sql.strip() + "\n", encoding="utf-8")

    print(f"STAGED (not executed): {rel}")
    print(f"run with: {run_cmd}")
    return 0


def execute(sql: str, connection_override: str | None = None) -> int:
    if not sql.strip():
        die("empty query.")
    enforce_read_only(sql)

    if connection_override:
        # Bootstrap mode: no context file yet, so search for .env from CWD.
        connection = connection_override
        env_file = find_env_file(Path.cwd())
    else:
        context = find_context()
        connection = read_connection(context)
        project_env = context.parent.parent / ".env"
        env_file = project_env if project_env.is_file() else None

    cmd = ["snow", "sql", "-q", sql, "--connection", connection, "--format", "JSON"]
    try:
        result = subprocess.run(cmd, env=snow_env(env_file), stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("BLOCKED: `snow` CLI not found on PATH.", file=sys.stderr)
        return BLOCK

    stderr = result.stderr.decode(errors="replace")
    if stderr:
        sys.stderr.write(stderr)
    if result.returncode != 0 and AUTH_ERROR_RE.search(stderr):
        env_note = (
            f"a .env was loaded from {env_file}" if env_file is not None
            else "no .env file was found"
        )
        print(
            "hint: this looks like a key-pair auth failure. If the connection "
            "uses an encrypted private key, put its passphrase in the project "
            "root .env (e.g. PRIVATE_KEY_PASSPHRASE=...) — snowman passes .env "
            f"to snow automatically. This run: {env_note}. If a .env was "
            "loaded and it still fails, the variable name is probably wrong "
            "for this connection.",
            file=sys.stderr,
        )
    return result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="snowman.py",
        description="Read-only Snowflake query wrapper; --stage writes DML/DDL "
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
    args = parser.parse_args(argv[1:])

    if args.stage:
        if not args.name:
            parser.error("--stage requires --name <purpose-slug>")
        if args.connection:
            parser.error("--connection is not valid with --stage")
        return stage(args.sql, args.name)
    if args.name:
        parser.error("--name is only valid with --stage")
    return execute(args.sql, connection_override=args.connection)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
