"""Tests for skills/snowman/hooks/snow_guard.py, the PreToolUse hook that
refuses direct `snow` calls. Standard library only; nothing runs `snow`.

    python3 -m unittest tests.test_snowman_guard
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "skills" / "snowman" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import snow_guard  # noqa: E402

REFUSED = {
    "plain": "snow sql -f .snowman/staged/x.sql --connection acme",
    "after &&": "cd proj && snow sql -q 'select 1'",
    "after ;": "ls; snow object drop table t",
    "after ||": "false || snow sql",
    "after a pipe": "cat x.sql | snow sql -i",
    "after a newline": "ls\nsnow sql -q x",
    "after a comment line": "ls # look\nsnow sql -q x",
    "background": "nohup snow sql &",
    "subshell": "(snow sql)",
    "group": "{ snow sql; }",
    "if body": "if true; then snow sql; fi",
    "$() substitution": "echo $(snow sql -q x)",
    "$() in double quotes": 'echo "$(snow sql)"',
    "backticks": "echo `snow sql`",
    "unquoted heredoc substitution": "cat <<EOF\n$(snow sql)\nEOF",
    "env assignment": "SNOWFLAKE_ROLE=x snow sql",
    "env wrapper": "env -u X snow sql",
    "command wrapper": "command snow sql",
    "exec wrapper": "exec snow sql",
    "sudo": "sudo -u me snow sql",
    "timeout": "timeout 5 snow sql",
    "time": "time snow sql",
    "xargs": "ls | xargs snow sql -f",
    "absolute path": "/opt/homebrew/bin/snow sql",
    "quoted name": 's"n"ow sql',
    "bash -c": "bash -c 'snow sql -q x'",
    "eval": "eval snow sql",
    "uvx": "uvx --from snowflake-cli snow sql",
    "uv run": "uv run --with snowflake-cli snow sql",
    "pipx run": "pipx run snowflake-cli sql",
    "snowsql": "snowsql -q 'select 1'",
    "snowsql --version": "snowsql --version",
    "other subcommand": "snow stage copy a @s",
    "connection add": "snow connection add",
    "unbalanced quote": "snow sql -q 'select",
    "after a quoted <<EOF pattern": "grep -n '<<EOF' notes.md\nsnow sql",
    "after a here-string": "cat <<<EOF\nsnow sql",
    "after a line continuation": "cd proj && \\\nsnow sql",
    "bash -lc": "bash -lc 'snow sql'",
    "bash -o value -c": "bash -o pipefail -c 'snow sql'",
    "bash reading a heredoc": "bash <<'EOF'\nsnow sql\nEOF",
    "after a redirect": ">out.txt snow sql",
    "command with a later -v": "command snow sql -v",
    "after a heredoc": "cat <<'EOF'\nhello\nEOF\nsnow sql",
}

ALLOWED = {
    "connection list": "snow connection list",
    "connection test": "snow connection test -c acme",
    "version": "snow --version",
    "help": "snow --help",
    "short help": "snow -h",
    "wrapper": 'uv run --python 3.13 --no-project /s/scripts/snowman.py "$SQL"',
    "wrapper staging": "python3 snowman.py --stage \"$SQL\" --name fix",
    "grep": "grep -rn snow skills",
    "rg pattern": "rg -n 'snow sql' docs",
    "echo": "echo snow",
    "snowflake word": "echo snowflake",
    "snowman path": "cat .snowman/context.md",
    "commit message": "git commit -m 'refuse snow sql'",
    "pipx other": "pipx run snowman",
    "literal backticks in single quotes": "rg -F '`snow sql`' docs",
    "quoted pipe argument": "printf '%s\\n' '|' snow",
    "backslash-newline inside single quotes": "printf 'x\\\nsnow sql'",
    "command -v": "command -v snow",
    "command -V": "command -V snow",
    "comment": "ls # then snow sql",
    "redirect into a file named snow": "echo hi > snow",
    "heredoc commit message": (
        "git commit -m \"$(cat <<'EOF'\nfix(snowman): refuse (direct) calls\n\n"
        "snow sql -f x.sql (was allowed)\nEOF\n)\""
    ),
    "quoted heredoc body": (
        "unset SQL && { IFS= read -r -d '' SQL || [ -n \"$SQL\" ]; } <<'SQL' &&\n"
        "snow sql\n$(snow sql)\nSQL\n"
        'uv run --python 3.13 --no-project /s/scripts/snowman.py "$SQL"'
    ),
}


def run_hook(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "snow_guard.py")],
        input=stdin, capture_output=True, text=True, check=False,
    )


class TestBlockedCall(unittest.TestCase):
    def test_refuses_direct_calls(self):
        for name, command in REFUSED.items():
            with self.subTest(name, command=command):
                self.assertIsNotNone(snow_guard.blocked_call(command))

    def test_allows_listed_calls_and_lookalikes(self):
        for name, command in ALLOWED.items():
            with self.subTest(name, command=command):
                self.assertIsNone(snow_guard.blocked_call(command))


class TestHookProcess(unittest.TestCase):
    def call(self, command, tool="Bash"):
        return run_hook(json.dumps({"tool_name": tool, "tool_input": {"command": command}}))

    def test_refusal_exits_2_and_names_the_wrapper(self):
        result = self.call("snow sql -f x.sql")
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKED: direct `snow` call", result.stderr)
        self.assertIn("scripts/snowman.py", result.stderr)

    def test_allowed_command_exits_0_silently(self):
        result = self.call("snow connection list")
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_cortex_lowercase_bash_is_checked(self):
        self.assertEqual(self.call("snow sql", tool="bash").returncode, 2)

    def test_malformed_input_passes(self):
        self.assertEqual(run_hook("not json").returncode, 0)
        self.assertEqual(run_hook('{"tool_name": "Read", "tool_input": {"file_path": "x"}}').returncode, 0)
        self.assertEqual(run_hook('{"tool_name": "Bash"}').returncode, 0)


class TestHookRegistration(unittest.TestCase):
    def test_hooks_json_runs_the_guard_on_bash(self):
        config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
        [entry] = config["hooks"]["PreToolUse"]
        self.assertEqual(set(entry["matcher"].split("|")), {"Bash", "bash"})
        [hook] = entry["hooks"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/snow_guard.py", hook["command"])


if __name__ == "__main__":
    unittest.main()
