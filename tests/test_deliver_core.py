"""deliver.py's dispatch, endings, refusal codes, run mark, records, machine directory and lists.

Most tests run deliver.py at its command line in a throwaway world from tests/deliver_kit.py.
The rest call a deliver module, the lists data file or the stand-in gh directly.

    python3 -m unittest tests.test_deliver_core
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

TESTS = Path(__file__).resolve().parent
USAGE = """\
usage: deliver.py <subcommand> [arguments]

Subcommands: start, preflight, check, save, pr, ready, merge, finish, deps, scan, report.
start, deps, scan and report never need a run mark. finish needs none only to resume a run whose
earlier finish left its PR waiting. Every other subcommand needs one.
Exit codes: 0 done, 10 refused, 20 a question for the owner, any other a crash.
"""
NO_MARK = "REFUSED {}.no-mark: no run mark in this checkout, so no run is in progress here\nNext: deliver.py start\n"
AT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class Dispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = deliver_kit.World(cls.addClassCleanup)

    def assert_ends(self, result, code, stdout, stderr=""):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, stderr))

    def test_help_prints_usage(self):
        self.assert_ends(self.world.deliver("--help"), 0, USAGE)

    def test_no_subcommand_exits_2_with_usage(self):
        self.assert_ends(self.world.deliver(), 2, "", f"deliver.py: name a subcommand\n\n{USAGE}")

    def test_unknown_subcommand_exits_2_with_usage(self):
        self.assert_ends(self.world.deliver("land"), 2, "", f"deliver.py: no subcommand named 'land'\n\n{USAGE}")

    def test_subcommand_not_built_exits_2_with_usage(self):
        deliver = deliver_kit.load("deliver")
        missing = [name for name in deliver.SUBCOMMANDS if not (deliver_kit.SCRIPTS / f"{name}.py").exists()]
        mark = self.world.write_mark()
        self.addCleanup(mark.unlink)
        for name in missing:
            with self.subTest(name):
                self.assert_ends(self.world.deliver(name), 2, "", f"deliver.py: {name} is not built yet\n\n{USAGE}")

    def assert_no_mark(self, name):
        self.assert_ends(self.world.deliver(name), 10, NO_MARK.format(name))

    def test_preflight_no_mark(self):
        self.assert_no_mark("preflight")

    def test_preflight_no_mark_outside_a_repo(self):
        result = self.world.deliver("preflight", cwd=self.world.home)
        self.assert_ends(result, 10, NO_MARK.format("preflight"))

    def test_check_no_mark(self):
        self.assert_no_mark("check")

    def test_save_no_mark(self):
        self.assert_no_mark("save")

    def test_pr_no_mark(self):
        self.assert_no_mark("pr")

    def test_ready_no_mark(self):
        self.assert_no_mark("ready")

    def test_merge_no_mark(self):
        self.assert_no_mark("merge")

    def test_finish_no_mark(self):
        self.assert_no_mark("finish")

    def test_start_deps_scan_and_report_never_need_a_mark_and_finish_only_to_resume_a_waiting_pr(self):
        deliver = deliver_kit.load("deliver")
        core = deliver_kit.load("core")
        # finish refuses finish.no-mark itself: it needs no mark only to resume a run whose earlier finish left its PR waiting.
        self.assertEqual(deliver.NO_MARK_NEEDED, {"start", "finish", "deps", "scan", "report"})
        needs = [name for name in deliver.SUBCOMMANDS if name not in deliver.NO_MARK_NEEDED]
        self.assertEqual([name for name in needs if f"{name}.no-mark" not in core.REFUSALS], [])


class RefusalCodes(unittest.TestCase):
    def test_every_code_has_a_test_named_for_it(self):
        core = deliver_kit.load("core")
        names = set()
        for path in TESTS.glob("test_deliver_*.py"):
            names.update(re.findall(r"^\s*def (test_\w+)\(", path.read_text(encoding="utf-8"), re.M))
        untested = []
        for code in core.REFUSALS:
            slug = "test_" + code.replace(".", "_").replace("-", "_")
            if not any(name == slug or name.startswith(slug + "_") for name in names):
                untested.append(f"{code}: no test named {slug}")
        self.assertEqual(untested, [])

    def test_every_code_is_subcommand_dot_reason(self):
        core = deliver_kit.load("core")
        deliver = deliver_kit.load("deliver")
        pattern = re.compile(rf"(?:{'|'.join(deliver.SUBCOMMANDS)})\.[a-z0-9]+(?:-[a-z0-9]+)*")
        self.assertEqual([code for code in core.REFUSALS if not pattern.fullmatch(code)], [])

    def test_a_code_outside_the_table_cannot_be_raised(self):
        core = deliver_kit.load("core")
        with self.assertRaises(KeyError):
            core.Refused("ready.not-in-the-table")


class MarkAndRecords(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)

    def test_write_mark_writes_the_fixed_layout_in_the_checkouts_git_dir(self):
        core = deliver_kit.load("core")
        tree = self.world.worktree("tree", "feat/one")
        git_dir = Path(self.world.git(tree, "rev-parse", "--path-format=absolute", "--git-dir"))
        mark = core.write_mark(git_dir, "run-7", "feat/one")
        written = json.loads((git_dir / "deliver-mark.json").read_text(encoding="utf-8"))
        self.assertEqual(written, mark)
        self.assertEqual(list(written), ["run", "branch", "role", "started"])
        self.assertEqual({k: v for k, v in written.items() if k != "started"},
                         {"run": "run-7", "branch": "feat/one", "role": "session"})
        self.assertRegex(written["started"], AT)
        self.assertEqual(git_dir, self.world.root / "work" / ".git" / "worktrees" / "tree")
        self.assertEqual(core.read_mark(git_dir), written)

    def test_mark_is_read_from_its_own_checkout_only(self):
        tree = self.world.worktree("tree", "feat/one")
        self.world.install_upstream()
        self.world.write_mark(tree, branch="feat/one")
        self.world.probe(cwd=tree)
        self.assertEqual(self.world.deliver("preflight", cwd=tree).returncode, 0)
        self.assertEqual(self.world.deliver("preflight").stdout, NO_MARK.format("preflight"))

    def test_records_from_a_worktree_go_to_the_shared_git_dir(self):
        tree = self.world.worktree("tree", "feat/one")
        self.world.write_mark(tree, run="run-9", branch="feat/one")
        self.world.deliver("preflight", cwd=tree)
        path = self.world.work / ".git" / "deliver" / "branches" / "feat" / "one" / "records.jsonl"
        self.assertTrue(path.is_file())
        self.assertEqual([(r["event"], r["run"]) for r in self.world.records("feat/one")], [("preflight", "run-9")])
        self.assertEqual(self.world.git(self.world.work, "status", "--porcelain"), "")

    def test_record_lines_start_with_event_and_at(self):
        core = deliver_kit.load("core")
        common = self.world.work / ".git"
        core.append_record(common, "main", "pr", number=12, url="https://example.invalid/pull/12")
        core.append_record(common, "main", "pr", number=12, url="https://example.invalid/pull/12")
        lines = self.world.records("main")
        self.assertEqual(len(lines), 2)
        self.assertEqual(list(lines[0]), ["event", "at", "number", "url"])
        self.assertRegex(lines[0]["at"], AT)


class MachineDirectory(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark()

    def test_default_is_under_home(self):
        (self.world.work / "docs" / "agents").mkdir(parents=True)
        (self.world.work / "docs" / "agents" / "stack.toml").write_text("check_slots = 'two'\n", encoding="utf-8")
        result = self.world.deliver("preflight", DELIVER_STATE_DIR=None)
        self.assertEqual(result.returncode, 10)
        log = self.world.home / ".local" / "state" / "deliver" / "preflight-stops.jsonl"
        self.assertEqual([line["code"] for line in deliver_kit.read_lines(log)], ["preflight.bad-settings"])
        self.assertFalse(self.world.state.exists())

    def test_no_line_holds_a_session_id(self):
        session = "5e55-10f1-d00d"
        names = ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "SESSION_ID")
        env = dict.fromkeys(names, session)
        self.world.deliver("preflight", **env)
        (self.world.work / "docs" / "agents").mkdir(parents=True)
        (self.world.work / "docs" / "agents" / "stack.toml").write_text("[small_edit\n", encoding="utf-8")
        self.assertEqual(self.world.deliver("preflight", **env).returncode, 10)
        written = [p for p in self.world.state.rglob("*") if p.is_file()]
        self.assertEqual([p.name for p in written], ["preflight-stops.jsonl"])
        for path in written:
            self.assertNotIn(session, path.read_text(encoding="utf-8"))
            self.assertNotIn("session", path.read_text(encoding="utf-8"))

    def test_append_state_refuses_a_session_field(self):
        core = deliver_kit.load("core")
        with self.assertRaises(ValueError):
            core.append_state("preflight-stops.jsonl", session_id="x")


class Lists(unittest.TestCase):
    def test_the_guard_reads_the_lists_without_the_program(self):
        # An isolated interpreter, outside the scripts folder, with only tomllib and re.
        code = (
            "import re, sys, tomllib\n"
            "lists = tomllib.load(open(sys.argv[1], 'rb'))\n"
            "assert not any(name in sys.modules for name in ('core', 'settings', 'preflight', 'deliver'))\n"
            "print(sorted(lists), [bool(re.search(p, sys.argv[2])) for p in lists['one_way_commands']].count(True))\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code, str(deliver_kit.SCRIPTS / "lists.toml"), "git push --force origin x"],
            cwd=TESTS, capture_output=True, text=True,
        )
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, "['critical_paths', 'known_hooks', 'one_way_commands', 'one_way_paths'] 1\n", ""),
        )

    def test_known_hooks_are_delivers_guard_and_snowmans_guard(self):
        lists = deliver_kit.load("settings").read_lists()
        self.assertEqual(lists["known_hooks"], [
            {"name": "deliver guard", "plugin": "deliver", "script": "scripts/guard.py"},
            {"name": "snowman guard", "plugin": "snowman", "script": "hooks/snow_guard.py"},
        ])
        self.assertTrue((deliver_kit.REPO_ROOT / "skills" / "snowman" / "hooks" / "snow_guard.py").is_file())

    def test_one_way_commands(self):
        commands = deliver_kit.load("settings").read_lists()["one_way_commands"]
        one_way = [
            "git push --force origin feat/x", "git push -f", "git push --force-with-lease origin x",
            "git push origin +main", "git -C repo push -fu origin x",
            "git push origin --delete feat/x", "git push origin :refs/tags/v1", "git push -d origin v1",
            "gh api -X DELETE repos/o/r/git/refs/heads/x",
            "gh release create v1.0.0", "npm publish", "uv publish", "twine upload dist/*", "cargo publish",
            "dbt run --target prod", "dbt build --target=production", "snow sql -c PROD -q 'select 1'",
        ]
        two_way = [
            "git push -u origin feat/x", "git push --follow-tags origin x", "git push origin HEAD:refs/heads/x",
            "gh release view v1", "npm install", "cd /srv/prod/app && ls", "cat prod.yml", "gh api repos/o/r/git/refs",
        ]
        hit = lambda command: any(re.search(p, command) for p in commands)  # noqa: E731
        self.assertEqual([c for c in one_way if not hit(c)], [])
        self.assertEqual([c for c in two_way if hit(c)], [])

    @staticmethod
    def hits(commands: list[str]) -> dict[str, bool]:
        """Whether any one-way command pattern matches each command."""
        patterns = deliver_kit.load("settings").read_lists()["one_way_commands"]
        return {c: any(re.search(p, c) for p in patterns) for c in commands}

    def test_a_mirror_or_pruning_push_is_one_way(self):
        commands = ["git push --mirror origin", "git push --prune origin refs/heads/*:refs/heads/*",
                    "git push origin ':main'", 'git push origin "+main"']
        self.assertEqual(self.hits(commands), dict.fromkeys(commands, True))

    def test_a_command_aimed_at_production_is_one_way(self):
        commands = ["dbt run --target prod", "dbt build --target=production", 'dbt run --target "prod"',
                    "dbt run -t prod", "snow sql -c PROD -q 'select 1'", "kubectl --context production apply -f x.yml",
                    "DBT_TARGET=prod dbt run", "cd app && vercel deploy --prod",
                    "pulumi up --stack prod", "pulumi up -s prod", "sls deploy -s prod", "firebase deploy --project prod",
                    "firebase deploy -P prod", "gcloud config set project prod", "AWS_PROFILE=prod aws s3 rm s3://x",
                    "heroku run rake -a myapp --remote production", "aws --profile prod s3 rm s3://x --recursive"]
        self.assertEqual(self.hits(commands), dict.fromkeys(commands, True))

    def test_a_production_variable_or_argument_is_one_way(self):
        commands = ["RAILS_ENV=production rails db:migrate", "ENV=prod ./deploy.sh", "make deploy ENV=prod",
                    "MIX_ENV=prod mix ecto.migrate", "terraform apply -var env=prod", "terraform workspace select prod",
                    "ansible-playbook -i production site.yml", "./deploy.sh production", "git push prod main",
                    "kubectl config use-context prod"]
        self.assertEqual(self.hits(commands), dict.fromkeys(commands, True))

    def test_a_mention_of_production_is_not_one_way(self):
        commands = ["git commit -m 'fix prod bug'", "echo production", "npm install --production",
                    "NODE_ENV=production npm run build", "git -C prod status", "grep -e prod notes.txt",
                    "dbt run --target prod-eu", "cd /srv/prod/app && ls", "cat prod.yml"]
        self.assertEqual(self.hits(commands), dict.fromkeys(commands, False))

    def test_quoted_text_is_never_one_way(self):
        commands = ['git commit -m "dbt run --target prod"', "git commit -m 'git push --force is banned'",
                    "gh pr create --title \"drop npm publish\" --body 'docker push and gh release create'",
                    "git log --grep 'push --force'", 'git commit -m "a \\"quoted\\" git push --mirror"',
                    "echo 'twine upload' && echo \"gem push\"", "gh issue comment 5 --body 'gh api -X DELETE git/refs/x'",
                    "git commit -m 'line one\nline two' && git push origin x", "echo 'gh release create' "]
        self.assertEqual(self.hits(commands), dict.fromkeys(commands, False))

    def test_doubtful_quoting_is_read_as_one_way(self):
        commands = ["git commit -F - <<'EOF'\nDon't break it\nEOF\ngit push --force",
                    "# don't forget\ngit push --force", "git commit -m $'it\\'s' && git push --force",
                    "git commit -m 'it\\'s fine' && git push --force", "echo 'unclosed git push --force",
                    # Apostrophes that pair up, so only the heredoc, comment or $'...' marks the doubt.
                    "cat <<EOF\nit's\nEOF\ngit push --force; echo it's", "# don't\ngit push --force # won't",
                    "echo $'a\\'b' && git push --force && echo it's"]
        self.assertEqual(self.hits(commands), dict.fromkeys(commands, True))

    def test_path_lists(self):
        core = deliver_kit.load("core")
        lists = deliver_kit.load("settings").read_lists()
        one_way = [".github/workflows/ci.yml", ".github/dependabot.yml", "CODEOWNERS", "docs/CODEOWNERS", "CLAUDE.md",
                   "AGENTS.md", ".claude/settings.json", ".mcp.json", ".husky/pre-commit", ".env", "api/.env.local",
                   "deploy/tls.pem", "config/secrets/db.yml"]
        critical = ["skills/deliver/SKILL.md", "AGENTS.md", "docs/agents/stack.toml", ".github/workflows/ci.yml",
                    "pyproject.toml", "web/package-lock.json", "uv.lock", "src/auth/session.py", "db/migrations/001.sql",
                    "models/staging/_sources.yml", "macros/cents.sql", "snapshots/orders.sql", "dbt_project.yml",
                    "Sales.SemanticModel/definition/relationships.tmdl",
                    "Sales.SemanticModel/definition/roles/east.tmdl"]
        neither = ["README.md", "src/report.py", "models/marts/orders.sql", "tests/test_report.py"]
        self.assertEqual([p for p in one_way if not core.path_matches(p, lists["one_way_paths"])], [])
        self.assertEqual([p for p in critical if not core.path_matches(p, lists["critical_paths"])], [])
        self.assertEqual([p for p in neither if core.path_matches(p, lists["one_way_paths"] + lists["critical_paths"])],
                         [])


class Kit(unittest.TestCase):
    def test_stand_in_gh_replays_saved_answers_and_records_each_call(self):
        world = deliver_kit.World(self.addCleanup)
        world.gh_answer(["pr", "view"], stdout='{"state":"OPEN"}\n')
        world.gh_answer(["repo", "view", "--json", "name"], stderr="denied\n", exit=4)
        run = lambda *args: subprocess.run(["gh", *args], cwd=world.work, env=world.env(),  # noqa: E731
                                           capture_output=True, text=True)
        results = [run("pr", "view", "12", "--json", "state"), run("repo", "view", "--json", "name"), run("auth", "status")]
        self.assertEqual([(r.returncode, r.stdout, r.stderr) for r in results], [
            (0, '{"state":"OPEN"}\n', ""),
            (4, "", "denied\n"),
            (1, "", "stand-in gh: no answer for auth status\n"),
        ])
        self.assertEqual(world.gh_calls(), [
            {"args": ["pr", "view", "12", "--json", "state"], "cwd": str(world.work)},
            {"args": ["repo", "view", "--json", "name"], "cwd": str(world.work)},
            {"args": ["auth", "status"], "cwd": str(world.work)},
        ])

    def test_stand_in_gh_answers_with_the_first_saved_prefix(self):
        world = deliver_kit.World(self.addCleanup)
        world.gh_answer(["pr"], stdout="first\n")
        world.gh_answer(["pr", "view"], stdout="second\n")
        result = subprocess.run(["gh", "pr", "view"], cwd=world.work, env=world.env(), capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "first\n", ""))

    def test_world_has_a_bare_remote_and_a_clone_on_main(self):
        world = deliver_kit.World(self.addCleanup)
        self.assertEqual(world.git(world.origin, "rev-parse", "--is-bare-repository"), "true")
        self.assertEqual(world.git(world.work, "remote", "get-url", "origin"), str(world.origin))
        self.assertEqual(world.git(world.work, "rev-parse", "HEAD"), world.git(world.origin, "rev-parse", "main"))
        self.assertEqual(world.git(world.work, "branch", "--show-current"), "main")


if __name__ == "__main__":
    unittest.main()
