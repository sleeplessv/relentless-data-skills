"""The guard hook, its registration, its refusal log, and preflight's guard probe check.

The guard runs as Claude Code runs it: a subprocess with a hook input on standard input. The
inputs in `deliver_guard_inputs/` were recorded from Claude Code 2.1.330 (the harness-guards
research, #213): `session.json` is the session's own call, `agent.json` an agent's call, which
carries `agent_id`, and `session-bypass.json` a session call in bypass mode. Ids and paths are
replaced; each test sets `cwd` and the command. `one-way-commands.json` holds the commands
#409's reviewers probed the one-way list with, each with the verdict of the 31ea0e2 list.

The folders `cortex/`, `codex/`, `cursor/` and `antigravity/` hold one input per case, each in
the shape the stage 2 probe kit's stand-in guard logged from that harness on a real run
(Cortex Code X1; Codex D2 and D6; Cursor X1; Antigravity A6, with the agent file its session
wrote), with ids zeroed, `user_email` dropped, and the command of the case. Paths, model
names and other private values are placeholders in angle brackets; the tests replace `<cwd>` and
`<brain>`, and the rest (`<transcript>`, `<home>`, `<model>`, `<version>`, `<summary>`,
`<description>`) stay as literal text.
A shape no run has logged ends `_not_yet_seen`: an agent's call on Cortex Code, and the
project's Claude Code hook as Cursor runs it. `cursor/empty-cwd.json` is Cursor's input when the
model names no folder (#464): `cwd` is empty and the workspace is in `workspace_roots`.
`cursor/wrapped-probe.json` is the probe as a model ran it inside its own shell line (#464).

    python3 -m unittest tests.test_deliver_guard
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

INPUTS = deliver_kit.GUARD_INPUTS
HOOKS = deliver_kit.REPO_ROOT / "skills" / "deliver" / "hooks" / "hooks.json"
guard = deliver_kit.load("guard")
FINISH = f"uv run --python 3.13 --no-project {deliver_kit.SCRIPTS / 'deliver.py'} finish"
OWNER = "Ask the owner to run it."
LOG_KEYS = ["at", "guard", "class", "permission_mode", "run", "harness"]

# One command of each class the guard refuses, with the guard that refuses it.
REFUSED = {
    "gh pr merge 12 --squash": ("raw-pr", "gh pr merge"),
    "cd sub && gh pr ready 12": ("raw-pr", "gh pr ready"),
    "git push --force origin feat/x": ("owner", "one-way"),
    "uv run --python 3.13 --no-project /x/scripts/deliver.py accept R2": ("owner", "deliver.py accept"),
    "python3 deliver.py waive reach": ("owner", "deliver.py waive reach"),
}
# Wrapped or quoted so the guard does not read them as the command: allowed.
WRAPPED = [
    'bash -c "gh pr merge 12"', "sh -c 'gh pr ready 12'", 'ssh host "git push --force"',
    'git commit -m "never gh pr merge by hand"', "echo 'deliver.py accept R1'",
    "gh pr view 12 --json mergeable", "python3 deliver.py waive check",
]

# Commands the 31ea0e2 list caught that the list now lets through on purpose, settled in #409
# (PR #432): text inside closed quotes is not a command, a mention of production is not a target,
# and a command wrapped in `bash -c`, `sh -c` or `ssh` passes, as the hook stops habit only.
SETTLED = {
    "git commit -m 'fix prod bug'": "a mention of production",
    "echo production": "a mention of production",
    'echo "git push --force"': "quoted text",
    "echo 'gh release create' ": "quoted text",
    'bash -c "git push --force"': "a wrapped command",
    "sh -c 'npm publish'": "a wrapped command",
    'ssh host "docker push x"': "a wrapped command",
}


def one_way(command: str) -> bool:
    patterns = deliver_kit.load("settings").read_lists()["one_way_commands"]
    return any(re.search(p, command) for p in patterns)


class OneWayList(unittest.TestCase):
    """The measure fixed for #412: the list fails safe against the 31ea0e2 list."""

    def test_nothing_the_31ea0e2_list_caught_is_missed(self):
        rows = json.loads((INPUTS / "one-way-commands.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 101)
        missed = [r["command"] for r in rows if r["old"] and r["command"] not in SETTLED and not one_way(r["command"])]
        self.assertEqual(missed, [])
        self.assertEqual(sorted(c for c in SETTLED if not one_way(c)), sorted(SETTLED))

    def test_a_one_way_command_in_a_substitution_inside_double_quotes_is_caught(self):
        commands = ['url="$(gh release create v1.2)"', 'out="$(git push --force origin main 2>&1)"',
                    'echo "`git push -f origin "main"`"', 'log="$(npm publish --tag "next" 2>&1)"']
        self.assertEqual({c: one_way(c) for c in commands}, dict.fromkeys(commands, True))


def deny(result: subprocess.CompletedProcess) -> str | None:
    """The reason of a deny answer; fails the test on any other non-silent answer."""
    if (result.returncode, result.stdout, result.stderr) == (0, "", ""):
        return None
    assert (result.returncode, result.stderr) == (0, ""), result
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert (output["hookEventName"], output["permissionDecision"]) == ("PreToolUse", "deny"), output
    return output["permissionDecisionReason"]


class Guard(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.mark = self.world.write_mark(run="run-7")

    def refusals(self) -> list[dict]:
        return self.world.state_lines(guard.LOG)

    def test_no_mark_allows_every_command_silently(self):
        self.mark.unlink()
        for command in [*REFUSED, guard.PROBE, "deliver.py merge"]:
            for recorded in ("session.json", "agent.json"):
                with self.subTest(command=command, recorded=recorded):
                    self.assertIsNone(deny(self.world.guard(command, recorded)))
        self.assertEqual(self.refusals(), [])

    def test_each_class_is_refused_to_the_session_with_a_mark(self):
        for command, (_, cls) in REFUSED.items():
            with self.subTest(command=command):
                reason = deny(self.world.guard(command))
                self.assertIsNotNone(reason)
                self.assertIn(f"\n{command}\n", reason)
                self.assertIn(str(self.mark), reason)
                self.assertIn(FINISH, reason)
                self.assertEqual(OWNER in reason, cls not in ("gh pr merge", "gh pr ready"))
        self.assertEqual([(r["guard"], r["class"]) for r in self.refusals()], list(REFUSED.values()))

    def test_deliver_merge_is_refused_only_to_an_agent(self):
        command = "uv run --python 3.13 --no-project /x/scripts/deliver.py merge"
        self.assertIsNone(deny(self.world.guard(command, "session.json")))
        reason = deny(self.world.guard(command, "agent.json"))
        self.assertIn("refused to an agent the session started", reason)
        self.assertEqual([(r["guard"], r["class"]) for r in self.refusals()], [("agent-merge", "deliver.py merge")])

    def test_an_agent_is_refused_every_class_too(self):
        for command in REFUSED:
            with self.subTest(command=command):
                self.assertIsNotNone(deny(self.world.guard(command, "agent.json")))

    def test_a_wrapped_or_quoted_command_is_allowed(self):
        for command in WRAPPED:
            with self.subTest(command=command):
                self.assertIsNone(deny(self.world.guard(command)))
        self.assertEqual(self.refusals(), [])

    def test_a_command_in_a_substitution_inside_double_quotes_is_refused(self):
        commands = {'url="$(gh release create v1.2)"': "one-way", 'out="$(git push --force origin main 2>&1)"': "one-way",
                    'n="$(gh pr merge 12)"': "gh pr merge", 'echo "`python3 deliver.py waive reach`"': "deliver.py waive reach"}
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNotNone(deny(self.world.guard(command)))
        self.assertEqual([r["class"] for r in self.refusals()], list(commands.values()))

    def test_an_unreadable_command_is_searched_raw(self):
        self.assertIsNotNone(deny(self.world.guard("gh pr merge 12 --body 'unclosed")))

    def test_the_repos_one_way_extra_is_refused(self):
        self.world.commit(self.world.work, "docs/agents/stack.toml", "[one_way]\nextra = ['\\bterraform\\s+apply\\b']\n",
                          "chore: stack settings")
        self.assertIsNotNone(deny(self.world.guard("terraform apply -auto-approve")))
        self.assertIsNone(deny(self.world.guard("terraform plan")))

    def test_a_repo_extra_that_is_not_a_list_adds_nothing(self):
        self.world.commit(self.world.work, "docs/agents/stack.toml", "[one_way]\nextra = 'apply'\n", "chore: stack settings")
        self.assertIsNone(deny(self.world.guard("ls -a")))

    def test_a_stack_file_that_is_not_utf8_still_refuses_the_list(self):
        (self.world.work / "docs" / "agents").mkdir(parents=True)
        (self.world.work / "docs" / "agents" / "stack.toml").write_bytes(b'[one_way]\nextra = ["\xff"]\n')
        result = self.world.guard("git push --force")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIsNotNone(deny(result))

    def test_a_dot_git_file_that_is_not_utf8_finds_no_mark(self):
        folder = self.world.root / "odd"
        folder.mkdir()
        (folder / ".git").write_bytes(b"gitdir: \xff\n")
        result = self.world.guard("gh pr merge 1", cwd=folder)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_the_probe_is_a_raw_merge_refusal_of_its_own_class(self):
        reason = deny(self.world.probe())
        self.assertIn("guard probe", reason)
        self.assertEqual([(r["guard"], r["class"]) for r in self.refusals()], [("raw-pr", "probe")])

    def test_each_refusal_logs_one_line_with_no_session_id(self):
        self.world.guard("gh pr merge 1")
        self.world.guard("git push --force", "session-bypass.json")
        lines = self.refusals()
        self.assertEqual([list(line) for line in lines], [LOG_KEYS, LOG_KEYS])
        self.assertEqual([(r["permission_mode"], r["run"]) for r in lines], [("default", "run-7"), ("bypassPermissions", "run-7")])
        self.assertRegex(lines[0]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        session_id = json.loads((INPUTS / "session.json").read_text(encoding="utf-8"))["session_id"]
        self.assertNotIn(session_id, (self.world.state / guard.LOG).read_text(encoding="utf-8"))

    def test_the_mark_is_found_from_the_inputs_cwd_or_the_shells_folder(self):
        sub = self.world.work / "a" / "b"
        sub.mkdir(parents=True)
        self.assertIsNotNone(deny(self.world.guard("gh pr merge 1", cwd=sub)))
        self.assertIsNotNone(deny(self.world.guard("gh pr merge 1", cwd=self.world.root, shell_cwd=sub)))
        self.assertIsNone(deny(self.world.guard("gh pr merge 1", cwd=self.world.root)))

    def test_a_worktrees_mark_holds_in_that_worktree_only(self):
        self.mark.unlink()
        tree = self.world.worktree("tree", "feat/x")
        self.world.write_mark(tree, branch="feat/x")
        self.assertIsNotNone(deny(self.world.guard("gh pr merge 1", cwd=tree)))
        self.assertIsNone(deny(self.world.guard("gh pr merge 1")))

    def test_malformed_input_exits_silently(self):
        for text in ("", "not json", "[]", '{"tool_input": {}}', '{"tool_input": {"command": 5}}'):
            with self.subTest(text=text):
                result = subprocess.run([sys.executable, str(deliver_kit.GUARD)], input=text, cwd=self.world.work,
                                        env=self.world.env(), capture_output=True, text=True)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_the_guard_starts_no_git_and_imports_nothing_of_the_program(self):
        bin_ = self.world.root / "guard-bin"
        bin_.mkdir()
        (bin_ / "git").write_text(f"#!/bin/sh\ntouch {self.world.root / 'git-ran'}\nexit 1\n", encoding="utf-8")
        (bin_ / "git").chmod(0o755)
        self.assertIsNotNone(deny(self.world.guard("gh pr merge 1", PATH=f"{bin_}{os.pathsep}/usr/bin:/bin")))
        self.assertFalse((self.world.root / "git-ran").exists())
        tree = ast.parse(deliver_kit.GUARD.read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imported - sys.stdlib_module_names, {"__future__"} - sys.stdlib_module_names)

    def test_the_probe_flag_makes_the_probe_only_on_its_own_gh_pr_merge(self):
        wrapped = f'cd sub && {guard.PROBE} 2>&1; echo "exit=$?"'
        commands = {guard.PROBE: "probe", wrapped: "probe", f"git status | {guard.PROBE}": "probe",
                    "gh pr merge 12 --squash": "gh pr merge", f"gh pr merge 12 --squash; echo {guard.PROBE.split()[-1]}":
                    "gh pr merge", f'echo "{guard.PROBE}"': None}
        for command, cls in commands.items():
            with self.subTest(command=command):
                self.assertEqual(deny(self.world.guard(command)) is None, cls is None)
        self.assertIn("guard probe", deny(self.world.guard(wrapped, "agent.json")))
        self.assertEqual([r["class"] for r in self.refusals()], [c for c in commands.values() if c] + ["probe"])


# The harness each input folder logs as.
LOGGED = {"cortex": "cortex-code"}
FORMS = {"cortex": "claude", "codex": "claude", "cursor": "cursor", "antigravity": "antigravity"}
# Each case's answer and logged class; a missing class is an allow.
CASES = {"probe": "probe", "raw-merge": "gh pr merge", "raw-ready": "gh pr ready", "one-way": "one-way",
         "control": None, "merge-session": None, "merge-agent": "deliver.py merge",
         "merge-agent_not_yet_seen": "deliver.py merge"}
SESSION, AGENT = "00000000-0000-4000-8000-000000000000", "00000000-0000-4000-8000-000000000001"


def answer(form: str, result: subprocess.CompletedProcess) -> tuple[str, str]:
    """The decision and reason of an answer, which must be in the given form."""
    assert (result.returncode, result.stderr) == (0, ""), result
    if form == "claude":
        if result.stdout == "":
            return "allow", ""
        output = json.loads(result.stdout)["hookSpecificOutput"]
        assert (output["hookEventName"], output["permissionDecision"]) == ("PreToolUse", "deny"), output
        return "deny", output["permissionDecisionReason"]
    output = json.loads(result.stdout)
    if form == "cursor":
        assert list(output) == ["permission", "user_message", "agent_message"], output
        assert output["user_message"] == output["agent_message"], output
        return output["permission"], output["user_message"]
    assert list(output) == ["decision", "reason"], output
    return output["decision"], output["reason"]


class Harnesses(unittest.TestCase):
    """The saved inputs of Cortex Code, Codex, Cursor and Antigravity, each run as the harness runs the hook."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.mark = self.world.write_mark(run="run-7")
        self.brain = self.world.root / "brain"
        self.agent_file = self.brain / SESSION / ".system_generated" / "subagents" / f"{AGENT}.json"
        self.agent_file.parent.mkdir(parents=True)
        shutil.copy(INPUTS / "antigravity" / "agent-file.json", self.agent_file)

    def text(self, harness: str, name: str) -> str:
        text = (INPUTS / harness / f"{name}.json").read_text(encoding="utf-8")
        return text.replace("<cwd>", str(self.world.work)).replace("<brain>", str(self.brain))

    def run_guard(self, text: str, **env: str | None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(deliver_kit.GUARD)], input=text, cwd=self.world.root,
                              env=self.world.env(**env), capture_output=True, text=True)

    def saved(self, harness: str, name: str, **env: str | None) -> tuple[str, str]:
        return answer(FORMS[harness], self.run_guard(self.text(harness, name), **env))

    def command(self, harness: str, name: str) -> str:
        data = json.loads(self.text(harness, name))
        if harness == "antigravity":
            return data["toolCall"]["args"]["CommandLine"]
        return data["command"] if harness == "cursor" else data["tool_input"]["command"]

    def cases(self, harness: str) -> list[str]:
        return [name for name in CASES if (INPUTS / harness / f"{name}.json").is_file()]

    def test_each_case_gives_its_answer_in_the_harness_form(self):
        for harness in FORMS:
            names = self.cases(harness)
            self.assertTrue({"probe", "raw-merge", "raw-ready", "one-way", "control", "merge-session"} <= set(names))
            for name in names:
                with self.subTest(harness=harness, case=name):
                    decision, reason = self.saved(harness, name)
                    self.assertEqual(decision, "deny" if CASES[name] else "allow")
                    if CASES[name]:
                        self.assertIn(f"\n{self.command(harness, name)}\n", reason)
                        self.assertIn(str(self.mark), reason)
                        self.assertIn(FINISH, reason)
            refused = [n for n in names if CASES[n]]
            lines = [r for r in self.refusals() if r["harness"] == LOGGED.get(harness, harness)]
            self.assertEqual([(r["class"], r["run"]) for r in lines], [(CASES[n], "run-7") for n in refused])
        self.assertEqual({r["harness"] for r in self.refusals()}, {LOGGED.get(h, h) for h in FORMS})

    def test_the_merge_script_from_an_agent_is_a_case_on_each_harness_that_marks_agents(self):
        names = {harness: [n for n in self.cases(harness) if n.startswith("merge-agent")] for harness in FORMS}
        self.assertEqual(names, {"cortex": ["merge-agent_not_yet_seen"], "codex": ["merge-agent"], "cursor": [],
                                 "antigravity": ["merge-agent"]})

    def test_no_mark_allows_every_case_in_the_harness_form(self):
        self.mark.unlink()
        for harness in FORMS:
            for name in self.cases(harness):
                with self.subTest(harness=harness, case=name):
                    result = self.run_guard(self.text(harness, name))
                    self.assertEqual(answer(FORMS[harness], result), ("allow", ""))
                    self.assertEqual(result.stdout == "", FORMS[harness] == "claude")
        self.assertEqual(self.refusals(), [])

    def refusals(self) -> list[dict]:
        return self.world.state_lines(guard.LOG)

    def test_codex_tools_other_than_the_shell_are_not_judged(self):
        # D2: the agent-start tool reaches the hook as collaborationspawn_agent; apply_patch's input has a
        # `command` that is the patch. Each text here holds a raw `gh pr merge`.
        for name in ("spawn-agent", "apply-patch"):
            with self.subTest(case=name):
                self.assertIn("gh pr merge", self.text("codex", name))
                self.assertEqual(self.saved("codex", name), ("allow", ""))
        self.assertEqual(self.refusals(), [])

    def test_antigravity_marks_the_agent_by_its_sessions_agent_file(self):
        self.assertEqual(self.saved("antigravity", "merge-agent")[0], "deny")
        self.agent_file.unlink()
        self.assertEqual(self.saved("antigravity", "merge-agent"), ("allow", ""))
        self.assertEqual(self.saved("antigravity", "raw-merge")[0], "deny")
        self.assertEqual([r["class"] for r in self.refusals()], ["deliver.py merge", "gh pr merge"])

    def test_antigravity_an_agent_file_under_another_name_is_not_this_agents(self):
        self.agent_file.rename(self.agent_file.with_name(f"{SESSION}.json"))
        self.assertEqual(self.saved("antigravity", "merge-agent"), ("allow", ""))
        text = self.text("antigravity", "merge-agent").replace(f'"conversationId": "{AGENT}"', '"conversationId": "../x"')
        self.assertEqual(answer("antigravity", self.run_guard(text)), ("allow", ""))

    def test_antigravity_another_tool_gets_an_explicit_allow(self):
        self.assertIn("gh pr merge", self.text("antigravity", "read-file"))
        self.assertEqual(self.saved("antigravity", "read-file"), ("allow", ""))

    def claude_form(self, command: str) -> str:
        data = json.loads(self.text("cursor", "claude-form_not_yet_seen"))
        data["tool_input"]["command"] = command
        return json.dumps(data)

    def test_cursor_both_hooks_give_one_answer_and_one_log_line(self):
        refused = [n for n in self.cases("cursor") if CASES[n]]
        for name in self.cases("cursor"):
            with self.subTest(case=name):
                own = self.saved("cursor", name)
                claude = answer("claude", self.run_guard(self.claude_form(self.command("cursor", name))))
                self.assertEqual(claude, own)
                self.assertEqual(self.saved("cursor", name), own)
        self.assertEqual([(r["class"], r["harness"]) for r in self.refusals()], [(CASES[n], "cursor") for n in refused])

    def test_cursor_logs_one_line_whatever_harness_the_claude_form_input_is_read_as(self):
        # A Claude-form input from Cursor without `cursor_version` is read as Claude Code's; it still
        # carries Cursor's conversation_id, and the command is logged once.
        data = json.loads(self.claude_form(guard.PROBE))
        del data["cursor_version"]
        self.assertEqual(self.saved("cursor", "probe")[0], "deny")
        self.assertEqual(answer("claude", self.run_guard(json.dumps(data)))[0], "deny")
        self.assertEqual([(r["class"], r["harness"]) for r in self.refusals()], [("probe", "cursor")])

    def test_cursor_logs_a_command_again_in_another_run_or_conversation(self):
        self.saved("cursor", "probe")
        self.world.write_mark(run="run-8")
        self.saved("cursor", "probe")
        other = self.text("cursor", "probe").replace(SESSION, "00000000-0000-4000-8000-000000000009")
        answer("cursor", self.run_guard(other))
        self.assertEqual([r["run"] for r in self.refusals()], ["run-7", "run-8", "run-8"])

    def empty_cwd(self, command: str, **changes: object) -> str:
        data = json.loads(self.text("cursor", "empty-cwd"))
        data.update(command=command, **changes)
        return json.dumps(data)

    def test_cursor_with_an_empty_cwd_finds_the_mark_from_workspace_roots(self):
        # #464: Cursor sends `"cwd": ""` when the model names no folder, and runs the hook from
        # a folder outside the workspace; run_guard runs it from the world's root, outside the checkout.
        refused = {guard.PROBE: "probe", "gh pr merge 12 --squash": "gh pr merge", "gh pr ready 12": "gh pr ready",
                   "git push --force origin feat/x": "one-way"}
        for command in refused:
            with self.subTest(command=command):
                decision, reason = answer("cursor", self.run_guard(self.empty_cwd(command)))
                self.assertEqual(decision, "deny")
                self.assertIn(f"\n{command}\n", reason)
                self.assertIn(str(self.mark), reason)
        self.assertEqual(answer("cursor", self.run_guard(self.empty_cwd("git status --short"))), ("allow", ""))
        self.assertEqual([(r["class"], r["harness"]) for r in self.refusals()],
                         [(cls, "cursor") for cls in refused.values()])

    def test_cursor_a_non_empty_cwd_is_searched_before_workspace_roots(self):
        outside = str(self.world.root)
        self.assertEqual(answer("cursor", self.run_guard(self.empty_cwd(guard.PROBE, cwd=str(self.world.work),
                                                                        workspace_roots=[outside])))[0], "deny")
        # Both checkouts are marked: the answer names the mark of the one `cwd` names.
        tree = self.world.worktree("tree", "feat/x")
        tree_mark = self.world.write_mark(tree, branch="feat/x")
        reason = answer("cursor", self.run_guard(self.empty_cwd(guard.PROBE, cwd=str(tree),
                                                                workspace_roots=[str(self.world.work)])))[1]
        self.assertIn(str(tree_mark), reason)
        self.assertNotIn(str(self.mark), reason)

    def test_cursor_workspace_roots_missing_not_a_list_or_not_strings_is_ignored(self):
        work = str(self.world.work)
        for roots in (None, work, {"0": work}, [5, None, {}, ["x"]], [""]):
            with self.subTest(roots=roots):
                data = json.loads(self.empty_cwd(guard.PROBE))
                if roots is None:
                    del data["workspace_roots"]
                else:
                    data["workspace_roots"] = roots
                self.assertEqual(answer("cursor", self.run_guard(json.dumps(data))), ("allow", ""))
        self.assertEqual(answer("cursor", self.run_guard(self.empty_cwd(guard.PROBE, workspace_roots=[5, work])))[0],
                         "deny")
        self.assertEqual([r["class"] for r in self.refusals()], ["probe"])

    def test_no_log_line_holds_a_session_or_conversation_id(self):
        for harness in FORMS:
            for name in self.cases(harness):
                self.saved(harness, name)
        self.assertEqual([list(line) for line in self.refusals()], [LOG_KEYS] * len(self.refusals()))
        text = (self.world.state / guard.LOG).read_text(encoding="utf-8")
        for value in (SESSION, AGENT, "00000000-0000-4000-8000-000000000002"):
            self.assertNotIn(value, text)
        self.assertNotIn(SESSION, " ".join(p.name for p in self.world.state.rglob("*")))

    def test_the_harness_of_a_claude_form_input(self):
        cases = [("session.json", {}, "claude-code"), ("session.json", {"CORTEX_SESSION_ID": "x"}, "cortex-code"),
                 ("session.json", {"CODEX_THREAD_ID": "x"}, "codex"), ("session.json", {"CURSOR_AGENT": "1"}, "cursor")]
        for recorded, env, _ in cases:
            self.world.guard("gh pr merge 1", recorded, **env)
        self.saved("cortex", "raw-merge", CODEX_THREAD_ID="x")
        self.saved("codex", "raw-merge", CORTEX_SESSION_ID="x")
        self.run_guard(self.claude_form("gh pr ready 1"), CORTEX_SESSION_ID="x")
        self.assertEqual([r["harness"] for r in self.refusals()],
                         [h for _, _, h in cases] + ["cortex-code", "codex", "cursor"])

    def test_a_probe_inside_a_shell_line_is_the_probe(self):
        # #464: Cursor's model ran the probe inside its own shell line, and the refusal was logged as a raw merge.
        command = self.command("cursor", "wrapped-probe")
        codex = json.loads(self.text("codex", "probe"))
        codex["tool_input"]["command"] = command
        for form, text in (("cursor", self.text("cursor", "wrapped-probe")), ("claude", json.dumps(codex))):
            with self.subTest(form=form):
                decision, reason = answer(form, self.run_guard(text))
                self.assertEqual(decision, "deny")
                self.assertIn(f"\n{command}\n{guard.REASONS['probe']}\n", reason)
        self.assertEqual([(r["guard"], r["class"], r["harness"]) for r in self.refusals()],
                         [("raw-pr", "probe", "cursor"), ("raw-pr", "probe", "codex")])


class Registration(unittest.TestCase):
    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.mark = self.world.write_mark()
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(list(hooks), ["PreToolUse"])
        [entry] = hooks["PreToolUse"]
        self.assertEqual(entry["matcher"], "Bash")
        [hook] = entry["hooks"]
        self.assertEqual(hook["type"], "command")
        self.command = hook["command"]
        self.bin = self.world.root / "hook-bin"
        self.bin.mkdir()

    def run_hook(self, plugin_root: Path) -> subprocess.CompletedProcess:
        data = json.loads((INPUTS / "session.json").read_text(encoding="utf-8"))
        data["cwd"] = str(self.world.work)
        data["tool_input"]["command"] = "gh pr merge 1"
        env = self.world.env(PATH=f"{self.bin}{os.pathsep}/usr/bin:/bin", CLAUDE_PLUGIN_ROOT=str(plugin_root))
        return subprocess.run(["/bin/sh", "-c", self.command], input=json.dumps(data), cwd=self.world.root, env=env,
                              capture_output=True, text=True)

    def test_the_guard_runs_through_uv_with_python_3_13(self):
        (self.bin / "uv").write_text(
            f"#!{sys.executable}\nimport os, sys\nopen({str(self.world.root / 'uv-args')!r}, 'w').write(' '.join(sys.argv[1:]))\n"
            f"os.execv({sys.executable!r}, [{sys.executable!r}, sys.argv[-1]])\n", encoding="utf-8")
        (self.bin / "uv").chmod(0o755)
        self.assertIsNotNone(deny(self.run_hook(HOOKS.parent.parent)))
        self.assertEqual((self.world.root / "uv-args").read_text(encoding="utf-8"),
                         f"run --python 3.13 --no-project --quiet {deliver_kit.GUARD}")

    @unittest.skipIf(shutil.which("uv", path="/usr/bin:/bin"), "a uv in /usr/bin or /bin would be found first")
    def test_without_uv_the_guard_runs_on_python3(self):
        (self.bin / "python3").symlink_to(sys.executable)
        self.assertIsNotNone(deny(self.run_hook(HOOKS.parent.parent)))

    @unittest.skipIf(shutil.which("uv", path="/usr/bin:/bin"), "a uv in /usr/bin or /bin would be found first")
    def test_an_old_python3_without_uv_exits_silently(self):
        # A python3 older than 3.13, such as macOS's /usr/bin/python3 (3.9, no tomllib).
        (self.bin / "python3").write_text(
            '#!/bin/sh\n[ "$1" = -c ] && exit 1\n'
            'echo "ModuleNotFoundError: No module named tomllib" >&2\nexit 1\n', encoding="utf-8")
        (self.bin / "python3").chmod(0o755)
        for marked in (True, False):
            with self.subTest(marked=marked):
                if not marked:
                    self.mark.unlink()
                result = self.run_hook(HOOKS.parent.parent)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_a_missing_guard_file_exits_silently(self):
        empty = self.world.root / "plugin"
        empty.mkdir()
        result = self.run_hook(empty)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))


class GuardProbeCheck(unittest.TestCase):
    """Preflight's guard probe check, run at `deliver.py preflight`'s command line."""

    def setUp(self):
        self.world = deliver_kit.World(self.addCleanup)
        self.world.write_mark(run="run-9", started="2026-11-27T18:00:00Z")
        deliver_kit.github_ok(self.world)
        self.world.install_upstream()

    def preflight(self) -> tuple[int, str, str, dict]:
        result = self.world.deliver("preflight")
        return result.returncode, result.stdout, result.stderr, self.world.records()[-1]

    def test_preflight_guards_off(self):
        code, out, err, record = self.preflight()
        self.assertEqual((code, err), (10, ""))
        self.assertEqual(out, (
            "warning: no docs/agents/stack.toml: every stack setting has its default\n"
            "REFUSED preflight.guards-off: the guards are off: no refusal of the guard probe is logged for run run-9 "
            "since its mark was written\n"
            f"Next: turn the hooks on, run {guard.PROBE}, then run deliver.py preflight\n"))
        self.assertEqual((record["result"], record["stops"], record["guard_probe"]), ("stop", ["preflight.guards-off"], "missing"))
        self.assertEqual([s["code"] for s in self.world.state_lines("preflight-stops.jsonl")], ["preflight.guards-off"])

    def test_a_probe_of_another_run_does_not_count(self):
        self.world.write_mark(run="run-8")
        self.world.probe()
        self.world.write_mark(run="run-9")
        self.assertEqual(len(self.world.state_lines(guard.LOG)), 1)
        self.assertEqual(self.preflight()[0], 10)

    def test_a_damaged_log_line_is_skipped(self):
        self.world.state.mkdir()
        (self.world.state / guard.LOG).write_text(
            '{"class": "pro\n[1]\n{"class": "probe", "run": "run-9", "at": 5}\n'
            '{"class": "probe", "run": "run-9", "at": null}\n', encoding="utf-8")
        self.world.probe()
        self.assertEqual(self.preflight()[0], 0)

    def test_a_probe_before_the_mark_does_not_count(self):
        self.world.probe()
        self.world.write_mark(run="run-9", started="2999-01-01T00:00:00Z")
        self.assertEqual(len(self.world.state_lines(guard.LOG)), 1)
        self.assertEqual(self.preflight()[0], 10)

    def test_a_logged_probe_passes_and_saves_the_permission_mode(self):
        self.world.probe()
        code, out, err, record = self.preflight()
        self.assertEqual((code, out.splitlines()[-1], err), (0, "Preflight passed.", ""))
        self.assertEqual((record["result"], record["guard_probe"], record["permission_mode"]), ("pass", "seen", "default"))

    def test_bypass_mode_is_a_warning(self):
        self.world.probe("session-bypass.json")
        code, out, err, record = self.preflight()
        self.assertEqual(code, 0)
        self.assertIn(f"warning: {deliver_kit.load('check_guard').BYPASS_WARNING}\n", out)
        self.assertEqual((record["result"], record["permission_mode"]), ("pass", "bypassPermissions"))


if __name__ == "__main__":
    unittest.main()
