"""The shared helper for the deliver.py tests: a throwaway world and a recording stand-in `gh`.

`World(add_cleanup)` builds, in one temporary folder:

- `home/`, the HOME of every command, with its own git config (no signing, no hooks, no
  machine settings) and `gh` config folder;
- `state/`, the machine directory, as `DELIVER_STATE_DIR`;
- `origin.git`, a bare repo standing in for the remote, whose `main` holds one commit;
- `work/`, a clone of it on `main`;
- `bin/gh`, a stand-in first on PATH. It appends each call as one JSON line to
  `gh-calls.jsonl` and answers from `gh-answers.json` with the first saved answer, in the order
  saved, whose arguments are the call's leading arguments (or all of them). So save the longer
  answer first: `["pr"]` saved before `["pr", "view"]` answers `gh pr view` too. With no answer
  it prints `stand-in gh: no answer for <args>` and exits 1.

`world.deliver(*args)` runs deliver.py as a session would, with only the world's environment, so
no test reads a real session's variables, touches the network or writes to the real machine
directory. A test that needs another stand-in puts it in `world.bin`.

Pass `self.addCleanup` from a test or `cls.addClassCleanup` from `setUpClass` to share one world
across a class. Later tickets add helpers here rather than in their own test files.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "deliver" / "scripts"
DELIVER = SCRIPTS / "deliver.py"

GH = """\
import json, os, sys
from pathlib import Path
world = Path(os.environ["DELIVER_KIT_WORLD"])
args = sys.argv[1:]
with (world / "gh-calls.jsonl").open("a") as calls:
    calls.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\\n")
answers = json.loads((world / "gh-answers.json").read_text())
for answer in answers:
    if args[:len(answer["args"])] == answer["args"]:
        sys.stdout.write(answer["stdout"])
        sys.stderr.write(answer["stderr"])
        sys.exit(answer["exit"])
sys.stderr.write("stand-in gh: no answer for " + " ".join(args) + "\\n")
sys.exit(1)
"""


def load(name: str):
    """Import a deliver script module in this process, under the name `deliver_<name>`.

    The scripts import each other by plain name; this puts their folder first on the path for
    the import only, so a same-named module of another skill is not picked up in its place.
    """
    key = f"deliver_{name}"
    if key not in sys.modules:
        sys.path.insert(0, str(SCRIPTS))
        try:
            spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[key] = module
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(SCRIPTS))
    return sys.modules[key]


class World:
    def __init__(self, add_cleanup: Callable):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="deliver-kit-")))
        add_cleanup(shutil.rmtree, str(self.root), True)
        self.home = self.root / "home"
        self.state = self.root / "state"
        self.bin = self.root / "bin"
        for folder in (self.home, self.bin):
            folder.mkdir()
        gitconfig = self.home / ".gitconfig"
        gitconfig.write_text(
            "[user]\n\tname = Deliver Test\n\temail = deliver-test@example.invalid\n"
            "[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n",
            encoding="utf-8",
        )
        self.base_env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": str(gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GH_CONFIG_DIR": str(self.home / ".config" / "gh"),
            "LC_ALL": "C",
            "LANG": "C",
            "DELIVER_STATE_DIR": str(self.state),
            "DELIVER_KIT_WORLD": str(self.root),
        }
        gh = self.bin / "gh"
        gh.write_text(f"#!{sys.executable} -I\n{GH}", encoding="utf-8")
        gh.chmod(0o755)
        (self.root / "gh-answers.json").write_text("[]", encoding="utf-8")
        self.origin = self.root / "origin.git"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.work = self.root / "work"
        self.git(self.root, "clone", "-q", str(self.origin), str(self.work))
        self.commit(self.work, "README.md", "seed\n", "chore: seed")
        self.git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")

    def env(self, **changes: str | None) -> dict[str, str]:
        """The world's environment; a change of None removes that variable."""
        env = dict(self.base_env)
        for key, value in changes.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def git(self, cwd: Path, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=cwd, env=self.base_env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr}")
        return proc.stdout.strip()

    def commit(self, repo: Path, name: str, content: str, message: str) -> str:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", message)
        return self.git(repo, "rev-parse", "HEAD")

    def worktree(self, name: str, branch: str) -> Path:
        path = self.root / name
        self.git(self.work, "worktree", "add", "-q", "-b", branch, str(path))
        return path

    def deliver(self, *args: str, cwd: Path | None = None, **env: str | None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(DELIVER), *args], cwd=cwd or self.work, env=self.env(**env),
            capture_output=True, text=True,
        )

    def write_mark(self, checkout: Path | None = None, run: str = "run-1", branch: str = "main",
                   role: str = "session", started: str = "2026-11-27T18:00:00Z") -> Path:
        """Write a run mark in the layout spec #407 fixes, without the program."""
        git_dir = Path(self.git(checkout or self.work, "rev-parse", "--path-format=absolute", "--git-dir"))
        mark = git_dir / "deliver-mark.json"
        mark.write_text(json.dumps({"run": run, "branch": branch, "role": role, "started": started}) + "\n",
                        encoding="utf-8")
        return mark

    def records(self, branch: str = "main") -> list[dict]:
        common = Path(self.git(self.work, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        return read_lines(common / "deliver" / "branches" / branch / "records.jsonl")

    def state_lines(self, name: str) -> list[dict]:
        return read_lines(self.state / name)

    def gh_answer(self, args: list[str], stdout: str = "", stderr: str = "", exit: int = 0) -> None:
        path = self.root / "gh-answers.json"
        answers = json.loads(path.read_text(encoding="utf-8"))
        answers.append({"args": args, "stdout": stdout, "stderr": stderr, "exit": exit})
        path.write_text(json.dumps(answers), encoding="utf-8")

    def gh_calls(self) -> list[dict]:
        return read_lines(self.root / "gh-calls.jsonl")


def read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
