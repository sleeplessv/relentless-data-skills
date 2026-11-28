"""deliver.py brief <role> --model <id>: write a reviewer's brief and print the line that is its whole prompt.

The roles are `requirements` and `defect` (spec #479, Briefs; #231 rules 27 to 29). In order,
`brief` refuses:

1. `brief.no-pr` while the branch's records hold no `pr` record;
2. `brief.not-pushed` when the PR's head commit on GitHub is not the local `HEAD`;
3. `brief.unreadable` when the plan is not saved or cannot be read, `brief.bad-settings` when the
   stack settings cannot be read, and `brief.no-pass` when a command proof of the saved plan, or a
   set `check_command`, has no counted pass on `HEAD`: `ready.passes_on_head`, which `ready` uses too;
4. `brief.no-review-skill` when the role's review skill (`code-review` for requirements,
   `ponytail-review` for defect) is not installed where `deps.find` looks.

It then writes `briefs/<role>-0.md` in the branch's records, replacing an earlier one: the role by
its definition file, the review skill's resolved `SKILL.md`, the `deliver` folder, the fixed point
(the merge base of `HEAD` with `origin/<the PR's base branch>`), the review target `HEAD`, one
`saved check output` line per counted pass on `HEAD`, the requirements source line, the saved
request, requirements and check plan word for word (never the Summary), the report form of
`findings.FORMS`, and the rules: run a proving command through `deliver.py check`, write no file,
start no agent, never run `deliver.py merge`. It appends a `brief` record (`role`, `round` 0,
`model`, `effort`, `commit`, `path` relative to the records folder, `fixed_point`) and prints
`Read <path> and follow it.` The effort is `high` where the harness of the run's newest preflight
takes an effort for an agent (Claude Code, Codex) and `high, not applied` elsewhere. `--model
session` is recorded as given. `brief` writes nothing in the checkout and starts no agent.

`brief callback <role>` writes the call-back brief of a role whose findings a fix answers (#231
rule 30). After `brief.no-pr` it refuses `brief.no-review` when no review of that role is saved
and `brief.no-fix` when `HEAD` is the commit that role's newest saved report read. Its round is
the place of `HEAD` among `findings.fix_rounds`, the commits saved call-backs read, or the next
one, so a brief whose report was never saved uses up no round; a third round ends in
`core.Question` before anything is written, handing the PR to the owner. Then come the review
brief's other refusals. The brief is the review brief's, with the commits since the role's last
read and the role's findings before the call-back report form, saved as `briefs/<role>-<round>.md`.
Its record carries the model and effort of that role's review brief.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

import checks_harness
import core
import deps
import findings
import ready
import render

DELIVER = Path(__file__).resolve().parent.parent
SKILLS = {"requirements": "code-review", "defect": "ponytail-review"}
EFFORT_APPLIED = ("claude-code", "codex")
TEXTS = (("request", "Request"), ("requirements", "Requirements"), ("plan", "Check plan"))
ROLE_LINES = {
    "requirements": "Do both of the skill's readings yourself, and start no helper for them.",
    "defect": "Follow ponytail-review as written, and write finding lines only.",
}
CALLBACK_LINE = "Judge whether the commits above fix each of your findings, and read only the lines they changed."
MAX_ROUNDS = 2
HAND_OVER = ("This call-back would start a third fix round, and a run takes two at most. The PR stays draft and goes to "
             "the owner with its open findings: run deliver.py ready, then deliver.py finish.")


def main(args: list[str], run: core.Run) -> None:
    callback = len(args) == 2 and args[0] == "callback"
    if callback and args[1] in SKILLS:
        role, model = args[1], None
        again = f"deliver.py brief callback {role}"
    elif len(args) == 3 and args[0] in SKILLS and args[1] == "--model" and args[2]:
        role, model = args[0], args[2]
        again = f"deliver.py brief {role} --model {shlex.quote(model)}"
    else:
        raise core.UsageError(f"brief takes a role, one of {', '.join(SKILLS)}, and --model <id>, "
                              "or callback and a role")
    branch = run.mark["branch"]
    folder = core.records_dir(run.common_dir, branch)
    records = render._records(folder)
    prs = [r for r in records if r["event"] == "pr"]
    if not prs:
        raise core.Refused("brief.no-pr", "deliver.py pr", branch=branch)
    number = prs[-1]["number"]
    head = _git(run, "rev-parse", "HEAD")
    if callback:
        reviews = [r for r in records if r["event"] == "review" and r["role"] == role]
        if not reviews:
            raise core.Refused("brief.no-review", f"deliver.py brief {role} --model <id>", role=role)
        read = reviews[-1]["commit"]
        if head == read:
            raise core.Refused("brief.no-fix", f"commit the fix, run its checks and deliver.py pr, then {again}",
                               commit=head[:7], role=role)
        rounds = findings.fix_rounds(records)
        round_ = rounds.index(head) + 1 if head in rounds else len(rounds) + 1
        if round_ > MAX_ROUNDS:
            raise core.Question(HAND_OVER)
        review = [r for r in records if r["event"] == "brief" and r["role"] == role and r["round"] == 0][-1]
        model, effort = review["model"], review["effort"]
    pr = json.loads(_gh(run, "pr", "view", str(number), "--json", "headRefOid,baseRefName"))
    if pr["headRefOid"] != head:
        raise core.Refused("brief.not-pushed", "deliver.py pr", number=number, remote=pr["headRefOid"][:7] or "unknown",
                           commit=head[:7])
    ready.passes_on_head(run, records, head, "brief", again)
    skill = deps.find(SKILLS[role], run.checkout)
    if skill is None:
        raise core.Refused("brief.no-review-skill", f"install {SKILLS[role]}, then {again}", skill=SKILLS[role])
    fork = _git(run, "merge-base", "HEAD", f"origin/{pr['baseRefName']}")
    outputs = list(dict.fromkeys(str(folder / r["output"]) for r in records
                                 if r["event"] == "check" and render.counted(r, r.get("command")) and r["commit"] == head))
    name = f"deliver-{role}-reviewer"
    lines = [
        f"role: {name}, defined in {DELIVER / 'agents' / f'{name}.md'}",
        f"review skill: {skill / 'SKILL.md'}",
        f"deliver folder: {DELIVER}",
        f"fixed point: {fork}",
        f"review target: {head}, pushed",
        *[f"saved check output: {path}" for path in outputs or ["none"]],
        "requirements source: the text below and nothing else",
    ]
    for kind, heading in TEXTS:
        if (folder / f"{kind}.md").is_file():
            lines += ["", f"## {heading}", "", (folder / f"{kind}.md").read_text(encoding="utf-8").rstrip("\n")]
    if callback:
        lines += ["", "## Commits since your last read", "", _git(run, "log", "--reverse", "--format=%H %s",
                                                                 f"{read}..HEAD"),
                  "", "## Your findings", "",
                  *[findings.report_line(f) for f in findings.all_findings(records) if f["reviewer"] == role]]
        form, last = findings.CALLBACK_FORM, CALLBACK_LINE
    else:
        round_, form, last = 0, findings.FORMS[role], ROLE_LINES[role]
    deliver = f"uv run --python 3.13 --no-project {DELIVER / 'scripts' / 'deliver.py'}"
    lines += ["", "## Report", "", *form, "",
              f"Run any command that proves a finding as `{deliver} check -- <command>`, or with python3 "
              "when uv is missing, so that its output is saved.",
              "Write no file.", "Start no agent.", "Never run `deliver.py merge`.", last]
    path = folder / "briefs" / f"{role}-{round_}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if round_ == 0:
        harness = next((r.get("harness") for r in reversed(records) if r["event"] == "preflight"
                        and r.get("run") == run.mark["run"]), None) or checks_harness.detect()
        effort = "high" if harness in EFFORT_APPLIED else "high, not applied"
    run.record("brief", role=role, round=round_, model=model, effort=effort, commit=head,
               path=str(path.relative_to(folder)), fixed_point=fork)
    print(f"Read {path} and follow it.")


def _git(run: core.Run, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=run.checkout, capture_output=True, text=True, check=True).stdout.strip()


def _gh(run: core.Run, *args: str) -> str:
    proc = subprocess.run(["gh", *args], cwd=run.checkout, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout
