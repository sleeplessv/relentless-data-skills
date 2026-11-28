"""deliver.py follow-up F<n>: file a ticket for a proven finding out of scope (#256 rule 38; #172 rule 13).

`follow-up` refuses `follow-up.unknown-finding` for a number no saved finding has,
`follow-up.in-scope` for a finding in scope, `follow-up.not-proven` for one that is not proven,
which is listed only, and `follow-up.bad-settings` when the stack settings cannot be read. With
`follow_ups` on, it runs `gh issue create` with the finding's text as the title, its report line
and a link to the PR as the body, and the label `labels.follow_up`, after the same secret check as
the description. It appends a `follow-up` record: `finding`, `state` `filed` with the `issue`
number, or `not filed` with the `reason` when `follow_ups` is off or `gh` fails (#176 rule 10). It
never refuses for either reason, so a run does not stop on a follow-up. `findings.state` reads
the record.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

import core
import findings
import render
import settings

ISSUE = re.compile(r"/issues/(\d+)\s*$")


def main(args: list[str], run: core.Run) -> None:
    if len(args) != 1:
        raise core.UsageError("follow-up takes a finding, F<n>")
    number = args[0]
    records = render._records(core.records_dir(run.common_dir, run.mark["branch"]))
    finding = next((f for f in findings.all_findings(records) if f["number"] == number), None)
    if finding is None:
        raise core.Refused("follow-up.unknown-finding", finding=number)
    if finding["scope"] == "in":
        raise core.Refused("follow-up.in-scope", findings.next_step(finding, records), finding=number)
    if not finding["proven"]:
        raise core.Refused("follow-up.not-proven", finding=number)
    try:
        stack, _ = settings.load(run.checkout)
    except settings.SettingsError as e:
        raise core.Refused("follow-up.bad-settings", f"fix {settings.PATH}, then deliver.py follow-up {number}",
                           error=str(e)) from None
    if not stack["follow_ups"]:
        return _not_filed(run, number, f"follow_ups = false in {settings.PATH}")
    url = [r for r in records if r["event"] == "pr"][-1]["url"]
    title = f"{finding['where']}: {finding['text'].rstrip('.')}"
    body = (f"{findings.report_line(finding)}\n\n"
            f"Found out of scope by the {findings.REPORTERS[finding['reviewer']]} of {url}.\n")
    render.refuse_secret(f"Finding {number}", "finding", body)
    fd, body_file = tempfile.mkstemp(prefix="deliver-follow-up-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        proc = subprocess.run(["gh", "issue", "create", "--title", title, "--body-file", body_file,
                               "--label", stack["labels"]["follow_up"]], cwd=run.checkout, capture_output=True, text=True)
    finally:
        os.unlink(body_file)
    issue = ISSUE.search(proc.stdout) if proc.returncode == 0 else None
    if issue is None:
        error = next((line.strip() for line in reversed(proc.stderr.splitlines()) if line.strip()),
                     f"exit {proc.returncode}" if proc.returncode else "it printed no issue URL")
        return _not_filed(run, number, f"gh issue create failed: {error}")
    run.record("follow-up", finding=number, state="filed", issue=int(issue[1]))
    print(f"Filed follow-up #{issue[1]} for {number}: {proc.stdout.strip()}")


def _not_filed(run: core.Run, number: str, reason: str) -> None:
    run.record("follow-up", finding=number, state="not filed", reason=reason)
    print(f"Follow-up not filed for {number}: {reason}.")
