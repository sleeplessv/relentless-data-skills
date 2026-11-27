"""Tests for skills/dbt-runner/scripts/preflight.py.

Standard library only, like the script itself. Run from the repo root:

    python3 -m unittest discover -s tests -v

Package checks use throwaway projects, and the live connection command is stubbed. The
preflight's stdout format is asserted deliberately — agents parse it, so it
is an interface, not an implementation detail.
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
# The fixtures' git reads no global or system config, so a developer's signing program never starts.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
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
        "runner": "uv run dbt",
        "engine": "v2   # v1 | v2",
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
        self.assertEqual(data["engine"], "v2")  # inline comment stripped
        self.assertEqual(
            data["required_env_vars"], ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"]
        )

    def test_quoted_values_keep_hash(self):
        self.assertEqual(
            preflight.strip_inline_comment("'value # not comment'"),
            "value # not comment",
        )

    def test_inline_empty_list_is_a_list(self):
        # Regression for #47: `[]` was stored as the string "[]", and the
        # env check then demanded variables named `[` and `]`.
        data = preflight.parse_frontmatter(
            "---\nprofile: p\nrequired_env_vars: []\n---\nbody", "ctx"
        )
        self.assertEqual(data["required_env_vars"], [])
        status, _ = preflight.check_env_vars(data)
        self.assertEqual(status, preflight.SKIP)

    def test_inline_list_items(self):
        data = preflight.parse_frontmatter(
            "---\nrequired_env_vars: [A_VAR, 'B_VAR']  # two\n---\n", "ctx"
        )
        self.assertEqual(data["required_env_vars"], ["A_VAR", "B_VAR"])

    def test_quoted_brackets_stay_a_string(self):
        data = preflight.parse_frontmatter(
            "---\ntarget: \"[x]\"\n---\n", "ctx"
        )
        self.assertEqual(data["target"], "[x]")

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


class WorktreeContextTests(unittest.TestCase):
    """A worktree without the (gitignored) context file reads the main one."""

    def git(self, cwd, *args):
        subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                       env={**os.environ, **GIT_ENV})

    def make_repo(self, stack):
        main = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.git(main, "init", "-q")
        project = main / "dbt_project"
        project.mkdir()
        (project / ".gitignore").write_text(".dbt-runner/\n")
        self.git(main, "add", ".")
        self.git(main, "-c", "user.name=t", "-c", "user.email=t@t",
                 "commit", "-qm", "init")
        return main

    def test_worktree_falls_back_to_main_checkout(self):
        with contextlib.ExitStack() as stack:
            main = self.make_repo(stack)
            ctx_dir = main / "dbt_project" / ".dbt-runner"
            ctx_dir.mkdir()
            (ctx_dir / "context.md").write_text(context_md(), encoding="utf-8")
            wt = Path(stack.enter_context(tempfile.TemporaryDirectory())) / "wt"
            self.git(main, "worktree", "add", "-q", str(wt))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                data = preflight.load_context(wt / "dbt_project")
            self.assertEqual(data["profile"], "corp_dt")
            self.assertIn("main checkout", buf.getvalue())

    def test_no_context_anywhere_still_fails(self):
        with contextlib.ExitStack() as stack:
            main = self.make_repo(stack)
            with self.assertRaises(SystemExit) as caught:
                preflight.load_context(main / "dbt_project")
            self.assertIn("FAIL context", str(caught.exception))


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
            (Path(tmp) / "packages.yml").write_text("packages:\n  - local: ../dep")
            status, msg = preflight.check_packages(Path(tmp))
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("<runner> deps", msg)

    def test_missing_dbt_packages_names_context_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "packages.yml").write_text("packages:\n  - local: ../dep")
            status, msg = preflight.check_packages(Path(tmp), "uv run dbt")
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("`uv run dbt deps`", msg)

    def test_dependency_manifest_distinguishes_packages_from_mesh_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "dependencies.yml"
            for value, expected in [
                ("projects:\n  - name: upstream", preflight.SKIP),
                ("  projects:\n    - name: upstream\n      packages: [nested]", preflight.SKIP),
                ("packages: [ ] # no packages", preflight.SKIP),
                ("packages:  # installed by dbt deps\n- local: ../dep", preflight.FAIL),
                ("packages: [{local: ../dep}]", preflight.FAIL),
            ]:
                with self.subTest(value=value):
                    manifest.write_text(value)
                    status, _ = preflight.check_packages(root)
                    self.assertEqual(status, expected)

    def test_packages_install_path_is_relative_to_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dependencies.yml").write_text("packages:\n  - local: ../dep")
            (root / "dbt_project.yml").write_text(
                'packages-install-path: "vendor packages" # local install'
            )
            (root / "dbt_packages").mkdir()
            status, msg = preflight.check_packages(root)
            self.assertEqual(status, preflight.FAIL)
            self.assertIn("vendor packages", msg)
            (root / "vendor packages" / "dep").mkdir(parents=True)
            self.assertEqual(preflight.check_packages(root)[0], preflight.OK)

    def test_flow_root_mappings_require_manual_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dbt_packages" / "dep").mkdir(parents=True)
            for manifest, project, unknown in (
                ("{packages: [{local: ../dep}]}", "name: demo", "packages.yml"),
                ("packages: [{local: ../dep}]", "{packages-install-path: dbt_packages}", "dbt_project.yml"),
            ):
                with self.subTest(unknown=unknown):
                    (root / "packages.yml").write_text(manifest)
                    (root / "dbt_project.yml").write_text(project)
                    status, msg = preflight.check_packages(root)
                    self.assertEqual(status, preflight.SKIP)
                    self.assertIn(unknown, msg)
                    self.assertIn("before running dbt", msg)

    def test_known_dependency_missing_despite_unreadable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packages.yml").write_text("{packages: [{local: ../dep}]}")
            (root / "package-lock.yml").write_text("packages: [{local: ../dep}]")
            status, msg = preflight.check_packages(root)
            self.assertEqual(status, preflight.FAIL)
            self.assertIn("dbt_packages/ is missing", msg)

    def test_templated_package_directory_requires_manual_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packages.yml").write_text("packages: [{local: ../dep}]")
            (root / "dbt_project.yml").write_text(
                """packages-install-path: "{{ env_var('PACKAGE_DIR') }}" """
            )
            status, msg = preflight.check_packages(root)
            self.assertEqual(status, preflight.SKIP)
            self.assertIn("verify the resolved directory", msg)

    def test_lockfile_status_in_a_git_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                               env={**os.environ, **GIT_ENV})

            git("init", "-q")
            project = root / "analytics"
            (project / "dbt_packages").mkdir(parents=True)
            lock = project / "package-lock.yml"
            (project / "packages.yml").write_text("packages: [{local: ../dep}]")
            (root / lock.name).write_text("unrelated untracked lock")
            self.assertEqual(preflight.check_packages(project),
                             (preflight.OK, "dbt_packages/ present"))
            lock.write_text("packages: [{local: ../dep}]")
            git("add", "analytics/package-lock.yml")
            git("-c", "user.name=test", "-c", "user.email=test@example.org",
                "-c", "commit.gpgsign=false", "commit", "-qm", "Track project lock")
            self.assertEqual(preflight.check_packages(project),
                             (preflight.OK, "dbt_packages/ present and package-lock.yml clean"))

            (project / "packages.yml").write_text("{packages: [{local: ../dep}]}")
            lock.unlink()
            for staged in (False, True):
                with self.subTest(staged=staged):
                    if staged:
                        git("add", "-u")
                    status, msg = preflight.check_packages(project)
                    self.assertEqual(status, preflight.FAIL)
                    self.assertIn("package-lock.yml has uncommitted changes", msg)

    def test_dirty_lockfile_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package-lock.yml").write_text("packages:\n  - local: ../dep")
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

    def test_project_root_profiles_found_without_profiles_path(self):
        """A project that ships its own profiles.yml passes with no
        `profiles_path` in the context (dbt reads the cwd before ~/.dbt)."""
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            env = {k: v for k, v in os.environ.items() if k != "DBT_PROFILES_DIR"}
            with mock.patch.dict(os.environ, env, clear=True):
                status, msg = preflight.check_profile(
                    {"profile": "corp_dt", "target": "local"}, project.root
                )
        self.assertEqual(status, preflight.OK)
        self.assertIn(str(project.profiles), msg)

    def test_recorded_relative_profiles_path_uses_the_dbt_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "config with spaces"
            profile_dir.mkdir()
            (profile_dir / "profiles.yml").write_text(PROFILES_YML)
            ctx = {"profiles_path": "config with spaces/profiles.yml",
                   "profile": "corp_dt", "target": "local"}
            self.assertEqual(preflight.check_profile(ctx, root)[0], preflight.OK)

    def test_dbt_profiles_dir_beats_project_root(self):
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            other = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            (other / "profiles.yml").write_text(
                "other_profile:\n  target: dev\n  outputs:\n    dev:\n"
                "      type: snowflake\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"DBT_PROFILES_DIR": str(other)}):
                status, msg = preflight.check_profile(
                    {"profile": "corp_dt", "target": "local"}, project.root
                )
        self.assertEqual(status, preflight.FAIL)
        self.assertIn(str(other), msg)


CORE_1_8_VERSION = """\
Core:
  - installed: 1.8.7
  - latest:    2.0.1 - Update available!

Plugins:
  - snowflake: 1.8.4 - Up to date!
"""

FUSION_VERSION = "dbt-fusion 2.0.0-preview.205\n"


class RunnerCheckTests(unittest.TestCase):
    """`<runner> --version` is stubbed: the check must never run dbt."""

    CTX = {"runner": "uv run dbt", "engine": "v1", "engine_version": "1.8.7"}

    def _check(self, ctx=None, stdout="", **kwargs):
        if not kwargs:
            kwargs["return_value"] = types.SimpleNamespace(
                returncode=0, stdout=stdout, stderr=""
            )
        with mock.patch.object(subprocess, "run", **kwargs) as run:
            status, msg = preflight.check_runner(
                self.CTX if ctx is None else ctx, Path(".")
            )
        return status, msg, run

    def test_missing_runner_fails_without_running_dbt(self):
        status, msg, run = self._check(ctx={"engine": "v1"})
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("no `runner`", msg)
        self.assertIn("invocation rule 1", msg)
        run.assert_not_called()

    def test_unresolvable_runner_fails(self):
        status, msg, run = self._check(side_effect=FileNotFoundError())
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("`uv` not found", msg)
        self.assertEqual(run.call_args[0][0], ["uv", "run", "dbt", "--version"])
        self.assertIn("timeout", run.call_args[1])

    def test_matching_v1_install_ok(self):
        status, msg, _ = self._check(stdout=CORE_1_8_VERSION)
        self.assertEqual(status, preflight.OK)
        self.assertIn("v1 1.8.7", msg)

    def test_engine_mismatch_fails(self):
        # The #46 incident: bare `dbt` was dbt-fusion on a pinned v1 project.
        status, msg, _ = self._check(
            ctx=dict(self.CTX, runner="dbt"), stdout=FUSION_VERSION
        )
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("v2 2.0.0-preview.205", msg)
        self.assertIn("engine: v1", msg)

    def test_minor_version_mismatch_fails(self):
        status, msg, _ = self._check(
            ctx=dict(self.CTX, engine_version="1.9.0"), stdout=CORE_1_8_VERSION
        )
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("1.8.7", msg)
        self.assertIn("engine_version: 1.9.0", msg)

    def test_patch_and_prerelease_differences_ok(self):
        status, _, _ = self._check(
            ctx={"runner": "dbt", "engine": "v2", "engine_version": "2.0.0"},
            stdout=FUSION_VERSION,
        )
        self.assertEqual(status, preflight.OK)

    def test_nonzero_exit_fails(self):
        bad = types.SimpleNamespace(returncode=2, stdout="",
                                    stderr="boom\nsecond line\n")
        status, msg, _ = self._check(return_value=bad)
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("exited 2", msg)
        self.assertIn("boom second line", msg)
        self.assertNotIn("\n", msg)  # one output line per check

    def test_timeout_fails(self):
        status, msg, _ = self._check(
            side_effect=subprocess.TimeoutExpired("uv", preflight.RUNNER_TIMEOUT)
        )
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("timed out", msg)

    def test_unrecognised_output_fails_and_shows_it(self):
        status, msg, _ = self._check(stdout="something else entirely\n")
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("something else entirely", msg)

    def test_unbalanced_quote_fails_without_running_dbt(self):
        status, msg, run = self._check(ctx=dict(self.CTX, runner='uv run "dbt'))
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("quoting", msg)
        run.assert_not_called()

    def test_missing_engine_keys_fail(self):
        status, msg, _ = self._check(
            ctx={"runner": "uv run dbt"}, stdout=CORE_1_8_VERSION
        )
        self.assertEqual(status, preflight.FAIL)
        self.assertIn("engine", msg)
        self.assertIn("install.md", msg)

    def test_legacy_engine_values(self):
        cases = [
            ("fusion", "2.0.0", FUSION_VERSION, preflight.OK),
            ("fusion", "1.8.7", CORE_1_8_VERSION, preflight.FAIL),
            ("core", "1.8.7", CORE_1_8_VERSION, preflight.OK),
            ("core", "2.0.0", FUSION_VERSION, preflight.OK),  # Core v2 beta
        ]
        for engine, version, stdout, expected in cases:
            with self.subTest(engine=engine, stdout=stdout):
                ctx = dict(self.CTX, engine=engine, engine_version=version)
                status, _, _ = self._check(ctx=ctx, stdout=stdout)
                self.assertEqual(status, expected)


class MainOutputTests(unittest.TestCase):
    """The stdout format and exit codes are the agent-facing interface."""

    ENV = {
        "SNOWFLAKE_ACCOUNT": "acct",
        "SNOWFLAKE_USER": "user",
    }

    def setUp(self):
        version = types.SimpleNamespace(
            returncode=0, stdout=FUSION_VERSION, stderr=""
        )
        self.run = mock.Mock(return_value=version)
        real_run = subprocess.run

        def run(argv, **kwargs):
            if argv[0] == "git":
                return real_run(argv, **kwargs)
            return self.run(argv, **kwargs)

        self.enterContext(mock.patch.object(subprocess, "run", run))

    def test_all_green(self):
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            key = stack.enter_context(tempfile.NamedTemporaryFile(suffix=".p8"))
            env = dict(self.ENV, SNOWFLAKE_PRIVATE_KEY_PATH=key.name)
            stack.enter_context(mock.patch.dict(os.environ, env))
            code, out = run_main(project.root)
        self.assertEqual(code, 0)
        self.assertIn("PREFLIGHT OK", out)
        for check in ("env:", "key:", "packages:", "profile:", "runner:"):
            self.assertIn(check, out)
        self.assertIn("OK   runner: `uv run dbt --version` reports v2", out)

    def test_indented_dependency_uses_indented_root_install_path(self):
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            key = stack.enter_context(tempfile.NamedTemporaryFile(suffix=".p8"))
            stack.enter_context(mock.patch.dict(os.environ, dict(
                self.ENV, SNOWFLAKE_PRIVATE_KEY_PATH=key.name
            )))
            (project.root / "packages.yml").write_text(
                "---\n# local dependency\n  packages:\n    - local: ../dep\n"
            )
            (project.root / "dbt_project.yml").write_text(
                "  name: local\n  packages-install-path: vendor\n  version: '1.0'\n"
            )
            code, out = run_main(project.root)
            self.assertEqual(code, 1)
            self.assertIn("FAIL packages: vendor/ is missing", out)
            (project.root / "vendor").mkdir()
            code, out = run_main(project.root)
            self.assertEqual(code, 0)
            self.assertIn("OK   packages: vendor/ present", out)

    def test_runner_mismatch_fails_preflight(self):
        self.run.return_value = types.SimpleNamespace(
            returncode=0, stdout=CORE_1_8_VERSION, stderr=""
        )
        with contextlib.ExitStack() as stack:
            project = TempProject(stack)
            key = stack.enter_context(tempfile.NamedTemporaryFile(suffix=".p8"))
            env = dict(self.ENV, SNOWFLAKE_PRIVATE_KEY_PATH=key.name)
            stack.enter_context(mock.patch.dict(os.environ, env))
            code, out = run_main(project.root)
        self.assertEqual(code, 1)
        self.assertIn("FAIL runner:", out)
        self.assertIn("PREFLIGHT FAILED (1 of 5 checks)", out)

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
    CTX = {"target": "local", "runner": "uv run dbt"}

    def _run(self, ctx=None, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with mock.patch.object(subprocess, "run", **kwargs) as run:
                code = preflight.run_connect(ctx or self.CTX, Path("."))
        return code, buf.getvalue(), run

    def test_success_uses_context_runner(self):
        ok = types.SimpleNamespace(returncode=0)
        code, out, run = self._run(return_value=ok)
        self.assertEqual(code, 0)
        self.assertIn("OK connect", out)
        self.assertEqual(run.call_args[0][0],
                         ["uv", "run", "dbt", "debug", "--target", "local"])

    def test_connect_uses_context_profile_and_recorded_directory(self):
        ctx = dict(self.CTX, profile="analytics",
                   profiles_path="config with spaces/profiles.yml")
        _, _, run = self._run(ctx=ctx, return_value=types.SimpleNamespace(returncode=0))
        self.assertEqual(run.call_args.args[0], [
            "uv", "run", "dbt", "debug", "--target", "local", "--profile", "analytics",
            "--profiles-dir", str(Path("config with spaces").resolve()),
        ])

    def test_path_runner(self):
        ok = types.SimpleNamespace(returncode=0)
        _, _, run = self._run(
            ctx={"target": "local", "runner": ".venv/bin/dbt"},
            return_value=ok,
        )
        self.assertEqual(run.call_args[0][0],
                         [".venv/bin/dbt", "debug", "--target", "local"])

    def test_missing_runner_falls_back_to_bare_dbt_and_says_so(self):
        ok = types.SimpleNamespace(returncode=0)
        code, out, run = self._run(ctx={"target": "local"}, return_value=ok)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args[0][0],
                         ["dbt", "debug", "--target", "local"])
        self.assertIn("no `runner` in context", out)

    def test_dbt_debug_failure(self):
        bad = types.SimpleNamespace(returncode=2)
        code, out, _ = self._run(return_value=bad)
        self.assertEqual(code, 1)
        self.assertIn("failures.md", out)

    def test_unbalanced_quote_in_runner_fails_cleanly(self):
        code, out, run = self._run(
            ctx={"target": "local", "runner": 'uv run "dbt'},
        )
        self.assertEqual(code, 1)
        self.assertIn("FAIL connect: cannot parse runner", out)
        self.assertIn("quoting", out)
        run.assert_not_called()

    def test_missing_runner_binary(self):
        code, out, _ = self._run(side_effect=FileNotFoundError())
        self.assertEqual(code, 1)
        self.assertIn("`uv` not found", out)
        self.assertIn("runner", out)


if __name__ == "__main__":
    unittest.main()
