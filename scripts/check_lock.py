#!/usr/bin/env python3
"""Take scripts/check.sh's lock on a file descriptor the script opened.

Usage: check_lock.py <fd> <lock-file> <holder-pid> <holder-start-time>

scripts/check.sh calls this; `scripts/check.sh --help` gives the rules. The lock
belongs to the open file behind <fd>, so it stays held after this process exits,
for as long as the script keeps <fd> open.

Exit status: 0 the lock is held; 75 the wait ran out; 2 CHECK_LOCK_WAIT is not
a whole number of seconds from 0 to MAX_WAIT; 3 the lock cannot be taken for a
reason other than another holder, and the run goes on without it.
"""
from __future__ import annotations

import fcntl
import os
import re
import signal
import sys
import time

DEFAULT_WAIT = 1800
MAX_WAIT = 10**8  # the longest alarm macOS serves; above it macOS arms none, so the wait would never end
HOLDER = re.compile(r"([0-9]+) ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\n?")


class TimedOut(Exception):
    pass


def on_alarm(signum: int, frame: object) -> None:
    raise TimedOut


def holder(path: str) -> str:
    """The holder's pid and start time as the file gives them, read only for the message."""
    try:
        with open(path, encoding="utf-8") as f:
            found = HOLDER.fullmatch(f.read(200))
    except (OSError, UnicodeDecodeError):
        found = None
    return f" (pid {found[1]}, started {found[2]})" if found else ""


def main(argv: list[str]) -> int:
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        # Ctrl-C while waiting ends the run without a traceback; a SIGINT the caller ignored stays ignored.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    fd, path, pid, started = int(argv[1]), argv[2], argv[3], argv[4]
    raw = os.environ.get("CHECK_LOCK_WAIT") or str(DEFAULT_WAIT)
    digits = raw.lstrip("0") or "0"  # so int() never meets more digits than it converts
    if not re.fullmatch(r"[0-9]+", raw) or len(digits) > len(str(MAX_WAIT)) or int(digits) > MAX_WAIT:
        print(f"check.sh: CHECK_LOCK_WAIT must be a whole number of seconds from 0 to {MAX_WAIT}, not {raw!r}.",
              file=sys.stderr)
        return 2
    wait = int(digits)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"check.sh: waiting up to {wait} s for another run of scripts/check.sh{holder(path)}.", flush=True)
            asked = time.monotonic()
            signal.signal(signal.SIGALRM, on_alarm)
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM})  # a mask the caller set cannot stop the bound
            try:
                if wait == 0:
                    raise TimedOut
                signal.alarm(wait)
                fcntl.flock(fd, fcntl.LOCK_EX)
            except TimedOut:
                print(f"check.sh: gave up after waiting {wait} s for another run of scripts/check.sh;"
                      " no check was run.", file=sys.stderr)
                return 75
            finally:
                signal.alarm(0)
            print(f"check.sh: waited {round(time.monotonic() - asked)} s for the lock.", flush=True)
    except OSError as error:
        print(f"check.sh: cannot lock {path} ({error.strerror}); running without the lock.", file=sys.stderr)
        return 3
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{pid} {started}\n".encode())
    except OSError:
        pass  # the pid and time only feed a waiter's message; the lock is held either way
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
