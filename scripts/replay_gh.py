#!/usr/bin/env python3
"""The stand-in `gh` of a `deliver` replay: GitHub played by files beside it and the clone's bare remote.

scripts/replay.py copies this file to <clone>/.git/replay-deliver/bin/gh, where the sandboxed session can read and
run it, and writes gh.json beside bin/: the repo's name, the bare remote's path and the ticket's number, title and
body. The stand-in appends each call to gh-calls.jsonl there as one JSON line, {"args", "cwd"}, with the text of a
--body-file argument under "body" when it can read the file, and keeps the PRs it has opened in prs.json. It answers:

- auth token; repo view --json F [--jq .a.b]; api repos/<repo>/rules/branches/<branch> (no rules);
- issue view <the ticket> --json F, with the ticket's title and body and no comments;
- pr list --head B --state S --json F; pr create --base D --head B --title T --body-file P [--draft];
- pr edit N --body-file P; pr ready N; pr view N|B --json F;
- pr checks N, as gh does when no check is reported; run list --commit C --json F (none);
- pr merge N --squash|--merge|--rebase --match-head-commit H: whichever method the call names, one commit holding the
  PR's change, made on the PR's base branch in the bare remote, whose tip it moves. The clone then fetches that branch,
  and its own branch of the same name moves to the new commit when it is still at the old tip and not checked out:
  deliver's cleanup switches the clone to that branch after a merge, and it pulls nothing.

--json names fields the stand-in has, and --jq is a path of plain keys such as .defaultBranchRef.name. Any other call,
a field it lacks, or another --jq exits 1 with one line that names the call.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent  # <clone>/.git/replay-deliver
METHODS = ("squash", "merge", "rebase")  # the flags of `pr merge`, each answered by a squash
BARE = ("draft", "delete-branch", *METHODS)  # flags that take no value


class NoAnswer(Exception):
    """Ends the call with exit 1 and the line that names it."""


class Fails(Exception):
    """An answer gh gives as a failure: its text on standard error, then exit 1."""


def git(origin: str, *args: str) -> str:
    done = subprocess.run(["git", "--git-dir", origin, *args], capture_output=True, text=True)
    if done.returncode:
        raise NoAnswer(f"git {args[0]} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout.strip()


def flags(args: list[str]) -> dict[str, str | bool]:
    """--name value pairs, and the flags BARE names as True, from `args`."""
    found: dict[str, str | bool] = {}
    at = 0
    while at < len(args):
        if args[at].startswith("--") and args[at][2:] in BARE:
            found[args[at][2:]] = True
        elif args[at].startswith("--") and at + 1 < len(args):
            found[args[at][2:]] = args[at + 1]
            at += 1
        at += 1
    return found


def fields(data: dict, given: dict) -> str:
    """`data` cut to the --json fields, then read with a --jq path of plain keys, as gh prints it."""
    if not isinstance(given.get("json"), str):
        raise NoAnswer("no --json fields")
    names = given["json"].split(",")
    if missing := [name for name in names if name not in data]:
        raise NoAnswer(f"no field {', '.join(missing)}")
    picked = {name: data[name] for name in names}
    jq = given.get("jq")
    if jq is None:
        return json.dumps(picked) + "\n"
    if not re.fullmatch(r"(\.[A-Za-z_][A-Za-z0-9_]*)+", str(jq)):
        raise NoAnswer(f"--jq {jq} is not a path of plain keys")
    value: object = picked
    for key in str(jq).split(".")[1:]:
        if not isinstance(value, dict) or key not in value:
            raise NoAnswer(f"--jq {jq}")
        value = value[key]
    return (value if isinstance(value, str) else json.dumps(value)) + "\n"


def answer(args: list[str], config: dict, prs: list[dict]) -> str:
    origin, repo = config["origin"], config["repo"]
    default = git(origin, "symbolic-ref", "--short", "HEAD")
    given = flags(args[2:])
    pair = " ".join(args[:2])
    if pair == "auth token":
        return "replay-stand-in-token\n"
    if pair == "repo view":
        return fields({"nameWithOwner": repo, "defaultBranchRef": {"name": default}, "viewerPermission": "ADMIN",
                       "hasIssuesEnabled": True}, given)
    if args[:1] == ["api"] and args[1:] == [f"repos/{repo}/rules/branches/{default}"]:
        return "[]\n"
    if pair == "issue view" and args[2:3] == [str(config["ticket"])]:
        return fields({"number": config["ticket"], "title": config["title"], "body": config["body"],
                       "comments": [], "state": "OPEN"}, flags(args[3:]))
    if pair == "pr list":
        found = [pr for pr in prs if pr["headRefName"] == given.get("head")
                 and pr["state"] == str(given.get("state", "open")).upper()]
        return json.dumps([json.loads(fields(view(origin, pr), given)) for pr in found]) + "\n"
    if pair == "pr create":
        head = str(given.get("head"))
        git(origin, "rev-parse", "--verify", f"refs/heads/{head}")  # GitHub opens no PR for a branch not pushed
        number = len(prs) + 1
        prs.append({"number": number, "url": f"https://github.invalid/{repo}/pull/{number}", "headRefName": head,
                    "baseRefName": str(given.get("base", default)), "title": str(given.get("title", head)),
                    "body": Path(str(given["body-file"])).read_text(), "state": "OPEN",
                    "isDraft": given.get("draft") is True})
        return prs[-1]["url"] + "\n"
    if args[:1] != ["pr"] and pair != "run list":
        raise NoAnswer("not a call the stand-in answers")
    if pair == "run list":
        return "[]\n"
    pr = find(prs, args[2:3])
    if args[1] == "view":
        return fields(view(origin, pr), flags(args[3:]))
    if args[1] == "edit" and "body-file" in given:
        pr["body"] = Path(str(given["body-file"])).read_text()
        return pr["url"] + "\n"
    if args[1] == "ready":
        pr["isDraft"] = False
        return ""
    if args[1] == "checks":
        raise Fails(f"no checks reported on the '{pr['headRefName']}' branch")
    if args[1] == "merge" and [method for method in METHODS if given.get(method) is True]:
        return merge(origin, pr, str(given.get("match-head-commit", "")))
    raise NoAnswer("not a call the stand-in answers")


def find(prs: list[dict], key: list[str]) -> dict:
    for pr in prs:
        if key and key[0] in (str(pr["number"]), pr["headRefName"]):
            return pr
    raise NoAnswer("no such PR")


def view(origin: str, pr: dict) -> dict:
    head = subprocess.run(["git", "--git-dir", origin, "rev-parse", "--verify", "-q", f"refs/heads/{pr['headRefName']}"],
                          capture_output=True, text=True).stdout.strip()
    return {**pr, "headRefOid": pr.get("headRefOid") or head, "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN" if pr["state"] == "OPEN" else "UNKNOWN", "reviewDecision": ""}


def merge(origin: str, pr: dict, match: str) -> str:
    """Squash the PR's branch onto its base branch in the bare remote, then bring the clone's branch of that name to
    the new commit where it is still at the old tip and not checked out."""
    if pr["state"] != "OPEN":
        raise NoAnswer("the PR is not open")
    head = git(origin, "rev-parse", f"refs/heads/{pr['headRefName']}")
    if match and match != head:
        raise NoAnswer(f"the head is {head}, not {match}")
    base = git(origin, "rev-parse", f"refs/heads/{pr['baseRefName']}")
    tree = git(origin, "merge-tree", "--write-tree", base, head).splitlines()[0]
    env = {**os.environ, "GIT_AUTHOR_NAME": "replay", "GIT_AUTHOR_EMAIL": "replay@localhost",
           "GIT_COMMITTER_NAME": "replay", "GIT_COMMITTER_EMAIL": "replay@localhost"}
    made = subprocess.run(["git", "--git-dir", origin, "commit-tree", "--no-gpg-sign", tree, "-p", base, "-m",
                           f"{pr['title']} (#{pr['number']})"], capture_output=True, text=True, env=env)
    if made.returncode:
        raise NoAnswer(f"git commit-tree exited {made.returncode}")
    target, new = f"refs/heads/{pr['baseRefName']}", made.stdout.strip()
    git(origin, "update-ref", target, new, base)
    pr.update(state="MERGED", headRefOid=head, mergeCommit={"oid": new})
    clone = str(HOME.parent)  # the clone's .git/
    git(clone, "fetch", "-q", origin, f"+{target}:refs/remotes/origin/{pr['baseRefName']}")
    checked_out = subprocess.run(["git", "--git-dir", clone, "symbolic-ref", "-q", "HEAD"], capture_output=True,
                                 text=True).stdout.strip()
    local = subprocess.run(["git", "--git-dir", clone, "rev-parse", "--verify", "-q", target], capture_output=True,
                           text=True).stdout.strip()
    if checked_out != target and local == base:
        git(clone, "update-ref", target, new, base)
    return ""


def main(args: list[str]) -> int:
    call: dict = {"args": args, "cwd": os.getcwd()}
    unread = None
    if "--body-file" in args[:-1]:
        try:
            call["body"] = Path(args[args.index("--body-file") + 1]).read_text()
        except (OSError, UnicodeDecodeError) as error:
            unread = error
    with open(HOME / "gh-calls.jsonl", "a") as calls:
        calls.write(json.dumps(call) + "\n")
    if unread is not None:
        print(f"stand-in gh: no answer for gh {' '.join(args)} (the --body-file cannot be read: {unread})",
              file=sys.stderr)
        return 1
    config = json.loads((HOME / "gh.json").read_text())
    store = HOME / "prs.json"
    prs = json.loads(store.read_text()) if store.is_file() else []
    try:
        sys.stdout.write(answer(args, config, prs))
    except (NoAnswer, IndexError, KeyError, OSError, ValueError) as error:
        print(f"stand-in gh: no answer for gh {' '.join(args)} ({error})", file=sys.stderr)
        return 1
    except Fails as failure:
        print(failure, file=sys.stderr)
        return 1
    finally:
        store.write_text(json.dumps(prs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
