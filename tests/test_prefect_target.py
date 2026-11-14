"""Tests for skills/prefect/scripts/target.py.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_prefect_target -v

Prefect itself is never imported: the settings object is a stand-in with the
attributes the script reads, and main() runs against stub modules. The stdout
format is asserted deliberately, because agents read it. The central property
under test is that no secret value reaches the output.
"""
from __future__ import annotations

import contextlib
import io
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "prefect" / "scripts"))

import target  # noqa: E402

CLOUD = "https://api.prefect.cloud/api"
SECRETS = ("DUMMYPASS", "DUMMYQ", "DUMMYFRAG", "DUMMYKEY", "DUMMYAUTH", "DUMMYHDR")


class Secret:
    """Stand-in for pydantic's SecretStr that would leak if ever rendered."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value

    __repr__ = __str__


def settings(url=None, key=None, auth_string=None, headers=None, ephemeral=False):
    return SimpleNamespace(
        api=SimpleNamespace(url=url, key=key, auth_string=auth_string),
        cloud=SimpleNamespace(api_url=CLOUD),
        server=SimpleNamespace(ephemeral=SimpleNamespace(enabled=ephemeral)),
        client=SimpleNamespace(custom_headers=headers or {}),
    )


def render(lines) -> str:
    return "\n".join(f"{key}: {value}" for key, value in lines)


class RedactUrlTest(unittest.TestCase):
    def test_strips_credentials_query_and_fragment(self):
        shown, stripped = target.redact_url(
            "http://svc:DUMMYPASS@prefect.example:4200/api?token=DUMMYQ#DUMMYFRAG"
        )
        self.assertEqual(shown, "http://prefect.example:4200/api")
        self.assertEqual(stripped, ["credentials", "query", "fragment"])

    def test_clean_url_is_unchanged(self):
        shown, stripped = target.redact_url("https://prefect.example/api")
        self.assertEqual(shown, "https://prefect.example/api")
        self.assertEqual(stripped, [])

    def test_password_containing_at_sign_is_stripped_whole(self):
        shown, _ = target.redact_url("http://svc:DUMMY@PASS@prefect.example/api")
        self.assertEqual(shown, "http://prefect.example/api")

    def test_url_without_scheme_is_withheld(self):
        shown, stripped = target.redact_url("svc:DUMMYPASS@prefect.example/api")
        self.assertNotIn("DUMMYPASS", shown)
        self.assertEqual(stripped, ["value"])


class TargetKindTest(unittest.TestCase):
    def test_kinds(self):
        cases = [
            (CLOUD + "/accounts/a/workspaces/w", False, "cloud"),
            ("http://prefect.example:4200/api", False, "server"),
            (None, True, "ephemeral"),
            (None, False, "none"),
        ]
        for url, ephemeral, expected in cases:
            with self.subTest(url=url, ephemeral=ephemeral):
                self.assertEqual(target.target_kind(url, CLOUD, ephemeral), expected)


class SummarizeTest(unittest.TestCase):
    def test_no_secret_value_reaches_the_output(self):
        resolved = settings(
            url="http://svc:DUMMYPASS@prefect.example:4200/api?token=DUMMYQ#DUMMYFRAG",
            key=Secret("pnu_DUMMYKEY"),
            auth_string=Secret("admin:DUMMYAUTH"),
            headers={"X-Proxy-Authorization": "Bearer DUMMYHDR"},
        )
        with mock.patch.dict("os.environ", {"PREFECT_API_KEY": "pnu_DUMMYKEY"}, clear=True):
            out = render(target.summarize(resolved, "staging", "3.9.3"))
        for secret in SECRETS:
            self.assertNotIn(secret, out)
        self.assertIn("api_url: http://prefect.example:4200/api", out)
        self.assertIn("api_url_stripped: credentials, query, fragment", out)
        self.assertIn("api_key: set, env PREFECT_API_KEY", out)
        self.assertIn(f"auth_string: set, {target.NOT_ENV}", out)
        self.assertIn("names: X-Proxy-Authorization", out)

    def test_api_key_against_a_server_gets_the_401_note(self):
        resolved = settings(url="http://prefect.example:4200/api", key=Secret("pnu_DUMMYKEY"))
        out = render(target.summarize(resolved, "staging", "3.9.3"))
        self.assertIn("target: server", out)
        self.assertIn("HTTP 401", out)

    def test_api_key_against_cloud_gets_no_note(self):
        resolved = settings(url=CLOUD + "/accounts/a/workspaces/w", key=Secret("pnu_DUMMYKEY"))
        out = render(target.summarize(resolved, "default", "3.9.3"))
        self.assertIn("target: cloud", out)
        self.assertNotIn("note:", out)

    def test_unset_url_with_ephemeral_mode_warns_about_remote_evidence(self):
        out = render(target.summarize(settings(ephemeral=True), None, "3.9.3"))
        self.assertIn("profile: unknown", out)
        self.assertIn("api_url: unset", out)
        self.assertIn("target: ephemeral", out)
        self.assertIn("no evidence about a remote instance", out)

    def test_unset_url_without_ephemeral_mode_has_no_target(self):
        out = render(target.summarize(settings(), "default", "3.9.3"))
        self.assertIn("target: none", out)
        self.assertIn("auth_string: unset", out)
        self.assertIn("custom_headers: unset", out)


class MainTest(unittest.TestCase):
    def run_main(self, modules):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(sys.modules, modules), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = target.main()
        return code, out.getvalue(), err.getvalue()

    def stub_modules(self, resolved):
        prefect = types.ModuleType("prefect")
        prefect.__version__ = "3.9.3"
        prefect_settings = types.ModuleType("prefect.settings")
        prefect_settings.get_current_settings = lambda: resolved
        prefect_context = types.ModuleType("prefect.context")
        prefect_context.get_settings_context = lambda: SimpleNamespace(
            profile=SimpleNamespace(name="staging")
        )
        return {
            "prefect": prefect,
            "prefect.settings": prefect_settings,
            "prefect.context": prefect_context,
        }

    def test_prints_key_value_lines_and_exits_zero(self):
        code, out, err = self.run_main(self.stub_modules(settings(ephemeral=True)))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out.splitlines()[:2], ["prefect_version: 3.9.3", "profile: staging"])

    def test_missing_prefect_exits_two_and_names_the_fix(self):
        code, out, err = self.run_main({"prefect": None})
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("project's Python", err)

    def test_unrecognized_settings_layout_exits_three(self):
        code, out, err = self.run_main(self.stub_modules(SimpleNamespace()))
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("not recognized", err)


if __name__ == "__main__":
    unittest.main()
