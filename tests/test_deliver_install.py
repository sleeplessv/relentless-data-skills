"""`deliver.py install` and `install --remove` against a fake home folder, and preflight's install checks.

Every test runs deliver.py at its command line in a throwaway world (`tests/deliver_kit.py`), from a
copy of the skill, so the home folder, the checkout and the skill's own files are the world's.

    python3 -m unittest tests.test_deliver_install
"""
from __future__ import annotations

import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

HARNESS = deliver_kit.SCRIPTS.parent / "harness"
# The folder of each harness's files in the skill, named as its adapter is.
FOLDER = {"cortex-code": "cortex", "codex": "codex", "cursor": "cursor", "antigravity": "antigravity"}
READER = {"cortex-code": ".snowflake/cortex/agents/deliver-reader.md", "codex": ".codex/agents/deliver-reader.toml",
          "antigravity": ".gemini/config/agents/deliver-reader.md"}
HOOKS = {"cortex-code": ".snowflake/cortex/hooks.json", "codex": ".codex/hooks.json", "cursor": ".cursor/hooks.json",
         "antigravity": ".gemini/config/hooks.json"}
CURSOR_READER = ".cursor/agents/deliver-reader.md"
EXCLUDE_LINE = "/.cursor/agents/deliver-reader.md"


def tree(root: Path) -> dict[str, bytes | None]:
    """Every file and folder under root, a file with its bytes, a folder as None."""
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


class Install(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.skill = self.world.root / "skill"
        shutil.copytree(deliver_kit.SCRIPTS.parent, self.skill, ignore=shutil.ignore_patterns("__pycache__"))
        self.world.script = self.skill / "scripts" / "deliver.py"
        self.home = self.world.home
        self.home_before = tree(self.home)

    def install(self, *args: str, cwd: Path | None = None, **env: str | None) -> subprocess.CompletedProcess:
        return self.world.deliver("install", *args, cwd=cwd or self.world.root, **env)

    def registered(self, harness: str) -> str:
        """The command `install` registered in the harness's hook file."""
        data = json.loads((self.home / HOOKS[harness]).read_text())
        if harness == "cursor":
            return data["hooks"]["beforeShellExecution"][-1]["command"]
        group = data["deliver-guard"] if harness == "antigravity" else data["hooks"]
        return group["PreToolUse"][-1]["hooks"][0]["command"]

    def test_install_writes_the_reader_file_and_the_hook(self):
        for harness in ("cortex-code", "codex", "antigravity"):
            with self.subTest(harness):
                result = self.install(harness)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                suffix = ".toml" if harness == "codex" else ".md"
                self.assertEqual((self.home / READER[harness]).read_bytes(),
                                 (HARNESS / FOLDER[harness] / f"deliver-reader{suffix}").read_bytes())
                guard = shlex.quote(str(self.skill / "scripts" / "guard.py"))
                committed = (HARNESS / FOLDER[harness] / "hooks.json").read_text().replace("@GUARD@", guard)
                self.assertEqual(json.loads((self.home / HOOKS[harness]).read_text()), json.loads(committed))
                self.assertIn(f"deliver_guard={guard}; ", self.registered(harness))

    def test_a_second_run_writes_nothing_and_says_so(self):
        for harness in ("cortex-code", "codex", "cursor", "antigravity"):
            with self.subTest(harness):
                self.assertEqual(self.install(harness, cwd=self.world.work).returncode, 0)
                before = tree(self.world.root)
                result = self.install(harness, cwd=self.world.work)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f"nothing changed: deliver is already installed on {harness}.\n", ""))
                self.assertEqual(tree(self.world.root), before)

    def test_install_keeps_every_other_entry_and_file(self):
        other = {"type": "command", "command": "echo other"}
        files = {
            "cortex-code": {"hooks": {"PreToolUse": [{"matcher": "bash", "hooks": [other]}], "Stop": [{"hooks": [other]}]},
                       "theme": "dark"},
            "codex": {"hooks": {"PreToolUse": [{"matcher": "", "hooks": [other]}]}},
            "cursor": {"version": 1, "hooks": {"beforeShellExecution": [{"command": "echo other"}]}},
            "antigravity": {"mine": {"PreToolUse": [{"matcher": "", "hooks": [other]}]}},
        }
        for harness, data in files.items():
            with self.subTest(harness):
                (self.home / HOOKS[harness]).parent.mkdir(parents=True, exist_ok=True)
                (self.home / HOOKS[harness]).write_text(json.dumps(data, indent=2) + "\n")
                agents = (self.world.work / CURSOR_READER if harness == "cursor" else self.home / READER[harness]).parent
                agents.mkdir(parents=True, exist_ok=True)
                (agents / "mine.md").write_text("mine\n")
                self.assertEqual(self.install(harness, cwd=self.world.work).returncode, 0)
                merged = json.loads((self.home / HOOKS[harness]).read_text())
                ours = self.registered(harness)
                for key, value in data.items():
                    self.assertIn(key, merged)
                if harness == "cursor":
                    self.assertEqual(merged["hooks"]["beforeShellExecution"], [{"command": "echo other"}, {"command": ours}])
                elif harness == "antigravity":
                    self.assertEqual(merged["mine"], data["mine"])
                else:
                    self.assertEqual(merged["hooks"]["PreToolUse"][0], data["hooks"]["PreToolUse"][0])
                    self.assertEqual(len(merged["hooks"]["PreToolUse"]), 2)
                self.assertEqual(merged.get("theme"), data.get("theme"))
                self.assertEqual((agents / "mine.md").read_text(), "mine\n")

    def test_install_replaces_an_older_entry_of_its_own(self):
        self.install("cortex-code")
        path = self.home / HOOKS["cortex-code"]
        data = json.loads(path.read_text())
        data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "deliver_guard=/old/guard.py; exit 0"
        path.write_text(json.dumps(data))
        result = self.install("cortex-code")
        self.assertEqual(result.stdout, f"added deliver's guard to {path}\n")
        self.assertEqual(len(json.loads(path.read_text())["hooks"]["PreToolUse"]), 1)

    def test_the_registered_command_runs_the_guard_and_exits_0_when_it_is_gone(self):
        self.install("cortex-code")
        command = self.registered("cortex-code")
        guard = self.skill / "scripts" / "guard.py"
        bare = self.world.root / "bare"
        bare.mkdir()
        (bare / "python3").symlink_to(sys.executable)
        env = {"PATH": f"{bare}:/usr/bin:/bin", "HOME": str(self.home)}
        guard.write_text("import sys\nprint('guard ran', sys.argv[1:])\n")
        ran = subprocess.run(["/bin/sh", "-c", command], env=env, capture_output=True, text=True)
        self.assertEqual((ran.returncode, ran.stdout), (0, "guard ran []\n"), ran.stderr)
        guard.unlink()
        gone = subprocess.run(["/bin/sh", "-c", command], env=env, capture_output=True, text=True)
        self.assertEqual((gone.returncode, gone.stdout, gone.stderr), (0, "", ""))

    def test_install_claude_code(self):
        for args in (("claude-code",), ("--remove", "claude-code")):
            with self.subTest(args):
                result = self.install(*args)
                self.assertEqual((result.returncode, result.stdout), (10, (
                    "REFUSED install.claude-code: on Claude Code the plugin supplies the reader and the guard, "
                    "so install it with the plugin\nNext: claude plugin install deliver@relentless-data-skills\n")))
        self.assertEqual(tree(self.home), self.home_before)

    def test_install_wrong_harness(self):
        for var, detected, next_line in (("CORTEX_SESSION_ID", "cortex-code", "Next: deliver.py install cortex-code\n"),
                                         ("CLAUDECODE", "claude-code", "")):
            with self.subTest(detected):
                result = self.install("codex", **{var: "1"})
                self.assertEqual((result.returncode, result.stdout), (10, (
                    f"REFUSED install.wrong-harness: this session runs on {detected}, not codex. "
                    f"Run install for codex from a plain shell\n{next_line}")))
        self.assertEqual(self.install("codex", CODEX_THREAD_ID="t-1").returncode, 0)

    def test_an_unknown_harness_is_a_usage_error(self):
        for args in ((), ("vim",), ("codex", "cursor")):
            with self.subTest(args):
                result = self.install(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("install takes one of cortex-code, codex, cursor, antigravity, claude-code", result.stderr)

    def test_install_bad_hook_file(self):
        path = self.home / HOOKS["codex"]
        path.parent.mkdir(parents=True)
        for text, error in (("{not json", "Expecting property name"), ('{"hooks": []}', "hooks is not an object"),
                            ('{"hooks": {"PreToolUse": {}}}', "hooks.PreToolUse is not a list")):
            with self.subTest(text):
                path.write_text(text)
                for args in (("codex",), ("--remove", "codex")):
                    result = self.install(*args)
                    self.assertEqual(result.returncode, 10)
                    self.assertTrue(result.stdout.startswith(
                        f"REFUSED install.bad-hook-file: {path} cannot be read as a hook file: "), result.stdout)
                    self.assertIn(error, result.stdout)
                    self.assertTrue(result.stdout.endswith(f"Next: fix {path}, then run deliver.py install {' '.join(args)}\n"))
                    self.assertEqual(path.read_text(), text)

    def test_install_codex_prints_the_trust_step_only_when_it_changed_the_hook_file(self):
        trust = "Codex runs no hook you have not trusted: start codex, type /hooks, trust deliver's guard, then quit.\n"
        first = self.install("codex")
        self.assertEqual(first.stdout, f"wrote {self.home / READER['codex']}\n"
                                       f"added deliver's guard to {self.home / HOOKS['codex']}\n{trust}")
        self.assertNotIn(trust, self.install("codex").stdout)
        (self.home / READER["codex"]).unlink()
        self.assertEqual(self.install("codex").stdout, f"wrote {self.home / READER['codex']}\n")
        (self.home / HOOKS["codex"]).unlink()
        self.assertTrue(self.install("codex").stdout.endswith(trust))
        for harness in ("cortex-code", "antigravity"):
            self.assertNotIn("trust", self.install(harness).stdout)

    def test_install_cursor_writes_the_checkout_file_and_one_exclude_line(self):
        common = Path(self.world.git(self.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        exclude = common / "info" / "exclude"
        first = self.install("cursor", cwd=self.world.work)
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual((self.world.work / CURSOR_READER).read_bytes(),
                         (HARNESS / "cursor" / "deliver-reader.md").read_bytes())
        self.assertIn("beforeShellExecution", json.loads((self.home / HOOKS["cursor"]).read_text())["hooks"])
        self.assertEqual(self.world.git(self.world.work, "status", "--porcelain", "--untracked-files=all"), "")
        second = self.world.worktree("second", "second")
        result = self.install("cursor", cwd=second)
        self.assertEqual((result.returncode, result.stdout), (0, f"wrote {second / CURSOR_READER}\n"))
        self.assertEqual(exclude.read_text().splitlines().count(EXCLUDE_LINE), 1)
        self.assertEqual(len(json.loads((self.home / HOOKS["cursor"]).read_text())["hooks"]["beforeShellExecution"]), 1)
        self.assertEqual(self.world.git(second, "status", "--porcelain", "--untracked-files=all"), "")

    def test_install_not_a_checkout(self):
        outside = self.world.root / "outside"
        outside.mkdir()
        for args in (("cursor",), ("--remove", "cursor")):
            with self.subTest(args):
                result = self.install(*args, cwd=outside)
                self.assertEqual((result.returncode, result.stdout), (10, (
                    "REFUSED install.not-a-checkout: cursor loads the reader only from a checkout's .cursor/agents/, "
                    "so run install inside the checkout\n")))
        self.assertEqual(tree(self.home), self.home_before)

    def test_remove_leaves_the_home_folder_as_it_was(self):
        other = {"hooks": {"PreToolUse": [{"matcher": "bash", "hooks": [{"type": "command", "command": "echo other"}]}]}}
        for start in ("empty", "with other entries"):
            for harness in ("cortex-code", "codex", "antigravity"):
                with self.subTest(start=start, harness=harness):
                    if start != "empty":
                        (self.home / HOOKS[harness]).parent.mkdir(parents=True, exist_ok=True)
                        (self.home / HOOKS[harness]).write_text(json.dumps(other, indent=2) + "\n")
                        (self.home / READER[harness]).parent.mkdir(parents=True, exist_ok=True)
                        (self.home / READER[harness]).with_name("mine.md").write_text("mine\n")
                    before = tree(self.home)
                    self.assertEqual(self.install(harness).returncode, 0)
                    self.assertNotEqual(tree(self.home), before)
                    result = self.install("--remove", harness)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(result.stdout, f"took deliver's guard out of {self.home / HOOKS[harness]}\n"
                                                    f"removed {self.home / READER[harness]}\n")
                    self.assertEqual(tree(self.home), before)
                    again = self.install("--remove", harness)
                    self.assertEqual(again.stdout, f"nothing to remove: deliver is not installed on {harness}.\n")

    def test_remove_gives_back_each_hook_file_shape_it_started_from(self):
        # Every key `install` may add: Cursor's `version`, each harness's top-level group (`hooks` or
        # Antigravity's `deliver-guard`) and the event list under it.
        other = {"type": "command", "command": "echo other"}
        shapes = {
            "cortex-code": ["", "{}", '{"hooks": {}}', '{"hooks": {"PreToolUse": []}}', '{"theme":"dark"}',
                            json.dumps({"hooks": {"PreToolUse": [{"matcher": "bash", "hooks": [other]}]}})],
            "codex": ["", "{}\n", '{"hooks": {}}', '{"hooks": {"Stop": []}}',
                      json.dumps({"hooks": {"PreToolUse": [{"matcher": "", "hooks": [other]}]}}, indent=4)],
            "cursor": ["", "{}", '{"version": 1}', '{"version": 2}', '{"hooks": {"beforeShellExecution": []}}',
                       '{"version": 1, "hooks": {}}', json.dumps({"hooks": {"stop": [{"command": "echo other"}]}})],
            "antigravity": ["", "{}", '{"deliver-guard": {}}', '{"deliver-guard": {"PreToolUse": []}}',
                            json.dumps({"mine": {"PreToolUse": [{"matcher": "", "hooks": [other]}]}})],
        }
        for harness, texts in shapes.items():
            path = self.home / HOOKS[harness]
            for text in texts:
                with self.subTest(harness=harness, text=text):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
                    before = tree(self.home)
                    self.assertEqual(self.install(harness, cwd=self.world.work).returncode, 0)
                    self.assertNotEqual(path.read_text(), text)
                    result = self.install("--remove", harness, cwd=self.world.work)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(path.read_text(), text)
                    self.assertEqual(tree(self.home), before)

    def test_remove_keeps_what_existed_before_install_even_when_empty(self):
        codex = self.home / ".codex"
        (codex / "agents").mkdir(parents=True)
        (codex / "hooks.json").write_text("")
        before = tree(self.home)
        self.assertEqual(self.install("codex").returncode, 0)
        self.assertEqual(self.install("--remove", "codex").returncode, 0)
        self.assertEqual(tree(self.home), before)
        # A reader file of the same name that was there before comes back as it was.
        (codex / "agents" / "deliver-reader.toml").write_text("mine\n")
        before = tree(self.home)
        self.install("codex")
        self.install("--remove", "codex")
        self.assertEqual(tree(self.home), before)

    def test_remove_cursor_keeps_an_empty_agents_folder_and_the_exclude_file_as_it_was(self):
        common = Path(self.world.git(self.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        (self.world.work / ".cursor" / "agents").mkdir(parents=True)
        (common / "info").mkdir(exist_ok=True)
        (common / "info" / "exclude").write_text("# mine, with no newline at the end")
        before = (tree(self.home), tree(self.world.work), tree(common / "info"))
        self.assertEqual(self.install("cursor", cwd=self.world.work).returncode, 0)
        self.assertEqual(self.install("--remove", "cursor", cwd=self.world.work).returncode, 0)
        self.assertEqual((tree(self.home), tree(self.world.work), tree(common / "info")), before)

    def test_remove_cursor_leaves_the_home_folder_and_the_checkout_as_they_were(self):
        common = Path(self.world.git(self.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        before = (tree(self.home), tree(self.world.work), tree(common / "info"))
        self.assertEqual(self.install("cursor", cwd=self.world.work).returncode, 0)
        result = self.install("--remove", "cursor", cwd=self.world.work)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((tree(self.home), tree(self.world.work), tree(common / "info")), before)

    def test_remove_with_no_ledger_takes_out_what_it_can_tell_is_deliver_s(self):
        # The machine directory cleared between install and remove: no record of what install made.
        other = {"hooks": {"PreToolUse": [{"matcher": "bash", "hooks": [{"type": "command", "command": "echo other"}]}]}}
        starts = {"cortex-code": [None, other], "codex": [None, other], "antigravity": [None, {"theme": "dark"}],
                  "cursor": [None, {"version": 1}, {"version": 1, "hooks": {"stop": [{"command": "echo other"}]}}]}
        common = Path(self.world.git(self.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        for harness, datas in starts.items():
            path = self.home / HOOKS[harness]
            for data in datas:
                with self.subTest(harness=harness, start=data):
                    path.unlink(missing_ok=True)
                    if data is not None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(data))
                    self.assertEqual(self.install(harness, cwd=self.world.work).returncode, 0)
                    shutil.rmtree(self.world.state)
                    result = self.install("--remove", harness, cwd=self.world.work)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertFalse((self.world.work / CURSOR_READER if harness == "cursor"
                                      else self.home / READER[harness]).exists())
                    # No container is left that only deliver's entry needed.
                    self.assertEqual(json.loads(path.read_text()), data or ({"version": 1} if harness == "cursor" else {}))
                    if harness == "cursor":
                        self.assertNotIn(EXCLUDE_LINE, (common / "info" / "exclude").read_text().splitlines())
                        self.assertEqual(self.world.git(self.world.work, "status", "--porcelain",
                                                        "--untracked-files=all"), "")

    def test_remove_keeps_a_reader_file_the_owner_edited_and_says_so(self):
        for harness in ("codex", "cursor"):
            with self.subTest(harness):
                reader = self.world.work / CURSOR_READER if harness == "cursor" else self.home / READER[harness]
                self.assertEqual(self.install(harness, cwd=self.world.work).returncode, 0)
                reader.write_text("edited\n")
                result = self.install("--remove", harness, cwd=self.world.work)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(f"kept {reader}: it differs from deliver's copy\n", result.stdout)
                self.assertEqual(reader.read_text(), "edited\n")
                self.assertNotIn("deliver_guard=", (self.home / HOOKS[harness]).read_text()
                                 if (self.home / HOOKS[harness]).exists() else "")
                if harness == "cursor":
                    # The reader stays excluded, so it shows as no untracked file.
                    self.assertIn(f"kept {EXCLUDE_LINE}", result.stdout)
                    self.assertEqual(self.world.git(self.world.work, "status", "--porcelain",
                                                    "--untracked-files=all"), "")

    def test_remove_cursor_keeps_the_exclude_line_while_another_checkout_holds_the_reader(self):
        second = self.world.worktree("second", "second")
        common = Path(self.world.git(self.world.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        exclude = common / "info" / "exclude"
        self.install("cursor", cwd=self.world.work)
        self.install("cursor", cwd=second)
        self.assertEqual(self.install("--remove", "cursor", cwd=second).returncode, 0)
        self.assertIn(EXCLUDE_LINE, exclude.read_text().splitlines())
        self.assertEqual(self.world.git(self.world.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(self.install("--remove", "cursor", cwd=self.world.work).returncode, 0)
        self.assertNotIn(EXCLUDE_LINE, exclude.read_text().splitlines())

    def test_remove_leaves_no_machine_directory_when_deliver_state_dir_is_unset(self):
        before = tree(self.home)
        self.assertEqual(self.install("codex", DELIVER_STATE_DIR=None).returncode, 0)
        self.assertTrue((self.home / ".local" / "state" / "deliver" / "install-ledger.json").is_file())
        self.assertEqual(self.install("--remove", "codex", DELIVER_STATE_DIR=None).returncode, 0)
        self.assertEqual(tree(self.home), before)

    def test_the_hook_slot_is_the_one_the_generator_writes(self):
        install = deliver_kit.load("install")
        spec = importlib.util.spec_from_file_location("gen_roles", deliver_kit.REPO_ROOT / "scripts" / "gen_roles.py")
        gen_roles = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen_roles)
        self.assertTrue(gen_roles.GUARD_COMMAND.startswith(f"{install.MARKER}{install.GUARD_SLOT}; "))
        self.assertEqual(sorted(folder for folder, _, _ in install.TARGETS.values()), sorted(gen_roles.HARNESSES))


class Preflight(unittest.TestCase):
    """Preflight's install checks, on a harness named by its variable."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark(run="run-3")
        self.world.probe()
        deliver_kit.github_ok(self.world)
        self.world.install_upstream()
        # Off Claude Code, preflight finds the required skills in `~/.agents/skills` (#458).
        shutil.copytree(self.world.home / ".claude" / "skills", self.world.home / ".agents" / "skills")
        (self.world.work / "docs" / "agents").mkdir(parents=True)
        (self.world.work / "docs" / "agents" / "stack.toml").write_text('check_command = "make check"\n')

    def preflight(self, **env: str) -> subprocess.CompletedProcess:
        """Preflight, without the adapter line and Cursor warning that #458 prints first."""
        result = self.world.deliver("preflight", **env)
        result.stdout = "".join(line for line in result.stdout.splitlines(keepends=True)
                                if not line.startswith(("adapter: ", "warning: on Cursor")))
        return result

    def test_preflight_install_missing(self):
        for harness, var in (("cortex-code", "CORTEX_SESSION_ID"), ("cursor", "CURSOR_AGENT")):
            with self.subTest(harness):
                result = self.preflight(**{var: "1"})
                path = self.world.home / READER["cortex-code"] if harness == "cortex-code" else self.world.work / CURSOR_READER
                self.assertEqual((result.returncode, result.stdout), (10, (
                    f"REFUSED preflight.install-missing: deliver is not installed on {harness}: "
                    f"{path} lacks what install writes\nNext: deliver.py install {harness}\n")))
                self.assertEqual(self.world.state_lines("preflight-stops.jsonl")[-1]["code"], "preflight.install-missing")

    def test_preflight_install_differs(self):
        self.assertEqual(self.world.deliver("install", "codex", CODEX_THREAD_ID="t-1").returncode, 0)
        self.assertEqual(self.preflight(CODEX_THREAD_ID="t-1").stdout, "Preflight passed.\n")
        hooks = self.world.home / HOOKS["codex"]
        for path, text in ((hooks, hooks.read_text().replace("timeout", "time")), (hooks, "{broken"),
                           (self.world.home / READER["codex"], "edited\n")):
            with self.subTest(path=path.name, text=text[:10]):
                saved = path.read_bytes()
                path.write_text(text)
                result = self.preflight(CODEX_THREAD_ID="t-1")
                self.assertEqual((result.returncode, result.stdout), (10, (
                    f"REFUSED preflight.install-differs: deliver's files on codex differ from the skill's copy: "
                    f"{path}\nNext: deliver.py install codex\n")))
                path.write_bytes(saved)

    def test_claude_code_and_a_plain_shell_skip_the_install_checks(self):
        for env in ({}, {"CLAUDECODE": "1"}):
            with self.subTest(env):
                self.assertEqual(self.preflight(**env).stdout, "Preflight passed.\n")


if __name__ == "__main__":
    unittest.main()
