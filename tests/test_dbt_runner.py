"""Tests for skills/dbt-runner/scripts/preflight.py.

Standard library only, like the script itself. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here ever talks to a warehouse: the git call in the packages check
and the `dbt debug` call behind --connect are mocked/stubbed. The preflight's
stdout format is asserted deliberately — agents parse it, so it is an
interface, not an implementation detail.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "dbt-runner" / "scripts"))

import preflight  # noqa: E402


PROFILES_YML = """\
corp_dt:
  target: local
  outputs:
    local:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      private_key_path: "{{ env_var('SNOWFLAKE_PRIVATE_KEY_PATH') }}"
    prd:
      type: snowflake

other_profile:
  target: dev
  outputs:
    dev:
      type: snowflake
"""


def context_md(**overrides) -> str:
    """Render a context file; keyword args override frontmatter lines."""
    fm = {
        "profile": "corp_dt",
        "target": "local",
        "engine": "fusion   # fusion | core",
        "engine_version": "2.0.0",
        "private_key_path_var": "SNOWFLAKE_PRIVATE_KEY_PATH",
    }
    fm.update(overrides)
    lines = ["---"]
    for key, value in fm.items():
        if value is None:
            continue
        lines.append(f"{key}: {value}")
    lines += [
        "required_env_vars:",
        "  - SNOWFLAKE_ACCOUNT",
        "  - SNOWFLAKE_USER",
        "---",
        "",
        "# dbt context for test project",
    ]
    return "\n".join(lines)


class TempProject:
    """A throwaway dbt project root with a context file and profiles.yml."""

    def __init__(self, stack: contextlib.ExitStack, context_text=None,
                 profiles_text=PROFILES_YML):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.profiles = self.root / "profiles.yml"
        self.profiles.write_text(profiles_text, encoding="utf-8")
        if context_text is None:
            context_text = context_md(
                profiles_path=str(self.profiles)
            )
        context_dir = self.root / ".dbt-runner"
        context_dir.mkdir()
        (context_dir / "context.md").write_text(context_text, encoding="utf-8")


def run_main(project_root: Path, *extra_args) -> "tuple[int, str]":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = preflight.main(["--project-root", str(project_root),
                                   *extra_args])
        except SystemExit as exc:  # load_context failures raise
            print(exc)
            code = 1
    return code, buf.getvalue()


class FrontmatterTests(unittest.TestCase):
    def test_scalars_lists_and_inline_comments(self):
        data = preflight.parse_frontmatter(context_md(), "ctx")
        self.assertEqual(data["profile"], "corp_dt")
        self.assertEqual(data["engine"], "fusion")  # inline comment stripped
        self.assertEqual(
            data["required_env_vars"], ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"]
        )

    def test_quoted_values_keep_hash(self):
        self.assertEqual(
            preflight.strip_inline_comment("'value # not comment'"),
            "value # not comment",
        )

    def test_missing_frontmatter_rejected(self):
        with self.assertRaises(SystemExit):
            preflight.parse_frontmatter("# no frontmatter here", "ctx")


class EnvCheckTests(unittest.TestCase):
    def test_all_set(self):
        ctx = {"required_env_vars": ["A_VAR", "B_VAR"]}
        with mock.patch.dict(os.environ, {"A_VAR": "x", "B_VAR": "y"}):
            status, msg = preflight.check_env_vars(ctx)
        self.assertEqual(status, preflight.OK)

    def test_missing_and_empty_fail_by_name_only(self):
        ctx = {"required_env_vars": ["A_VAR", "B_VAR"]}
        with mock.patch.dict(os.environ, {"A_VAR": "supersecret", "B_VAR": " "},
                             clear=False):
            status, msg = preflight.check_env_vars(ctx)
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("B_VAR", msg)
        self.assertNotIn("A_VAR,", msg)
        self.assertNotIn("supersecret", msg)  # values are never echoed

    def test_no_list_skips(self):
        status, _ = preflight.check_env_vars({})
        self.assertEqual(status, preflight.SKIP)


class PrivateKeyCheckTests(unittest.TestCase):
    def test_existing_key_ok(self):
        with tempfile.NamedTemporaryFile(suffix=".p8") as key:
            ctx = {"private_key_path_var": "KEY_VAR"}
            with mock.patch.dict(os.environ, {"KEY_VAR": key.name}):
                status, _ = preflight.check_private_key(ctx)
        self.assertEqual(status, preflight.OK)

    def test_missing_file_fails(self):
        ctx = {"private_key_path_var": "KEY_VAR"}
        with mock.patch.dict(os.environ, {"KEY_VAR": "/nonexistent/rsa.p8"}):
            status, msg = preflight.check_private_key(ctx)
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("does not exist", msg)

    def test_unset_var_and_unconfigured_skip(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            status, _ = preflight.check_private_key(
                {"private_key_path_var": "KEY_VAR"}
            )
        self.assertEqual(status, preflight.SKIP)
        status, _ = preflight.check_private_key({})
        self.assertEqual(status, preflight.SKIP)


class PackagesCheckTests(unittest.TestCase):
    def test_no_manifest_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, _ = preflight.check_packages(Path(tmp))
        self.assertEqual(status, preflight.SKIP)

    def test_manifest_without_dbt_packages_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "packages.yml").write_text("packages: []")
            status, msg = preflight.check_packages(Path(tmp))
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("dbt deps", msg)

    def test_clean_lockfile_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package-lock.yml").write_text("packages: []")
            (root / "dbt_packages").mkdir()
            clean = types.SimpleNamespace(returncode=0, stdout=b"")
            with mock.patch.object(subprocess, "run", return_value=clean):
                status, _ = preflight.check_packages(root)
        self.assertEqual(status, preflight.OK)

    def test_dirty_lockfile_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package-lock.yml").write_text("packages: []")
            (root / "dbt_packages").mkdir()
            dirty = types.SimpleNamespace(
                returncode=0, stdout=b" M package-lock.yml\n"
            )
            with mock.patch.object(subprocess, "run", return_value=dirty):
                status, msg = preflight.check_packages(root)
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("uncommitted", msg)


class ProfileCheckTests(unittest.TestCase):
    def _check(self, **overrides):
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            ctx = {
                "profile": "corp_dt",
                "target": "local",
                "profiles_path": str(project.profiles),
            }
            ctx.update(overrides)
            return preflight.check_profile(ctx)

    def test_profile_and_target_found(self):
        status, msg = self._check()
        self.assertEqual(status, preflight.OK)
        self.assertIn("corp_dt", msg)

    def test_second_output_found(self):
        status, _ = self._check(target="prd")
        self.assertEqual(status, preflight.OK)

    def test_unknown_target_lists_real_ones(self):
        status, msg = self._check(target="staging")
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("local", msg)
        self.assertIn("prd", msg)

    def test_unknown_profile_fails(self):
        status, msg = self._check(profile="nope")
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("not found", msg)

    def test_missing_profiles_file_fails(self):
        status, msg = self._check(profiles_path="/nonexistent/profiles.yml")
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("profiles.yml", msg)


class MainOutputTests(unittest.TestCase):
    """The stdout format and exit codes are the agent-facing interface."""

    ENV = {
        "SNOWFLAKE_ACCOUNT": "acct",
        "SNOWFLAKE_USER": "user",
    }

    def test_all_green(self):
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            key = stack.enter_context(tempfile.NamedTemporaryFile(suffix=".p8"))
            env = dict(self.ENV, SNOWFLAKE_PRIVATE_KEY_PATH=key.name)
            stack.enter_context(mock.patch.dict(os.environ, env))
            code, out = run_main(project.root)
        self.assertEqual(code, 0)
        self.assertIn("PREFLIGHT OK", out)
        for check in ("env:", "key:", "packages:", "profile:"):
            self.assertIn(check, out)

    def test_failure_is_nonzero_and_named(self):
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            stack.enter_context(
                mock.patch.dict(os.environ, self.ENV, clear=True)
            )
            os.environ.pop("SNOWFLAKE_USER")
            code, out = run_main(project.root)
        self.assertEqual(code, 1)
        self.assertIn("PREFLIGHT FAILED", out)
        self.assertIn("FAIL env:", out)
        self.assertIn("SNOWFLAKE_USER", out)

    def test_secret_values_never_in_output(self):
        passphrase = "hunter2-passphrase-value"
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            env = dict(self.ENV,
                       SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=passphrase)
            stack.enter_context(mock.patch.dict(os.environ, env))
            code, out = run_main(project.root)
        self.assertNotIn(passphrase, out)
        self.assertNotIn("acct", out.replace("PREFLIGHT", ""))

    def test_missing_context_points_at_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run_main(Path(tmp))
        self.assertEqual(code, 1)
        self.assertIn("install.md", out)


class ConnectTests(unittest.TestCase):
    CTX = {"target": "local"}

    def _run(self, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with mock.patch.object(subprocess, "run", **kwargs) as run:
                code = preflight.run_connect(self.CTX, Path("."))
        return code, buf.getvalue(), run

    def test_success(self):
        ok = types.SimpleNamespace(returncode=0)
        code, out, run = self._run(return_value=ok)
        self.assertEqual(code, 0)
        self.assertIn("OK connect", out)
        self.assertEqual(run.call_args[0][0],
                         ["dbt", "debug", "--target", "local"])

    def test_dbt_debug_failure(self):
        bad = types.SimpleNamespace(returncode=2)
        code, out, _ = self._run(return_value=bad)
        self.assertEqual(code, 1)
        self.assertIn("failures.md", out)

    def test_missing_dbt_binary(self):
        code, out, _ = self._run(side_effect=FileNotFoundError())
        self.assertEqual(code, 1)
        self.assertIn("not found", out)


if __name__ == "__main__":
    unittest.main()
