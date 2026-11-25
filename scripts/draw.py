#!/usr/bin/env python3
"""Draw the replay set. `--help` gives the rules and the files the draw reads and writes."""
from __future__ import annotations

import fcntl
import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True  # importing the sibling would otherwise write scripts/__pycache__/ into the checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan  # noqa: E402  (a sibling script, not an installed package)

GENERATION_ONE = ("orchestrator-mode", "implement-ticket", "implement-feature", "implement-backlog")
CRITERIA_HEADINGS = ("Acceptance criteria", "Acceptance", "Done when")
BUCKETS = {f"{low}-{high}": range(low, high + 1) for low, high in ((0, 50), (51, 300), (301, 1500))}
PER_BUCKET = 10
CHECK_TIMEOUT = 3600  # seconds, for each of setup and check
CLOCK_SLACK = timedelta(minutes=1)  # between the machine's clock in the log and GitHub's
EXIT_SHORT = 3
NO_PUSH = "GitHub records no push to the PR's branch by the time it was first ready for review"
PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
MAY_OPEN = re.compile(r"\bgh\s+pr\s+create\b")
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([\w.-]+)\1")
COMMAND_END = set(";&|()\n")


def one_of(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " or " + items[-1]


HELP = f"""\
Draw the replay set: {PER_BUCKET * len(BUCKETS)} tickets generation one finished, {PER_BUCKET} per size bucket.

Usage: python3 scripts/draw.py [--seed N]

The pool is every ticket that meets all of these:
- One session under $CLAUDE_CONFIG_DIR/projects (default ~/.claude) ran
  `gh pr create`, itself or through a helper, and the run's result holds the
  ticket's PR's URL. GitHub says the PR was opened while the command ran. No
  other such run in the session prints another PR's URL. Lines a resumed
  session's log copied from an earlier session count as the earlier session's.
- That session loaded a generation-one skill:
  {one_of(list(GENERATION_ONE))}.
- The PR is merged and closes one issue, the ticket, in the PR's own repo. No
  other PR in the pool closes it.
- The ticket's body holds an item of a list under
  {one_of([f'"## {heading}"' for heading in CRITERIA_HEADINGS])}.
- The PR's repo is in repos.json, and the ticket is in no earlier set, kept or
  set aside.

A ticket's size is its PR's additions plus deletions. The buckets are
{one_of(list(BUCKETS)).replace(" or ", " and ")} changed lines. A larger PR is in no bucket.
Each bucket's pool is sorted by repo and ticket number, then shuffled by
random.Random seeded with "<seed>:<bucket>". The draw tries the tickets in that
order until {PER_BUCKET} pass. A try runs the repo's setup command, where it has one,
and then its check command, each with sh, in a clean checkout of the commit
before the merged PR: the first parent of the PR's merge commit. A step that
runs for more than {CHECK_TIMEOUT // 60} minutes is stopped. When the try ends, every process
its steps started is stopped. A ticket is set aside when its repo cannot be
cloned, when that commit is missing or cannot be checked out, when the PR came
from a fork, when GitHub records no push to the PR's branch by the time it was
first ready, or when its setup or check exits non-zero or is stopped.

The commit first marked ready is the head of the PR's branch at the PR's first
ready_for_review event, or at its creation when it has none: the newest push
GitHub records for that branch at or before then.

Every file is in the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver):

  repos.json            The owner's repo list, written by hand. A JSON list of
                        {{"repo": "owner/name", "check": "<command>",
                        "setup": "<command>"}} objects. "setup" is optional.
  project-labels.json   The key from label to repo: {{"A": "owner/name", ...}}.
                        A repo keeps its label. A new repo takes the first
                        label not in use, in repos.json order: A to Z, then
                        AA, AB and on.
  replay-set-<n>.json   Set n, as {{"set", "seed", "drawn_at", "tickets",
                        "set_aside"}}. A ticket entry holds label, ticket,
                        bucket, size, title, body, base_commit, ready_commit,
                        model, pr, session, log and check_output. A set-aside
                        entry holds label, ticket, bucket, reason and
                        check_output. Paths are relative to the machine
                        directory.
  checks/<label>-<ticket>.txt
                        The output of each try: its setup and check, or the
                        clone or checkout that failed, or why it was not run.
  logs/<session>.jsonl and logs/<session>/
                        A copy of each kept ticket's session log and the
                        session's folder, helpers' transcripts included,
                        scanned into scan-rows.jsonl.
  draw-work/            Clones and checkouts, removed when the draw ends.

Output names projects by label only. A session log that cannot be read is
skipped and counted.

Exit 0: a set was written. Exit 1: an error; no set was written. Exit 2: bad
usage. Exit {EXIT_SHORT}: a bucket holds fewer than {PER_BUCKET} tickets, or cannot reach {PER_BUCKET} once
tickets are set aside; no set was written, and the count per bucket is printed."""


class DrawError(Exception):
    """Ends the draw with exit 1 and no set written."""


def label_name(number: int) -> str:
    """1 is A, 26 is Z, 27 is AA."""
    label = ""
    while number:
        number, rest = divmod(number - 1, 26)
        label = chr(ord("A") + rest) + label
    return label


def generation_one(skills: list[str]) -> bool:
    # A plugin's skill may carry the plugin's name as a prefix, as in plugin:implement-ticket.
    return any(name.split(":")[-1] in GENERATION_ONE for name in skills)


def moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def parts(line: dict) -> list[dict]:
    content = (line.get("message") or {}).get("content")
    return [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []


def result_text(part: dict) -> str:
    content = part.get("content")
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content or "")


def runs_gh_pr_create(command: str) -> bool:
    """True when a shell command runs `gh pr create`, not when it only holds those words as text."""
    kept, end = [], None
    for text in command.split("\n"):
        if end is not None:  # a here-document's body is the input of a command, not a command
            end = None if text.strip() == end else end
            continue
        kept.append(text)
        if found := HEREDOC.findall(text):
            end = found[-1][1]
    lexer = shlex.shlex("\n".join(kept).replace("\\\n", " "), posix=True, punctuation_chars=True)
    lexer.whitespace = " \t\r"  # a newline ends a command, as ; does
    lexer.wordchars += "$="
    try:
        tokens = list(lexer)
    except ValueError:  # an unclosed quote
        return False
    words: list[str] = []
    for token in [*tokens, ";"]:
        if set(token) <= COMMAND_END:
            if words[:3] == ["gh", "pr", "create"]:
                return True
            words = []
        elif words or not re.fullmatch(r"\w+=\S*", token):  # a leading NAME=value sets the command's environment
            words.append(token)
    return False


def own_lines(log: Path) -> tuple[list[dict], list[dict]]:
    """The session's own lines: its log's, less those copied from an earlier session, then its helpers'."""
    main = [line for line in scan.read_lines(log) if line.get("sessionId") in (None, log.stem)]
    return main, [line for path in scan.helper_logs(log) for line in scan.read_lines(path)]


def opened_prs(lines: list[dict]) -> dict[tuple[str, int], tuple[datetime, datetime]]:
    """Each PR whose URL a successful `gh pr create` run prints, as (owner/name in lower case, number),
    with the times of the run's call and of its result."""
    calls = {part.get("id"): line.get("timestamp") for line in lines if line.get("type") == "assistant"
             for part in parts(line) if part.get("type") == "tool_use" and part.get("name") == "Bash"
             and runs_gh_pr_create(str((part.get("input") or {}).get("command")))}
    found = {}
    for line in lines:
        for part in parts(line) if line.get("type") == "user" else []:
            start, end = calls.get(part.get("tool_use_id")), line.get("timestamp")
            if part.get("type") == "tool_result" and not part.get("is_error") and isinstance(start, str) \
                    and isinstance(end, str):
                for repo, number in PR_URL.findall(result_text(part)):
                    found[(repo.lower(), int(number))] = (moment(start), moment(end))
    return found


def has_criteria(body: str | None) -> bool:
    """True when the body holds an item of a list under one of the CRITERIA_HEADINGS, read as Markdown."""
    headings = {heading.lower() for heading in CRITERIA_HEADINGS}
    under, fence, paragraph = False, "", ""
    for text in re.sub(r"<!--.*?(?:-->|\Z)", "", body or "", flags=re.DOTALL).splitlines():
        if fence:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", text):
                fence = ""
            continue
        if opening := re.match(r" {0,3}(`{3,}(?!.*`)|~{3,})", text):
            fence, paragraph = opening.group(1), ""
            continue
        if heading := re.fullmatch(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*", text):
            level, title = len(heading.group(1)), heading.group(2) or ""
        elif paragraph and (underline := re.fullmatch(r" {0,3}(=+|-+)[ \t]*", text)):
            level, title = (1 if underline.group(1)[0] == "=" else 2), paragraph
        else:
            if re.fullmatch(r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*", text) or not text.strip():
                paragraph = ""  # a thematic break or a blank line
            elif re.match(r" {0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+\S", text):  # deeper is an indented code line
                if under:
                    return True
                paragraph = ""
            else:
                paragraph = text.strip()
            continue
        paragraph = ""
        if level <= 2:
            under = level == 2 and title.strip().lower() in headings
    return False


def pages(text: str) -> list:
    """The items of every page `gh api --paginate` printed: one JSON list per page."""
    decoder, items, at = json.JSONDecoder(), [], 0
    text = text.strip()
    while at < len(text):
        page, at = decoder.raw_decode(text, at)
        items += page
        at = len(text) - len(text[at:].lstrip())
    return items


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except ValueError:
        raise DrawError(f"{path} is not JSON.")


def stop(group: int) -> None:
    try:
        os.killpg(group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # the group has ended
        pass


class Draw:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.state = scan.state_dir()
        self.work = self.state / "draw-work"
        self.clones: dict[str, tuple[Path, str]] = {}  # label: (clone, its failure's output or "")

    def gh(self, label: str, *args: str) -> str:
        result = subprocess.run(["gh", *args], text=True, capture_output=True)
        if result.returncode:
            # gh's own message can name the repo, so it goes to a file, not to the output.
            scan.write_private(self.state / "draw-error.txt", result.stderr)
            raise DrawError(f"`gh {args[0]} {args[1]}` failed for project {label} with exit {result.returncode}. "
                            f"Its message is in {self.state / 'draw-error.txt'}.")
        return result.stdout

    def repos(self) -> dict[str, dict]:
        path = self.state / "repos.json"
        if not path.is_file():
            raise DrawError(f"{path} does not exist. Write the repo list there first; --help gives its format.")
        entries = read_json(path)
        if not isinstance(entries, list) or not all(
                isinstance(entry, dict) and isinstance(entry.get("repo"), str)
                and re.fullmatch(r"[\w.-]+/[\w.-]+", entry["repo"])
                and isinstance(entry.get("check"), str) and entry["check"].strip()
                and isinstance(entry.get("setup", ""), str) for entry in entries):
            raise DrawError(f'{path} must be a list of {{"repo": "owner/name", "check": "...", "setup": "..."}} '
                            "objects, with setup optional.")
        return {entry["repo"].lower(): entry for entry in entries}

    def labels(self, repos: dict[str, dict]) -> dict[str, str]:
        """Each listed repo's label, from the key file; a new repo gets the next free label."""
        path = self.state / "project-labels.json"
        key = read_json(path) if path.is_file() else {}
        labels = {repo.lower(): label for label, repo in key.items()}
        new = [repo for repo in repos if repo not in labels]
        for repo in new:
            label = next(label for label in map(label_name, range(1, len(key) + 2)) if label not in key)
            labels[repo], key[label] = label, repos[repo]["repo"]
        if new:
            scan.write_private(path, json.dumps(key, indent=2) + "\n")
        return labels

    def sets(self) -> dict[int, Path]:
        """The sets earlier calls wrote, by number."""
        return {int(found.group(1)): path for path in self.state.iterdir()
                if (found := re.fullmatch(r"replay-set-(\d+)\.json", path.name))}

    def used(self) -> set[tuple[str, int]]:
        """Every (label, ticket) an earlier set kept or set aside."""
        used = set()
        for path in self.sets().values():
            earlier = read_json(path)
            used |= {(entry["label"], entry["ticket"]) for entry in earlier["tickets"] + earlier["set_aside"]}
        return used

    def candidate(self, repo: dict, label: str, pr: int, opener: dict) -> dict | None:
        view = json.loads(self.gh(label, "pr", "view", str(pr), "--repo", repo["repo"], "--json",
                                  "state,additions,deletions,createdAt,mergeCommit,closingIssuesReferences,"
                                  "headRefName,isCrossRepository"))
        start, end = opener["while"]
        size = view["additions"] + view["deletions"]
        bucket = next((name for name, sizes in BUCKETS.items() if size in sizes), None)
        closes = view.get("closingIssuesReferences") or []
        if (view.get("state") != "MERGED" or bucket is None or len(closes) != 1
                or "/".join((closes[0]["repository"]["owner"]["login"], closes[0]["repository"]["name"])).lower()
                != repo["repo"].lower()
                or not start - CLOCK_SLACK <= moment(view["createdAt"]) <= end + CLOCK_SLACK):
            return None
        number = closes[0]["number"]
        issue = json.loads(self.gh(label, "issue", "view", str(number), "--repo", repo["repo"], "--json", "title,body"))
        if not has_criteria(issue.get("body")):
            return None
        return {"label": label, "ticket": number, "bucket": bucket, "size": size, "title": issue["title"],
                "body": issue["body"], "pr": pr, "session": opener["log"].stem, "model": opener["model"],
                "repo": repo, "merge": view["mergeCommit"]["oid"], "created": view["createdAt"],
                "branch": view["headRefName"], "fork": view["isCrossRepository"], "source": opener["log"]}

    def pool(self, repos: dict[str, dict], labels: dict[str, str]) -> dict[str, list[dict]]:
        openers: dict[tuple[str, int], list[dict]] = {}
        unreadable = 0
        for log in sorted((scan.config_dir() / "projects").glob("*/*.jsonl")):
            try:
                if not any(MAY_OPEN.search(path.read_text(errors="replace")) for path in [log, *scan.helper_logs(log)]):
                    continue
                main, helpers = own_lines(log)
                prs = opened_prs(main + helpers)
                opener = {"log": log, "prs": len(prs), "skills": scan.skills(main + helpers), "model": scan.model(main)}
            except (OSError, SystemExit, ValueError):  # a dangling link, a line that is not JSON, a bad timestamp
                unreadable += 1
                continue
            for pr, run in prs.items():
                openers.setdefault(pr, []).append({**opener, "while": run})
        tickets: dict[tuple[str, int], dict | None] = {}
        for (repo, pr), sessions in sorted(openers.items()):
            if repo not in repos or len(sessions) != 1 or sessions[0]["prs"] != 1 \
                    or not generation_one(sessions[0]["skills"]):
                continue
            try:
                scan.scan(sessions[0]["log"].stem, sessions[0]["log"])  # the draw saves the scan's row for a kept ticket
            except (OSError, SystemExit, ValueError):  # a truncated meta.json or a malformed timestamp
                unreadable += 1
                continue
            found = self.candidate(repos[repo], labels[repo], pr, sessions[0])
            if found:
                key = (repo, found["ticket"])
                tickets[key] = None if key in tickets else found  # a ticket with two PRs has no PR of its own
        if unreadable:
            print(f"Skipped {unreadable} session logs that could not be read.")
        used = self.used()
        buckets: dict[str, list[dict]] = {name: [] for name in BUCKETS}
        for _, found in sorted(tickets.items()):  # by repo and ticket, so the repo list's order changes nothing
            if found and (found["label"], found["ticket"]) not in used:
                buckets[found["bucket"]].append(found)
        return buckets

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], text=True, capture_output=True)

    def clone(self, candidate: dict) -> tuple[Path, str]:
        """The repo's clone, and the failed clone's output, or "" when it was cloned."""
        label, repo = candidate["label"], candidate["repo"]["repo"]
        if label not in self.clones:
            target = self.work / label
            result = subprocess.run(["gh", "repo", "clone", repo, str(target)], text=True, capture_output=True)
            failure = (f"$ gh repo clone {repo} {target}\n{result.stdout}{result.stderr}".rstrip("\n")
                       + f"\nclone exit {result.returncode}\n") if result.returncode else ""
            self.clones[label] = (target, failure)
        return self.clones[label]

    def ready_commit(self, candidate: dict) -> str | None:
        repo, label = candidate["repo"]["repo"], candidate["label"]
        events = pages(self.gh(label, "api", "--paginate", f"repos/{repo}/issues/{candidate['pr']}/timeline"))
        ready = min((moment(event["created_at"]) for event in events if event.get("event") == "ready_for_review"),
                    default=moment(candidate["created"]))
        ref = quote(f"refs/heads/{candidate['branch']}", safe="/")
        pushes = [push for push in pages(self.gh(label, "api", "--paginate",
                                                 f"repos/{repo}/activity?ref={ref}&per_page=100"))
                  if moment(push["timestamp"]) <= ready]  # the branch is pushed seconds before the PR opens
        head = max(pushes, key=lambda push: moment(push["timestamp"]), default={}).get("after", "")
        return head if head.strip("0") else None  # a deleted branch's push leads to 000…

    def run_check(self, candidate: dict, clone: Path, base: str, output: Path) -> str | None:
        """Run setup and check in a clean checkout of `base`; None when both pass, else the reason."""
        tree = self.work / f"{candidate['label']}-{candidate['ticket']}"
        groups: list[int] = []
        try:
            added = self.git("-C", str(clone), "worktree", "add", "--detach", "--quiet", str(tree), base)
            if added.returncode:
                output.write_text(f"$ git worktree add --detach {tree} {base}\n{added.stderr}".rstrip("\n")
                                  + f"\ncheckout exit {added.returncode}\n")
                return "the commit before the merged PR cannot be checked out"
            with open(output, "w") as out:
                for step in ("setup", "check"):
                    command = candidate["repo"].get(step)
                    if not command:
                        continue
                    out.write(f"$ {command}\n")
                    out.flush()
                    # Its own process group, so the processes it starts can be stopped with it.
                    process = subprocess.Popen(command, shell=True, cwd=tree, stdin=subprocess.DEVNULL, stdout=out,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    groups.append(process.pid)
                    try:
                        code = process.wait(timeout=CHECK_TIMEOUT)
                    except subprocess.TimeoutExpired:
                        stop(process.pid)
                        process.wait()
                        out.write(f"\n{step} ran for more than {CHECK_TIMEOUT} seconds\n")
                        return f"{step} ran for more than {CHECK_TIMEOUT} seconds"
                    out.write(f"\n{step} exit {code}\n")
                    if code:
                        return f"{step} exited {code}"
        finally:
            for group in groups:
                stop(group)
            self.git("-C", str(clone), "worktree", "remove", "--force", str(tree))
            self.git("-C", str(clone), "worktree", "prune")
        return None

    def try_ticket(self, candidate: dict) -> str | None:
        """Fill in the entry's commits and run its check; None when it is kept, else why it is set aside."""
        output = self.state / "checks" / f"{candidate['label']}-{candidate['ticket']}.txt"
        output.parent.mkdir(exist_ok=True)
        candidate["check_output"] = str(output.relative_to(self.state))
        clone, failure = self.clone(candidate)
        if failure:
            output.write_text(failure)
            return "the repo cannot be cloned"
        candidate["base_commit"] = self.git("-C", str(clone), "rev-parse", "--verify", "--quiet",
                                            candidate["merge"] + "^1").stdout.strip()
        if not candidate["base_commit"]:
            reason = "the commit before the merged PR is missing"
        elif candidate["fork"]:
            reason = "the PR came from a fork, whose pushes GitHub records in the fork"
        elif not (ready := self.ready_commit(candidate)):
            reason = NO_PUSH
        else:
            candidate["ready_commit"] = ready
            return self.run_check(candidate, clone, candidate["base_commit"], output)
        output.write_text(reason + "\n")
        return reason

    def save_log(self, candidate: dict) -> str:
        """Copy the session's log and its folder; check its transcripts arrived and scan the copy."""
        source = candidate["source"]
        copy = self.state / "logs" / source.name
        copy.parent.mkdir(exist_ok=True)
        try:
            shutil.copyfile(source, copy)
            if source.with_suffix("").is_dir():
                shutil.copytree(source.with_suffix(""), copy.with_suffix(""), dirs_exist_ok=True)
        except OSError:  # shutil.Error too: whatever it could not read, the check below covers what is needed
            pass
        transcripts = [source, *scan.helper_logs(source)]
        missing = sum(not (copy.parent / path.relative_to(source.parent)).is_file() for path in transcripts)
        if missing:
            raise DrawError(f"could not save the session log of project {candidate['label']} ticket "
                            f"{candidate['ticket']}: {missing} of its {len(transcripts)} transcripts did not copy.")
        scan.write_row(scan.scan(source.stem, copy))
        return str(copy.relative_to(self.state))

    def run(self) -> int:
        with open(self.state / "draw.lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DrawError("another draw is running in this machine directory.")
            print(f"Seed {self.seed}.")
            repos = self.repos()
            buckets = self.pool(repos, self.labels(repos))
            kept: list[dict] = []
            aside: list[dict] = []
            if all(len(found) >= PER_BUCKET for found in buckets.values()):
                shutil.rmtree(self.work, ignore_errors=True)
                self.work.mkdir()
                try:
                    for name, found in buckets.items():
                        order = list(found)
                        random.Random(f"{self.seed}:{name}").shuffle(order)
                        for candidate in order:
                            if sum(entry["bucket"] == name for entry in kept) == PER_BUCKET:
                                break
                            reason = self.try_ticket(candidate)
                            if reason:
                                aside.append({**candidate, "reason": reason})
                            else:
                                kept.append(candidate)
                finally:
                    shutil.rmtree(self.work, ignore_errors=True)
            for name, found in buckets.items():
                print(f"{name}: pool {len(found)}, set aside {sum(entry['bucket'] == name for entry in aside)}, "
                      f"kept {sum(entry['bucket'] == name for entry in kept)}.")
            if len(kept) < PER_BUCKET * len(BUCKETS):
                print(f"No set written: a bucket cannot reach {PER_BUCKET} tickets.")
                return EXIT_SHORT
            for candidate in kept:
                candidate["log"] = self.save_log(candidate)
            fields = ("label", "ticket", "bucket", "size", "title", "body", "base_commit", "ready_commit", "model",
                      "pr", "session", "log", "check_output")
            number = 1 + max(self.sets(), default=0)
            path = self.state / f"replay-set-{number}.json"
            scan.write_private(path, json.dumps({
                "set": number, "seed": self.seed, "drawn_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "tickets": [{field: entry[field] for field in fields} for entry in kept],
                "set_aside": [{field: entry[field] for field in ("label", "ticket", "bucket", "reason", "check_output")}
                              for entry in aside]}, indent=2) + "\n")
            print(f"Wrote {path}.")
            return 0


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(HELP)
        return 0
    if argv == []:
        seed = random.SystemRandom().randrange(2**32)
    elif len(argv) == 2 and argv[0] == "--seed" and argv[1].isdecimal():
        seed = int(argv[1])
    else:
        print(HELP, file=sys.stderr)
        return 2
    try:
        return Draw(seed).run()
    except DrawError as error:
        print(f"draw: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
