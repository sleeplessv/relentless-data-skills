#!/usr/bin/env python3
"""PROTOTYPE, throwaway. Never merged.

Answers one question from the wayfinder ticket "Running the cross-harness test
from Claude Code through Herdr" (#188): how a Claude Code session starts each
harness, hands it a task, knows the run finished, and reads the result and the
run's measurements.

    python3 xh.py run <harness> [--connection NAME]   one probe run, one row
    python3 xh.py all [--connection NAME]             every harness, one table

Each run: a fresh fixture folder (own git init, no remote), the harness started
headless in a Herdr terminal (`hc run --bg`), `hc wait` until the process
exits, then the row is read from the saved output. Raw output stays in the
fixture folder so a wrong parser can be fixed without a rerun.
"""
import argparse
import glob
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time

CODEWORD = "heron-41"
SKILLWORD = "marlin-77"
# A stand-in for `deliver`: typed by the owner, closed to model invocation.
SKILL = f"""---
name: xh-probe
description: Cross-harness test probe. Only the owner starts it.
disable-model-invocation: true
---

Reply with only the word {SKILLWORD}, a space, and the argument you were given. Do nothing else.
"""
SKILL_DIRS = [".claude/skills", ".agents/skills", ".cursor/skills", ".cortex/skills"]
TASK = (
    "Append the line xh-ok to notes.txt. "
    "Then reply with only the codeword given in AGENTS.md."
)

# argv per harness. {task} is replaced. Light-class models keep the probe cheap.
HARNESSES = {
    "claude": {
        "argv": ["claude", "-p", "{task}", "--model", "haiku", "--output-format", "json",
                 "--permission-mode", "acceptEdits"],
        "format": "json",
    },
    "codex": {
        "argv": ["codex", "exec", "--json", "-m", "gpt-6-luna", "--sandbox", "workspace-write",
                 "--skip-git-repo-check", "{task}"],
        "format": "jsonl",
    },
    "cursor": {
        "argv": ["cursor-agent", "-p", "--output-format", "stream-json", "--force",
                 "--model", "claude-haiku-5-5-high", "{task}"],
        "format": "jsonl",
    },
    "antigravity": {
        "argv": ["agy", "-p", "{task}", "--model", "gemini-4-neon-low", "--output-format", "stream-json",
                 "--mode", "accept-edits"],
        "format": "jsonl",
    },
    # Every Snowflake connection on this machine belongs to a client, so a
    # Cortex Code run needs the connection named by the owner: --connection.
    "cortex": {
        "argv": ["cortex", "-p", "{task}", "--output-format", "stream-json", "--private",
                 "--max-turns", "8", "-m", "claude-haiku-4-5", "--bypass"],
        "format": "jsonl",
    },
}


def sh(*argv, check=True):
    return subprocess.run(argv, capture_output=True, text=True, check=check).stdout


def make_fixture(harness):
    root = os.path.realpath(tempfile.mkdtemp(prefix=f"xh-{harness}-"))
    with open(os.path.join(root, "AGENTS.md"), "w") as f:
        f.write(f"# Fixture\n\nThe codeword is {CODEWORD}.\n")
    with open(os.path.join(root, "CLAUDE.md"), "w") as f:
        f.write("@AGENTS.md\n")
    with open(os.path.join(root, "notes.txt"), "w") as f:
        f.write("first line\n")
    for d in SKILL_DIRS:
        os.makedirs(os.path.join(root, d, "xh-probe"))
        with open(os.path.join(root, d, "xh-probe", "SKILL.md"), "w") as f:
            f.write(SKILL)
    sh("git", "-C", root, "init", "-q")
    sh("git", "-C", root, "add", "-A")
    sh("git", "-C", root, "-c", "user.name=xh", "-c", "user.email=xh@example.invalid",
       "commit", "-qm", "fixture")
    return root


def launch(harness, fixture, connection, prompt):
    spec = HARNESSES[harness]
    argv = [a.replace("{task}", prompt) for a in spec["argv"]]
    if harness == "cortex":
        argv += ["-c", connection]
    line = "set -o pipefail; " + shlex.join(argv) + " 2> .xh-err.txt | tee .xh-out.txt"
    me = os.environ.get("HC_TERMINAL_ID", "x")
    # Names are unique machine-wide, so two runs of one harness need the pid.
    name = f"xh-{harness[:6]}-{os.getpid()}-{me}"[:32]
    out = sh("hc", "run", "--bg", "--json", "--no-notify", "--name", name, "--cwd", fixture,
             "bash", "-c", line)
    return json.loads(out)["address"], argv


def wait(term, limit=900):
    """Finished means the process exited: `state: finished` from `hc get`.

    `hc wait` alone is not enough. For a program hc knows as an agent it also
    returns when the agent's status changes, with the process still alive.
    """
    start, reasons = time.time(), []
    while time.time() - start < limit:
        got = json.loads(sh("hc", "wait", term, "--timeout", "170", "--json", check=False) or "{}")
        reasons.append(got.get("reason"))
        info = json.loads(sh("hc", "get", term, "--json", check=False) or "{}")
        if info.get("state") == "finished":
            return {"reason": "exit", "wait_returns": reasons}
        time.sleep(2)
    return {"reason": "driver timeout", "wait_returns": reasons}


def records(path, fmt):
    text = open(path).read() if os.path.exists(path) else ""
    if fmt == "json":
        try:
            whole = json.loads(text)
            return whole if isinstance(whole, list) else [whole]
        except ValueError:
            pass
    rows = []
    for raw in text.splitlines():
        raw = raw.strip()
        if raw.startswith("{"):
            try:
                rows.append(json.loads(raw))
            except ValueError:
                pass
    return rows


def find(obj, *keys):
    """First value under any of keys, searched depth-first."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, "", {}, []):
                return obj[k]
        for v in obj.values():
            hit = find(v, *keys)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = find(v, *keys)
            if hit is not None:
                return hit
    return None


def parse(harness, recs):
    last = recs[-1] if recs else {}
    row = {"result": None, "session": None, "model": None, "usage": None, "refused": None}
    if harness == "claude":
        row["result"] = last.get("result")
        row["session"] = last.get("session_id")
        row["model"] = ", ".join((last.get("modelUsage") or {}).keys()) or None
        row["usage"] = last.get("usage")
        row["refused"] = last.get("permission_denials")
    elif harness == "codex":
        for r in recs:
            item = r.get("item") or {}
            if r.get("type") == "item.completed" and item.get("type") == "agent_message":
                row["result"] = item.get("text")
            if r.get("type") == "thread.started":
                row["session"] = r.get("thread_id")
            if r.get("type") == "turn.completed":
                row["usage"] = r.get("usage")
        # The exec output names no model; the session log does, found by thread id.
        logs = glob.glob(os.path.expanduser(f"~/.codex/sessions/*/*/*/*{row['session']}*.jsonl"))
        for raw in open(logs[0]) if logs else []:
            r = json.loads(raw)
            if r.get("type") == "turn_context":
                p = r.get("payload") or {}
                row["model"] = f"{p.get('model')} / {p.get('effort')}"
    elif harness == "cursor":
        row["result"] = last.get("result")
        row["session"] = last.get("session_id")
        row["usage"] = last.get("usage")
        row["model"] = find(recs, "model")
    elif harness == "antigravity":
        res = next((r["result"] for r in reversed(recs) if r.get("event") == "result"), last)
        row["result"] = res.get("response")
        row["session"] = res.get("conversation_id")
        row["usage"] = res.get("usage")
        row["refused"] = res.get("denied_actions")
        row["model"] = find(recs, "model")
    elif harness == "cortex":
        row["result"] = find(last, "result", "text")
        row["session"] = find(recs, "session_id", "sessionId")
        row["usage"] = find(last, "usage")
        row["model"] = find(recs, "model")
    return row


def run(harness, connection=None, prompt=TASK):
    if harness == "cortex" and not connection:
        return {"harness": harness, "skipped": "needs --connection: every connection is a client's"}
    fixture = make_fixture(harness)
    term, argv = launch(harness, fixture, connection, prompt)
    ended = wait(term)
    info = json.loads(sh("hc", "get", term, "--json", check=False) or "{}")
    sh("hc", "kill", term, check=False)
    sh("hc", "rm", term, check=False)
    recs = records(os.path.join(fixture, ".xh-out.txt"), HARNESSES[harness]["format"])
    row = parse(harness, recs)
    notes = open(os.path.join(fixture, "notes.txt")).read()
    row.update({
        "harness": harness,
        "fixture": fixture,
        "finished_by": ended.get("reason"),
        "exit_code": info.get("exit_code"),
        "wait_returns": ended.get("wait_returns"),
        "seconds": round(((info.get("finished_ms") or 0) - (info.get("created_ms") or 0)) / 1000, 1),
        "edit_made": "xh-ok" in notes,
        "codeword_returned": CODEWORD in (row["result"] or ""),
        "skill_word_returned": SKILLWORD in (row["result"] or ""),
        "record_keys": sorted({k for r in recs for k in r})[:40],
    })
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "all"])
    ap.add_argument("harness", nargs="?")
    ap.add_argument("--connection")
    ap.add_argument("--prompt", default=TASK, help='e.g. "/xh-probe T1" to start the stand-in skill')
    a = ap.parse_args()
    names = list(HARNESSES) if a.mode == "all" else [a.harness]
    for n in names:
        print(json.dumps(run(n, a.connection, a.prompt), indent=2, default=str))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
