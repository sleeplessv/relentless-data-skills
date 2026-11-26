"""Test the lock that makes full runs of scripts/check.sh wait their turn.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_check_lock -v

Each test copies scripts/check.sh and scripts/check_lock.py into a throwaway git
repository whose checks are stand-ins, so the script takes its lock the way it
always does around a stand-in body. This repo's checks and its unit test suite
never run here. Every run uses a lock file of its own: CHECK_LOCK_FILE in the
test's temporary folder, or the throwaway repository's own git directory.

Tests wait on a file or on a process's exit, never on a sleep of fixed length.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
GIT = shutil.which("git")
DEADLINE = 120  # seconds; a bound on waiting for a file or a process, not a sleep

HELP = """\
Run the repo's local checks; stop at the first failure.

Usage: scripts/check.sh [--fast] [--network] [--browser] [--base <commit-or-ref>]
  --fast     skip the unit test suite (used by the pre-commit hook)
  --network  also run scripts/check_doc_urls.py (needs network access)
  --browser  also run the dossier tests with Playwright and Chromium, via uv
             (needs uv and network access); a skipped test fails the run
  --base     baseline for skill_versions.py; also settable via CHECK_BASE.
             Default: git merge-base HEAD origin/main, falling back to main.

One full run at a time: a run without --fast takes a lock before its first
check and holds it until it exits, so it waits while another run of this
clone holds the lock. A run with --fast, --help or a usage error takes no
lock and never waits.

The lock is fcntl.flock on one file, taken through python3 by
scripts/check_lock.py. The file is check.sh.lock in the clone's shared git
directory (git rev-parse --git-common-dir), so every worktree of the clone
uses the same lock. Only the system says whether the lock is held. The file's
presence and content decide nothing, so a killed run, even one killed with
SIGKILL, blocks no later run. The script's own process holds the lock and the
checks it starts do not, so a process that a check leaves running cannot keep
it. The holder writes its process id and start time into the file, and only
the waiting line reads them.

A run that has to wait prints one line at once. The line names the holder's
process id and start time where the file gives them, and the longest the run
will wait. When its turn comes the run prints how long it waited.
CHECK_LOCK_WAIT sets that bound in whole seconds from 0 to 86400 (default
1800). At the bound the run prints one line on standard error, runs no check,
and exits 75. A run that cannot open or lock the file for any reason other
than another holder prints one line and runs without the lock.
CHECK_LOCK_FILE names another lock file, for the tests or for one deliberate
run beside another. No switch skips the lock.

Limits: a second clone on this machine has its own lock. A run killed with
SIGKILL frees the lock while processes it started may still be finishing.

Exit status: 0 when every check passes, the failing check's own status, 2 for
bad usage or a bad CHECK_LOCK_WAIT, 75 when the wait ran out.
"""
README_SENTENCE = (
    "A run without `--fast` waits its turn behind any other such run of this clone"
    " and needs no guard before it, as [`scripts/check.sh --help`](scripts/check.sh) explains."
)
AGENTS_SENTENCE = (
    "A full run waits its turn behind any other full run of this clone and needs no guard before it,"
    " as `scripts/check.sh --help` explains."
)

# The first check, scripts/lint_skill.py, is the stand-in body. STANDIN_DIR and
# STANDIN_NAME switch it on; without them it passes at once, like the others.
STANDIN_BODY = textwrap.dedent('''\
    import os, sys, time
    from pathlib import Path

    name = os.environ.get("STANDIN_NAME")
    if name:
        state = Path(os.environ["STANDIN_DIR"])
        (state / f"{name}.pid").write_text(str(os.getpid()))
        try:
            os.close(os.open(state / "running", os.O_CREAT | os.O_EXCL))
        except FileExistsError:
            with open(state / "log", "a") as log:
                log.write(f"overlap {name}\\n")
        with open(state / "log", "a") as log:
            log.write(f"start {name}\\n")
        if os.environ.get("STANDIN_LEAVE"):
            if os.fork() == 0:
                os.setsid()
                null = os.open(os.devnull, os.O_RDWR)
                for fd in (0, 1, 2):
                    os.dup2(null, fd)
                (state / f"{name}.leftover").write_text(str(os.getpid()))
                while True:
                    time.sleep(60)
        if os.environ.get("STANDIN_HOLD"):
            while not (state / f"{name}.go").exists():
                time.sleep(0.02)
        (state / "running").unlink()
        with open(state / "log", "a") as log:
            log.write(f"end {name}\\n")
        sys.exit(int(os.environ.get("STANDIN_EXIT", "0")))
''')


def wait_until(predicate, what: str) -> None:
    deadline = time.monotonic() + DEADLINE
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.02)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class Holder:
    """Another process that holds the lock on `path` until released."""

    def __init__(self, path: Path, content: str) -> None:
        code = textwrap.dedent('''\
            import fcntl, sys
            f = open(sys.argv[1], "a")
            fcntl.flock(f, fcntl.LOCK_EX)
            f.truncate(0)
            f.write(sys.argv[2])
            f.flush()
            print("held", flush=True)
            sys.stdin.read()
        ''')
        self.proc = subprocess.Popen(
            [sys.executable, "-c", code, str(path), content],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        assert self.proc.stdout.readline() == "held\n"

    def release(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait()
            self.proc.stdout.close()


@unittest.skipUnless(BASH and GIT, "needs bash and git")
class CheckLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state = self.tmp / "state"
        self.state.mkdir()
        self.lock = self.tmp / "check.lock"
        self.repo = self.tmp / "repo"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        for name in ("check.sh", "check_lock.py"):
            shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
        (scripts / "lint_skill.py").write_text(STANDIN_BODY)
        for name in ("sync_registry.py", "skill_versions.py"):
            (scripts / name).write_text("")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_standin.py").write_text(
            "import unittest\n\nclass T(unittest.TestCase):\n    def test_passes(self):\n        pass\n"
        )
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "claude").write_text("#!/bin/sh\nexit 0\n")
        (bin_dir / "claude").chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CHECK_", "STANDIN_", "GIT_"))}
        self.env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            CHECK_LOCK_FILE=str(self.lock),
            STANDIN_DIR=str(self.state),
            PYTHONDONTWRITEBYTECODE="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
        )
        git = lambda *args: subprocess.run([GIT, *args], cwd=self.repo, env=self.env, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("add", ".")
        git("commit", "-q", "-m", "stand-ins")

    # -- helpers ----------------------------------------------------------

    def hold(self, content: str = "") -> Holder:
        holder = Holder(self.lock, content)
        self.addCleanup(holder.release)
        return holder

    def start(self, *args: str, name: str = "", cwd: Path | None = None, **env: str) -> subprocess.Popen:
        """Start check.sh in the background, its output going to files under state/."""
        run_env = dict(self.env, **env)
        if name:
            run_env["STANDIN_NAME"] = name
        tag = name or f"run{len(list(self.state.glob('*.out')))}"
        out = open(self.state / f"{tag}.out", "w")
        err = open(self.state / f"{tag}.err", "w")
        self.addCleanup(out.close)
        self.addCleanup(err.close)
        proc = subprocess.Popen(
            [BASH, "scripts/check.sh", *args], cwd=cwd or self.repo, env=run_env,
            stdout=out, stderr=err, start_new_session=True,
        )
        proc.tag = tag
        self.addCleanup(self.stop, proc)
        return proc

    def stop(self, proc: subprocess.Popen) -> None:
        """End the run and anything left in its process group, such as a killed holder's body."""
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()

    def run_check(self, *args: str, **kwargs) -> tuple[int, str, str]:
        proc = self.start(*args, **kwargs)
        proc.wait(timeout=DEADLINE)
        return proc.returncode, self.out(proc), self.err(proc)

    def out(self, proc: subprocess.Popen) -> str:
        return (self.state / f"{proc.tag}.out").read_text()

    def err(self, proc: subprocess.Popen) -> str:
        return (self.state / f"{proc.tag}.err").read_text()

    def notices(self, err: str) -> list[str]:
        """The script's own lines on standard error, without the stand-in suite's report."""
        return [line for line in err.splitlines() if line.startswith(("check.sh:", "FAIL:"))]

    def log(self) -> list[str]:
        path = self.state / "log"
        return path.read_text().splitlines() if path.exists() else []

    # -- tests ------------------------------------------------------------

    def test_a_full_run_waits_then_gives_up_with_75_and_runs_no_check(self) -> None:
        self.hold()
        rc, out, err = self.run_check(name="late", CHECK_LOCK_WAIT="1")
        self.assertEqual(out.splitlines(), ["check.sh: waiting up to 1 s for another run of scripts/check.sh."])
        self.assertEqual(
            err.splitlines(),
            ["check.sh: gave up after waiting 1 s for another run of scripts/check.sh; no check was run."],
        )
        self.assertEqual(rc, 75)
        self.assertEqual(self.log(), [])

    def test_a_fast_run_starts_its_checks_at_once_while_the_lock_is_held(self) -> None:
        self.hold()
        for wait in ("0", "not a number"):
            with self.subTest(CHECK_LOCK_WAIT=wait):
                rc, out, err = self.run_check("--fast", name=f"fast{len(self.log())}", CHECK_LOCK_WAIT=wait)
                self.assertEqual(out.splitlines()[:2], ["==> skill lint", "PASS: skill lint"])
                self.assertIn("SKIP: unit tests (--fast)", out.splitlines())
                self.assertEqual(out.splitlines()[-1], "All checks passed.")
                self.assertEqual((rc, err), (0, ""))

    def test_help_and_a_usage_error_never_wait(self) -> None:
        self.hold()
        rc, out, err = self.run_check("--help", CHECK_LOCK_WAIT="0")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out, HELP)
        rc, out, err = self.run_check("--bogus", CHECK_LOCK_WAIT="0")
        self.assertEqual((rc, out, err), (2, "", "check.sh: unknown argument: --bogus\n"))
        self.assertEqual(self.log(), [])

    def test_the_waiting_line_names_the_holder_where_the_file_gives_it(self) -> None:
        shapes = {
            "4242 2026-11-26 14:40:01\n": " (pid 4242, started 2026-11-26 14:40:01)",
            "": "",
            "not a pid\n": "",
            "4242\n": "",
            "4242 2026-11-26 14:40:01\nmore\n": "",
        }
        for content, named in shapes.items():
            with self.subTest(content=content):
                holder = self.hold(content)
                rc, out, err = self.run_check(CHECK_LOCK_WAIT="0")
                holder.release()
                self.assertEqual(out, f"check.sh: waiting up to 0 s for another run of scripts/check.sh{named}.\n")
                self.assertEqual(
                    err, "check.sh: gave up after waiting 0 s for another run of scripts/check.sh; no check was run.\n"
                )
                self.assertEqual(rc, 75)
        self.assertEqual(self.log(), [])

    def test_the_holder_writes_its_pid_and_start_time(self) -> None:
        self.assertFalse(self.lock.exists())
        proc = self.start(name="first", STANDIN_HOLD="1")
        wait_until(lambda: "start first" in self.log(), "the body to start")
        self.assertRegex(self.lock.read_text(), rf"\A{proc.pid} [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}} [0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}\n\Z")
        (self.state / "first.go").touch()
        self.assertEqual(proc.wait(timeout=DEADLINE), 0)

    def test_three_waiters_each_get_a_turn_and_no_two_bodies_run_at_once(self) -> None:
        holder = self.hold()
        names = ("a", "b", "c")
        procs = {name: self.start(name=name, STANDIN_HOLD="1") for name in names}
        for name, proc in procs.items():
            wait_until(lambda: self.out(proc).startswith("check.sh: waiting up to 1800 s"), f"{name} to wait")
        self.assertEqual(self.log(), [])
        holder.release()
        order = []
        for turn in range(3):
            wait_until(lambda: len(self.log()) == 2 * turn + 1, f"turn {turn + 1} to start")
            current = self.log()[-1].removeprefix("start ")
            self.assertIn(current, names)
            order.append(current)
            (self.state / f"{current}.go").touch()
            self.assertEqual(procs[current].wait(timeout=DEADLINE), 0)
        self.assertEqual(sorted(order), list(names))
        self.assertEqual(self.log(), [line for name in order for line in (f"start {name}", f"end {name}")])
        for name, proc in procs.items():
            lines = self.out(proc).splitlines()
            self.assertRegex(lines[1], r"\Acheck\.sh: waited [0-9]+ s for the lock\.\Z")
            self.assertEqual(lines[2], "==> skill lint")
            self.assertEqual(lines[-1], "All checks passed.")

    def test_a_killed_holder_frees_the_lock_at_once(self) -> None:
        for sig in (signal.SIGKILL, signal.SIGTERM):
            with self.subTest(signal=sig.name):
                name = sig.name.lower()
                holder = self.start(name=name, STANDIN_HOLD="1")
                wait_until(lambda: f"start {name}" in self.log(), "the holder's body to start")
                os.kill(holder.pid, sig)
                self.assertEqual(holder.wait(timeout=DEADLINE), -sig)
                self.assertTrue(self.lock.read_text().startswith(f"{holder.pid} "))
                rc, out, err = self.run_check(CHECK_LOCK_WAIT="0")
                self.assertEqual(out.splitlines()[0], "==> skill lint")
                self.assertEqual((rc, self.notices(err)), (0, []))
                (self.state / f"{name}.go").touch()  # the killed holder's body is still running; let it end
                body = int((self.state / f"{name}.pid").read_text())
                wait_until(lambda: not alive(body), "the orphaned body to end")
                (self.state / "running").unlink(missing_ok=True)

    def test_a_holder_whose_check_fails_frees_the_lock(self) -> None:
        rc, out, err = self.run_check(name="failing", STANDIN_EXIT="1")
        self.assertEqual((rc, self.notices(err)), (1, ["FAIL: skill lint (exit 1)"]))
        rc, out, err = self.run_check(CHECK_LOCK_WAIT="0")
        self.assertEqual((rc, out.splitlines()[-1], self.notices(err)), (0, "All checks passed.", []))

    def test_a_process_a_body_leaves_running_does_not_hold_the_lock(self) -> None:
        rc, out, err = self.run_check(name="leaver", STANDIN_LEAVE="1")
        self.assertEqual(rc, 0)
        leftover = self.state / "leaver.leftover"
        wait_until(leftover.exists, "the leftover process to start")
        pid = int(leftover.read_text())
        self.addCleanup(kill, pid)
        self.assertTrue(alive(pid))
        rc, out, err = self.run_check(CHECK_LOCK_WAIT="0")
        self.assertEqual((rc, out.splitlines()[0], self.notices(err)), (0, "==> skill lint", []))

    def test_a_lock_file_that_cannot_be_opened_runs_without_the_lock(self) -> None:
        read_only = self.tmp / "read-only.lock"
        read_only.write_text("")
        read_only.chmod(0o444)
        shapes = {"a missing folder": self.tmp / "missing" / "check.lock", "a folder": self.tmp}
        if os.geteuid() != 0:  # root writes to a read-only file
            shapes["a file without write access"] = read_only
        for shape, path in shapes.items():
            with self.subTest(shape=shape):
                rc, out, err = self.run_check(CHECK_LOCK_FILE=str(path))
                self.assertEqual(self.notices(err), [f"check.sh: cannot open {path}; running without the lock."])
                self.assertEqual((rc, out.splitlines()[0], out.splitlines()[-1]), (0, "==> skill lint", "All checks passed."))

    def test_a_lock_the_system_refuses_runs_without_the_lock(self) -> None:
        # fd 9 is not open in the helper, so flock fails with EBADF: a refusal other than another holder.
        result = subprocess.run(
            [sys.executable, str(self.repo / "scripts" / "check_lock.py"), "9", str(self.lock), "4242"],
            capture_output=True, text=True, env=self.env, timeout=DEADLINE,
        )
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (3, "", f"check.sh: cannot lock {self.lock} (Bad file descriptor); running without the lock.\n"),
        )

    def test_a_bad_check_lock_wait_is_a_usage_error(self) -> None:
        for value in ("abc", "-5", "1.5", "86401", " 5"):
            with self.subTest(CHECK_LOCK_WAIT=value):
                rc, out, err = self.run_check(CHECK_LOCK_WAIT=value)
                self.assertEqual((rc, out), (2, ""))
                self.assertEqual(
                    err, f"check.sh: CHECK_LOCK_WAIT must be a whole number of seconds from 0 to 86400, not {value!r}.\n"
                )
        self.assertEqual(self.log(), [])

    def test_an_interrupted_waiter_ends_without_running_a_check(self) -> None:
        self.hold()
        for value in (None, ""):
            with self.subTest(CHECK_LOCK_WAIT=value):
                env = {} if value is None else {"CHECK_LOCK_WAIT": value}
                proc = self.start(**env)
                line = "check.sh: waiting up to 1800 s for another run of scripts/check.sh.\n"
                wait_until(lambda: self.out(proc) == line, "the waiting line")
                os.killpg(proc.pid, signal.SIGINT)
                # bash dies by SIGINT, or exits 130 where it was started with SIGINT ignored
                self.assertIn(proc.wait(timeout=DEADLINE), (-signal.SIGINT, 128 + signal.SIGINT))
                self.assertEqual((self.out(proc), self.err(proc)), (line, ""))
        self.assertEqual(self.log(), [])

    def test_the_main_checkout_and_a_linked_worktree_share_one_lock(self) -> None:
        linked = self.tmp / "linked"
        subprocess.run([GIT, "worktree", "add", "-q", str(linked)], cwd=self.repo, env=self.env, check=True)
        del self.env["CHECK_LOCK_FILE"]
        self.lock = self.repo / ".git" / "check.sh.lock"
        self.hold()
        for where, env in ((self.repo, {}), (linked, {}), (linked, {"CHECK_LOCK_FILE": ""})):
            with self.subTest(cwd=where, **env):
                rc, out, err = self.run_check(cwd=where, CHECK_LOCK_WAIT="0", **env)
                self.assertEqual(rc, 75)
                self.assertEqual(out, "check.sh: waiting up to 0 s for another run of scripts/check.sh.\n")


class CheckLockDocsTest(unittest.TestCase):
    def test_the_readme_and_agents_md_point_to_the_help(self) -> None:
        readme = " ".join((REPO_ROOT / "README.md").read_text().split())
        self.assertRegex(readme, rf"(?:\A|\. ){re.escape(README_SENTENCE)}(?: |\Z)")
        checks = next(line for line in (REPO_ROOT / "AGENTS.md").read_text().splitlines() if line.startswith("- **Checks.**"))
        self.assertTrue(checks.endswith(" " + AGENTS_SENTENCE), checks)


if __name__ == "__main__":
    unittest.main()
