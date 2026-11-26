"""Exercise scripts/draw.py at its command line against a world the tests build.

Each test builds its own world in a temporary folder: bare git repos made with
`git fast-import`, whose check command passes at some commits and fails at
others; session logs in the shape of Claude Code's, none copied from a real
session; and a stand-in `gh`, first on PATH, that replays saved answers, records
every call and clones the bare repos. HOME, the machine directory and the Claude
config directory all point inside that folder, so no test touches the network,
the real machine directory or a real session log.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ALPHA = "example-org/alpha"
BETA = "example-org/beta"
MODEL = "claude-test-model-1"
EARLIER_MODEL = "claude-test-model-0"
OPENS = "gh pr create --draft --body-file body.md"
CREATED = "2026-01-05T10:04:30Z"  # between the opening call's line, at 10:04, and its result's, at 10:05
SETUP = "touch .setup-done"
CHECK = "test -e .setup-done && test ! -e broken"

# Records each call as one line, clones a bare repo for `repo clone`, and prints the
# saved answer for `pr view`, `issue view` and `api`. A call with no saved answer exits 1.
# So does a call with a saved failure, <answer>.fails, after printing it, and so does the
# first clone of a repo beside whose bare repo lies <name>.fail-once, after writing the
# clone's folder, as git does when a hook fails.
GH = r"""#!/bin/bash
printf '%s\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "repo clone")
    if [ -e "$GH_REMOTES/$3.fail-once" ]; then
      mv "$GH_REMOTES/$3.fail-once" "$GH_REMOTES/$3.failed"; git clone -q "$GH_REMOTES/$3.git" "$4"
      echo "stand-in gh: the clone failed" >&2; exit 1
    fi
    exec git clone -q "$GH_REMOTES/$3.git" "$4" ;;
  "pr view"|"issue view")
    for ((at = 1; at < $#; at++)); do [ "${!at}" = --repo ] && { next=$((at + 1)); repo=${!next}; }; done
    key="$1 $repo $3" ;;
  "api --paginate") key="api $3" ;;
  *) key="$*" ;;
esac
file="$GH_ANSWERS/${key//[ \/]/_}"
[ -f "$file.fails" ] && { cat "$file.fails"; echo "stand-in gh: the request failed" >&2; exit 1; }
[ -f "$file" ] || { echo "stand-in gh: no saved answer for $key" >&2; exit 1; }
cat "$file"
"""


@dataclass
class Ticket:
    """One finished ticket: its issue, its PR, the session that opened the PR and its two commits."""

    number: int
    size: int
    repo: str = ALPHA
    passes: bool = True  # the check passes at the commit before the merged PR
    skill: str = "implement-ticket"
    criteria: str = "## Acceptance criteria\n\n- [ ] The report prints the total."
    prs: int = 1  # PRs its session opened
    closes: int = 1  # issues its PR closes
    state: str = "MERGED"
    draft: bool = False  # opened as a draft and marked ready later
    by_helper: bool = False  # a helper of the session opened the PR
    rival: str = ""  # a Bash command a second session runs at 10:04, whose result at 10:05 prints the PR's URL
    copied: bool = False  # a resumed session's log starts with copies of this session's lines
    issue: int = 0  # the issue the PR closes, when not `number`
    command: str = OPENS  # the Bash command whose result prints the PR's URL
    again: str = ""  # a later Bash command, at 10:40, whose result prints the PR's URL again
    later: str = ""  # a later Bash command, at 10:20, whose result prints the URL of a PR in an unlisted repo
    also: int = 0  # another ticket whose PR's URL the opening command's result prints too
    model: object = MODEL  # the model the session's responses name; "" for none
    created: str = CREATED  # when GitHub says the PR was opened
    inherited: str = ""  # a skill loaded in lines this session's log copied from an earlier session
    pushed: bool = True  # GitHub records the pushes to the PR's branch
    recorded: bool = True  # GitHub answers the request for the branch's pushes
    lost: bool = False  # the merge commit GitHub names is not in the repo
    fork: bool = False  # the PR came from a fork
    refuses_checkout: bool = False  # a hook makes checking out the commit before the merged PR fail
    merge: str = ""  # the merge commit's SHA, set when the world builds its repo

    @property
    def pr(self) -> int:
        return self.number + 500

    @property
    def session(self) -> str:
        return f"00000000-0000-4000-8000-{self.number:012d}"

    @property
    def rival_session(self) -> str:
        return f"00000000-0000-4000-9000-{self.number:012d}"

    def commit(self, letter: str) -> str:
        return f"{self.number:08d}" + letter * 32

URL = f"https://github.com/{ALPHA}/pull/501"
UNLISTED = "https://github.com/example-org/gamma/pull/9"
HERE_BODY = "gh pr create --title \"t\" --body \"$(cat <<'EOF'\nRun exit 0; then gh pr create || true.\nEOF\n)\""
# What the reader says of a Bash call that exited 0, and what bash does with it in the shell test's arrangements of
# its stand-ins. The reader says "opens" when the call has a form that --help lists, "maybe" when its text holds the
# words gh, pr and create otherwise, and None when it does not. The shell, across the arrangements, "starts"
# `gh pr create` in every run that exits 0, and some run exits 0; "skips" it in some run that exits 0, though some
# run starts it; "fails": no run exits 0, though some run starts it; or starts it in "none" of the runs.
FORMS: dict[str, dict[str, str]] = {
    "opens": dict.fromkeys([
        # The five forms real sessions use.
        'gh pr create --title "t" --body "b"', "git push -u origin b && gh pr create --fill",
        "cd x && gh pr create --fill", "gh pr create --fill 2>&1 | tail -1", HERE_BODY,
        # The shape of the call that opened this repo's own PR for #281.
        "cat > body.md <<'EOF'\nBody text.\nEOF\ncd x && git push -q -u origin HEAD 2>&1 | tail -2; "
        "cd .. && gh pr create --draft --base main --head ticket-1 --title \"Ticket 1\" --body-file body.md",
        "git push &&\ngh pr create", "gh pr create --fill |\n  tail -3", "gh pr create \\\n  --fill",
        "cd .\ngh pr create\n", "git log > log.txt; gh pr create && git push",
        "gh pr create --title 'it'\\''s \"quoted\"' --body \"costs \\$5, \\`kept\\`\""], "starts"),
    "maybe": {
        # The 13 commands the reader at 97b879d read wrongly.
        'time { :; } >"$((1 / 0))"; gh pr create': "none",
        "time { :; }; command X=1 gh pr create": "none",
        "time { PATH=/absent; }; gh pr create": "none",
        "time '-p' gh pr create": "none",
        "env A=1 -u A gh pr create": "none",
        "/no/such/gh pr create": "none",
        "gh pr create --fill || gh pr view --json url --jq .url": "starts",
        'cli=gh; command "$cli" pr create': "starts",
        "env -C . gh pr create": "starts",
        '{ :; } >"$(gh pr create)"': "fails",
        "echo $[ $(gh pr create) + 1 ]": "fails",
        'set -- pr create; gh "$@"': "starts",
        "x='pr create'; gh ''$x": "starts",
        # A compound command, a function, prefixes, another program, and calls with an && before and a ; after.
        "if true; then gh pr create --fill; fi": "starts",
        "{ gh pr create; }": "starts",
        "(gh pr create)": "starts",
        "f() { gh pr create; }; f": "starts",
        "env A=1 gh pr create": "starts",
        "command gh pr create": "starts",
        "time gh pr create": "starts",
        "nohup gh pr create": "starts",
        "bash -c 'gh pr create'": "starts",
        "eval gh pr create": "starts",
        "git push && gh pr create --fill; cd .": "skips",
        f"false && gh pr create --fill; printf '%s\\n' {URL}": "none",
        # Calls that end or replace the shell, change what gh names, or abandon the line before gh.
        "exit 0; gh pr create": "none",
        "exec true; gh pr create": "none",
        "gh() { :; }; gh pr create": "none",
        "PATH=/absent; gh pr create": "none",
        f"echo $((1/0)); gh pr create\nprintf '%s\\n' {URL}": "none",
        f"gh pr create > missing-folder/out; printf '%s\\n' {URL}": "none",
        f"gh pr create < missing-file; printf '%s\\n' {URL}": "none",
        "$GH pr create": "skips",
        "gh pr view --json url || gh pr create --fill": "skips",
        "git push ||\ngh pr create": "skips",
        "git push && gh pr create &": "skips",
        # Forms near the list that it leaves off.
        "gh pr create  # open it": "starts",
        "GH=1 gh pr create": "starts",
        "gh pr create; gh pr create": "starts",
        "gh pr 'cre'ate": "starts",
        "./tools/gh pr create": "starts",
        "gh pr create --body \"$(cat <<'EOF'\nEOF)\nEOF\n)\"": "starts",
        "cat <<EOF\n$(gh pr create)\nEOF": "starts",
        # Text that names the words and runs no gh pr create.
        "echo 'gh pr create'": "none",
        "gh pr view --json url --jq .url; echo create": "none",
        "cat <<'EOF'\n$(gh pr create)\nEOF": "none",
        "# gh pr create": "none",
        "gh pr create-preview": "none",
        "command -v gh pr create": "none"},
    # The known limit: a call that builds the words when it runs, or a script that runs gh pr create.
    "neither": {
        "gh pr view --json url --jq .url": "none", "echo done": "none",
        "gh pr $'cre\\x61te'": "starts", "sh ./open-pr.sh": "starts"}}
# Forms whose reading is asserted but which no test hands to a shell: each can find a program past the
# stand-ins, so it could start the real gh.
PAST_THE_STAND_IN = {"command -p gh pr create": "command -p searches the system's default path, not PATH"}


def shell_forms() -> list[tuple[str, str, str]]:
    """Each form the shell test hands to bash: (what the reader should say, the form, what bash does with it)."""
    return [(does, command, outcome) for does, commands in FORMS.items() for command, outcome in commands.items()]


def outcome(runs: list[tuple[int, bool]]) -> str:
    """What bash did with a form across the arrangements, from each run's exit and whether it started the stand-in
    gh with `pr create`, in the words FORMS uses."""
    passed = [called for code, called in runs if code == 0]
    if not any(called for _, called in runs):
        return "none"
    if not passed:
        return "fails"
    return "starts" if all(passed) else "skips"


def shell_path(root: Path, stand_ins: set[str]) -> str:
    """The PATH a form runs with: the stand-ins' folder, then a folder that links each program in /usr/bin and
    /bin but those the stand-ins replace, so a form that misses a stand-in finds no real one behind it."""
    system = root / "system"
    if not system.exists():
        system.mkdir()
        for folder in ("/usr/bin", "/bin"):
            for program in sorted(Path(folder).iterdir()):
                if program.name not in stand_ins | {"gh"} and not (system / program.name).exists():
                    (system / program.name).symlink_to(program)
    return f"{root / 'bin'}:{system}"


# A stand-in gh that records each call and prints the PR's URL for `pr create`; its exits are set per run.
STAND_IN = f"""#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
if [ "$1" = pr ] && [ "$2" = create ]; then echo created >> "$CREATES"; echo {URL}; exit "$CREATE_EXIT"; fi
if [ "$1" = pr ] && [ "$2" = view ]; then exit "$VIEW_EXIT"; fi
"""


def sized(start: int, count: int, size: int, **fields: object) -> list[Ticket]:
    return [Ticket(number, size, **fields) for number in range(start, start + count)]


def full_pool(per_bucket: int = 12, **fields: object) -> list[Ticket]:
    """`per_bucket` tickets of 20, 100 and 800 changed lines, numbered from 1, 101 and 201."""
    return sized(1, per_bucket, 20, **fields) + sized(101, per_bucket, 100, **fields) + sized(201, per_bucket, 800, **fields)


def line(session: str, kind: str, minute: int, **fields: object) -> dict:
    return {"type": kind, "sessionId": session, "uuid": f"{session}-{kind}-{minute}",
            "timestamp": f"2026-01-05T10:{minute:02d}:00.000Z", "cwd": "/work/example", **fields}


def assistant(session: str, minute: int, content: list, model: str = MODEL) -> dict:
    usage = {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40}
    return line(session, "assistant", minute, message={
        "id": f"msg_{session}_{minute}", "role": "assistant", **({"model": model} if model else {}), "content": content,
        "usage": usage})


def opening(session: str, minute: int, url: str, command: str = OPENS, model: str = MODEL) -> list[dict]:
    """A Bash call, by default one that runs `gh pr create`, and the result that prints a PR's URL."""
    call = f"toolu_{session}_{minute}"
    return [assistant(session, minute, [{"type": "tool_use", "id": call, "name": "Bash",
                                         "input": {"command": command}}], model),
            line(session, "user", minute + 1, message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call, "content": url + "\n", "is_error": False}]})]


def write_lines(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in lines))


def read_lines(path: Path) -> list[dict]:
    return [json.loads(text) for text in path.read_text().splitlines()]


def retime(path: Path, moment: str | None, kind: str = "") -> None:
    """Give every line of a log, or every line of one kind, the time `moment`, or no time when it is None."""
    write_lines(path, [entry if kind and entry["type"] != kind else
                       {key: value for key, value in entry.items() if key != "timestamp"}
                       | ({"timestamp": moment} if moment else {}) for entry in read_lines(path)])


def vetoed(result: subprocess.CompletedProcess[str]) -> int:
    """How many PRs of the listed repos a draw printed that a call may have opened."""
    found = [line for line in result.stdout.splitlines() if line.startswith("Vetoed ")]
    return int(found[0].split()[1])


def counts(result: subprocess.CompletedProcess[str]) -> tuple[int, int, int]:
    """The 0-50 pool, the 51-300 pool and the count of skipped logs a draw printed."""
    printed = result.stdout.splitlines()
    pools = {text.split(":")[0]: int(text.split()[2].rstrip(",")) for text in printed if ": pool " in text}
    skipped = [int(text.split()[1]) for text in printed if text.startswith("Skipped ")]
    return pools["0-50"], pools["51-300"], (skipped or [0])[0]


class World:
    """The repos, logs and saved `gh` answers for one test, under one temporary folder."""

    def __init__(self, root: Path, tickets: list[Ticket], repos: list[dict] | None = None) -> None:
        self.root = root
        self.state = root / "state"
        self.config = root / "claude"
        self.remotes = root / "remotes"
        self.bin = root / "bin"
        self.gh_log = root / "gh-calls.log"
        self.tickets = {ticket.number: ticket for ticket in tickets}
        self.answers: dict[str, str] = {}
        self.bases: dict[int, str] = {}
        self.bin.mkdir(parents=True)
        (self.bin / "gh").write_text(GH)
        (self.bin / "gh").chmod(0o755)
        # The scripts run from a copy, so a test sees anything a run writes beside them.
        self.source = root / "source"
        shutil.copytree(SCRIPTS, self.source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        refused = [ticket.number for ticket in tickets if ticket.refuses_checkout]
        if refused:  # git reads the hook folder from $HOME/.gitconfig
            hooks = root / "hooks"
            hooks.mkdir()
            (hooks / "post-checkout").write_text("#!/bin/sh\ncase \"$(git rev-parse --git-dir)\" in\n" + "".join(
                f"  */worktrees/A-{number}) echo 'the hook refused the checkout' >&2; exit 1 ;;\n" for number in refused)
                + "esac\n")
            (hooks / "post-checkout").chmod(0o755)
            (root / "home").mkdir()
            (root / "home" / ".gitconfig").write_text(f"[core]\n\thooksPath = {hooks}\n")
        for repo in dict.fromkeys(ticket.repo for ticket in tickets):
            self.build_repo(repo, [ticket for ticket in tickets if ticket.repo == repo])
        for ticket in tickets:
            self.save_answers(ticket)
            self.write_log(ticket)
        self.write_repos([{"repo": ALPHA, "check": CHECK, "setup": SETUP}] if repos is None else repos)

    def build_repo(self, repo: str, tickets: list[Ticket]) -> None:
        """A bare repo whose history is, per ticket, the commit before its PR and then its merge commit."""
        bare = self.remotes / f"{repo}.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        stream, mark = [], 0

        def commit(message: str, broken: bool) -> int:
            nonlocal mark
            mark += 1
            files = {"counter": f"{mark}\n", **({"broken": "yes\n"} if broken else {})}
            stream.append(f"commit refs/heads/main\nmark :{mark}\n"
                          f"committer Test <test@example.com> {1767600000 + mark} +0000\n"
                          f"data {len(message)}\n{message}\n" + (f"from :{mark - 1}\n" if mark > 1 else "")
                          + "deleteall\n" + "".join(f"M 644 inline {name}\ndata {len(text)}\n{text}\n"
                                                    for name, text in files.items()))
            return mark

        marks = {}
        for ticket in tickets:
            marks[ticket.number] = commit(f"before {ticket.number}", broken=not ticket.passes)
            commit(f"merge {ticket.number}", broken=False)
        marks_file = self.root / "marks"
        subprocess.run(["git", "-C", str(bare), "fast-import", "--quiet", f"--export-marks={marks_file}"],
                       input="".join(stream), text=True, check=True)
        shas = dict(entry.split() for entry in marks_file.read_text().splitlines())
        for ticket in tickets:
            self.bases[ticket.number] = shas[f":{marks[ticket.number]}"]
            ticket.merge = shas[f":{marks[ticket.number] + 1}"]

    def save_answers(self, ticket: Ticket) -> None:
        """The PR, its issue, its timeline and its branch's pushes, as `gh` gives them.

        Commit a is on the branch when the PR opens at 10:04:30. Commit b, made at 10:10, is pushed at
        10:20. Commit c, made at 10:25, is pushed at 11:00. A draft is ready at 10:30, so its head then
        is b, though c was made before then.
        """
        repo, pr = ticket.repo, ticket.pr
        merge = "f" * 40 if ticket.lost else ticket.merge
        commits = [{"oid": ticket.commit(letter), "committedDate": f"2026-01-05T10:{minute}:00Z"}
                   for letter, minute in (("a", "00"), ("b", "10"), ("c", "25"))]
        self.answers[f"pr {repo} {pr}"] = json.dumps({
            "state": ticket.state, "additions": ticket.size - ticket.size // 4, "deletions": ticket.size // 4,
            "createdAt": ticket.created, "mergeCommit": {"oid": merge} if ticket.state == "MERGED" else None,
            "headRefName": f"ticket-{ticket.number}", "isCrossRepository": ticket.fork, "commits": commits,
            "closingIssuesReferences": [{"number": (ticket.issue or ticket.number) + extra, "repository": {
                "name": repo.split("/")[1], "owner": {"login": repo.split("/")[0]}}} for extra in range(ticket.closes)]})
        for extra in range(1, ticket.prs):  # the session's other PRs, each opened while its own command ran
            self.answers[f"pr {repo} {pr + 1000 * extra}"] = self.answers[f"pr {repo} {pr}"].replace(
                ticket.created, f"2026-01-05T10:{4 + 2 * extra:02d}:30Z")
        self.answers[f"issue {repo} {ticket.issue or ticket.number}"] = json.dumps({
            "title": f"Ticket {ticket.number}", "body": f"## What to build\n\nThing {ticket.number}.\n\n{ticket.criteria}\n"})
        events = [{"event": "committed", "sha": commit["oid"]} for commit in commits]
        if ticket.draft:  # two pages, as `gh api --paginate` prints them; ready at 10:30, draft again, ready at 11:30
            events = [*events, {"event": "ready_for_review", "created_at": "2026-01-05T10:30:00Z"},
                      {"event": "convert_to_draft", "created_at": "2026-01-05T11:10:00Z"}]
            pages = [events[:2], [*events[2:], {"event": "ready_for_review", "created_at": "2026-01-05T11:30:00Z"}]]
        else:
            pages = [events]
        self.answers[f"api repos/{repo}/issues/{pr}/timeline"] = "\n".join(json.dumps(page) for page in pages)
        pushes = [("branch_creation", "10:04:20", "0" * 40, "a"), ("push", "10:20:00", "a", "b"),
                  ("push", "11:00:00", "b", "c"), ("branch_deletion", "12:00:00", "c", "0" * 40)]
        activity = [{"activity_type": kind, "timestamp": f"2026-01-05T{moment}Z", "ref": f"refs/heads/ticket-{ticket.number}",
                     "before": before if len(before) == 40 else ticket.commit(before),
                     "after": after if len(after) == 40 else ticket.commit(after)}
                    for kind, moment, before, after in reversed(pushes)] if ticket.pushed else []  # newest first
        if ticket.recorded:
            self.answers[f"api repos/{repo}/activity?ref=refs/heads/ticket-{ticket.number}&per_page=100"] = "\n".join(
                json.dumps(page) for page in (activity[:2], activity[2:]))

    def log_path(self, ticket: Ticket, session: str | None = None) -> Path:
        return self.config / "projects" / "-work-example" / f"{session or ticket.session}.jsonl"

    def write_log(self, ticket: Ticket) -> None:
        session = ticket.session
        lines = [line(session, "user", 0, message={"role": "user", "content": "Implement the ticket."})]
        copied: list[dict] = []
        if ticket.inherited:  # copied from an earlier session: its skill load and two of its responses
            earlier = f"00000000-0000-4000-b000-{ticket.number:012d}"
            copied = [line(earlier, "user", 0, isMeta=True, message={"role": "user", "content": [{"type": "text", "text":
                          f"Base directory for this skill: /home/someone/.claude/skills/{ticket.inherited}\n\n# Body"}]}),
                      *[assistant(earlier, minute, [{"type": "text", "text": "Earlier work."}], EARLIER_MODEL)
                        for minute in (1, 2)]]
            lines = [*copied, *lines]
        if ":" in ticket.skill:  # a plugin's skill, loaded by a Skill call
            lines += [assistant(session, 1, [{"type": "tool_use", "id": f"toolu_skill_{session}", "name": "Skill",
                                              "input": {"skill": ticket.skill}}], ticket.model),
                      line(session, "user", 1, message={"role": "user", "content": [
                          {"type": "tool_result", "tool_use_id": f"toolu_skill_{session}", "content": "Launching skill"}]})]
        else:
            lines.append(line(session, "user", 1, isMeta=True, message={"role": "user", "content": [
                {"type": "text", "text": f"Base directory for this skill: /home/someone/.claude/skills/{ticket.skill}\n\n# Body"}]}))
        urls = [f"https://github.com/{ticket.repo}/pull/{ticket.pr + 1000 * extra}" for extra in range(ticket.prs)]
        printed = [*urls]
        if ticket.also:
            printed[0] += f"\nhttps://github.com/{ticket.repo}/pull/{ticket.also + 500}"
        opened = [entry for minute, url in enumerate(printed, 2)
                  for entry in opening(session, minute * 2, url, ticket.command, ticket.model)]
        if ticket.again:
            opened += opening(session, 40, urls[0], ticket.again, ticket.model)
        if ticket.later:
            opened += opening(session, 20, UNLISTED, ticket.later, ticket.model)
        if ticket.by_helper:  # a forked helper's log starts with the lines its parent's log copied
            helper = self.log_path(ticket).with_suffix("") / "subagents" / "agent-a1.jsonl"
            write_lines(helper, copied + [{**entry, "agentId": "a1", "isSidechain": True} for entry in opened])
            opened = [assistant(session, 30, [{"type": "text", "text": "The helper opened the PR."}], ticket.model)]
        write_lines(self.log_path(ticket), lines + opened)
        if ticket.rival:
            write_lines(self.log_path(ticket, ticket.rival_session), opening(
                ticket.rival_session, 4, f"https://github.com/{ticket.repo}/pull/{ticket.pr}", ticket.rival))
        if ticket.copied:
            other = f"00000000-0000-4000-a000-{ticket.number:012d}"
            own = line(other, "user", 40, message={"role": "user", "content": "Carry on."})
            write_lines(self.log_path(ticket, other), lines + opened + [own])

    def write_repos(self, repos: list[dict]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "repos.json").write_text(json.dumps(repos))

    def draw(self, *args: str, state: Path | None = None, prelude: str = "") -> subprocess.CompletedProcess[str]:
        """Run the draw; `prelude` is Python run in the same process first, to break something the world cannot."""
        program, env = self.command(args, state, prelude)
        return subprocess.run(program, cwd=self.root / "cwd", env=env, text=True, capture_output=True)

    def start(self, *args: str) -> subprocess.Popen[str]:
        """Start the draw and return at once."""
        program, env = self.command(args, None, "")
        return subprocess.Popen(program, cwd=self.root / "cwd", env=env, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)

    def command(self, args: tuple[str, ...], state: Path | None, prelude: str) -> tuple[list[str], dict[str, str]]:
        answers = self.root / "answers"
        shutil.rmtree(answers, ignore_errors=True)
        answers.mkdir()
        for key, answer in self.answers.items():
            (answers / re.sub(r"[ /]", "_", key)).write_text(answer + "\n")
        env = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
        env = {**env, "HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(state or self.state),
               "CLAUDE_CONFIG_DIR": str(self.config), "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
               "GH_LOG": str(self.gh_log), "GH_ANSWERS": str(answers), "GH_REMOTES": str(self.remotes)}
        (self.root / "cwd").mkdir(exist_ok=True)
        program = [str(self.source / "draw.py"), *args]
        if prelude:
            program = ["-c", f"{prelude}\nimport runpy, sys\nsys.argv = {program!r}\n"
                             f"runpy.run_path(sys.argv[0], run_name='__main__')"]
        return [sys.executable, *program], env

    def set_file(self, number: int = 1, state: Path | None = None) -> dict:
        return json.loads(((state or self.state) / f"replay-set-{number}.json").read_text())


class TestOneDraw(unittest.TestCase):
    """One draw of a pool of 36 tickets, all passing, each opened by a helper; the tests read what it left.

    Beside the logs lie a dangling link where a log would be and, in each session's folder, a dangling
    link next to the helper's transcript. A partial set file from an earlier run is left readable by all.
    """

    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        world = cls.world = World(Path(temporary.name), full_pool(by_helper=True))
        projects = world.config / "projects" / "-work-example"
        (projects / "00000000-0000-4000-c000-000000000000.jsonl").symlink_to(world.root / "expired.jsonl")
        for ticket in world.tickets.values():
            (world.log_path(ticket).with_suffix("") / "expired.txt").symlink_to(world.root / "expired.txt")
        partial = world.state / "replay-set-1.json.partial"
        partial.write_text("left by a run that stopped\n")
        partial.chmod(0o644)
        cls.outside = [world.root / name for name in ("claude", "remotes", "home", "cwd", "bin", "source")]
        cls.before = cls.files()
        cls.result = world.draw("--seed", "7")

    @classmethod
    def files(cls) -> dict[str, bytes]:
        return {str(path): path.read_bytes() for folder in cls.outside if folder.exists()
                for path in sorted(folder.rglob("*")) if path.is_file()}

    def test_the_draw_writes_ten_tickets_per_bucket_with_each_entrys_fields(self) -> None:
        world = self.world
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        drawn = world.set_file()
        self.assertEqual(drawn["seed"], 7)
        buckets = [entry["bucket"] for entry in drawn["tickets"]]
        self.assertEqual(buckets, ["0-50"] * 10 + ["51-300"] * 10 + ["301-1500"] * 10)
        for entry in drawn["tickets"]:
            ticket = world.tickets[entry["ticket"]]
            self.assertEqual(entry, {
                "label": "A", "ticket": ticket.number, "bucket": entry["bucket"], "size": ticket.size,
                "title": f"Ticket {ticket.number}",
                "body": f"## What to build\n\nThing {ticket.number}.\n\n{ticket.criteria}\n",
                "base_commit": world.bases[ticket.number], "ready_commit": ticket.commit("a"), "model": MODEL,
                "pr": ticket.pr, "session": ticket.session, "log": f"logs/{ticket.session}.jsonl",
                "check_output": f"checks/A-{ticket.number}.txt"})
        self.assertEqual(json.loads((world.state / "project-labels.json").read_text()), {"A": ALPHA})

    def test_the_draw_copies_and_scans_each_kept_session_log_with_its_helpers(self) -> None:
        world = self.world
        entries = world.set_file()["tickets"]
        for entry in entries:
            source = world.log_path(world.tickets[entry["ticket"]])
            copy = world.state / entry["log"]
            self.assertEqual(copy.read_text(), source.read_text())
            helper = Path("subagents") / "agent-a1.jsonl"
            self.assertEqual((copy.with_suffix("") / helper).read_text(),
                             (source.with_suffix("") / helper).read_text())
        rows = [json.loads(text) for text in (world.state / "scan-rows.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(row["session"] for row in rows), sorted(entry["session"] for entry in entries))
        self.assertEqual({(row["model"], row["skills"] == ["implement-ticket"], len(row["helpers"])) for row in rows},
                         {(MODEL, True, 1)})

    def test_the_draw_writes_only_in_the_machine_directory_and_prints_labels_not_repos(self) -> None:
        state = self.world.state
        self.assertEqual(self.files(), self.before)
        self.assertEqual(sorted(path.name for path in state.iterdir()), [
            "checks", "draw.lock", "logs", "project-labels.json", "replay-set-1.json", "repos.json",
            "scan-rows.jsonl", "scan-rows.lock"])
        self.assertEqual(self.result.stdout.splitlines(), [
            "Seed 7.", "Skipped 1 session logs that could not be read.",
            "Vetoed 0 PRs of the listed repos: a call may have opened each, so none is in the pool.",
            "0-50: pool 12, set aside 0, kept 10.",
            "51-300: pool 12, set aside 0, kept 10.", "301-1500: pool 12, set aside 0, kept 10.",
            f"Wrote {state / 'replay-set-1.json'}."])
        self.assertEqual(self.result.stderr, "")
        self.assertEqual(oct((state / "replay-set-1.json").stat().st_mode & 0o777), oct(0o600))


class TestDraw(unittest.TestCase):
    def world(self, tickets: list[Ticket], repos: list[dict] | None = None) -> World:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return World(Path(temporary.name), tickets, repos)

    def test_help_prints_the_usage_and_formats(self) -> None:
        result = self.world([]).draw("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[:3], [
            "Draw the replay set: 30 tickets generation one finished, 10 per size bucket.", "",
            "Usage: python3 scripts/draw.py [--seed N]"])

    def test_help_gives_the_opening_forms_the_veto_the_limit_and_what_it_takes_for_granted_each_once(self) -> None:
        sentences = [
            "A call runs `gh pr create` for certain when it exited 0 and has this form, which shows that bash "
            "started that command:",
            "Every other command is cd, git, cat or tail.",
            "The draw takes for granted that the call ran in bash 5.2 or later, with its default options; that no "
            "alias, function, variable or option set before the call changes what a name in it runs; and that gh "
            "names the GitHub CLI and cd, git, cat and tail the commands of those names, wherever the call runs them.",
            "Any other call whose text holds the words gh, pr and create, in any order, case or quoting, may have "
            "opened the PR its result names, if GitHub's time falls in its span.",
            "A call whose text does not hold the three words does not count.",
            "So a command that builds the words when it runs, or a script or program that runs gh pr create, leaves "
            "no evidence.",
            "Before the count per bucket, the draw prints how many PRs of the listed repos a call may have opened."]
        help_text = " ".join(self.world([]).draw("--help").stdout.split())
        source = " ".join((SCRIPTS / "draw.py").read_text().split())
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        draw = importlib.import_module("draw")
        for sentence in sentences:
            with self.subTest(sentence=sentence):
                self.assertEqual(help_text.count(sentence), 1)
                self.assertEqual(source.count(sentence), 1)  # the help is the one place that says it
        for function in (draw.runs_gh_pr_create, draw.opening_form):
            self.assertNotIn("takes for granted", function.__doc__)
            self.assertNotIn("cd, git, cat or tail", function.__doc__)

    def test_the_draw_prints_how_many_prs_of_the_listed_repos_a_call_may_have_opened(self) -> None:
        # Ticket 2's session may have opened its PR; ticket 3's may have too, in a repo outside the list.
        for tickets, count in (([Ticket(1, 20)], 0),
                               ([Ticket(1, 20), Ticket(2, 20, command="env A=1 gh pr create"),
                                 Ticket(3, 20, repo=BETA, command="env A=1 gh pr create")], 1)):
            with self.subTest(count=count):
                result = self.world(tickets).draw()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(result.stdout.splitlines()[1], f"Vetoed {count} PRs of the listed repos: a call "
                                                                f"may have opened each, so none is in the pool.")

    def test_pool_holds_only_tickets_that_meet_readings_2_and_3_in_listed_repos(self) -> None:
        kept = [
            Ticket(1, 20, command="cd .\ngh pr create --fill"), Ticket(2, 20, command="gh\tpr\tcreate --title 'Ticket 2' --fill"),
            Ticket(3, 20, criteria="```html\n<!-- a literal comment opener\n```\n\n## Acceptance\n\n- yes"),
            Ticket(4, 20, criteria="  ## Acceptance\n\n- The report prints the total."),
            Ticket(5, 20, command="cd ../alpha && gh  pr create --fill"),
            Ticket(6, 20, inherited="tdd"), Ticket(7, 20, by_helper=True), Ticket(8, 20, copied=True),
            Ticket(9, 20, criteria="## Acceptance\n\n1. The report prints the total.", command="git push 2>&1 | tail -1; gh pr create --fill 2>&1 | tail -1"),
            Ticket(10, 50, criteria="## Done when\n\n* The report prints the total."),
            Ticket(101, 100, again=OPENS), Ticket(102, 100, also=24),
            *sized(103, 6, 100), Ticket(109, 51), Ticket(110, 300, skill="some-plugin:implement-backlog"),
            *sized(201, 8, 800, draft=True), Ticket(209, 301, draft=True), Ticket(210, 1500)]
        left_out = [
            Ticket(11, 20, skill="tdd"), Ticket(12, 20, prs=2), Ticket(13, 20, closes=2), Ticket(14, 1501),
            Ticket(15, 20, criteria="## Acceptance criteria\n\nThe report prints the total."),
            Ticket(16, 20, criteria="## Notes\n\n- The report prints the total."),
            Ticket(17, 20, criteria="## Acceptance criteria\n\n```\n- not a list item\n```"),
            Ticket(18, 20, state="OPEN"), Ticket(19, 20, rival=OPENS), Ticket(20, 20, repo=BETA),
            Ticket(21, 20, issue=300), Ticket(22, 100, issue=300),
            Ticket(23, 20, command="echo 'gh pr create'; gh pr view --json url --jq .url"),
            Ticket(24, 20, command="gh pr create --fill || gh pr view --json url --jq .url", created="2026-01-04T09:00:00Z"),
            Ticket(25, 20, skill="tdd", inherited="implement-ticket"),
            Ticket(26, 20, criteria="## Acceptance criteria\n\n    - an indented code line"),
            Ticket(27, 20, criteria="## Acceptance criteria\n\n<!--\n- a commented-out item\n-->"),
            Ticket(28, 20, criteria="## Acceptance criteria\n\n````\n```\n- inside a longer fence\n````"),
            Ticket(29, 20, criteria="Acceptance criteria\n---\n\n- under a heading made by underlining"),
            Ticket(30, 20, criteria="    Acceptance\n---\n\n- under an indented code line"),
            Ticket(31, 20, skill="tdd", inherited="implement-ticket", by_helper=True),
            Ticket(32, 20, model=""), Ticket(33, 20, command="if true; then gh pr create --fill; fi"),
            Ticket(34, 20)]
        world = self.world(kept + left_out)
        projects = world.config / "projects" / "-work-example"
        # A session whose times have no zone, which the draw counts, and whose run keeps ticket 34 out of the pool;
        # and a log of prose that names the command beside an empty skill line, which it passes over.
        write_lines(projects / "00000000-0000-4000-d000-000000000001.jsonl", [
            {**entry, "timestamp": entry["timestamp"].removesuffix("Z")} for entry in
            opening("00000000-0000-4000-d000-000000000001", 4, f"https://github.com/{ALPHA}/pull/534")])
        write_lines(projects / "00000000-0000-4000-d000-000000000002.jsonl", [
            line("00000000-0000-4000-d000-000000000002", "user", 0, message={"role": "user", "content": "Run gh pr create."}),
            line("00000000-0000-4000-d000-000000000002", "user", 1, isMeta=True, message={"role": "user", "content": [
                {"type": "text", "text": "Base directory for this skill: "}]})])
        # And one whose line holds a message that is not an object, which it counts.
        write_lines(projects / "00000000-0000-4000-d000-000000000003.jsonl", [
            line("00000000-0000-4000-d000-000000000003", "assistant", 4, message=[f"https://github.com/{ALPHA}/pull/599"])])
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[1], "Skipped 2 session logs that could not be read.")
        self.assertEqual(sorted(entry["ticket"] for entry in world.set_file()["tickets"]),
                         [ticket.number for ticket in kept])
        self.assertEqual(world.set_file()["set_aside"], [])
        for entry in world.set_file()["tickets"]:
            ticket = world.tickets[entry["ticket"]]
            self.assertEqual((entry["ready_commit"], entry["model"]), (ticket.commit("b" if ticket.draft else "a"), MODEL),
                             ticket.number)

    def test_a_command_makes_its_session_the_opener_only_when_it_surely_ran_gh_pr_create(self) -> None:
        for does, commands in FORMS.items():
            for command in commands:
                with self.subTest(command=command):
                    # Ticket 1's session runs the command. Ticket 101's opens its PR and a second session runs it.
                    # Ticket 102's opens its PR and later runs it, printing the URL of a PR in an unlisted repo.
                    world = self.world([Ticket(1, 20, command=command), Ticket(101, 100, rival=command),
                                        Ticket(102, 100, later=command)])
                    result = world.draw()
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertEqual(counts(result), (does == "opens", 2 * (does == "neither"), 0))
                    self.assertEqual(vetoed(result), 2 * (does == "maybe"))

    def test_each_form_s_reading_holds_for_what_a_shell_does_with_it(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        draw = importlib.import_module("draw")
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "bin").mkdir()
        (root / "tools").mkdir()
        (root / "x").mkdir()
        for name, text in (("gh", STAND_IN), ("git", '#!/bin/sh\nexit "$GIT_EXIT"\n')):
            (root / "bin" / name).write_text(text)
            (root / "bin" / name).chmod(0o755)
        (root / "tools" / "gh").symlink_to(root / "bin" / "gh")
        (root / "open-pr.sh").write_text("gh pr create\n")
        calls, creates = root / "calls", root / "creates"
        arrangements = [{"GIT_EXIT": git, "CREATE_EXIT": create, "VIEW_EXIT": view, "GH": gh}
                        for git in "01" for create in "01" for view in "01" for gh in ("gh", "true")]
        for command in PAST_THE_STAND_IN:
            self.assertEqual(draw.runs_gh_pr_create(command), "maybe")
        for does, command, expected in shell_forms():
            with self.subTest(command=command):
                self.assertEqual(draw.runs_gh_pr_create(command), {"opens": "opens", "maybe": "maybe"}.get(does))
                runs = []  # (the shell's exit, whether gh was asked to create a PR) per arrangement
                for arrangement in arrangements:
                    calls.write_text("")
                    creates.write_text("")
                    env = {"PATH": shell_path(root, {"gh"}), "HOME": str(root), "CALLS": str(calls),
                           "CREATES": str(creates), **arrangement}
                    code = subprocess.run(["bash", "-c", command], cwd=root, env=env, capture_output=True).returncode
                    for _ in range(20):  # a call in the background may come a moment after the shell ends
                        if creates.read_text() or "&" not in command:
                            break
                        subprocess.run(["sleep", "0.05"])
                    runs.append((code, creates.read_text() != ""))
                self.assertEqual(outcome(runs), expected, runs)

    def test_no_form_the_shell_test_runs_can_reach_a_program_outside_its_stand_ins(self) -> None:
        # Each form runs with `sh` in the place of gh, and a stand-in sh first on PATH that only records. A
        # script named `pr` marks the run when any other sh reads it, as a gh found past the stand-in would.
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for folder in ("bin", "tools", "x"):
            (root / folder).mkdir()
        for name, text in (("sh", '#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\n'),
                           ("git", '#!/bin/bash\nexit "$GIT_EXIT"\n')):
            (root / "bin" / name).write_text(text)
            (root / "bin" / name).chmod(0o755)
        (root / "tools" / "sh").symlink_to(root / "bin" / "sh")
        mark = root / "escaped"
        (root / "pr").write_text(f": > {mark}\n")
        for _, command, _ in shell_forms():
            with self.subTest(command=command):
                mark.unlink(missing_ok=True)
                probe = re.sub(r"\bgh\b", "sh", command)
                for git in "01":
                    env = {"PATH": shell_path(root, {"sh"}), "HOME": str(root), "CALLS": str(root / "calls"),
                           "GIT_EXIT": git, "GH": "sh"}
                    subprocess.run(["bash", "-c", probe], cwd=root, env=env, capture_output=True)
                subprocess.run(["sleep", "0.05"] if "&" in command else ["true"])
                self.assertFalse(mark.exists(), "a program outside the stand-ins ran")

    def test_a_list_counts_only_in_a_criteria_section_read_as_markdown(self) -> None:
        bodies = {
            "## Acceptance\n\n- yes": 1,
            "## Acceptance\n\nNone yet.\n\nOther work\n----------\n\n- unrelated task": 0,
            "## Acceptance\n\nIntro.\n---\n\n- under a heading made by underlining": 0,
            "## Acceptance\n\nIntro.\n\n# Other\n\n- unrelated": 0,
            "## Acceptance\n\nIntro.\n### Detail\n\n- yes": 1,
            "Acceptance criteria\n===\n\n- under a heading made by underlining": 0,
            "    Acceptance\n---\n\n- under an indented code line": 0,
            "## Acceptance\n\n    code\n---\n\n- yes": 1,
            "## Acceptance\n\nSee `<!--` here.\n\n- yes": 1,
            "## Acceptance\n\n    <!--\n\n- yes": 1,
            "## Acceptance\n\n```\n<!--\n```\n\n- yes": 1,
            "## Acceptance\n\n<!-- never closed\n\n- hidden": 0,
            "## Acceptance\n\n<div>\n- inside raw HTML\n</div>": 0,
            "## Acceptance\n\n<pre>\n- inside\n\n- still inside\n</pre>": 0,
            "## Acceptance\n\n<my-note>\n- inside a custom element\n</my-note>": 0}
        for body, pool in bodies.items():
            with self.subTest(body=body):
                result = self.world([Ticket(1, 20, criteria=body)]).draw()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(counts(result), (pool, 0, 0))

    def test_a_ticket_whose_list_cannot_be_read_with_certainty_is_left_out_as_one_with_no_list(self) -> None:
        bodies = {
            "## Acceptance\n\n- Print the total.\n    <details><summary>Example</summary></details>\n- Count rows.": 0,
            "## Acceptance\n\n- Print a total.\n- ```text\n  - Example switch\n  ```": 0,
            "## Acceptance\n\n- Print the total.\n> A quote.\n- Count rows.": 0,
            "## Acceptance\n\n- Print the total.\n  - Count rows.": 1}
        for body, pool in bodies.items():
            with self.subTest(body=body):
                result = self.world([Ticket(1, 20, criteria=body)]).draw()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(counts(result), (pool, 0, 0))

    def test_the_model_is_a_name_from_the_session_s_own_responses_or_a_helper_s_copy_of_one(self) -> None:
        for case, pool in (("a helper's copy", 1), ("a helper's own", 0), (17, 0), (" ", 0)):
            with self.subTest(case=case):
                ticket = Ticket(1, 20, model=case if isinstance(case, int) or case == " " else "")
                world = self.world([ticket])
                response = next(entry for entry in read_lines(world.log_path(ticket)) if entry["type"] == "assistant")
                if case == "a helper's copy":  # the same response, with the model the main log's copy lacks
                    write_lines(world.log_path(ticket).with_suffix("") / "subagents" / "agent-a1.jsonl", [
                        {**response, "message": {**response["message"], "model": MODEL}}])
                elif case == "a helper's own":
                    write_lines(world.log_path(ticket).with_suffix("") / "subagents" / "agent-a1.jsonl", [
                        assistant(ticket.session, 50, [{"type": "text", "text": "Done."}])])
                result = world.draw()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(counts(result), (pool, 0, 0))

    def test_a_session_that_cannot_be_scanned_still_counts_as_another_opener(self) -> None:
        ticket = Ticket(1, 20)
        world = self.world([ticket])
        rival = world.log_path(ticket, ticket.rival_session)
        rival.write_text(world.log_path(ticket).read_text().replace(ticket.session, ticket.rival_session))
        write_lines(rival.with_suffix("") / "subagents" / "agent-r1.jsonl", [line(ticket.rival_session, "user", 50)])
        (rival.with_suffix("") / "subagents" / "agent-r1.meta.json").write_text("[]\n")
        result = world.draw()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(counts(result), (0, 0, 1))

    def test_a_run_whose_time_is_missing_or_out_of_range_vetoes_and_is_counted_without_ending_the_draw(self) -> None:
        for case in ("a PR in an unlisted repo", "a rival with no time", "a rival at the first moment",
                     "the session's results at the last moment"):
            with self.subTest(case=case):
                ticket = Ticket(1, 20, rival=OPENS if "rival" in case else "")
                world = self.world([ticket])
                if case == "a PR in an unlisted repo":  # the session opened a second PR, timing aside
                    log = world.log_path(ticket)
                    write_lines(log, read_lines(log) + [
                        {key: value for key, value in entry.items() if key != "timestamp"} for entry in
                        opening(ticket.session, 20, "https://github.com/example-org/gamma/pull/9")])
                elif "rival" in case:
                    retime(world.log_path(ticket, ticket.rival_session),
                           None if "no time" in case else "0001-01-01T00:00:00Z")
                else:
                    retime(world.log_path(ticket), "9999-12-31T23:59:59Z", "user")
                result = world.draw()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(counts(result), (0, 0, int(case != "a PR in an unlisted repo")))

    def test_a_ticket_whose_check_fails_before_the_change_is_replaced_by_the_next_in_seed_order(self) -> None:
        passing = self.world(full_pool())
        self.assertEqual(passing.draw("--seed", "5").returncode, 0)
        first = [entry["ticket"] for entry in passing.set_file()["tickets"] if entry["bucket"] == "0-50"]
        failed = first[3]
        world = self.world([Ticket(ticket.number, ticket.size, passes=ticket.number != failed)
                            for ticket in full_pool()])
        result = world.draw("--seed", "5")
        self.assertEqual(result.returncode, 0, result.stderr)
        drawn = [entry["ticket"] for entry in world.set_file()["tickets"] if entry["bucket"] == "0-50"]
        self.assertEqual(drawn[:9], [number for number in first if number != failed])
        self.assertNotIn(drawn[9], first)
        self.assertEqual(world.set_file()["set_aside"], [{"label": "A", "ticket": failed, "bucket": "0-50",
                                                           "reason": "check exited 1",
                                                           "check_output": f"checks/A-{failed}.txt"}])
        self.assertEqual(result.stdout.splitlines()[2:5], ["0-50: pool 12, set aside 1, kept 10.",
                                                            "51-300: pool 12, set aside 0, kept 10.",
                                                            "301-1500: pool 12, set aside 0, kept 10."])
        self.assertEqual((world.state / f"checks/A-{failed}.txt").read_text(),
                         f"$ {SETUP}\n\nsetup exit 0\n$ {CHECK}\n\ncheck exit 1\n")
        self.assertEqual((world.state / f"checks/A-{drawn[0]}.txt").read_text(),
                         f"$ {SETUP}\n\nsetup exit 0\n$ {CHECK}\n\ncheck exit 0\n")

    def test_a_bucket_whose_pool_holds_fewer_than_ten_writes_no_set_and_runs_no_check(self) -> None:
        world = self.world(sized(1, 12, 20) + sized(101, 9, 100) + sized(201, 12, 800))
        result = world.draw("--seed", "2")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "Seed 2.",
            "Vetoed 0 PRs of the listed repos: a call may have opened each, so none is in the pool.",
            "0-50: pool 12, set aside 0, kept 0.", "51-300: pool 9, set aside 0, kept 0.",
            "301-1500: pool 12, set aside 0, kept 0.", "No set written: a bucket cannot reach 10 tickets."])
        self.assertEqual(sorted(path.name for path in world.state.iterdir()),
                         ["draw.lock", "project-labels.json", "repos.json"])
        self.assertNotIn("repo clone", world.gh_log.read_text())

    def test_a_bucket_that_cannot_reach_ten_once_tickets_are_set_aside_writes_no_set(self) -> None:
        world = self.world(sized(1, 12, 20) + sized(101, 12, 100)
                           + sized(201, 9, 800) + sized(210, 2, 800, passes=False))
        result = world.draw("--seed", "2")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "Seed 2.",
            "Vetoed 0 PRs of the listed repos: a call may have opened each, so none is in the pool.",
            "0-50: pool 12, set aside 0, kept 10.", "51-300: pool 12, set aside 0, kept 10.",
            "301-1500: pool 11, set aside 2, kept 9.", "No set written: a bucket cannot reach 10 tickets."])
        self.assertEqual(list(world.state.glob("replay-set-*")), [])
        self.assertFalse((world.state / "logs").exists())
        self.assertFalse((world.state / "draw-work").exists())

    def test_the_same_seed_on_the_same_pool_and_check_results_gives_the_same_set(self) -> None:
        world = self.world(full_pool(13) + [Ticket(14, 20, passes=False), Ticket(114, 100, passes=False)])
        other = world.root / "other-state"
        world.write_repos([{"repo": ALPHA, "check": CHECK, "setup": SETUP}])
        shutil.copytree(world.state, other)
        for state in (world.state, other):
            self.assertEqual(world.draw("--seed", "11", state=state).returncode, 0)
        first, again = world.set_file(state=world.state), world.set_file(state=other)
        self.assertNotEqual(first["set_aside"], [])
        self.assertEqual((first["tickets"], first["set_aside"]), (again["tickets"], again["set_aside"]))

    def test_a_second_call_draws_thirty_more_with_no_ticket_kept_or_set_aside_before(self) -> None:
        world = self.world([Ticket(ticket.number, ticket.size, passes=ticket.number % 100 > 3)
                            for ticket in full_pool(26)])
        self.assertEqual(world.draw("--seed", "1").returncode, 0)
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = world.set_file(1), world.set_file(2)
        self.assertNotEqual(first["set_aside"], [])
        self.assertEqual((second["set"], len(second["tickets"])), (2, 30))
        earlier = {entry["ticket"] for entry in first["tickets"] + first["set_aside"]}
        self.assertEqual(earlier & {entry["ticket"] for entry in second["tickets"] + second["set_aside"]}, set())

    def test_a_ticket_that_cannot_be_tried_is_set_aside_with_its_output_and_replaced(self) -> None:
        cannot = [Ticket(11, 20, lost=True), Ticket(12, 20, pushed=False), Ticket(13, 20, refuses_checkout=True),
                  Ticket(14, 20, repo=BETA), Ticket(15, 20, fork=True), Ticket(17, 20, recorded=False)]
        world = self.world(full_pool(10) + cannot + [Ticket(16, 20, repo=BETA)],
                           repos=[{"repo": ALPHA, "check": CHECK, "setup": SETUP}, {"repo": BETA, "check": CHECK, "setup": SETUP}])
        (world.remotes / f"{BETA}.fail-once").touch()  # the first clone fails, the next works
        result = world.draw("--seed", "1")  # its order tries 11 to 17, and 14 before 16
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(16, [entry["ticket"] for entry in world.set_file()["tickets"]])
        self.assertEqual(world.gh_log.read_text().count(f"repo clone {BETA} "), 2)
        aside = {entry["ticket"]: entry for entry in world.set_file()["set_aside"]}
        self.assertEqual({number: (entry["label"], entry["reason"]) for number, entry in aside.items()}, {
            11: ("A", "the commit before the merged PR is missing"),
            12: ("A", "GitHub records no push to the PR's branch by the time it was first ready for review"),
            13: ("A", "the commit before the merged PR cannot be checked out"),
            14: ("B", "the repo cannot be cloned"),
            15: ("A", "the PR came from a fork, whose pushes GitHub records in the fork"),
            17: ("A", "GitHub's record of the PR's history or of the pushes to its branch could not be read")})
        outputs = {number: (world.state / entry["check_output"]).read_text().splitlines()
                   for number, entry in aside.items()}
        self.assertEqual(outputs[11], ["the commit before the merged PR is missing"])
        self.assertEqual(outputs[12], ["GitHub records no push to the PR's branch by the time it was first ready for review"])
        self.assertEqual(outputs[13][-2:], ["the hook refused the checkout", "checkout exit 1"])
        self.assertEqual(outputs[14], [f"$ gh repo clone {BETA} {world.state / 'draw-work' / 'B'}",
                                       "stand-in gh: the clone failed", "clone exit 1"])
        self.assertEqual(outputs[17][1:], [f"stand-in gh: no saved answer for api repos/{ALPHA}/activity?ref=refs/heads/"
                                           "ticket-17&per_page=100", "gh exit 1"])
        self.assertEqual(result.stdout.splitlines()[2], "0-50: pool 17, set aside 6, kept 10.")

    def test_the_seed_gives_the_same_tickets_whatever_the_order_of_the_repo_list(self) -> None:
        alpha = full_pool(6)
        beta = [Ticket(ticket.number + 1000, ticket.size, repo=BETA) for ticket in alpha]
        world = self.world(alpha + beta)
        listed = [{"repo": ALPHA, "check": CHECK, "setup": SETUP}, {"repo": BETA, "check": CHECK, "setup": SETUP}]
        world.write_repos(listed)
        reversed_state = world.root / "reversed"
        reversed_state.mkdir()
        (reversed_state / "repos.json").write_text(json.dumps(listed[::-1]))
        drawn = []
        for state in (world.state, reversed_state):
            # The second draw names its machine directory relative to the folder it runs in.
            result = world.draw("--seed", "7", state=Path("..") / state.name if state == reversed_state else state)
            self.assertEqual(result.returncode, 0, result.stderr)
            key = json.loads((state / "project-labels.json").read_text())
            drawn.append(sorted((key[entry["label"]], entry["ticket"]) for entry in world.set_file(state=state)["tickets"]))
        self.assertEqual(json.loads((reversed_state / "project-labels.json").read_text()), {"A": BETA, "B": ALPHA})
        self.assertEqual(drawn[0], drawn[1])

    def test_a_check_s_background_processes_end_with_its_try(self) -> None:
        late = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, late)
        check = f"{CHECK} && {{ (sleep 1; touch {late}/$$) & }}"  # leaves a process that writes after the check
        world = self.world(full_pool(10), repos=[{"repo": ALPHA, "check": check, "setup": SETUP}])
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        subprocess.run(["sleep", "1.5"])
        self.assertEqual(list(late.iterdir()), [])

    def test_a_gh_answer_that_fails_or_cannot_be_read_sets_its_ticket_aside_with_what_gh_printed(self) -> None:
        bad = [Ticket(11, 20), Ticket(12, 20), Ticket(13, 20, draft=True)]
        world = self.world(full_pool(10) + bad)  # seed 2 tries all three before the last good ticket
        timeline = f"api repos/{ALPHA}/issues/511/timeline"
        world.answers[timeline + ".fails"] = '{"message": "Server Error"}'
        world.answers[f"api repos/{ALPHA}/activity?ref=refs/heads/ticket-12&per_page=100"] = "["
        world.answers[f"api repos/{ALPHA}/issues/513/timeline"] = json.dumps(
            [{"event": "ready_for_review", "created_at": 17}])
        result = world.draw("--seed", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[2], "0-50: pool 13, set aside 3, kept 10.")
        aside = {entry["ticket"]: entry for entry in world.set_file()["set_aside"]}
        self.assertEqual({number: entry["reason"] for number, entry in aside.items()}, dict.fromkeys(
            (11, 12, 13), "GitHub's record of the PR's history or of the pushes to its branch could not be read"))
        outputs = {number: (world.state / entry["check_output"]).read_text().splitlines()
                   for number, entry in aside.items()}
        self.assertEqual(outputs[11], [f"$ gh {timeline.replace('api', 'api --paginate', 1)}", '{"message": "Server Error"}',
                                       "stand-in gh: the request failed", "gh exit 1"])
        self.assertEqual(outputs[12][1:], ["[", "the draw cannot read the answer (JSONDecodeError)"])
        self.assertEqual(outputs[13][-1], "the draw cannot read the answer (TypeError)")

    def test_what_setup_starts_runs_through_the_check_and_ends_with_the_try(self) -> None:
        late = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, late)
        setup = f"{SETUP} && {{ (sleep 0.2; touch ready; sleep 1; touch {late}/$$) & }}"
        world = self.world(full_pool(10), repos=[{"repo": ALPHA, "check": f"{CHECK} && sleep 0.4 && test -e ready",
                                                  "setup": setup}])
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(world.set_file()["set_aside"], [])
        subprocess.run(["sleep", "1.5"])
        self.assertEqual(list(late.iterdir()), [])

    def test_an_interrupt_during_a_check_stops_the_check(self) -> None:
        marks = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, marks)
        check = f"{CHECK} && touch {marks}/started && sleep 1 && touch {marks}/late"
        world = self.world(full_pool(10), repos=[{"repo": ALPHA, "check": check, "setup": SETUP}])
        draw = world.start("--seed", "1")
        self.addCleanup(draw.kill)
        for _ in range(600):
            if (marks / "started").exists() or draw.poll() is not None:
                break
            subprocess.run(["sleep", "0.05"])
        draw.send_signal(signal.SIGINT)
        draw.communicate(timeout=60)
        subprocess.run(["sleep", "1.5"])
        self.assertEqual(sorted(path.name for path in marks.iterdir()), ["started"])

    def test_a_log_that_cannot_be_saved_ends_the_draw_naming_its_label_and_no_path(self) -> None:
        world = self.world(full_pool(10))
        (world.state / "scan-rows.lock").mkdir()  # the scan row cannot be written
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"\Adraw: could not save the session log of project A ticket \d+ "
                                        r"\(IsADirectoryError\)\.\n\Z")
        self.assertEqual(list(world.state.glob("replay-set-*")), [])

    def test_a_transcript_that_does_not_copy_whole_ends_the_draw_before_a_set(self) -> None:
        world = self.world(full_pool(10))
        # Each copy creates its target, writes nothing and fails, as a full disk would.
        result = world.draw("--seed", "1", prelude="import shutil\n"
                            "def copy(source, target, **options):\n"
                            "    open(target, 'w').close()\n"
                            "    raise OSError(28, 'No space left on device')\n"
                            "shutil.copyfile = copy")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"\Adraw: could not save the session log of project A ticket \d+ "
                                        r"\(OSError\)\.\n\Z")
        self.assertEqual(list(world.state.glob("replay-set-*")), [])
        self.assertFalse((world.state / "scan-rows.jsonl").exists())

    def test_a_helper_folder_that_cannot_be_listed_skips_its_session(self) -> None:
        ticket = Ticket(1, 20, by_helper=True)
        world = self.world([ticket])
        hidden = world.log_path(ticket).with_suffix("") / "subagents" / "workflows" / "run-1"
        hidden.mkdir(parents=True)
        hidden.chmod(0)
        self.addCleanup(hidden.chmod, 0o755)
        result = world.draw()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(counts(result), (0, 0, 1))

    def test_a_log_that_shrinks_after_its_session_qualified_ends_the_draw_before_a_set(self) -> None:
        world = self.world(full_pool(10))
        projects = world.config / "projects" / "-work-example"
        setup = f'{SETUP} && for log in {projects}/*.jsonl; do : > "$log"; done'
        world.write_repos([{"repo": ALPHA, "check": CHECK, "setup": setup}])
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"\Adraw: could not save the session log of project A ticket \d+ "
                                        r"\(OSError\)\.\n\Z")
        self.assertEqual(list(world.state.glob("replay-set-*")), [])

    def test_a_log_replaced_by_one_of_its_length_after_its_session_qualified_ends_the_draw_before_a_set(self) -> None:
        world = self.world(full_pool(10))
        projects = world.config / "projects" / "-work-example"
        setup = (f'{SETUP} && for log in {projects}/*.jsonl; do tr a b < "$log" > "$log.new" && '
                 'mv "$log.new" "$log"; done')
        world.write_repos([{"repo": ALPHA, "check": CHECK, "setup": setup}])
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"\Adraw: could not save the session log of project A ticket \d+ "
                                        r"\(OSError\)\.\n\Z")
        self.assertEqual(list(world.state.glob("replay-set-*")), [])

    def test_a_retry_keeps_nothing_from_the_archive_of_an_earlier_draw(self) -> None:
        world = self.world(full_pool(10, by_helper=True))
        for ticket in world.tickets.values():
            folder = world.log_path(ticket).with_suffix("") / "subagents"
            write_lines(folder / "agent-a2.jsonl", [{**entry, "agentId": "a2"} for entry in read_lines(folder / "agent-a1.jsonl")])
        (world.state / "scan-rows.lock").mkdir()  # the first draw copies a log and then cannot write its row
        self.assertEqual(world.draw("--seed", "1").returncode, 1)
        (world.state / "scan-rows.lock").rmdir()
        for ticket in world.tickets.values():
            (world.log_path(ticket).with_suffix("") / "subagents" / "agent-a2.jsonl").unlink()
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(text) for text in (world.state / "scan-rows.jsonl").read_text().splitlines()]
        self.assertEqual({tuple(helper["id"] for helper in row["helpers"]) for row in rows}, {("a1",)})
        self.assertEqual(list((world.state / "logs").rglob("agent-a2*")), [])

    def test_an_unreadable_helper_folder_leaves_the_session_s_readable_opening_counting_against_others(self) -> None:
        ticket = Ticket(1, 20)
        world = self.world([ticket])
        rival = world.log_path(ticket, ticket.rival_session)
        rival.write_text(world.log_path(ticket).read_text().replace(ticket.session, ticket.rival_session))
        hidden = rival.with_suffix("") / "subagents" / "workflows" / "run-1"
        hidden.mkdir(parents=True)
        hidden.chmod(0)
        self.addCleanup(hidden.chmod, 0o755)
        result = world.draw()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(counts(result), (0, 0, 1))

    def test_a_session_folder_that_cannot_be_searched_skips_its_session(self) -> None:
        ticket = Ticket(1, 20)
        world = self.world([ticket])
        folder = world.log_path(ticket).with_suffix("")
        write_lines(folder / "subagents" / "agent-a1.jsonl",
                    opening(ticket.session, 20, "https://github.com/example-org/gamma/pull/9"))
        folder.chmod(0)
        self.addCleanup(folder.chmod, 0o755)
        result = world.draw()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(counts(result), (0, 0, 1))

    def test_lines_a_session_writes_while_the_draw_reads_its_log_are_in_the_archive(self) -> None:
        world = self.world(full_pool(10))
        pending = {}  # each log's opening call and result, written as the draw first opens the log
        for ticket in world.tickets.values():
            path = world.log_path(ticket)
            text = path.read_text().splitlines(keepends=True)
            path.write_text("".join(text[:-2]))
            pending[str(path)] = "".join(text[-2:])
        (world.root / "pending.json").write_text(json.dumps(pending))
        result = world.draw("--seed", "1", prelude="import json, pathlib\n"
                            f"pending = json.loads(pathlib.Path({str(world.root / 'pending.json')!r}).read_text())\n"
                            "real_open = pathlib.Path.open\n"
                            "def open_(self, mode='r', *args, **options):\n"
                            "    if 'r' in mode and str(self) in pending:\n"
                            "        with real_open(self, 'a') as log:\n"
                            "            log.write(pending.pop(str(self)))\n"
                            "    return real_open(self, mode, *args, **options)\n"
                            "pathlib.Path.open = open_")
        self.assertEqual(result.returncode, 0, result.stderr)
        for entry in world.set_file()["tickets"]:
            self.assertEqual((world.state / entry["log"]).read_text(),
                             world.log_path(world.tickets[entry["ticket"]]).read_text())

    def test_a_retry_that_cannot_copy_a_log_leaves_the_earlier_archive_as_it_was(self) -> None:
        world = self.world(full_pool(10, by_helper=True))
        (world.state / "scan-rows.lock").mkdir()  # the first draw saves a log and then cannot write its row
        self.assertEqual(world.draw("--seed", "1").returncode, 1)
        (world.state / "scan-rows.lock").rmdir()
        logs = world.state / "logs"
        saved = {path: path.read_bytes() for path in logs.rglob("*") if path.is_file()}
        self.assertNotEqual(saved, {})
        projects = world.config / "projects" / "-work-example"
        setup = f'{SETUP} && for log in {projects}/*.jsonl; do [ ! -e "$log" ] || mv "$log" "$log.gone"; done'  # they expire
        world.write_repos([{"repo": ALPHA, "check": CHECK, "setup": setup}])
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"\Adraw: could not save the session log of project A ticket \d+ "
                                        r"\(FileNotFoundError\)\.\n\Z")
        self.assertEqual({path: path.read_bytes() for path in logs.rglob("*") if path.is_file()}, saved)
        self.assertEqual(sorted(path.name for path in logs.iterdir()), sorted({
            path.relative_to(logs).parts[0] for path in saved}))

    def test_an_interrupt_while_a_timed_out_check_is_stopped_signals_its_group_once(self) -> None:
        world = self.world(full_pool(10))
        record = world.root / "killpg.txt"
        result = world.draw("--seed", "1", prelude="import os, subprocess\n"
                            "real_wait = subprocess.Popen.wait\n"
                            "def wait(self, timeout=None):\n"
                            "    if timeout == 3600:  # every step times out at once\n"
                            "        raise subprocess.TimeoutExpired(self.args, timeout)\n"
                            "    return real_wait(self, timeout)\n"
                            "subprocess.Popen.wait = wait\n"
                            "real_killpg = os.killpg\n"
                            "def killpg(group, number):\n"
                            f"    with open({str(record)!r}, 'a') as out:\n"
                            "        out.write(f'{number}\\n')\n"
                            "    real_killpg(group, number)\n"
                            "    raise KeyboardInterrupt  # as if Ctrl-C came right after the signal\n"
                            "os.killpg = killpg")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(record.read_text(), f"{int(signal.SIGKILL)}\n")
        self.assertNotIn("PermissionError", result.stderr)
        self.assertEqual(result.stderr.splitlines()[-1], "KeyboardInterrupt")

    def test_a_sigterm_during_a_check_stops_the_check(self) -> None:
        marks = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, marks)
        check = f"{CHECK} && touch {marks}/started && sleep 1 && touch {marks}/late"
        world = self.world(full_pool(10), repos=[{"repo": ALPHA, "check": check, "setup": SETUP}])
        draw = world.start("--seed", "1")
        self.addCleanup(draw.kill)
        for _ in range(600):
            if (marks / "started").exists() or draw.poll() is not None:
                break
            subprocess.run(["sleep", "0.05"])
        draw.send_signal(signal.SIGTERM)
        draw.communicate(timeout=60)
        subprocess.run(["sleep", "1.5"])
        self.assertEqual(sorted(path.name for path in marks.iterdir()), ["started"])
        self.assertFalse((world.state / "draw-work").exists())

    def test_the_model_takes_one_vote_per_parent_response_however_many_helpers_copy_it(self) -> None:
        world = self.world(full_pool(10))
        other = "claude-test-model-2"
        for ticket in world.tickets.values():
            log = world.log_path(ticket)
            copied = assistant(ticket.session, 50, [{"type": "text", "text": "Noted."}], other)
            write_lines(log, read_lines(log) + [assistant(ticket.session, minute, [{"type": "text", "text": "Working."}])
                                                for minute in (46, 48)] + [copied])
            for number in range(1, 5):
                write_lines(log.with_suffix("") / "subagents" / f"agent-b{number}.jsonl", [copied])
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({entry["model"] for entry in world.set_file()["tickets"]}, {MODEL})

    def test_a_scan_row_file_that_cannot_be_read_ends_the_draw_naming_its_label_and_no_path(self) -> None:
        world = self.world(full_pool(10))
        (world.state / "scan-rows.jsonl").write_text("[]\n")
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"\Adraw: could not save the session log of project A ticket \d+ "
                                        r"\(AttributeError\)\.\n\Z")
        self.assertEqual(list(world.state.glob("replay-set-*")), [])

    def test_a_failed_gh_call_names_the_label_keeps_gh_s_message_in_a_file_and_writes_no_set(self) -> None:
        world = self.world(full_pool(10))
        del world.answers[f"issue {ALPHA} 5"]
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines(), [
            f"draw: `gh issue view` failed for project A with exit 1. Its message is in {world.state / 'draw-error.txt'}."])
        self.assertEqual((world.state / "draw-error.txt").read_text(),
                         f"stand-in gh: no saved answer for issue {ALPHA} 5\n")
        self.assertEqual(list(world.state.glob("replay-set-*")), [])

    def test_a_missing_repo_list_or_a_bad_argument_writes_no_set(self) -> None:
        world = self.world(full_pool(10))
        (world.state / "repos.json").unlink()
        result = world.draw()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines(), [
            f"draw: {world.state / 'repos.json'} does not exist. Write the repo list there first; --help gives its format."])
        self.assertEqual(world.draw("--seed", "x").returncode, 2)
        self.assertEqual(list(world.state.glob("replay-set-*")), [])


if __name__ == "__main__":
    unittest.main()
