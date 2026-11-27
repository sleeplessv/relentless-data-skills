"""Preflight: the checks a run makes on its environment before the edit (#178 rules 1 to 5).

`CHECKS` is the one ordered list, cheapest first: the harness checks, then git and `gh`, then
the upstream skills, then the repo's named commands. The runner calls each in turn and ends at
the first stop. A check is a function of the `Context` that returns None for a pass, a `Warn`
with its one line, or a `Stop` whose code is in `core.REFUSALS` and whose next command is the
fix the owner can run. A check may read `ctx.settings` once the settings check has run, and
may set `ctx.guard_probe`, `ctx.permission_mode` and `ctx.harness`, which the record saves.

To add a check, write it in its own module beside this one, import it here and put it in
`CHECKS` at its place in the order. Give each new stop code its line in `core.REFUSALS` and
its test.

Every run saves one `preflight` record in the branch's records, and a stop also appends one
line to `preflight-stops.jsonl` in the machine directory. A run with no stop prints
`Preflight passed.`, after one `warning: <line>` line per warning; a run with neither a stop nor
a warning prints only that line. `deliver.py preflight` calls `run`; `start` (#419) is to call it
too.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import check_guard
import checks_claude
import core
import deps
import settings

STOP_LOG = "preflight-stops.jsonl"
CLEAN = "Preflight passed."
RERUN = "deliver.py preflight"


@dataclass
class Stop:
    code: str
    next_command: str
    fields: dict = field(default_factory=dict)


@dataclass
class Warn:
    line: str


@dataclass
class Context:
    run: core.Run
    settings: dict | None = None
    harness: str = "claude-code"
    guard_probe: str = "missing"
    permission_mode: str | None = None


Check = Callable[[Context], "Stop | Warn | None"]


def check_settings(ctx: Context) -> Stop | Warn | None:
    """Read the stack settings: a missing file is a warning, an unreadable one a stop."""
    try:
        ctx.settings, warnings = settings.load(ctx.run.checkout)
    except settings.SettingsError as e:
        return Stop("preflight.bad-settings", f"fix {settings.PATH}, then run {RERUN}", {"error": str(e)})
    return Warn(warnings[0]) if warnings else None


CHECKS: list[Check] = [
    check_settings,
    checks_claude.check_background,
    checks_claude.check_trust,
    checks_claude.check_hooks_on,
    checks_claude.check_shell_hooks,
    checks_claude.check_reader,
    checks_claude.check_roles,
    checks_claude.check_plugin_twice,
    checks_claude.check_agents_at_once,
    checks_claude.check_effort,
    check_guard.check_guard_probe,
    deps.check_required_skills,
    deps.check_skill_hashes,
]


def run_checks(ctx: Context, checks: list[Check]) -> tuple[Stop | None, list[str]]:
    """Call the checks in order until one stops; return the stop and the warnings."""
    warnings = []
    for check in checks:
        result = check(ctx)
        if isinstance(result, Stop):
            return result, warnings
        if isinstance(result, Warn):
            warnings.append(result.line)
    return None, warnings


def run(run: core.Run, checks: list[Check] | None = None) -> None:
    """Run preflight for the marked run, save its record, and print or refuse."""
    ctx = Context(run)
    stop, warnings = run_checks(ctx, CHECKS if checks is None else checks)
    run_id = run.mark["run"]
    run.record(
        "preflight", run=run_id, result="stop" if stop else "pass", stops=[stop.code] if stop else [],
        warnings=warnings, guard_probe=ctx.guard_probe, permission_mode=ctx.permission_mode, harness=ctx.harness,
    )
    for line in warnings:
        print(f"warning: {line}")
    if stop:
        core.append_state(STOP_LOG, run=run_id, code=stop.code, harness=ctx.harness)
        raise core.Refused(stop.code, stop.next_command, **stop.fields)
    print(CLEAN)


def main(args: list[str], run_: core.Run) -> None:
    if args:
        raise core.UsageError(f"preflight takes no arguments, got: {' '.join(args)}")
    run(run_)
