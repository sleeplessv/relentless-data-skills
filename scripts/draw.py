#!/usr/bin/env python3
"""Draw the replay set: 30 tickets generation one finished, 10 per size bucket.

Usage: python3 scripts/draw.py [--seed N]

The pool is every ticket that meets all of these:
- One session under $CLAUDE_CONFIG_DIR/projects (default ~/.claude) opened the
  ticket's PR with `gh pr create`, itself or through a helper, and opened no
  other PR.
- That session loaded a generation-one skill: orchestrator-mode,
  implement-ticket, implement-feature or implement-backlog.
- The PR is merged and closes one issue, the ticket. No other PR in the pool
  closes it.
- The ticket's body holds an item of a list under "## Acceptance criteria",
  "## Acceptance" or "## Done when".
- The PR's repo is in repos.json, and the ticket is in no earlier set, kept or
  set aside.

A ticket's size is its PR's additions plus deletions. The buckets are 0-50,
51-300 and 301-1500 changed lines. A larger PR is in no bucket. Each bucket's
pool is sorted by label and ticket number, then shuffled by random.Random seeded
with "<seed>:<bucket>". The draw tries the tickets in that order until 10 pass.
A try runs the repo's setup command, where it has one, and then its check
command, each with sh, in a clean checkout of the commit before the merged PR:
the first parent of the PR's merge commit. A ticket is set aside when that
commit is missing, when its PR had no commit when first marked ready, or when
its setup or check exits non-zero or runs for more than an hour.

The commit first marked ready is the PR's last commit committed at or before its
first ready_for_review event, or at or before its creation when it has none.

Every file is in the machine directory, $DELIVER_STATE_DIR (default
~/.local/state/deliver):

  repos.json            The owner's repo list, written by hand. A JSON list of
                        {"repo": "owner/name", "check": "<command>",
                        "setup": "<command>"} objects. "setup" is optional.
  project-labels.json   The key from label to repo: {"A": "owner/name", ...}.
                        A repo keeps its label. A new repo takes the next
                        letter, in repos.json order.
  replay-set-<n>.json   Set n, as {"set", "seed", "drawn_at", "tickets",
                        "set_aside"}. A ticket entry holds label, ticket,
                        bucket, size, title, body, base_commit, ready_commit,
                        model, pr, session, log and check_output. A set-aside
                        entry holds label, ticket, bucket, reason and
                        check_output. Paths are relative to the machine
                        directory.
  checks/<label>-<ticket>.txt
                        The output of each try's setup and check.
  logs/<session>.jsonl and logs/<session>/
                        A copy of each kept ticket's session log, helpers'
                        transcripts included, scanned into scan-rows.jsonl.
  draw-work/            Clones and checkouts, removed when the draw ends.

Output names projects by label only.

Exit 0: a set was written. Exit 1: an error; no set was written. Exit 2: bad
usage. Exit 3: a bucket holds fewer than 10 tickets, or cannot reach 10 once
tickets are set aside; no set was written, and the count per bucket is printed.
"""
from __future__ import annotations

import fcntl
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan  # noqa: E402  (a sibling script, not an installed package)

GENERATION_ONE = frozenset({"orchestrator-mode", "implement-ticket", "implement-feature", "implement-backlog"})
BUCKETS = {"0-50": range(0, 51), "51-300": range(51, 301), "301-1500": range(301, 1501)}
PER_BUCKET = 10
CRITERIA_HEADINGS = ("acceptance criteria", "acceptance", "done when")
OPENS_PR = "gh pr create"
PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
CHECK_TIMEOUT = 3600  # seconds
EXIT_SHORT = 3


class DrawError(Exception):
    """Ends the draw with exit 1 and no set written."""


def generation_one(skills: list[str] | None) -> bool:
    # A plugin's skill may carry the plugin's name as a prefix, as in plugin:implement-ticket.
    return any(name.split(":")[-1] in GENERATION_ONE for name in skills or [])


def parts(line: dict) -> list[dict]:
    content = (line.get("message") or {}).get("content")
    return [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []


def result_text(part: dict) -> str:
    content = part.get("content")
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content or "")


def opened_prs(log: Path) -> set[tuple[str, int]]:
    """The PRs a session or its helpers opened with `gh pr create`, as (owner/name in lower case, number)."""
    files = [log, *scan.helper_logs(log)]
    if not any(OPENS_PR in path.read_text(errors="replace") for path in files):
        return set()
    # A resumed session's log can start with copies of another session's lines. Those are that session's.
    lines = [line for line in scan.read_lines(log) if line.get("sessionId") in (None, log.stem)]
    for path in files[1:]:
        lines += scan.read_lines(path)
    calls = {part.get("id") for line in lines if line.get("type") == "assistant" for part in parts(line)
             if part.get("type") == "tool_use" and part.get("name") == "Bash"
             and OPENS_PR in str((part.get("input") or {}).get("command"))}
    return {(repo.lower(), int(number)) for line in lines if line.get("type") == "user" for part in parts(line)
            if part.get("type") == "tool_result" and part.get("tool_use_id") in calls and not part.get("is_error")
            for repo, number in PR_URL.findall(result_text(part))}


def has_criteria(body: str | None) -> bool:
    """True when the body holds an item of a list under one of the CRITERIA_HEADINGS."""
    under = fenced = False
    for text in (body or "").splitlines():
        if text.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif fenced:
            continue
        elif heading := re.fullmatch(r"(#{1,6})\s+(.*?)[\s#]*", text):
            if len(heading.group(1)) <= 2:
                under = heading.group(1) == "##" and heading.group(2).lower() in CRITERIA_HEADINGS
        elif under and re.match(r"\s*(?:[-*+]|\d+[.)])\s+\S", text):
            return True
    return False


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read, whole or not at all."""
    partial = path.with_name(path.name + ".partial")
    with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
        file.write(text)
    partial.replace(path)


class Draw:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.state = scan.state_dir()
        self.work = self.state / "draw-work"
        self.clones: dict[str, Path] = {}

    def gh(self, label: str, *args: str) -> str:
        result = subprocess.run(["gh", *args], text=True, capture_output=True)
        if result.returncode:
            # gh's own message can name the repo, so it goes to a file, not to the output.
            write_private(self.state / "draw-error.txt", result.stderr)
            raise DrawError(f"`gh {args[0]} {args[1]}` failed for project {label} with exit {result.returncode}. "
                            f"Its message is in {self.state / 'draw-error.txt'}.")
        return result.stdout

    def repos(self) -> dict[str, dict]:
        path = self.state / "repos.json"
        try:
            entries = json.loads(path.read_text())
        except FileNotFoundError:
            raise DrawError(f"{path} does not exist. Write the repo list there first; --help gives its format.")
        except ValueError:
            raise DrawError(f"{path} is not JSON.")
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
        key = json.loads(path.read_text()) if path.is_file() else {}
        labels = {repo.lower(): label for label, repo in key.items()}
        for repo, entry in repos.items():
            if repo not in labels:
                number, label = len(key) + 1, ""
                while number:
                    number, rest = divmod(number - 1, 26)
                    label = chr(ord("A") + rest) + label
                labels[repo], key[label] = label, entry["repo"]
                write_private(path, json.dumps(key, indent=2) + "\n")
        return labels

    def used(self) -> set[tuple[str, int]]:
        """Every (label, ticket) an earlier set kept or set aside."""
        used = set()
        for path in self.state.glob("replay-set-*.json"):
            earlier = json.loads(path.read_text())
            used |= {(entry["label"], entry["ticket"]) for entry in earlier["tickets"] + earlier["set_aside"]}
        return used

    def candidate(self, repo: dict, label: str, pr: int, log: Path, row: dict) -> dict | None:
        view = json.loads(self.gh(label, "pr", "view", str(pr), "--repo", repo["repo"], "--json",
                                  "state,additions,deletions,createdAt,mergeCommit,commits,closingIssuesReferences"))
        size = view["additions"] + view["deletions"]
        bucket = next((name for name, sizes in BUCKETS.items() if size in sizes), None)
        closes = view.get("closingIssuesReferences") or []
        if view.get("state") != "MERGED" or bucket is None or len(closes) != 1 or "/".join(
                (closes[0]["repository"]["owner"]["login"], closes[0]["repository"]["name"])).lower() != repo["repo"].lower():
            return None
        number = closes[0]["number"]
        issue = json.loads(self.gh(label, "issue", "view", str(number), "--repo", repo["repo"], "--json", "title,body"))
        if not has_criteria(issue.get("body")):
            return None
        return {"label": label, "ticket": number, "bucket": bucket, "size": size, "title": issue["title"],
                "body": issue["body"], "pr": pr, "session": log.stem, "model": row["model"], "repo": repo,
                "merge": view["mergeCommit"]["oid"], "created": view["createdAt"], "commits": view["commits"],
                "source": log}

    def pool(self, repos: dict[str, dict], labels: dict[str, str]) -> dict[str, list[dict]]:
        openers: dict[tuple[str, int], list[tuple[Path, int]]] = {}
        unreadable = 0
        for log in sorted((scan.config_dir() / "projects").glob("*/*.jsonl")):
            try:
                prs = opened_prs(log)
            except SystemExit:  # scan.read_lines stops at a line that is not JSON
                unreadable += 1
                continue
            for pr in prs:
                openers.setdefault(pr, []).append((log, len(prs)))
        if unreadable:
            print(f"Skipped {unreadable} session logs that hold a line that is not JSON.")
        tickets: dict[tuple[str, int], dict | None] = {}
        for (repo, pr), sessions in sorted(openers.items()):
            if repo not in repos or len(sessions) != 1 or sessions[0][1] != 1:
                continue
            log = sessions[0][0]
            row = scan.scan(log.stem, log)
            if not generation_one(row["skills"]):
                continue
            found = self.candidate(repos[repo], labels[repo], pr, log, row)
            if found:
                key = (found["label"], found["ticket"])
                tickets[key] = None if key in tickets else found  # a ticket with two PRs has no PR of its own
        used = self.used()
        buckets: dict[str, list[dict]] = {name: [] for name in BUCKETS}
        for key, found in sorted(tickets.items()):
            if found and key not in used:
                buckets[found["bucket"]].append(found)
        return buckets

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], text=True, capture_output=True)

    def clone(self, candidate: dict) -> Path:
        label = candidate["label"]
        if label not in self.clones:
            self.gh(label, "repo", "clone", candidate["repo"]["repo"], str(self.work / label))
            self.clones[label] = self.work / label
        return self.clones[label]

    def ready_commit(self, candidate: dict) -> str | None:
        timeline = self.gh(candidate["label"], "api", "--paginate",
                           f"repos/{candidate['repo']['repo']}/issues/{candidate['pr']}/timeline").strip()
        decoder, events, at = json.JSONDecoder(), [], 0
        while at < len(timeline):  # --paginate prints one JSON list per page
            page, at = decoder.raw_decode(timeline, at)
            events += page
            at = len(timeline) - len(timeline[at:].lstrip())
        moments = [datetime.fromisoformat(event["created_at"]) for event in events
                   if event.get("event") == "ready_for_review"]
        moment = min(moments, default=datetime.fromisoformat(candidate["created"]))
        heads = [commit["oid"] for commit in candidate["commits"]
                 if datetime.fromisoformat(commit["committedDate"]) <= moment]
        return heads[-1] if heads else None

    def run_check(self, candidate: dict, clone: Path, base: str, output: Path) -> str | None:
        """Run setup and check in a clean checkout of `base`; None when both pass, else the reason."""
        tree = self.work / f"{candidate['label']}-{candidate['ticket']}"
        if self.git("-C", str(clone), "worktree", "add", "--detach", "--quiet", str(tree), base).returncode:
            return "the commit before the merged PR cannot be checked out"
        try:
            with open(output, "w") as out:
                for step in ("setup", "check"):
                    command = candidate["repo"].get(step)
                    if not command:
                        continue
                    out.write(f"$ {command}\n")
                    out.flush()
                    try:
                        code = subprocess.run(command, shell=True, cwd=tree, stdin=subprocess.DEVNULL, stdout=out,
                                              stderr=subprocess.STDOUT, timeout=CHECK_TIMEOUT).returncode
                    except subprocess.TimeoutExpired:
                        out.write(f"\n{step} ran for more than {CHECK_TIMEOUT} seconds\n")
                        return f"{step} ran for more than {CHECK_TIMEOUT} seconds"
                    out.write(f"\n{step} exit {code}\n")
                    if code:
                        return f"{step} exited {code}"
        finally:
            self.git("-C", str(clone), "worktree", "remove", "--force", str(tree))
        return None

    def try_ticket(self, candidate: dict) -> str | None:
        """Fill in the entry's commits and run its check; None when it is kept, else why it is set aside."""
        output = self.state / "checks" / f"{candidate['label']}-{candidate['ticket']}.txt"
        output.parent.mkdir(exist_ok=True)
        candidate["check_output"] = str(output.relative_to(self.state))
        clone = self.clone(candidate)
        base = self.git("-C", str(clone), "rev-parse", "--verify", "--quiet", candidate["merge"] + "^1").stdout.strip()
        candidate["base_commit"] = base
        candidate["ready_commit"] = self.ready_commit(candidate)
        if not base:
            reason = "the commit before the merged PR is missing"
        elif not candidate["ready_commit"]:
            reason = "the PR had no commit when it was first marked ready"
        else:
            return self.run_check(candidate, clone, base, output)
        output.write_text(reason + "\n")
        return reason

    def save_log(self, candidate: dict) -> str:
        source = candidate["source"]
        copy = self.state / "logs" / source.name
        copy.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, copy)
        if source.with_suffix("").is_dir():
            shutil.copytree(source.with_suffix(""), copy.with_suffix(""), dirs_exist_ok=True)
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
                        order = sorted(found, key=lambda entry: (entry["label"], entry["ticket"]))
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
            number = 1 + max((int(path.stem.rsplit("-", 1)[1]) for path in self.state.glob("replay-set-*.json")),
                             default=0)
            path = self.state / f"replay-set-{number}.json"
            write_private(path, json.dumps({
                "set": number, "seed": self.seed, "drawn_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "tickets": [{field: entry[field] for field in fields} for entry in kept],
                "set_aside": [{field: entry[field] for field in ("label", "ticket", "bucket", "reason", "check_output")}
                              for entry in aside]}, indent=2) + "\n")
            print(f"Wrote {path}.")
            return 0


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv == []:
        seed = random.SystemRandom().randrange(2**32)
    elif len(argv) == 2 and argv[0] == "--seed" and argv[1].isdecimal():
        seed = int(argv[1])
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        return Draw(seed).run()
    except DrawError as error:
        print(f"draw: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
