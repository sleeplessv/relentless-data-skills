"""Preflight's checks that do not depend on the harness (#420).

`Order` reads `preflight.CHECKS` in process and pins the order of the checks. Each test in
`Checks` runs `deliver.py preflight` at its command line in one shared throwaway world with a run
mark, a stand-in `gh` and, where a check reads them, its own git config, stack settings and
stand-ins, and asserts the whole output and the exit code.

    python3 -m unittest tests.test_deliver_checks_env
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

preflight = deliver_kit.load("preflight")
checks_env = preflight.checks_env

CLEAN = "Preflight passed.\n"
STACK = 'check_command = "make check"\n'
RERUN = ", then run deliver.py preflight"
SIGN_TEST = "git commit-tree -S -m test 4b825dc642cb6eb9a060e54bf8d69288fbee4904"
GOOD_GPG = """\
#!/bin/sh
cat >/dev/null
echo "[GNUPG:] SIG_CREATED D 1 8 00 1 X" >&2
printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nAA==\\n-----END PGP SIGNATURE-----\\n'
"""
BAD_GPG = '#!/bin/sh\necho "gpg: signing failed: No secret key" >&2\nexit 2\n'
NO_COUNT = "it printed no count"


def repo_view(repo="owner/repo", branch="main", permission="ADMIN", issues=True) -> str:
    return json.dumps({"nameWithOwner": repo, "defaultBranchRef": {"name": branch},
                       "viewerPermission": permission, "hasIssuesEnabled": issues})


class Order(unittest.TestCase):
    def test_harness_then_git_and_gh_then_the_repos_commands(self):
        order = [preflight.check_settings, preflight.check_guard.check_guard_probe, checks_env.check_python,
                 checks_env.check_writable, checks_env.check_signing, checks_env.check_gh_signed_in, checks_env.check_github,
                 checks_env.check_push, checks_env.check_issues, checks_env.check_branch_rules,
                 checks_env.check_check_command, checks_env.check_reach, checks_env.check_dependents]
        places = [preflight.CHECKS.index(check) for check in order]
        self.assertEqual(places, sorted(places))


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)
        cls.common = Path(cls.world.git(cls.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        cls.tools = cls.world.root / "tools"
        cls.tools.mkdir()
        calls = cls.world.root / "count-calls"
        counter = f'#!/bin/sh\n[ $# -ge 1 ] || exit 64\nprintf "%s\\n" "$*" >> {calls}\necho 3\n'
        for name, text in (("good-gpg", GOOD_GPG), ("bad-gpg", BAD_GPG), ("count", counter)):
            (cls.tools / name).write_text(text, encoding="utf-8")
            (cls.tools / name).chmod(0o755)

    def setUp(self):
        self.world.write_mark(run="run-9")
        self.world.probe()
        deliver_kit.reset_gh(self.world)
        self.stack(STACK)
        for key in ("commit.gpgsign", "gpg.program"):
            subprocess.run(["git", "config", "--unset-all", key], cwd=self.world.work, env=self.world.base_env)

    def stack(self, text: str) -> None:
        path = self.world.work / "docs" / "agents" / "stack.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def preflight(self, **env: str | None) -> tuple[int, str, str]:
        deliver_kit.github_ok(self.world)
        result = self.world.deliver("preflight", **env)
        return result.returncode, result.stdout, result.stderr

    def refused(self, code: str, reason: str, next_command: str) -> tuple[int, str, str]:
        return 10, f"REFUSED {code}: {reason}\nNext: {next_command}{RERUN}\n", ""

    def path_with(self, **tools: str | Path) -> str:
        """A PATH holding git, the stand-in gh and the named tools: a file's text, a link's target, or None for none."""
        folder = self.world.root / f"path-{self.id().rsplit('.', 1)[-1]}"
        folder.mkdir()
        for name, target in {"git": shutil.which("git"), "gh": self.world.bin / "gh", **tools}.items():
            if target is None:
                continue
            if isinstance(target, str) and target.startswith("#!"):
                (folder / name).write_text(target, encoding="utf-8")
                (folder / name).chmod(0o755)
            else:
                (folder / name).symlink_to(target)
        return str(folder)

    def test_clean_world_passes_with_one_line(self):
        self.assertEqual(self.preflight(), (0, CLEAN, ""))

    # Python: uv, or a python3 of 3.13 or newer.

    def test_uv_alone_passes(self):
        path = self.path_with(uv="#!/bin/sh\nexit 0\n", python3="#!/bin/sh\nexit 1\n")
        self.assertEqual(self.preflight(PATH=path), (0, CLEAN, ""))

    def test_python3_of_3_13_alone_passes(self):
        self.assertEqual(self.preflight(PATH=self.path_with(python3=sys.executable)), (0, CLEAN, ""))

    def test_preflight_no_python(self):
        self.assertEqual(self.preflight(PATH=self.path_with(python3="#!/bin/sh\nexit 1\n")), self.refused(
            "preflight.no-python", "this machine has neither uv nor a python3 of 3.13 or newer",
            "curl -LsSf https://astral.sh/uv/install.sh | sh"))

    # Writes: the branch's records folder and the machine directory.

    def test_preflight_cannot_write(self):
        self.world.write_mark(run="run-9", branch="blocked")
        blocked = self.common / "deliver" / "branches" / "blocked"
        blocked.parent.mkdir(parents=True, exist_ok=True)
        blocked.write_text("a file where the folder goes\n", encoding="utf-8")
        self.addCleanup(blocked.unlink)
        self.assertEqual(self.preflight(), self.refused(
            "preflight.cannot-write", f"the run cannot write {blocked}: File exists",
            f"move or delete the file {blocked}, which sits where a folder is needed"))
        self.assertEqual(self.world.state_lines("preflight-stops.jsonl")[-1]["code"], "preflight.cannot-write")

    def test_preflight_cannot_write_the_machine_directory(self):
        state = self.world.root / "read-only-state"
        state.mkdir()
        shutil.copy(self.world.state / "guard-refusals.jsonl", state)
        state.chmod(0o555)
        self.addCleanup(state.chmod, 0o755)
        self.assertEqual(self.preflight(DELIVER_STATE_DIR=str(state)), self.refused(
            "preflight.cannot-write", f"the run cannot write {state}: Permission denied",
            f"`chmod u+w {state}`, or set DELIVER_STATE_DIR to a folder you can write"))
        self.assertEqual([r["stops"] for r in self.world.records()][-1:], [["preflight.cannot-write"]])

    # Signing: a test signature where git signs commits.

    def sign_with(self, program: str) -> None:
        self.world.git(self.world.work, "config", "commit.gpgsign", "true")
        self.world.git(self.world.work, "config", "gpg.program", str(self.tools / program))

    def test_signing_that_works_passes(self):
        self.sign_with("good-gpg")
        self.assertEqual(self.preflight(), (0, CLEAN, ""))

    def test_preflight_no_signature(self):
        self.sign_with("bad-gpg")
        self.assertEqual(self.preflight(), self.refused(
            "preflight.no-signature", "git signs commits here, and a test signature failed: "
            "gpg: signing failed: No secret key", f"fix signing until `{SIGN_TEST}` works here"))

    # gh and GitHub.

    def test_preflight_gh_signed_out(self):
        self.world.gh_answer(["auth", "token"], stderr="no oauth token\n", exit=1)
        self.assertEqual(self.preflight(), self.refused(
            "preflight.gh-signed-out", "gh is not signed in to GitHub", "gh auth login"))

    def test_preflight_no_gh(self):
        path = self.path_with(gh=None, python3=sys.executable)
        self.assertEqual(self.preflight(PATH=path), self.refused(
            "preflight.no-gh", "gh cannot be started: No such file or directory", "install gh from https://cli.github.com"))

    def test_preflight_no_github(self):
        self.world.gh_answer(["repo", "view"], stderr="error connecting to api.github.com\n", exit=1)
        self.assertEqual(self.preflight(), self.refused(
            "preflight.no-github", "gh cannot read this repo from GitHub: error connecting to api.github.com",
            "`gh repo set-default` to name this checkout's GitHub repo, or `gh auth status` if gh cannot reach GitHub"))

    def test_preflight_cannot_push(self):
        self.world.gh_answer(["repo", "view"], stdout=repo_view(permission="READ"))
        self.assertEqual(self.preflight(), self.refused(
            "preflight.cannot-push", "the gh account cannot push to owner/repo: its permission is READ",
            "`gh auth login` as an account that can push to owner/repo"))

    def test_write_permission_passes(self):
        self.world.gh_answer(["repo", "view"], stdout=repo_view(permission="WRITE"))
        self.assertEqual(self.preflight(), (0, CLEAN, ""))

    def test_issues_off_with_follow_ups_on_warns(self):
        self.world.gh_answer(["repo", "view"], stdout=repo_view(issues=False))
        self.assertEqual(self.preflight(), (
            0, 'warning: issues are off on owner/repo, so each follow-up is listed as "follow-up not filed": turn issues '
            "on in the repo's settings, or set follow_ups = false in docs/agents/stack.toml\n" + CLEAN, ""))

    def test_issues_off_with_follow_ups_off_passes(self):
        self.stack(STACK + "follow_ups = false\n")
        self.world.gh_answer(["repo", "view"], stdout=repo_view(issues=False))
        self.assertEqual(self.preflight(), (0, CLEAN, ""))

    # Branch rules of the default branch.

    def rules(self, stdout: str = "", exit: int = 0) -> tuple[int, str, str]:
        self.world.gh_answer(["repo", "view"], stdout=repo_view(repo="acme/widgets", branch="trunk"))
        self.world.gh_answer(["api"], stdout=stdout, exit=exit)
        result = self.preflight()
        api = [call["args"] for call in self.world.gh_calls() if call["args"][:1] == ["api"]]
        self.assertEqual(api, [["api", "repos/acme/widgets/rules/branches/trunk"]])
        return result

    def test_a_required_approval_warns_that_the_run_ends_at_ready(self):
        rules = [{"type": "required_status_checks", "parameters": {}},
                 {"type": "pull_request", "parameters": {"required_approving_review_count": 1}}]
        self.assertEqual(self.rules(json.dumps(rules)), (
            0, "warning: trunk needs an approving review the agent cannot give: run will end at ready\n" + CLEAN, ""))

    def test_rules_with_no_required_approval_pass(self):
        rules = [{"type": "pull_request", "parameters": {"required_approving_review_count": 0}}]
        self.assertEqual(self.rules(json.dumps(rules)), (0, CLEAN, ""))

    def test_unreadable_rules_go_ahead(self):
        for stdout, exit in (('{"message": "Not Found"}', 1), ("", 1), ("<html>", 0), ('{"message": "x"}', 0),
                             ('[{"type": "pull_request"}]', 0)):
            with self.subTest(stdout=stdout, exit=exit):
                deliver_kit.reset_gh(self.world)
                self.assertEqual(self.rules(stdout, exit), (0, CLEAN, ""))

    # The repo's commands.

    def test_empty_check_command_warns(self):
        self.stack("")
        self.assertEqual(self.preflight(), (
            0, "warning: check_command is empty in docs/agents/stack.toml, so ready relies on the check plan's "
            "commands: set check_command there to the command that runs this repo's checks\n" + CLEAN, ""))

    def test_reach_commands_that_run_pass(self):
        ran = self.world.root / "reach-ran"
        self.addCleanup(lambda: ran.unlink(missing_ok=True))
        self.stack(STACK + f'[reach]\nread = "echo read >> {ran}"\nbuild = "echo build >> {ran}"\n')
        self.assertEqual(self.preflight(), (0, CLEAN, ""))
        self.assertEqual(ran.read_text(encoding="utf-8"), "read\nbuild\n")

    def test_preflight_reach_failed(self):
        self.stack(STACK + '[reach]\nread = "true"\nbuild = "echo no build >&2; exit 3"\n')
        self.assertEqual(self.preflight(), self.refused(
            "preflight.reach-failed", "the reach command build, `echo no build >&2; exit 3`, failed with exit 3: "
            "no build", "change [reach] build in docs/agents/stack.toml, or what it reaches, until "
            "`echo no build >&2; exit 3` exits 0"))

    def test_reach_command_without_sh_stops(self):
        self.stack(STACK + '[reach]\nread = "true"\n')
        self.assertEqual(self.preflight(PATH=self.path_with(python3=sys.executable)), self.refused(
            "preflight.reach-failed", "the reach command read, `true`, failed with exit 127: sh: No such file or directory",
            "change [reach] read in docs/agents/stack.toml, or what it reaches, until `true` exits 0"))

    def test_reach_output_that_is_not_utf_8_is_read_with_replacement(self):
        self.stack(STACK + "[reach]\nread = 'printf \"\\377\"'\nbuild = 'printf \"no \\377 build\" >&2; exit 3'\n")
        self.assertEqual(self.preflight(), self.refused(
            "preflight.reach-failed", "the reach command build, `printf \"no \\377 build\" >&2; exit 3`, failed with "
            "exit 3: no \ufffd build", "change [reach] build in docs/agents/stack.toml, or what it reaches, until "
            "`printf \"no \\377 build\" >&2; exit 3` exits 0"))

    # The dependents command, run as the small test runs it, on the world's one tracked path.

    def dependents(self, command: str) -> None:
        self.stack(STACK + f'[small_edit]\ndependents_command = "{command}"\n')

    def test_empty_dependents_command_runs_nothing_and_warns_nothing(self):
        """A `README.md` on PATH records a call: an empty command run on the path would start it."""
        calls = self.world.root / "readme-calls"
        path = self.path_with(**{"README.md": f'#!/bin/sh\necho ran >> {calls}\necho 3\n', "python3": sys.executable})
        self.assertEqual(self.preflight(PATH=f"{path}{os.pathsep}/bin"), (0, CLEAN, ""))
        self.assertFalse(calls.exists())

    def test_dependents_command_that_needs_a_path_passes(self):
        calls = self.world.root / "count-calls"
        self.addCleanup(lambda: calls.unlink(missing_ok=True))
        self.dependents(self.tools / "count")
        self.assertEqual(self.preflight(), (0, CLEAN, ""))
        self.assertEqual(calls.read_text(encoding="utf-8"), "README.md\n")

    def test_failing_dependents_command_warns(self):
        self.dependents(self.tools / "bad-gpg")
        self.assertEqual(self.preflight(), (
            0, f"warning: the dependents command `{self.tools / 'bad-gpg'} README.md` failed on the sample path "
            "README.md (exit 2), and a failure on a change's own paths sends that change to review: fix [small_edit] "
            "dependents_command in docs/agents/stack.toml until it prints a count first, or empty it\n" + CLEAN, ""))

    def test_dependents_command_that_prints_no_count_warns(self):
        self.dependents("true")
        self.assertEqual(self.preflight(), (
            0, f"warning: the dependents command `true README.md` failed on the sample path README.md ({NO_COUNT}), "
            "and a failure on a change's own paths sends that change to review: fix [small_edit] dependents_command "
            "in docs/agents/stack.toml until it prints a count first, or empty it\n" + CLEAN, ""))

if __name__ == "__main__":
    unittest.main()
