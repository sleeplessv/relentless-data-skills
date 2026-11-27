#!/usr/bin/env python3
"""deliver.py: the one program of the deliver skill (#256 rules 1 to 5).

Run it as `uv run --python 3.13 --no-project deliver.py <subcommand> [arguments]`, or with a
`python3` of 3.13 or newer. Standard library only; it calls nothing but `git` and `gh`.

Each subcommand is a module beside this file, named for it, whose `main(args, run)` takes the
remaining arguments and the `core.Run` of the current folder (None outside a git working tree).
Endings and refusal codes are in `core.py`. Every subcommand but those in `NO_MARK_NEEDED`
refuses where the checkout has no run mark, before its module loads. A name in `SUBCOMMANDS`
whose module does not exist yet exits 2 with the usage text. To build a subcommand, add its
module; to add a subcommand, also add its name to `SUBCOMMANDS`, and a `<name>.no-mark` code
to `core.REFUSALS` with its test unless it is in `NO_MARK_NEEDED`. `finish` is in it but keeps
its code: it refuses for itself, since it also runs on a branch's records once the mark is gone.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

if sys.version_info < (3, 13):
    sys.exit("deliver.py needs Python 3.13 or newer")

import core  # noqa: E402

HERE = Path(__file__).resolve().parent
SUBCOMMANDS = ("start", "preflight", "check", "save", "pr", "ready", "merge", "finish", "deps", "scan", "report")
NO_MARK_NEEDED = frozenset({"start", "finish", "deps", "scan", "report"})
USAGE = f"""\
usage: deliver.py <subcommand> [arguments]

Subcommands: {", ".join(SUBCOMMANDS)}.
Every subcommand but start, deps, scan and report needs a run mark; finish also runs on a branch's records.
Exit codes: 0 done, 10 refused, 20 a question for the owner, any other a crash."""


def usage_error(message: str) -> int:
    print(f"deliver.py: {message}\n\n{USAGE}", file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    if argv[:1] in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if not argv:
        return usage_error("name a subcommand")
    name, args = argv[0], argv[1:]
    if name not in SUBCOMMANDS:
        return usage_error(f"no subcommand named {name!r}")
    run = core.find_run(Path.cwd())
    try:
        if name not in NO_MARK_NEEDED and (run is None or run.mark is None):
            raise core.Refused(f"{name}.no-mark", "deliver.py start")
        if not (HERE / f"{name}.py").is_file():
            return usage_error(f"{name} is not built yet")
        importlib.import_module(name).main(args, run)
    except core.Refused as refusal:
        print("\n".join(refusal.lines()))
        return 10
    except core.Question as question:
        print(question)
        return 20
    except core.UsageError as e:
        return usage_error(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
