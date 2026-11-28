"""deliver.py settle F<n> --check <command> | --unsettled: settle a finding in scope without a fix (#256 rule 38).

`settle` refuses `settle.unknown-finding` for a number no saved finding has, and
`settle.out-of-scope` for a finding out of scope. `--check <command>` marks the finding
disproven only when that exact command text has a counted pass on `HEAD` (`render.counted`), and
refuses `settle.no-pass` otherwise; it may settle a proven finding too. `--unsettled` refuses
`settle.proven` for a proven finding, which only a fix or a check settles (#172 rule 15; #176
rules 7, 8). It appends a `settle` record: `finding`, `state` (`disproven` or `unsettled`), and for
a check the `command` and the `commit` it passed on. `findings.state` reads the record.
"""
from __future__ import annotations

import shlex
import subprocess

import core
import findings
import render


def main(args: list[str], run: core.Run) -> None:
    if not (len(args) == 3 and args[1] == "--check" and args[2]) and not (len(args) == 2 and args[1] == "--unsettled"):
        raise core.UsageError("settle takes a finding, F<n>, and --check <command> or --unsettled")
    number = args[0]
    records = render._records(core.records_dir(run.common_dir, run.mark["branch"]))
    finding = next((f for f in findings.all_findings(records) if f["number"] == number), None)
    if finding is None:
        raise core.Refused("settle.unknown-finding", finding=number)
    if finding["scope"] == "out":
        raise core.Refused("settle.out-of-scope", f"deliver.py follow-up {number}" if finding["proven"] else None,
                           finding=number)
    if args[1] == "--unsettled":
        if finding["proven"]:
            raise core.Refused("settle.proven", f"fix it in a commit, or deliver.py settle {number} --check <command>",
                               finding=number)
        run.record("settle", finding=number, state="unsettled")
        print(f"{number} is unsettled; the owner decides it.")
        return
    command = args[2]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=run.checkout, capture_output=True, text=True,
                          check=True).stdout.strip()
    if not any(render.counted(r, command) and r["commit"] == head for r in records):
        raise core.Refused("settle.no-pass", f"deliver.py check -- {shlex.quote(command)}, then deliver.py settle "
                           f"{number} --check {shlex.quote(command)}", command=command, commit=head[:7])
    run.record("settle", finding=number, state="disproven", command=command, commit=head)
    print(f"{number} is disproven: `{command}` passes on {head[:7]}.")
