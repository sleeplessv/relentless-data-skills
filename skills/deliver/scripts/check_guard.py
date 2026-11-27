"""Preflight's guard probe check (#178 check table row 1; spec #407 reading 4).

`start` writes the run mark and prints the probe step; the session then runs `guard.PROBE`, which
the guard refuses and logs. This check passes when `guard-refusals.jsonl` in the machine
directory holds a refusal of the probe for this run, made at or after the mark's `started` time.
It reads the permission mode from the newest such refusal and warns in bypass mode. With no such
refusal the run stops: the guards are off.
"""
from __future__ import annotations

import json
import sys

import core
import guard

BYPASS = "bypassPermissions"
BYPASS_WARNING = (
    "the session runs in bypass mode (bypassPermissions): Claude Code asks about no command, "
    "so the guard's refusals are all that stops one"
)


def check_guard_probe(ctx):
    # preflight imports this module, so the result types come from the module that made `ctx`:
    # an import of preflight here would be circular, and a test loads it under another name.
    preflight = sys.modules[type(ctx).__module__]
    mark = ctx.run.mark
    try:
        lines = (core.state_dir() / guard.LOG).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    probes = [
        line for line in map(json.loads, lines)
        if line.get("class") == "probe" and line.get("run") == mark["run"] and line.get("at", "") >= mark["started"]
    ]
    if not probes:
        return preflight.Stop("preflight.guards-off", f"turn the hooks on, run {guard.PROBE}, then run {preflight.RERUN}",
                              {"run": mark["run"]})
    ctx.guard_probe = "seen"
    ctx.permission_mode = probes[-1].get("permission_mode")
    return preflight.Warn(BYPASS_WARNING) if ctx.permission_mode == BYPASS else None
