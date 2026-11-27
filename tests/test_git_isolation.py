"""The git fixtures of the test suite never start a signing program named in the caller's git config.

Each case gives the caller a git config that turns signing on and names a signing program that records each call:
in `$HOME/.gitconfig`, in a file named by `GIT_CONFIG_GLOBAL`, or in a system file named by `GIT_CONFIG_SYSTEM`. A
plain `git commit` under that environment starts the program, which shows the config is read. The fixtures of the
judge, statusline and dbt-runner tests then build their repos under the same environment, and the program is never
started. Run from the repo root:

    python3 -m unittest tests.test_git_isolation -v
"""
from __future__ import annotations

import contextlib
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SIGNING = {  # the two signing programs a git config can name
    "gpg.ssh.program": "[gpg]\n\tformat = ssh\n[gpg \"ssh\"]\n\tprogram = {program}\n[user]\n\tsigningkey = {key}\n",
    "gpg.program": "[gpg]\n\tformat = openpgp\n\tprogram = {program}\n",
}


def fixtures(stack: contextlib.ExitStack) -> dict:
    """Each test file's git fixture, as a call that builds its repo and commits."""
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
        stack.callback(sys.path.remove, str(TESTS))
    judge, statusline, dbt_runner = (importlib.import_module(name)
                                     for name in ("test_judge", "test_statusline", "test_dbt_runner"))

    def status() -> None:
        case = statusline.StatuslineTest()
        stack.callback(case.doCleanups)
        case.setUp()
        case.render("main", [])
        (case.repo / "a.txt").write_text("a\n")
        case.commit_all()

    return {
        "judge": lambda: judge.World(Path(stack.enter_context(tempfile.TemporaryDirectory()))),
        "statusline": status,
        "dbt-runner": lambda: dbt_runner.WorktreeContextTests().make_repo(stack),
    }


class GitIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.calls = self.root / "calls"
        self.program = self.root / "sign"
        self.program.write_text(f'#!/bin/sh\necho "$*" >>"{self.calls}"\nexit 1\n')
        self.program.chmod(0o755)
        (self.root / "key.pub").write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHRlc3Q= test\n")

    def caller(self, setting: str, source: str) -> dict:
        """The caller's environment: an empty home of its own, with signing turned on in `source`'s config only."""
        case = self.root / f"{setting}-{source}"
        (case / "home").mkdir(parents=True)
        config = ("[commit]\n\tgpgsign = true\n[tag]\n\tgpgsign = true\n"
                  + SIGNING[setting].format(program=self.program, key=self.root / "key.pub"))
        path = {"home": case / "home" / ".gitconfig", "GIT_CONFIG_GLOBAL": case / "global",
                "GIT_CONFIG_SYSTEM": case / "system"}[source]
        path.write_text(config)
        env = {key: value for key, value in os.environ.items()
               if key not in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_SYSTEM", "XDG_CONFIG_HOME")}
        env["HOME"] = str(case / "home")
        env["GIT_CONFIG_SYSTEM"] = os.devnull  # no machine settings: only the case's own config reaches git
        if source != "home":
            env[source] = str(path)
        return env

    def signed(self) -> list[str]:
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        self.calls.unlink(missing_ok=True)
        return calls

    def test_no_fixture_starts_the_signing_program_the_caller_names(self) -> None:
        for setting in SIGNING:
            for source in ("home", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
                with self.subTest(setting=setting, source=source), \
                        mock.patch.dict(os.environ, self.caller(setting, source), clear=True):
                    repo = self.root / f"{setting}-{source}" / "control"
                    subprocess.run(["git", "init", "-q", str(repo)], check=True)
                    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit",
                                    "-q", "--allow-empty", "-m", "control"], capture_output=True)
                    self.assertTrue(self.signed(), "a plain git commit did not start the signing program, so this "
                                                   "case proves nothing")
                    with contextlib.ExitStack() as stack:
                        for name, build in fixtures(stack).items():
                            with self.subTest(fixture=name):
                                try:
                                    build()
                                except subprocess.CalledProcessError as error:
                                    self.assertFalse(self.signed(), f"{error}: {error.stderr}")
                                    raise
                                self.assertEqual(self.signed(), [])


if __name__ == "__main__":
    unittest.main()
