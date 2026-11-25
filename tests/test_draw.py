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

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

DRAW = Path(__file__).resolve().parent.parent / "scripts" / "draw.py"
ALPHA = "example-org/alpha"
BETA = "example-org/beta"
MODEL = "claude-test-model-1"
SETUP = "touch .setup-done"
CHECK = "test -e .setup-done && test ! -e broken"

# Records each call as one line, clones a bare repo for `repo clone`, and prints the
# saved answer for `pr view`, `issue view` and `api`. A call with no saved answer exits 1.
GH = r"""#!/bin/bash
printf '%s\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "repo clone") exec git clone -q "$GH_REMOTES/$3.git" "$4" ;;
  "pr view"|"issue view")
    for ((at = 1; at < $#; at++)); do [ "${!at}" = --repo ] && { next=$((at + 1)); repo=${!next}; }; done
    key="$1 $repo $3" ;;
  "api --paginate") key="api $3" ;;
  *) key="$*" ;;
esac
file="$GH_ANSWERS/${key//[ \/]/_}"
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
    merge: str = ""  # the merge commit's SHA, set when the world builds its repo

    @property
    def pr(self) -> int:
        return self.number + 500

    @property
    def session(self) -> str:
        return f"00000000-0000-4000-8000-{self.number:012d}"

    def commit(self, letter: str) -> str:
        return f"{self.number:08d}" + letter * 32


def sized(start: int, count: int, size: int, **fields: object) -> list[Ticket]:
    return [Ticket(number, size, **fields) for number in range(start, start + count)]


def full_pool(per_bucket: int = 12, **fields: object) -> list[Ticket]:
    """`per_bucket` tickets of 20, 100 and 800 changed lines, numbered from 1, 101 and 201."""
    return sized(1, per_bucket, 20, **fields) + sized(101, per_bucket, 100, **fields) + sized(201, per_bucket, 800, **fields)


def line(session: str, kind: str, minute: int, **fields: object) -> dict:
    return {"type": kind, "sessionId": session, "uuid": f"{session}-{kind}-{minute}",
            "timestamp": f"2026-01-05T10:{minute:02d}:00.000Z", "cwd": "/work/example", **fields}


def assistant(session: str, minute: int, content: list) -> dict:
    usage = {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40}
    return line(session, "assistant", minute, message={
        "id": f"msg_{session}_{minute}", "role": "assistant", "model": MODEL, "content": content, "usage": usage})


def opening(session: str, minute: int, url: str) -> list[dict]:
    """A Bash call that runs `gh pr create` and the result that prints the new PR's URL."""
    call = f"toolu_{session}_{minute}"
    return [assistant(session, minute, [{"type": "tool_use", "id": call, "name": "Bash",
                                         "input": {"command": "gh pr create --draft --body-file body.md"}}]),
            line(session, "user", minute + 1, message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call, "content": url + "\n", "is_error": False}]})]


def write_lines(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in lines))


class World:
    """The repos, logs and saved `gh` answers for one test, under one temporary folder."""

    def __init__(self, root: Path, tickets: list[Ticket], repos: list[dict] | None = None) -> None:
        self.root = root
        self.state = root / "state"
        self.config = root / "claude"
        self.remotes = root / "remotes"
        self.bin = root / "bin"
        self.gh_log = root / "gh-calls.jsonl"
        self.tickets = {ticket.number: ticket for ticket in tickets}
        self.answers: dict[str, str] = {}
        self.bases: dict[int, str] = {}
        self.bin.mkdir(parents=True)
        (self.bin / "gh").write_text(GH)
        (self.bin / "gh").chmod(0o755)
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
        repo, pr = ticket.repo, ticket.pr
        commits = [{"oid": ticket.commit(letter), "committedDate": f"2026-01-01T{hour}:00:00Z"}
                   for letter, hour in (("a", 10), ("b", 11), ("c", 13))]
        self.answers[f"pr {repo} {pr}"] = json.dumps({
            "state": ticket.state, "additions": ticket.size - ticket.size // 4, "deletions": ticket.size // 4,
            "createdAt": "2026-01-01T12:00:00Z", "mergeCommit": {"oid": ticket.merge} if ticket.state == "MERGED" else None,
            "commits": commits,
            "closingIssuesReferences": [{"number": ticket.number + extra, "repository": {
                "name": repo.split("/")[1], "owner": {"login": repo.split("/")[0]}}} for extra in range(ticket.closes)]})
        self.answers[f"issue {repo} {ticket.number}"] = json.dumps({
            "title": f"Ticket {ticket.number}", "body": f"## What to build\n\nThing {ticket.number}.\n\n{ticket.criteria}\n"})
        events = [{"event": "committed", "sha": commit["oid"]} for commit in commits]
        if ticket.draft:  # two pages, as `gh api --paginate` prints them; ready at 10:30, draft again, ready at 12:30
            events = [*events, {"event": "ready_for_review", "created_at": "2026-01-01T10:30:00Z"},
                      {"event": "convert_to_draft", "created_at": "2026-01-01T12:10:00Z"}]
            pages = [events[:2], [*events[2:], {"event": "ready_for_review", "created_at": "2026-01-01T12:30:00Z"}]]
        else:
            pages = [events]
        self.answers[f"api repos/{repo}/issues/{pr}/timeline"] = "\n".join(json.dumps(page) for page in pages)

    def log_path(self, ticket: Ticket) -> Path:
        return self.config / "projects" / "-work-example" / f"{ticket.session}.jsonl"

    def write_log(self, ticket: Ticket) -> None:
        session = ticket.session
        lines = [line(session, "user", 0, message={"role": "user", "content": "Implement the ticket."}),
                 line(session, "user", 1, isMeta=True, message={"role": "user", "content": [
                     {"type": "text", "text": f"Base directory for this skill: /home/someone/.claude/skills/{ticket.skill}\n\n# Body"}]})]
        urls = [f"https://github.com/{ticket.repo}/pull/{ticket.pr + 1000 * extra}" for extra in range(ticket.prs)]
        opened = [entry for minute, url in enumerate(urls, 2) for entry in opening(session, minute * 2, url)]
        if ticket.by_helper:
            helper = self.log_path(ticket).with_suffix("") / "subagents" / "agent-a1.jsonl"
            write_lines(helper, [{**entry, "agentId": "a1", "isSidechain": True} for entry in opened])
            opened = [assistant(session, 30, [{"type": "text", "text": "The helper opened the PR."}])]
        write_lines(self.log_path(ticket), lines + opened)

    def write_repos(self, repos: list[dict]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "repos.json").write_text(json.dumps(repos))

    def draw(self, *args: str, state: Path | None = None) -> subprocess.CompletedProcess[str]:
        answers = self.root / "answers"
        shutil.rmtree(answers, ignore_errors=True)
        answers.mkdir()
        for key, answer in self.answers.items():
            (answers / re.sub(r"[ /]", "_", key)).write_text(answer + "\n")
        env = {**os.environ, "HOME": str(self.root / "home"), "DELIVER_STATE_DIR": str(state or self.state),
               "CLAUDE_CONFIG_DIR": str(self.config), "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
               "GH_LOG": str(self.gh_log), "GH_ANSWERS": str(answers), "GH_REMOTES": str(self.remotes)}
        work = self.root / "cwd"
        work.mkdir(exist_ok=True)
        return subprocess.run([sys.executable, str(DRAW), *args], cwd=work, env=env, text=True, capture_output=True)

    def set_file(self, number: int = 1, state: Path | None = None) -> dict:
        return json.loads(((state or self.state) / f"replay-set-{number}.json").read_text())


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

    def test_draw_writes_ten_tickets_per_bucket_with_each_entrys_fields(self) -> None:
        world = self.world(full_pool())
        result = world.draw("--seed", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
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
                "base_commit": world.bases[ticket.number], "ready_commit": ticket.commit("b"), "model": MODEL,
                "pr": ticket.pr, "session": ticket.session, "log": f"logs/{ticket.session}.jsonl",
                "check_output": f"checks/A-{ticket.number}.txt"})
        self.assertEqual(json.loads((world.state / "project-labels.json").read_text()), {"A": ALPHA})


if __name__ == "__main__":
    unittest.main()
