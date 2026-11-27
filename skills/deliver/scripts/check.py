"""`deliver.py check -- <command>`: run a check in the slot and save it (#256 rules 27 to 29).

One argument after `--` is run as a shell command line and saved as written; several are joined
with `shlex.join` first, so both spellings of one command save the same text for `ready` to match.
The check waits for a slot, runs the command, and saves its stdout and stderr together to
`checks/<n>.txt` in the branch's records, then appends a `check` record: `command`, `exit`,
`output` (that file, relative to the records folder), `commit`, `selected_nothing` and
`slot_wait_s`. `commit` is null when a tracked file was changed before or after the command, or
`HEAD` moved while it ran. `check` never refuses inside a run: a failing command is saved and
ends in exit 0.

The slot is a lock file in the machine directory held with `fcntl.flock`, which the system frees
when the holder dies; the command's process does not inherit it. There is one slot, or
`check_slots` when `ports_command` is set (#179 rule 5).
"""
from __future__ import annotations

import fcntl
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

import core
import settings
from save import tied_commit

WAITING = "Waiting for a check slot."
# The three signs of a command that selected nothing (#256 rule 29), each matched on one line.
SELECTED_NOTHING = re.compile(
    r"^Ran 0 tests in "                                            # unittest
    r"|^[= ]*no tests ran in [\d.]+s[= ]*$"                         # pytest
    r"|^(?:\d\d:\d\d:\d\d\s+|.*?:\s+)?Nothing to do\.",                # dbt
    re.M,
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def selected_nothing(output: str) -> bool:
    return bool(SELECTED_NOTHING.search(ANSI.sub("", output)))


def slot_count(run: core.Run) -> int:
    try:
        stack, _ = settings.load(run.checkout)
    except settings.SettingsError:
        return 1
    return max(stack["check_slots"], 1) if stack["ports_command"] else 1


@contextmanager
def slot(count: int) -> Iterator[None]:
    """Hold one of `count` slot locks; print one waiting line when none is free at once."""
    folder = core.state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    files = [(folder / f"check-slot-{i}.lock").open("a") for i in range(count)]
    try:
        held, waited = None, False
        while held is None:
            for f in files:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                held = f
                break
            else:
                if not waited:
                    print(WAITING, file=sys.stderr, flush=True)
                    waited = True
                if count == 1:
                    fcntl.flock(files[0], fcntl.LOCK_EX)
                    held = files[0]
                else:
                    time.sleep(0.1)
        yield
    finally:
        for f in files:
            f.close()


def save_output(run: core.Run, output: bytes) -> str:
    """Write the output to the next free `checks/<n>.txt`; return its path in the records."""
    folder = core.records_dir(run.common_dir, run.mark["branch"]) / "checks"
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        try:
            with (folder / f"{n}.txt").open("xb") as f:
                f.write(output)
            return f"checks/{n}.txt"
        except FileExistsError:
            n += 1


def main(args: list[str], run: core.Run) -> None:
    if args[:1] != ["--"] or len(args) < 2:
        raise core.UsageError("check takes a command after --: deliver.py check -- <command>")
    command = args[1] if len(args) == 2 else shlex.join(args[1:])
    asked = time.monotonic()
    with slot(slot_count(run)):
        waited = round(time.monotonic() - asked, 1)
        before = tied_commit(run)
        proc = subprocess.run(["sh", "-c", command], cwd=run.checkout, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        after = tied_commit(run)
    text = proc.stdout.decode("utf-8", errors="replace")
    commit = before if before == after else None
    nothing = selected_nothing(text)
    output = save_output(run, proc.stdout)
    run.record("check", command=command, exit=proc.returncode, output=output, commit=commit,
               selected_nothing=nothing, slot_wait_s=waited)
    sys.stdout.write(text if not text or text.endswith("\n") else text + "\n")
    at = f"at {commit[:7]}" if commit else "tied to no commit"
    note = "; it selected nothing, so it is not a pass" if nothing else ""
    print(f"Saved check {output}: exit {proc.returncode}, {at}{note}.")
