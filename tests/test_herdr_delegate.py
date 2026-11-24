"""Exercise the Codex caller check exactly as the skill runs it."""

import os
from pathlib import Path
import subprocess
import unittest


REFERENCE = (Path(__file__).resolve().parents[1] / "skills/herdr-delegate"
             / "references/codex-caller.md")
BLOCK = REFERENCE.read_text().split("```sh\n", 1)[1].split("\n```", 1)[0]
# A shell with a Codex parent. The test chooses that parent's command line.
PS = """
ps() {
  [ "$2" != "$FAIL_FIELD" ] || return 1
  case "$2" in
    comm=) if [ "$4" = "$$" ]; then echo sh; else echo /bin/codex; fi ;;
    args=) if [ "$4" = "$$" ]; then echo 'sh -c codex app-server --managed-daemon'; else echo "$CODEX_ARGS"; fi ;;
    ppid=) if [ "$4" = "$$" ]; then echo '   2'; else echo '   1'; fi ;;
    *) return 1 ;;
  esac
}
"""


class CallerCheckTests(unittest.TestCase):
    def run_check(self, args, terminal="t79", fail_field=""):
        env = dict(os.environ, CODEX_ARGS=args, FAIL_FIELD=fail_field)
        env.pop("HC_TERMINAL_ID", None)
        if terminal is not None:
            env["HC_TERMINAL_ID"] = terminal
        return subprocess.run(["sh", "-c", PS + BLOCK], env=env,
                              capture_output=True, text=True, timeout=5)

    def test_failed_process_read_never_returns_inherited_id(self):
        for field in ("comm=", "args=", "ppid="):
            with self.subTest(field=field):
                result = self.run_check("codex app-server --managed-daemon", fail_field=field)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_managed_daemon_leaves_address_for_user_confirmation(self):
        result = self.run_check("codex app-server --managed-daemon")
        self.assertEqual((result.returncode, result.stdout), (0, "managed-daemon\n"))

    def test_direct_caller_preserves_inherited_or_absent_id(self):
        for terminal in ("t79", None):
            with self.subTest(terminal=terminal):
                result = self.run_check("codex --no-daemon", terminal=terminal)
                self.assertEqual((result.returncode, result.stdout), (0, f"CALLER={terminal or ''}\n"))
