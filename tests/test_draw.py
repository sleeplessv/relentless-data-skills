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
    twin: bool = False  # a second session also opened the PR
    copied: bool = False  # a resumed session's log starts with copies of this session's lines
    issue: int = 0  # the issue the PR closes, when not `number`
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
            "closingIssuesReferences": [{"number": (ticket.issue or ticket.number) + extra, "repository": {
                "name": repo.split("/")[1], "owner": {"login": repo.split("/")[0]}}} for extra in range(ticket.closes)]})
        self.answers[f"issue {repo} {ticket.issue or ticket.number}"] = json.dumps({
            "title": f"Ticket {ticket.number}", "body": f"## What to build\n\nThing {ticket.number}.\n\n{ticket.criteria}\n"})
        events = [{"event": "committed", "sha": commit["oid"]} for commit in commits]
        if ticket.draft:  # two pages, as `gh api --paginate` prints them; ready at 10:30, draft again, ready at 12:30
            events = [*events, {"event": "ready_for_review", "created_at": "2026-01-01T10:30:00Z"},
                      {"event": "convert_to_draft", "created_at": "2026-01-01T12:10:00Z"}]
            pages = [events[:2], [*events[2:], {"event": "ready_for_review", "created_at": "2026-01-01T12:30:00Z"}]]
        else:
            pages = [events]
        self.answers[f"api repos/{repo}/issues/{pr}/timeline"] = "\n".join(json.dumps(page) for page in pages)

    def log_path(self, ticket: Ticket, session: str | None = None) -> Path:
        return self.config / "projects" / "-work-example" / f"{session or ticket.session}.jsonl"

    def write_log(self, ticket: Ticket) -> None:
        session = ticket.session
        lines = [line(session, "user", 0, message={"role": "user", "content": "Implement the ticket."})]
        if ":" in ticket.skill:  # a plugin's skill, loaded by a Skill call
            lines += [assistant(session, 1, [{"type": "tool_use", "id": f"toolu_skill_{session}", "name": "Skill",
                                              "input": {"skill": ticket.skill}}]),
                      line(session, "user", 1, message={"role": "user", "content": [
                          {"type": "tool_result", "tool_use_id": f"toolu_skill_{session}", "content": "Launching skill"}]})]
        else:
            lines.append(line(session, "user", 1, isMeta=True, message={"role": "user", "content": [
                {"type": "text", "text": f"Base directory for this skill: /home/someone/.claude/skills/{ticket.skill}\n\n# Body"}]}))
        urls = [f"https://github.com/{ticket.repo}/pull/{ticket.pr + 1000 * extra}" for extra in range(ticket.prs)]
        opened = [entry for minute, url in enumerate(urls, 2) for entry in opening(session, minute * 2, url)]
        if ticket.by_helper:
            helper = self.log_path(ticket).with_suffix("") / "subagents" / "agent-a1.jsonl"
            write_lines(helper, [{**entry, "agentId": "a1", "isSidechain": True} for entry in opened])
            opened = [assistant(session, 30, [{"type": "text", "text": "The helper opened the PR."}])]
        write_lines(self.log_path(ticket), lines + opened)
        if ticket.twin:
            other = f"00000000-0000-4000-9000-{ticket.number:012d}"
            write_lines(self.log_path(ticket, other), opening(other, 2, f"https://github.com/{ticket.repo}/pull/{ticket.pr}"))
        if ticket.copied:
            other = f"00000000-0000-4000-a000-{ticket.number:012d}"
            own = line(other, "user", 40, message={"role": "user", "content": "Carry on."})
            write_lines(self.log_path(ticket, other), lines + opened + [own])

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


class TestOneDraw(unittest.TestCase):
    """One draw of a pool of 36 tickets, all passing, each opened by a helper; the tests read what it left."""

    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.world = World(Path(temporary.name), full_pool(by_helper=True))
        cls.outside = [cls.world.root / name for name in ("claude", "remotes", "home", "cwd", "bin")]
        cls.before = cls.files()
        cls.result = cls.world.draw("--seed", "7")

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
                "base_commit": world.bases[ticket.number], "ready_commit": ticket.commit("b"), "model": MODEL,
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
            "Seed 7.", "0-50: pool 12, set aside 0, kept 10.", "51-300: pool 12, set aside 0, kept 10.",
            "301-1500: pool 12, set aside 0, kept 10.", f"Wrote {state / 'replay-set-1.json'}."])
        self.assertNotIn("example-org", self.result.stdout + self.result.stderr)


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

    def test_pool_holds_only_tickets_that_meet_readings_2_and_3_in_listed_repos(self) -> None:
        kept = [
            *sized(1, 6, 20), Ticket(7, 20, by_helper=True), Ticket(8, 20, copied=True),
            Ticket(9, 20, criteria="## Acceptance\n\n1. The report prints the total."),
            Ticket(10, 50, criteria="## Done when\n\n* The report prints the total."),
            *sized(101, 8, 100), Ticket(109, 51), Ticket(110, 300, skill="some-plugin:implement-backlog"),
            *sized(201, 8, 800, draft=True), Ticket(209, 301, draft=True), Ticket(210, 1500)]
        left_out = [
            Ticket(11, 20, skill="tdd"), Ticket(12, 20, prs=2), Ticket(13, 20, closes=2), Ticket(14, 1501),
            Ticket(15, 20, criteria="## Acceptance criteria\n\nThe report prints the total."),
            Ticket(16, 20, criteria="## Notes\n\n- The report prints the total."),
            Ticket(17, 20, criteria="## Acceptance criteria\n\n```\n- not a list item\n```"),
            Ticket(18, 20, state="OPEN"), Ticket(19, 20, twin=True), Ticket(20, 20, repo=BETA),
            Ticket(21, 20, issue=300), Ticket(22, 100, issue=300)]
        world = self.world(kept + left_out)
        result = world.draw("--seed", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(entry["ticket"] for entry in world.set_file()["tickets"]),
                         [ticket.number for ticket in kept])
        self.assertEqual(world.set_file()["set_aside"], [])
        for entry in world.set_file()["tickets"]:  # committed at 10:00, 11:00 and 13:00; created at 12:00
            ticket = world.tickets[entry["ticket"]]
            self.assertEqual(entry["ready_commit"], ticket.commit("a" if ticket.draft else "b"), ticket.number)

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
        self.assertEqual(result.stdout.splitlines()[1:4], ["0-50: pool 12, set aside 1, kept 10.",
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
            "Seed 2.", "0-50: pool 12, set aside 0, kept 0.", "51-300: pool 9, set aside 0, kept 0.",
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
            "Seed 2.", "0-50: pool 12, set aside 0, kept 10.", "51-300: pool 12, set aside 0, kept 10.",
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
