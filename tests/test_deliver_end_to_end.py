"""deliver.py end to end: a small edit through every step a session runs, in the order SKILL.md gives.

Each test runs `deliver.py` at its command line, and the guard on a hook input recorded from
Claude Code, in a throwaway world of tests/deliver_kit.py: a clone, its bare remote and the
stand-in gh. The world's plugin copy has the stand-in scan of tests/test_deliver_ready.py, and
its gh merges a PR as GitHub squashes one: a new commit on the bare remote's `main` whose parent
is the old `main` and whose tree is the PR head's. Nothing touches the network or the real
machine directory.

    python3 -m unittest tests.test_deliver_end_to_end
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

core = deliver_kit.load("core")
from test_deliver_merge import CHECKS, PASS, answer, wrapped  # noqa: E402
from test_deliver_ready import SCAN_STUB  # noqa: E402

CHECK = "python3 -m unittest"
TICKET = "7"
BODY = ("## What to build\n\nAdd a `double` function to calc.py.\n\n"
        "## Acceptance criteria\n\n- [ ] double returns twice its argument\n")
PLAN = f"""\
| # | Requirement | Proof |
|---|---|---|
| R1 | double returns twice its argument | `{CHECK}` |

Assumptions
- A1 (R1): calc.py has no other caller. Checked with git grep: held.

door: two-way — one function and its test; nothing deploys on merge
"""
SUMMARY = "```diff\n calc.py\n+  double(n)\n```\n"
URL = "https://github.com/owner/repo/pull/12"
READY_VIEW = ["pr", "view", "12", "--json", "headRefOid", "--jq", ".headRefOid"]
REPO_VIEW = ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]
GRANT = ("Run grant: push this branch, open and update its PR, mark it ready and merge it through the scripts, "
         "file follow-up tickets.")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.work = self.world.work
        self.world.commit(self.work, ".gitignore", "__pycache__/\n", "chore: ignore bytecode")
        self.world.commit(self.work, "docs/agents/stack.toml", f'check_command = "{CHECK}"\n', "chore: stack settings")
        self.world.commit(self.work, "calc.py", "def add(a, b):\n    return a + b\n", "feat: calc")
        self.world.commit(self.work, "test_calc.py", (
            "import unittest\nimport calc\n\n\nclass Calc(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(calc.add(1, 2), 3)\n"), "test: calc")
        self.world.git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.world.gh_answer(["issue", "view", TICKET], json.dumps({"title": "Add double", "body": BODY, "comments": []}))
        self.world.gh_answer(REPO_VIEW, "main\n")
        deliver_kit.github_ok(self.world)
        self.world.gh_answer(["pr", "list"], "[]")
        self.world.gh_answer(["pr", "create"], URL + "\n")
        self.world.install_upstream()
        (self.world.root / "plugin" / "scripts" / "scan.py").write_text(SCAN_STUB, encoding="utf-8")
        self.tmp = self.world.root / "tmp"
        self.tmp.mkdir()

    def deliver(self, *args: str, **env: str) -> str:
        """Run one deliver.py command as the session would; it must exit 0. Returns its output."""
        result = self.world.deliver(*args, TMPDIR=str(self.tmp), **env)
        self.assertEqual((result.returncode, result.stderr), (0, ""), f"deliver.py {' '.join(args)}: {result.stdout}")
        return result.stdout

    def drop(self, kind: str, text: str) -> None:
        """Write a text into the drop folder and save it, as SKILL.md step 3 says."""
        (self.work / ".deliver").mkdir(exist_ok=True)
        (self.work / ".deliver" / f"{kind}.md").write_text(text, encoding="utf-8")
        self.deliver("save", kind)

    def head(self) -> str:
        return self.world.git(self.work, "rev-parse", "HEAD")

    def events(self, branch: str) -> list[tuple[str, object]]:
        return [(r["event"], r.get("result", r.get("kind", r.get("exit")))) for r in self.world.records(branch)]

    def begin(self) -> str:
        """Steps 1 to 3: start the ticket's run, pass the probe and preflight, save the plan. Returns the branch."""
        started = self.deliver("start", TICKET)
        found = re.match(r"Started run ([0-9a-f]{8}) on branch (\S+)\.\n", started)
        self.assertIsNotNone(found, started)
        run, branch = found.groups()
        self.assertEqual(self.world.git(self.work, "branch", "--show-current"), branch)
        step = re.search(r"^Next: run (.+), which the guard refuses, then deliver\.py (start --resume)$", started, re.M)
        self.assertIsNotNone(step, started)
        probe = self.world.guard(step[1])
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.deliver(*step[2].split()).splitlines()[-2:], ["Preflight passed.", GRANT])
        self.drop("plan", PLAN)
        self.assertEqual(self.events(branch), [
            ("start", None), ("save", "request"), ("preflight", "pass"), ("save", "plan")])
        preflight = self.world.records(branch)[2]
        self.assertEqual((preflight["run"], preflight["guard_probe"]), (run, "seen"))
        return branch

    def edit(self, files: dict[str, str]) -> str:
        """Steps 4 and 5: write the files and commit them with plain `git commit -m`. Returns the commit."""
        for name, content in files.items():
            (self.work / name).write_text(content, encoding="utf-8")
        self.world.git(self.work, "add", *files)
        self.world.git(self.work, "commit", "-q", "-m", "feat: add double")
        return self.head()

    def through_pr(self, commit: str) -> None:
        """Steps 6 to 8 up to `pr`: the check on the last commit, the summary, and the draft PR at that commit."""
        self.deliver("check", "--", *CHECK.split())
        self.drop("summary", SUMMARY)
        self.assertEqual(self.deliver("pr"), f"Opened draft PR #12: {URL}\n")
        self.world.gh_answer(READY_VIEW, commit + "\n")
        self.world.gh_answer(["pr", "edit"])
        self.world.gh_answer(["pr", "ready"])

    def gh_args(self) -> list[list[str]]:
        return [call["args"] for call in self.world.gh_calls()]

    def folder(self, branch: str) -> Path:
        """The branch's records folder in the clone's common git directory."""
        common = self.world.git(self.work, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return core.records_dir(Path(common), branch)

    def assert_body_files_removed(self) -> None:
        """Each --body-file deliver.py handed the stand-in gh is gone once the call returned."""
        files = [call["args"][call["args"].index("--body-file") + 1] for call in self.world.gh_calls()
                 if "--body-file" in call["args"]]
        self.assertTrue(files)
        self.assertEqual([f for f in files if Path(f).exists()], [])

    def edit_bodies(self) -> list[str]:
        """The bodies of the `gh pr edit` calls, each of which must name PR #12."""
        edits = [call for call in self.world.gh_calls() if call["args"][:2] == ["pr", "edit"]]
        self.assertEqual([call["args"][2] for call in edits], ["12"] * len(edits))
        return [call["body"] for call in edits]

    def github_merges(self, commit: str) -> str:
        """A PATH whose gh squashes the PR on `pr merge`: a new commit on the bare remote's main."""
        origin = str(self.world.origin)
        return wrapped(self.world, "gh", (
            "if args[:2] == ['pr', 'merge']:\n"
            "    import subprocess\n"
            f"    git = lambda *a: subprocess.run(['git', '--git-dir', {origin!r}, *a], check=True,"
            " capture_output=True, text=True).stdout.strip()\n"
            "    base = git('rev-parse', 'refs/heads/main')\n"
            f"    tree = git('merge-tree', '--write-tree', base, {commit!r}).splitlines()[0]\n"
            "    squash = git('commit-tree', tree, '-p', base, '-m', 'feat: add double (#12)')\n"
            "    git('update-ref', 'refs/heads/main', squash, base)"))

    def test_a_small_edit_runs_from_start_to_finish(self):
        branch = self.begin()
        commit = self.edit({
            "calc.py": "def add(a, b):\n    return a + b\n\n\ndef double(n):\n    return 2 * n\n",
            "test_calc.py": (self.work / "test_calc.py").read_text(encoding="utf-8")
            + "\n    def test_double(self):\n        self.assertEqual(calc.double(4), 8)\n",
        })
        self.through_pr(commit)

        records = self.world.records(branch)
        check = records[4]
        self.assertEqual({k: check[k] for k in ("event", "command", "exit", "commit", "selected_nothing")},
                         {"event": "check", "command": CHECK, "exit": 0, "commit": commit, "selected_nothing": False})
        self.assertEqual(self.events(branch)[4:], [("check", 0), ("save", "summary"), ("pr", None)])
        self.assertEqual((records[5]["commit"], records[6]["number"], records[6]["url"]), (commit, 12, URL))
        output = (self.folder(branch) / check["output"]).read_text(encoding="utf-8").splitlines()
        self.assertIn("Ran 2 tests", "\n".join(output))
        self.assertEqual(output[-1], "OK")

        self.assertEqual(self.world.git(self.world.origin, "rev-parse", f"refs/heads/{branch}"), commit)
        create = [call for call in self.world.gh_calls() if call["args"][:2] == ["pr", "create"]]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0]["args"][:9], [
            "pr", "create", "--draft", "--base", "main", "--head", branch, "--title", "feat: add double"])
        self.assertTrue(create[0]["body"].startswith("## Summary\n"))
        self.assertIn("double returns twice its argument", create[0]["body"])
        self.assertIn("Closes #7", create[0]["body"])
        self.assertIn(SUMMARY, create[0]["body"])
        self.assertEqual(self.world.git(self.work, "status", "--porcelain"), "")

        self.assertEqual(self.deliver("ready").splitlines(), [
            "small edit: a two-way door, 7 lines and a low blast radius.", f"Marked PR #12 ready: {URL}"])
        self.assertIn(["pr", "ready", "12"], self.gh_args())
        [described] = self.edit_bodies()
        self.assertIn("merge: pending\n", described)
        self.assertEqual(self.events(branch)[7:], [("ready", "small edit")])
        self.assertEqual((self.world.records(branch)[7]["commit"], (self.world.root / "scan-starts.txt").read_text()),
                         (commit, "start\n"))
        self.assert_body_files_removed()  # pr's and ready's, before the reset drops their calls

        self.world.gh_reset()
        answer(self.world, commit, checks=PASS, body=described)
        base = self.world.git(self.world.origin, "rev-parse", "refs/heads/main")
        self.assertEqual(self.deliver("merge", PATH=self.github_merges(commit)), (
            f"Merged PR #12 with squash at {commit[:7]}.\nSwitched this checkout to main.\n"
            f"Removed the remote branch origin/{branch} and the local branch {branch}.\n"))
        merge = ["pr", "merge", "12", "--squash", "--match-head-commit", commit]
        self.assertLess(self.gh_args().index(CHECKS), self.gh_args().index(merge))
        [merged] = self.edit_bodies()
        self.assertEqual(merged, described.replace("merge: pending\n", "merge: by the session, squash\n"))
        self.assertEqual(self.events(branch)[8:], [("merge", None)])
        main = self.world.git(self.world.origin, "rev-parse", "refs/heads/main")
        self.assertNotEqual(main, commit)
        self.assertEqual(self.world.git(self.world.origin, "rev-parse", "main^@"), base)
        self.assertEqual(*(self.world.git(self.world.origin, "rev-parse", f"{c}^{{tree}}") for c in (main, commit)))
        self.assert_body_files_removed()

        self.assertEqual(self.deliver("finish"), f"#7 merged: PR #12\nRemoved the records of {branch}.\n")
        self.assertFalse(self.folder(branch).exists())
        self.assertFalse((self.work / ".git" / "deliver-mark.json").exists())
        self.assertEqual(self.world.git(self.work, "status", "--porcelain"), "")

    def test_ready_refuses_a_change_that_needs_a_review(self):
        branch = self.begin()
        added = "".join(  # 13 functions of 4 lines: 52, over the small test's 50
            f"\n\ndef times_{n}(x):\n    return {n} * x\n" for n in range(2, 15))
        commit = self.edit({"calc.py": "def add(a, b):\n    return a + b\n" + added})
        self.through_pr(commit)

        result = self.world.deliver("ready", TMPDIR=str(self.tmp))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (10, (
            "REFUSED ready.needs-review: this change needs a review: 52 lines, over the limit of 50\n"), ""))
        self.assertEqual(self.events(branch)[-1], ("ready", "needs review"))
        self.assertEqual([a[:2] for a in self.gh_args() if a[:2] in (["pr", "edit"], ["pr", "ready"])], [])  # still draft
        self.assertFalse((self.world.root / "scan-starts.txt").exists())
        self.assert_body_files_removed()


if __name__ == "__main__":
    unittest.main()
