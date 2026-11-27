"""deliver.py end to end: a small edit through every step a session runs, in the order SKILL.md gives.

Each test runs `deliver.py` at its command line, and the guard on a hook input recorded from
Claude Code, in a throwaway world of tests/deliver_kit.py: a clone, its bare remote and the
stand-in gh. Nothing touches the network or the real machine directory.

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
        self.tmp = self.world.root / "tmp"
        self.tmp.mkdir()

    def deliver(self, *args: str) -> str:
        """Run one deliver.py command as the session would; it must exit 0. Returns its output."""
        result = self.world.deliver(*args, TMPDIR=str(self.tmp))
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
        found = re.match(r"Started run ([0-9a-f]{8}) on branch (\S+)\.\n", self.deliver("start", TICKET))
        self.assertIsNotNone(found)
        run, branch = found.groups()
        self.assertEqual(self.world.git(self.work, "branch", "--show-current"), branch)
        probe = self.world.probe()
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.deliver("start", "--resume").splitlines()[-2:], ["Preflight passed.", GRANT])
        self.drop("plan", PLAN)
        self.assertEqual(self.events(branch), [
            ("start", None), ("save", "request"), ("preflight", "pass"), ("save", "plan")])
        self.assertEqual(self.world.records(branch)[2]["run"], run)
        return branch

    def edit(self, files: dict[str, str]) -> str:
        """Steps 4 and 5: write the files and commit them with plain `git commit -m`. Returns the commit."""
        for name, content in files.items():
            (self.work / name).write_text(content, encoding="utf-8")
        self.world.git(self.work, "add", *files)
        self.world.git(self.work, "commit", "-q", "-m", "feat: add double")
        return self.head()

    def through_pr(self) -> None:
        """Steps 6 to 8 up to `pr`: the check on the last commit, the summary, and the draft PR."""
        self.deliver("check", "--", *CHECK.split())
        self.drop("summary", SUMMARY)
        self.assertEqual(self.deliver("pr"), f"Opened draft PR #12: {URL}\n")

    def test_a_small_edit_runs_from_start_to_pr(self):
        branch = self.begin()
        commit = self.edit({
            "calc.py": "def add(a, b):\n    return a + b\n\n\ndef double(n):\n    return 2 * n\n",
            "test_calc.py": (self.work / "test_calc.py").read_text(encoding="utf-8")
            + "\n    def test_double(self):\n        self.assertEqual(calc.double(4), 8)\n",
        })
        self.through_pr()

        records = self.world.records(branch)
        check = records[4]
        self.assertEqual({k: check[k] for k in ("event", "command", "exit", "commit", "selected_nothing")},
                         {"event": "check", "command": CHECK, "exit": 0, "commit": commit, "selected_nothing": False})
        self.assertEqual(self.events(branch)[4:], [("check", 0), ("save", "summary"), ("pr", None)])
        self.assertEqual((records[5]["commit"], records[6]["number"], records[6]["url"]), (commit, 12, URL))

        self.assertEqual(self.world.git(self.world.origin, "rev-parse", f"refs/heads/{branch}"), commit)
        create = [call for call in self.world.gh_calls() if call["args"][:2] == ["pr", "create"]]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0]["args"][:9], [
            "pr", "create", "--draft", "--base", "main", "--head", branch, "--title", "feat: add double"])
        self.assertTrue(create[0]["body"].startswith("## Summary\n"))
        self.assertIn("double returns twice its argument", create[0]["body"])
        self.assertIn("Closes #7", create[0]["body"])
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertEqual(self.world.git(self.work, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
