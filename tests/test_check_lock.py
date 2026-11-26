"""Test the lock that makes full runs of scripts/check.sh wait their turn.

Standard library only. Run from the repo root:

    python3 -m unittest tests.test_check_lock -v

Each test copies scripts/check.sh and scripts/check_lock.py into a throwaway git
repository whose checks are stand-ins, so the script takes its lock the way it
always does around a stand-in body. This repo's checks and its unit test suite
never run here. Every run uses a lock file of its own: CHECK_LOCK_FILE in the
test's temporary folder, or the throwaway repository's own git directory.

Tests wait on a file or on a process's exit, never on a sleep of fixed length.
Where a test checks how long a run waited, it takes its bounds from the times the
run's output files were written, from another run's timed-out exit, or from the
test's own clock readings around the run. Where a bound leaves slack for a late
start, late scheduling or rounding, the comment where it is set says how much.
The bound a run arms is not timed at all: a sitecustomize module on PYTHONPATH
records each non-zero argument of signal.alarm, and the tests read the record.
Every run sets TZ=UTC, so timestamps order the same in any zone.
"""
from __future__ import annotations

import math
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
START_TIME_PATTERN = "[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"  # as the lock file gives it

# What `--help` must state. Each row is a short label and the terms of one fact: regular
# expressions, matched without case, that must all match in one window of the help, a
# sentence or a sentence and its neighbour. A term joins the fact's subject to what the
# help says of it, so a fact with part of its meaning changed fails; a term starting with
# "!" must not match. A rewording that keeps the fact passes.
HELP_FACTS = {
    "lock scope": (
        r"--fast", r"\bbefore\b[^.]{0,20}\bfirst check\b", r"\bholds?\b[^.]{0,25}\buntil\b[^.]{0,15}\bexits?\b"),
    "lock exemptions": (
        r"--fast", r"--help", r"\busage error\b", r"\bno lock\b", r"\bnever waits?\b"),
    "lock mechanism": (r"\bfcntl\.flock\b", r"\bpython3\b", r"scripts/check_lock\.py"),
    "lock place": (r"\bcheck\.sh\.lock\b", r"--git-common-dir", r"\bworktrees?\b"),
    "lock authority": (
        r"\bonly\b|\balone\b", r"\bsystem\b[^.]{0,40}\b(?:says?|tells?|reports?|decides?)\b", r"\bheld\b"),
    "file content": (
        r"\bpresence\b", r"\bcontent\b", r"\bnothing\b", r"\bSIGKILL\b",
        r"\b(?:blocks? no|never blocks?|(?:does|do) not block|cannot block)\b"),
    "lock ownership": (
        r"\bscript\b[^.]{0,60}\b(?:owns|holds|keeps)\b", r"\bchecks?\b[^.,]{0,40}\b(?:do not|never)\b"),
    "holder record": (
        r"\bholder\b[^.]{0,30}\b(?:writes?|records?|stores?|saves?|puts?)\b[^.]{0,30}\b(?:process id|pid)\b",
        r"\bfile\b", r"\bstart time\b|\btime\b[^.]{0,20}\bstarted\b"),
    "waiting line timing": (
        r"\bwait\b", r"\bprints?\b[^.]{0,15}\bline\b", r"\b(?:at once|immediately|straight away|right away)\b"),
    "waiting line content": (
        r"\bline\b[^.]{0,30}\b(?:names?|shows?|gives?|states?|includes?)\b[^.]{0,20}\bholder\b",
        r"\b(?:process id|pid)\b", r"\bstart time\b", r"\blongest\b"),
    "waiter blocks": (
        r"\bblocks?\b[^.]{0,25}\bsystem\b", r"\b(?:gives?|grants?)\b",
        r"!\b(?:never|not|no longer)\s+blocks?\b", r"!\bpoll"),
    "next waiter": (
        r"\bsystem\b[^.]{0,20}\b(?:picks?|chooses?|selects?)\b[^.]{0,40}\bnext\b",
        r"\b(?:no fixed order|any order|no (?:set|particular|guaranteed) order)\b",
        r"!\bnever (?:picks?|chooses?|selects?)\b"),
    "turn line": (r"\bturn\b", r"\bprints?\b[^.]{0,20}\bhow long\b[^.]{0,15}\bwaited\b"),
    "wait bound": (
        r"\bCHECK_LOCK_WAIT\b", r"\bwhole\b[^.]{0,20}\bseconds\b", r"\b0\b[^.]{0,10}\b100000000\b", r"\b1800\b"),
    "give-up line": (
        r"\bbound\b", r"\bstandard error\b", r"\bhow long\b", r"\bno check\b", r"\bexits? (?:with )?(?:status )?75\b"),
    "lock refused": (
        r"\bcannot\b", r"\bopen\b", r"\bother than\b[^.]{0,20}\bholder\b", r"\bruns? without the lock\b"),
    "lock file override": (
        r"\bCHECK_LOCK_FILE\b[^.]{0,30}\b(?:another|different|other|alternate)\b[^.]{0,10}\block file\b", r"\btests\b"),
    "no bypass": (r"\bno (?:switch|option|flag)\b[^.]{0,15}\b(?:skips?|disables?|bypass(?:es)?)\b[^.]{0,15}\block\b",),
    "second clone": (r"\bsecond clone\b[^.]{0,40}\b(?:own|separate)\b",),
    "SIGKILL limit": (r"\bSIGKILL\b[^.]{0,30}\bfrees?\b[^.]{0,15}\block\b", r"\bprocesses\b[^.]{0,30}\bstill\b"),
    "exit codes": (
        r"\bexit (?:status|codes?)\b", r"\b0\b[^,]{0,30}\bevery check\b[^,]{0,10}\bpass", r"\bfailing check'?s? own\b",
        r"\b2\b[^,]{0,25}\b(?:usage|CHECK_LOCK_WAIT)\b", r"\b75\b[^,.]{0,25}\bwait\b"),
}

# The standard output of a full run in which every stand-in check passed.
EVERY_CHECK = [
    line for name in ("skill lint", "registry check", "skill versions (base main)", "unit tests", "claude plugin validate")
    for line in (f"==> {name}", f"PASS: {name}")
] + ["All checks passed."]

README_SENTENCE = (
    "A run without `--fast` waits its turn behind any other such run of this clone"
    " and needs no guard before it, as [`scripts/check.sh --help`](scripts/check.sh) explains."
)
AGENTS_SENTENCE = (
    "A full run waits its turn behind any other full run of this clone and needs no guard before it,"
    " as [`scripts/check.sh --help`](scripts/check.sh) explains."
)

# The first check, scripts/lint_skill.py, is the stand-in body. STANDIN_DIR and
# STANDIN_NAME switch it on; without them it passes at once, like the others.
STANDIN_BODY = textwrap.dedent('''\
    import os, sys, time
    from pathlib import Path

    def publish(path, text):
        """Write the file whole, so a reader never finds it empty."""
        part = path.with_name(path.name + ".part")
        part.write_text(text)
        os.replace(part, path)

    name = os.environ.get("STANDIN_NAME")
    if name:
        state = Path(os.environ["STANDIN_DIR"])
        try:
            os.close(os.open(state / "running", os.O_CREAT | os.O_EXCL))
        except FileExistsError:
            with open(state / "log", "a") as log:
                log.write(f"overlap {name}\\n")
        with open(state / "log", "a") as log:
            log.write(f"start {name}\\n")
        if os.environ.get("STANDIN_LEAVE"):
            if os.fork() == 0:  # stays in the run's process group, which the test's cleanup kills
                null = os.open(os.devnull, os.O_RDWR)
                for fd in (0, 1, 2):
                    os.dup2(null, fd)
                publish(state / f"{name}.leftover", str(os.getpid()))
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

# The last check, `claude plugin validate`, holds until STANDIN_DIR/claude.go
# exists when STANDIN_CLAUDE_HOLD is set.
FAKE_CLAUDE = textwrap.dedent('''\
    #!/bin/sh
    if [ -n "$STANDIN_CLAUDE_HOLD" ]; then
      : > "$STANDIN_DIR/claude.started"
      until [ -e "$STANDIN_DIR/claude.go" ]; do sleep 0.02; done
    fi
    exit 0
''')

# Python reads this at start-up of every python3 the script runs, because setUp puts
# its folder on PYTHONPATH. It appends each non-zero argument of signal.alarm to
# STANDIN_DIR/alarms, so a test sees the bound the helper armed without timing it.
ALARM_SHIM = textwrap.dedent('''\
    import os, signal

    _alarm = signal.alarm

    def alarm(seconds):
        if seconds:
            with open(os.path.join(os.environ["STANDIN_DIR"], "alarms"), "a") as record:
                record.write(f"{seconds}\\n")
        return _alarm(seconds)

    signal.alarm = alarm
''')

# `--browser` runs its tests through `uv` from the shell function browser_tests,
# inside a command substitution. With STANDIN_UV_LEAVE set, that call leaves a
# process running.
FAKE_UV = textwrap.dedent('''\
    #!/bin/sh
    case "$*" in
      *unittest*)
        if [ -n "$STANDIN_UV_LEAVE" ]; then
          sh -c 'echo $$ > "$STANDIN_DIR/uv.part"; mv "$STANDIN_DIR/uv.part" "$STANDIN_DIR/uv.leftover"; exec sleep 600' \\
            < /dev/null > /dev/null 2>&1 &
        fi
        echo "test_page (tests.test_dossier.T.test_page) ... ok" ;;
    esac
    exit 0
''')


def now() -> str:
    """The time now as the script writes it: every run has TZ=UTC."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


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
        for name, body in (("claude", FAKE_CLAUDE), ("uv", FAKE_UV)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        shim_dir = self.tmp / "shim"
        shim_dir.mkdir()
        (shim_dir / "sitecustomize.py").write_text(ALARM_SHIM)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CHECK_", "STANDIN_", "GIT_"))}
        self.env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            CHECK_LOCK_FILE=str(self.lock),
            STANDIN_DIR=str(self.state),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=str(shim_dir),
            TZ="UTC",  # a local clock repeats an hour once a year; UTC never does
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

    def start(self, *args: str, name: str = "", cwd: Path | None = None, preexec=None, **env: str) -> subprocess.Popen:
        """Start check.sh in the background, its output going to files under state/.

        preexec runs in the child before bash starts, to set what the run inherits.
        """
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
            stdout=out, stderr=err, start_new_session=True, preexec_fn=preexec,
        )
        proc.tag = tag
        self.addCleanup(self.stop, proc)
        return proc

    def stop(self, proc: subprocess.Popen) -> None:
        """End the run and anything left in its process group, such as a killed holder's body."""
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # macOS can answer EPERM once every process in the group has exited
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

    def written_start(self, proc: subprocess.Popen) -> str:
        """The start time the lock file gives for `proc`, which must be its only content."""
        found = re.fullmatch(rf"{proc.pid} ({START_TIME_PATTERN})\n", self.lock.read_text())
        self.assertIsNotNone(found, self.lock.read_text())
        return found[1]

    def alarms(self) -> list[str]:
        """The non-zero arguments the helper gave signal.alarm, as the shim recorded them."""
        path = self.state / "alarms"
        return path.read_text().splitlines() if path.exists() else []

    def assert_gave_up_after_one_second(self, proc: subprocess.Popen) -> None:
        """The run printed its waiting line, then its give-up line, exited 75 and armed a 1 s alarm.

        The alarm is the bound the helper arms, which the shim records, so no clock window is needed
        to tell 1 s from 2 s. The waiting line is the only write to standard output and the give-up
        line the only write to standard error, so the times of those files are the two lines' times.
        """
        self.assertEqual(proc.wait(timeout=DEADLINE), 75)
        self.assertEqual(self.out(proc).splitlines(), ["check.sh: waiting up to 1 s for another run of scripts/check.sh."])
        self.assertEqual(
            self.err(proc).splitlines(),
            ["check.sh: gave up after waiting 1 s for another run of scripts/check.sh; no check was run."],
        )
        self.assertEqual(self.alarms(), ["1"])
        # 0.1 s below the bound for the file systems' time stamps; nothing above it, since the alarm is checked.
        gap = (self.state / f"{proc.tag}.err").stat().st_mtime - (self.state / f"{proc.tag}.out").stat().st_mtime
        self.assertGreaterEqual(gap, 0.9)
        self.assertEqual(self.log(), [])

    def waited(self, proc: subprocess.Popen) -> int:
        """The seconds the run's turn line reports."""
        found = re.fullmatch(r"check\.sh: waited ([0-9]+) s for the lock\.", self.out(proc).splitlines()[1])
        self.assertIsNotNone(found, self.out(proc))
        return int(found[1])

    # -- tests ------------------------------------------------------------

    def test_a_full_run_waits_then_gives_up_with_75_and_runs_no_check(self) -> None:
        self.hold()
        proc = self.start(name="late", CHECK_LOCK_WAIT="1")
        self.assert_gave_up_after_one_second(proc)

    def test_a_run_started_with_sigalrm_blocked_still_gives_up_at_its_bound(self) -> None:
        self.hold()
        proc = self.start(name="blocked", CHECK_LOCK_WAIT="1",
                          preexec=lambda: signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM}))
        self.assert_gave_up_after_one_second(proc)

    def test_a_fast_run_starts_its_checks_at_once_while_the_lock_is_held(self) -> None:
        self.hold()
        for wait in ("0", "not a number"):
            with self.subTest(CHECK_LOCK_WAIT=wait):
                rc, out, err = self.run_check("--fast", name=f"fast{len(self.log())}", CHECK_LOCK_WAIT=wait)
                self.assertEqual(out.splitlines()[:2], ["==> skill lint", "PASS: skill lint"])
                self.assertIn("SKIP: unit tests (--fast)", out.splitlines())
                self.assertEqual(out.splitlines()[-1], "All checks passed.")
                self.assertEqual((rc, err), (0, ""))

    def test_help_prints_the_whole_header_and_help_and_a_usage_error_never_wait(self) -> None:
        self.hold()
        rc, out, err = self.run_check("--help", name="help", CHECK_LOCK_WAIT="0")
        self.assertEqual((rc, err), (0, ""))
        lines = (self.repo / "scripts" / "check.sh").read_text().splitlines()
        header = [re.sub(r"\A# ?", "", line) for line in lines[1:lines.index("set -euo pipefail")]]
        self.assertEqual(out.splitlines(), header)
        sentences = re.split(r"(?<=\.) (?=[A-Z])", " ".join(out.split()))
        windows = sentences + [" ".join(pair) for pair in zip(sentences, sentences[1:])]
        for fact, terms in HELP_FACTS.items():
            with self.subTest(fact=fact):
                self.assertTrue(
                    any(all(bool(re.search(term.lstrip("!"), window, re.IGNORECASE)) != term.startswith("!")
                            for term in terms) for window in windows),
                    f"no part of the help states: {fact}",
                )
        rc, out, err = self.run_check("--bogus", name="bogus", CHECK_LOCK_WAIT="0")
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
        for number, (content, named) in enumerate(shapes.items()):
            with self.subTest(content=content):
                holder = self.hold(content)
                rc, out, err = self.run_check(name=f"shape{number}", CHECK_LOCK_WAIT="0")
                holder.release()
                self.assertEqual(out, f"check.sh: waiting up to 0 s for another run of scripts/check.sh{named}.\n")
                self.assertEqual(
                    err, "check.sh: gave up after waiting 0 s for another run of scripts/check.sh; no check was run.\n"
                )
                self.assertEqual(rc, 75)
        self.assertEqual(self.log(), [])

    def test_the_holder_writes_its_pid_and_start_time(self) -> None:
        self.assertFalse(self.lock.exists())
        before = now()
        proc = self.start(name="first", STANDIN_HOLD="1")
        wait_until(lambda: "start first" in self.log(), "the body to start")
        written = self.written_start(proc)
        self.assertTrue(before <= written <= now(), written)
        (self.state / "first.go").touch()
        self.assertEqual(proc.wait(timeout=DEADLINE), 0)

    def test_a_run_that_waited_writes_when_it_started_and_says_how_long_it_waited(self) -> None:
        holder = self.hold()
        before, started = now(), time.monotonic()
        proc = self.start(name="queued", STANDIN_HOLD="1")
        wait_until(lambda: self.out(proc).startswith("check.sh: waiting"), "the run to wait")
        waiting = now()
        # A second run with a 2 s bound waits behind the same holder. Its timed-out exit
        # comes at least 2 s after the queued run began to wait.
        other = self.start(name="other", CHECK_LOCK_WAIT="2")
        self.assertEqual(other.wait(timeout=DEADLINE), 75)
        holder.release()
        wait_until(lambda: "start queued" in self.log(), "the body to start")
        seen = time.monotonic()
        written = self.written_start(proc)
        self.assertTrue(before <= written <= waiting, f"{written} is not between {before} and {waiting}")
        # The run waited within [started, seen], which already holds any late start-up or
        # scheduling; the +1 is room for the line's rounding.
        self.assertTrue(2 <= self.waited(proc) <= math.ceil(seen - started) + 1, (self.waited(proc), seen - started))
        (self.state / "queued.go").touch()
        self.assertEqual(proc.wait(timeout=DEADLINE), 0)

    def test_the_lock_is_held_until_the_run_exits(self) -> None:
        proc = self.start(STANDIN_CLAUDE_HOLD="1")
        wait_until((self.state / "claude.started").exists, "the last check to start")
        rc, out, err = self.run_check(CHECK_LOCK_WAIT="0")
        self.assertEqual(
            (rc, out), (75, f"check.sh: waiting up to 0 s for another run of scripts/check.sh (pid {proc.pid}, started {self.written_start(proc)}).\n")
        )
        (self.state / "claude.go").touch()
        self.assertEqual(proc.wait(timeout=DEADLINE), 0)

    def test_three_waiters_each_get_a_turn_and_no_two_bodies_run_at_once(self) -> None:
        holder = self.hold()
        names = ("a", "b", "c")
        started = time.monotonic()
        procs = {name: self.start(name=name, STANDIN_HOLD="1") for name in names}
        seen = {}
        for name, proc in procs.items():
            wait_until(lambda: self.out(proc).startswith("check.sh: waiting up to 1800 s"), f"{name} to wait")
        self.assertEqual(self.log(), [])
        holder.release()
        order = []
        for turn in range(3):
            wait_until(lambda: len(self.log()) == 2 * turn + 1, f"turn {turn + 1} to start")
            current = self.log()[-1].removeprefix("start ")
            seen[current] = time.monotonic()
            self.assertIn(current, names)
            order.append(current)
            (self.state / f"{current}.go").touch()
            self.assertEqual(procs[current].wait(timeout=DEADLINE), 0)
        self.assertEqual(sorted(order), list(names))
        self.assertEqual(self.log(), [line for name in order for line in (f"start {name}", f"end {name}")])
        for name, proc in procs.items():
            lines = self.out(proc).splitlines()
            # Each waited within [started, seen[name]]; the +1 is room for the line's rounding.
            self.assertLessEqual(self.waited(proc), math.ceil(seen[name] - started) + 1)
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
                wait_until(lambda: f"end {name}" in self.log(), "the orphaned body to end")

    def test_a_holder_whose_check_fails_frees_the_lock(self) -> None:
        proc = self.start(name="failing", STANDIN_EXIT="1", STANDIN_HOLD="1")
        wait_until(lambda: "start failing" in self.log(), "the failing body to start")
        self.assertEqual(self.run_check(CHECK_LOCK_WAIT="0")[0], 75)
        (self.state / "failing.go").touch()
        self.assertEqual((proc.wait(timeout=DEADLINE), self.notices(self.err(proc))), (1, ["FAIL: skill lint (exit 1)"]))
        rc, out, err = self.run_check(CHECK_LOCK_WAIT="0")
        self.assertEqual((rc, out.splitlines()[-1], self.notices(err)), (0, "All checks passed.", []))

    def test_a_process_a_check_leaves_running_does_not_hold_the_lock(self) -> None:
        shapes = {
            "a program": ((), {"name": "leaver", "STANDIN_LEAVE": "1"}, "leaver.leftover"),
            "a program started by a shell function": (("--browser",), {"STANDIN_UV_LEAVE": "1"}, "uv.leftover"),
        }
        for shape, (args, env, mark) in shapes.items():
            with self.subTest(check=shape):
                rc, out, err = self.run_check(*args, **env)
                self.assertEqual((rc, out.splitlines()[-1]), (0, "All checks passed."))
                leftover = self.state / mark
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
        for number, (shape, path) in enumerate(shapes.items()):
            with self.subTest(shape=shape):
                rc, out, err = self.run_check(name=f"open{number}", CHECK_LOCK_FILE=str(path))
                self.assertEqual(self.notices(err), [f"check.sh: cannot open {path}; running without the lock."])
                self.assertEqual((rc, out.splitlines()), (0, EVERY_CHECK))
                self.assertEqual(self.log()[-2:], [f"start open{number}", f"end open{number}"])

    def test_a_lock_the_system_refuses_runs_without_the_lock(self) -> None:
        # fd 9 is not open in the helper, so flock fails with EBADF: a refusal other than another holder.
        line = f"check.sh: cannot lock {self.lock} (Bad file descriptor); running without the lock."
        result = subprocess.run(
            [sys.executable, str(self.repo / "scripts" / "check_lock.py"), "9", str(self.lock), "4242", now()],
            capture_output=True, text=True, env=self.env, timeout=DEADLINE,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (3, "", line + "\n"))
        # Given that status from the helper, the script runs every check.
        (self.repo / "scripts" / "check_lock.py").write_text(f"import sys\nprint({line!r}, file=sys.stderr)\nsys.exit(3)\n")
        rc, out, err = self.run_check(name="unlocked")
        self.assertEqual((rc, out.splitlines(), self.notices(err)), (0, EVERY_CHECK, [line]))
        self.assertEqual(self.log(), ["start unlocked", "end unlocked"])

    def test_a_bad_check_lock_wait_is_a_usage_error(self) -> None:
        for number, value in enumerate(("abc", "-5", "1.5", " 5", "100000001", "9" * 5000)):
            with self.subTest(CHECK_LOCK_WAIT=value[:12]):
                rc, out, err = self.run_check(name=f"bad{number}", CHECK_LOCK_WAIT=value)
                self.assertEqual((rc, out), (2, ""))
                self.assertEqual(
                    err, f"check.sh: CHECK_LOCK_WAIT must be a whole number of seconds from 0 to 100000000, not {value!r}.\n"
                )
        self.assertEqual(self.log(), [])

    def test_a_long_check_lock_wait_is_served(self) -> None:
        holder = self.hold()
        proc = self.start(CHECK_LOCK_WAIT="100000000")
        wait_until(lambda: self.out(proc).startswith("check.sh: waiting up to 100000000 s"), "the waiting line")
        holder.release()
        self.assertEqual(proc.wait(timeout=DEADLINE), 0)
        self.hold()
        rc, out, err = self.run_check(CHECK_LOCK_WAIT="0" * 5000 + "1")
        self.assertEqual((rc, out), (75, "check.sh: waiting up to 1 s for another run of scripts/check.sh.\n"))

    def test_an_interrupted_waiter_ends_without_running_a_check(self) -> None:
        self.hold()
        for value in (None, ""):
            with self.subTest(CHECK_LOCK_WAIT=value):
                env = {} if value is None else {"CHECK_LOCK_WAIT": value}
                proc = self.start(name=f"int{len(env)}", preexec=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL), **env)
                line = "check.sh: waiting up to 1800 s for another run of scripts/check.sh.\n"
                wait_until(lambda: self.out(proc) == line, "the waiting line")
                os.killpg(proc.pid, signal.SIGINT)
                # bash dies by SIGINT, or exits 130 when it saw its child die by SIGINT first
                self.assertIn(proc.wait(timeout=DEADLINE), (-signal.SIGINT, 128 + signal.SIGINT))
                self.assertEqual((self.out(proc), self.err(proc)), (line, ""))
        self.assertEqual(self.log(), [])

    def test_a_waiter_whose_caller_ignored_sigint_keeps_waiting(self) -> None:
        holder = self.hold()
        proc = self.start(preexec=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN))
        wait_until(lambda: self.out(proc).startswith("check.sh: waiting"), "the waiting line")
        os.killpg(proc.pid, signal.SIGINT)
        holder.release()
        self.assertEqual(proc.wait(timeout=DEADLINE), 0)
        self.assertEqual(self.out(proc).splitlines()[-1], "All checks passed.")

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
        paragraph = next(
            part for part in (REPO_ROOT / "README.md").read_text().split("\n\n")
            if part.startswith("Run `scripts/check.sh` before committing.")
        )
        self.assertRegex(" ".join(paragraph.split()), rf"\. {re.escape(README_SENTENCE)}(?: |\Z)")
        checks = next(line for line in (REPO_ROOT / "AGENTS.md").read_text().splitlines() if line.startswith("- **Checks.**"))
        self.assertTrue(checks.endswith(" " + AGENTS_SENTENCE), checks)


if __name__ == "__main__":
    unittest.main()
