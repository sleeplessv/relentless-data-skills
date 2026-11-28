"""Preflight's install check: on Cortex Code, Codex, Cursor and Antigravity, what `install` writes is in place.

It reads the same items `deliver.py install` writes (spec #457, "Install"), so the stop it gives
is the state that `install` fixes. Claude Code and a plain shell skip it: the plugin supplies the
role files and the guard there.
"""
from __future__ import annotations

import sys

import install


def check_installed(ctx):
    """Stop at the first file or registration that is missing or differs from the skill's copy."""
    harness = ctx.harness
    if harness not in install.TARGETS:
        return None
    for item in install.items(harness, ctx.run):
        state = item.state()
        if state != "ok":
            # The result types come from the module that made `ctx`, as in check_guard.
            return sys.modules[type(ctx).__module__].Stop(
                f"preflight.install-{state}", f"deliver.py install {harness}", {"harness": harness, "path": str(item.path)})
    return None
