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

import fcntl
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
            source = REPO_ROOT / "scripts" / name
            if source.exists():
                shutil.copy2(source, scripts / name)
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
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()

    def run_check(self, *args: str, **kwargs) -> tuple[int, str, str]:
        proc = self.start(*args, **kwargs)
        proc.wait(timeout=DEADLINE)
        return proc.returncode, self.out(proc), self.err(proc)

    def out(self, proc: subprocess.Popen) -> str:
        return (self.state / f"{proc.tag}.out").read_text()

    def err(self, proc: subprocess.Popen) -> str:
        return (self.state / f"{proc.tag}.err").read_text()

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


if __name__ == "__main__":
    unittest.main()
