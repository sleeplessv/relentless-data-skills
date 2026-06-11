#!/usr/bin/env python3
"""dbt-runner preflight — static environment checks before the first dbt
command of a session.

Standard library only, Python 3.9+. The default run is fully static (no
network, sandbox-safe): it verifies the things that make dbt fail before any
model runs — env vars, the private key file, package state, and the
profile/target. `--connect` additionally shells out to `dbt debug` for a live
connection test (needs network — run with sandboxing disabled).

Reads required env-var names (names only, never values) from the per-project
`.dbt-runner/context.md`. Output is one line per check — `OK` / `FAIL` /
`SKIP` — and the exit code is 0 only when nothing FAILed. This output format
is an interface: agents parse it, so changes to it are breaking changes.

Usage:
    python3 preflight.py [--project-root DIR] [--connect]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

CONTEXT_RELPATH = Path(".dbt-runner") / "context.md"

OK = "OK"
FAIL = "FAIL"
SKIP = "SKIP"


# --------------------------------------------------------------------------
# Context file parsing
# --------------------------------------------------------------------------

def strip_inline_comment(value: str) -> str:
    """Drop a trailing ` # ...` YAML comment from an unquoted scalar."""
    value = value.strip()
    if value.startswith(("'", '"')):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
        return value.strip("'\"")
    hash_pos = value.find(" #")
    if hash_pos != -1:
        value = value[:hash_pos]
    return value.strip()


def parse_frontmatter(text: str, where: str) -> dict:
    """Parse the YAML frontmatter of the context file.

    Supports the two shapes the context file uses: top-level scalars
    (`key: value`) and one-level lists of scalars (`key:` followed by
    `- item` lines). Anything fancier is out of scope on purpose.
    """
    if not text.startswith("---"):
        raise SystemExit(
            f"{FAIL} context: {where} must open with a YAML frontmatter"
            " block (---). Re-run the bootstrap (references/install.md)."
        )
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SystemExit(
            f"{FAIL} context: frontmatter in {where} is not closed with ---."
        )
    data: dict = {}
    current_list = None
    for raw in parts[1].splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- ") and current_list is not None:
            data[current_list].append(strip_inline_comment(stripped[2:]))
            continue
        if ":" in stripped and not raw.startswith((" ", "\t")):
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = strip_inline_comment(value)
            if value:
                data[key] = value
                current_list = None
            else:
                data[key] = []
                current_list = key
    return data


def load_context(project_root: Path) -> dict:
    context_path = project_root / CONTEXT_RELPATH
    if not context_path.is_file():
        raise SystemExit(
            f"{FAIL} context: no {CONTEXT_RELPATH} found under {project_root}."
            " First run in this project — do the bootstrap in"
            " references/install.md, then re-run the preflight."
        )
    return parse_frontmatter(
        context_path.read_text(encoding="utf-8"), str(context_path)
    )


# --------------------------------------------------------------------------
# Checks — each returns (status, message)
# --------------------------------------------------------------------------

def check_env_vars(context: dict) -> tuple:
    required = context.get("required_env_vars", [])
    if not required:
        return SKIP, "no required_env_vars listed in context"
    missing = [v for v in required if not os.environ.get(v, "").strip()]
    if missing:
        return FAIL, (
            "missing or empty: " + ", ".join(missing)
            + ". Remedy: export them (the project .env or your shell"
            " profile usually sets these), then re-run. dbt's env_var()"
            " raises at parse time, so dbt cannot run until these are set."
        )
    return OK, f"all {len(required)} required env vars set and non-empty"


def check_private_key(context: dict) -> tuple:
    var = context.get("private_key_path_var", "")
    if not var:
        return SKIP, "no private_key_path_var in context (not key-pair auth)"
    path_value = os.environ.get(var, "").strip()
    if not path_value:
        return SKIP, f"{var} is unset — covered by the env check"
    key_path = Path(os.path.expanduser(path_value))
    if not key_path.is_file():
        return FAIL, (
            f"{var} points at {key_path}, which does not exist."
            " Remedy: fix the path or restore the key file; key-pair auth"
            " fails with a JWT/file-not-found error otherwise."
        )
    if not os.access(key_path, os.R_OK):
        return FAIL, (
            f"{var} points at {key_path}, which is not readable."
            " Remedy: fix file permissions."
        )
    return OK, f"private key file exists and is readable ({key_path})"


def check_packages(project_root: Path) -> tuple:
    has_manifest = (project_root / "packages.yml").is_file() or (
        project_root / "package-lock.yml"
    ).is_file()
    if not has_manifest:
        return SKIP, "project declares no dbt packages"
    if not (project_root / "dbt_packages").is_dir():
        return FAIL, (
            "dbt_packages/ is missing but the project declares packages."
            " Remedy: run `dbt deps` (every dbt_utils.* call fails until"
            " then)."
        )
    if (project_root / "package-lock.yml").is_file():
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--", "package-lock.yml"],
                cwd=str(project_root),
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return OK, "dbt_packages/ present (git state not checkable)"
        if result.returncode == 0 and result.stdout.strip():
            return FAIL, (
                "package-lock.yml has uncommitted changes — something"
                " (often a subagent running `dbt deps`) dirtied it."
                " Remedy: inspect with `git diff package-lock.yml`;"
                " revert unless the change was intentional."
            )
    return OK, "dbt_packages/ present and package-lock.yml clean"


def first_level_keys(lines: list, start: int, parent_indent: int) -> tuple:
    """Collect the first-level child keys of the block starting after
    ``lines[start]`` (whose own indent is ``parent_indent``).

    Returns (keys, next_index_after_block).
    """
    keys = []
    child_indent = None
    i = start + 1
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent <= parent_indent:
            break
        if child_indent is None:
            child_indent = indent
        if indent == child_indent and stripped.endswith(":"):
            keys.append(stripped[:-1].strip())
        i += 1
    return keys, i


def check_profile(context: dict) -> tuple:
    profile = context.get("profile", "")
    target = context.get("target", "")
    if not profile or not target:
        return FAIL, (
            "context file lacks profile/target keys. Remedy: re-run the"
            " bootstrap (references/install.md)."
        )
    profiles_path = Path(
        os.path.expanduser(
            context.get("profiles_path")
            or os.path.join(
                os.environ.get("DBT_PROFILES_DIR", "~/.dbt"), "profiles.yml"
            )
        )
    )
    if not profiles_path.is_file():
        return FAIL, (
            f"no profiles.yml at {profiles_path}. Remedy: dbt has no"
            " connection config on this machine — create the profile or"
            " set DBT_PROFILES_DIR."
        )
    lines = profiles_path.read_text(encoding="utf-8").splitlines()
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if raw.startswith((" ", "\t")) or stripped != f"{profile}:":
            continue
        profile_keys, _ = first_level_keys(lines, i, -1)
        for j in range(i + 1, len(lines)):
            inner = lines[j].strip()
            if inner == "outputs:" and lines[j].startswith((" ", "\t")):
                indent = len(lines[j]) - len(lines[j].lstrip())
                targets, _ = first_level_keys(lines, j, indent)
                if target in targets:
                    return OK, (
                        f"profile '{profile}' target '{target}' found in"
                        f" {profiles_path}"
                    )
                return FAIL, (
                    f"profile '{profile}' exists in {profiles_path} but has"
                    f" no target '{target}' (targets: {', '.join(targets)})."
                    " Remedy: fix the target in the context file or in"
                    " profiles.yml."
                )
            if not lines[j].startswith((" ", "\t")) and inner:
                break
        return FAIL, (
            f"profile '{profile}' in {profiles_path} has no outputs: block"
            f" (keys: {', '.join(profile_keys)})."
        )
    return FAIL, (
        f"profile '{profile}' not found in {profiles_path}. Remedy: the"
        " project's dbt_project.yml names a profile that this machine's"
        " profiles.yml doesn't define."
    )


# --------------------------------------------------------------------------
# Live connection test (--connect)
# --------------------------------------------------------------------------

def run_connect(context: dict, project_root: Path) -> int:
    target = context.get("target", "")
    cmd = ["dbt", "debug"]
    if target:
        cmd += ["--target", target]
    print(f"connect: running `{' '.join(cmd)}` (needs network — if this"
          " fails with a DNS/connection error, suspect a sandboxed shell"
          " before debugging auth)")
    try:
        result = subprocess.run(cmd, cwd=str(project_root), timeout=300)
    except FileNotFoundError:
        print(f"{FAIL} connect: `dbt` binary not found on PATH.")
        return 1
    except subprocess.TimeoutExpired:
        print(f"{FAIL} connect: `dbt debug` timed out after 300s —"
              " suspended warehouse or blocked network egress.")
        return 1
    if result.returncode != 0:
        print(f"{FAIL} connect: `dbt debug` exited {result.returncode} —"
              " see its output above and references/failures.md.")
        return 1
    print(f"{OK} connect: `dbt debug` succeeded")
    return 0


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", default=".",
        help="dbt project root holding .dbt-runner/context.md (default: cwd)",
    )
    parser.add_argument(
        "--connect", action="store_true",
        help="also run `dbt debug` for a live connection test (needs network)",
    )
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()

    context = load_context(project_root)

    checks = [
        ("env", check_env_vars(context)),
        ("key", check_private_key(context)),
        ("packages", check_packages(project_root)),
        ("profile", check_profile(context)),
    ]
    failed = 0
    for name, (status, message) in checks:
        print(f"{status:<4} {name}: {message}")
        if status == FAIL:
            failed += 1

    if failed:
        print(f"PREFLIGHT FAILED ({failed} of {len(checks)} checks) — fix"
              " the FAIL lines before running dbt.")
        return 1

    if args.connect:
        if run_connect(context, project_root) != 0:
            print("PREFLIGHT FAILED (connect)")
            return 1

    print("PREFLIGHT OK — safe to run dbt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
