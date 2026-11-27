"""The shared helper for the deliver.py tests: a throwaway world and a recording stand-in `gh`.

`World(add_cleanup)` builds, in one temporary folder:

- `home/`, the HOME of every command, with its own git config (no signing, no hooks, no
  machine settings) and `gh` config folder;
- `state/`, the machine directory, as `DELIVER_STATE_DIR`;
- `origin.git`, a bare repo standing in for the remote, whose `main` holds one commit;
- `work/`, a clone of it on `main`;
- `bin/gh`, a stand-in first on PATH. It appends each call as one JSON line to
  `gh-calls.jsonl`, with the text of a `--body-file` argument under `body`, and answers from `gh-answers.json` with the first saved answer, in the order
  saved, whose arguments are the call's leading arguments (or all of them). So save the longer
  answer first: `["pr"]` saved before `["pr", "view"]` answers `gh pr view` too. With no answer
  it prints `stand-in gh: no answer for <args>` and exits 1.

`world.deliver(*args)` runs deliver.py as a session would, with only the world's environment, so
no test reads a real session's variables, touches the network or writes to the real machine
directory. A test that needs another stand-in puts it in `world.bin`.

`world.guard(command)` runs the guard hook as Claude Code does, on a hook input recorded from
Claude Code (`deliver_guard_inputs/`) with its `cwd` set to the clone and its command replaced.
`world.probe()` runs the guard probe that way, so a marked run's preflight finds its refusal.

Claude Code as preflight reads it passes: `CLAUDE_CODE_EFFORT_LEVEL` is set, and `world.trust(folder)`
marks a folder trusted in `home/.claude.json`, which the world does for the clone and each worktree.
`tests/test_deliver_checks_claude.py` builds the other Claude Code files under `home/`.

`world.install_upstream()` installs a stand-in of each upstream skill in the home's Claude Code
skills folder, and from then on `world.deliver` runs a copy of the plugin whose upstream contract
holds the stand-ins' folder hashes, so preflight finds every skill unchanged.

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
GUARD = SCRIPTS / "guard.py"
GUARD_INPUTS = REPO_ROOT / "tests" / "deliver_guard_inputs"
UPSTREAM = ("code-review", "ponytail-review", "pr", "to-spec", "to-tickets", "triage")

GH = """\
import json, os, sys
from pathlib import Path
world = Path(os.environ["DELIVER_KIT_WORLD"])
args = sys.argv[1:]
call = {"args": args, "cwd": os.getcwd()}
if "--body-file" in args[:-1]:
    call["body"] = Path(args[args.index("--body-file") + 1]).read_text()
with (world / "gh-calls.jsonl").open("a") as calls:
    calls.write(json.dumps(call) + "\\n")
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
            "CLAUDE_CODE_EFFORT_LEVEL": "high",
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
        self.trust(self.work)
        self.script = DELIVER

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
        self.trust(path)
        return path

    def trust(self, folder: Path, trusted: bool = True) -> None:
        """Record in Claude Code's trust record, home/.claude.json, whether the folder is trusted."""
        path = self.home / ".claude.json"
        record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"projects": {}}
        record["projects"][str(folder)] = {"hasTrustDialogAccepted": trusted}
        path.write_text(json.dumps(record), encoding="utf-8")

    def deliver(self, *args: str, cwd: Path | None = None, **env: str | None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.script), *args], cwd=cwd or self.work, env=self.env(**env),
            capture_output=True, text=True,
        )

    def guard(self, command: str, recorded: str = "session.json", cwd: Path | None = None,
              shell_cwd: Path | None = None, **env: str | None) -> subprocess.CompletedProcess:
        """Run the guard on a recorded hook input, from `shell_cwd` (default: outside every repo)."""
        data = json.loads((GUARD_INPUTS / recorded).read_text(encoding="utf-8"))
        data["cwd"] = str(cwd or self.work)
        data["tool_input"]["command"] = command
        return subprocess.run(
            [sys.executable, str(GUARD)], input=json.dumps(data), cwd=shell_cwd or self.root,
            env=self.env(**env), capture_output=True, text=True,
        )

    def probe(self, recorded: str = "session.json", cwd: Path | None = None) -> subprocess.CompletedProcess:
        return self.guard(load("guard").PROBE, recorded, cwd)

    def install_skill(self, name: str, root: Path | None = None) -> Path:
        """A stand-in skill folder `<root>/skills/<name>` (default root: the home's `.claude`)."""
        folder = (root or self.home / ".claude") / "skills" / name
        (folder / "references").mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
        (folder / "references" / "notes.md").write_text(f"{name} notes\n", encoding="utf-8")
        return folder

    def install_upstream(self, names: tuple[str, ...] = UPSTREAM) -> dict[str, Path]:
        """Install stand-ins of `names` and run deliver.py from a plugin copy whose contract fits them."""
        folders = {name: self.install_skill(name) for name in names}
        plugin = self.root / "plugin"
        shutil.copytree(SCRIPTS.parent, plugin, ignore=shutil.ignore_patterns("__pycache__"))
        deps = load("deps")
        contract = deps.load_contract()
        for name, folder in folders.items():
            contract[name]["folder_hash"] = deps.folder_hash(folder)
        (plugin / "upstream.toml").write_text("".join(
            f"[{name}]\n" + "".join(f"{key} = {json.dumps(value)}\n" for key, value in entry.items())
            for name, entry in contract.items()
        ), encoding="utf-8")
        self.script = plugin / "scripts" / "deliver.py"
        return folders

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


# GitHub as preflight's checks read it (#420). `github_ok` saves the answers of a repo the signed-in
# account can push to, with issues on and no branch rule; save a test's own answer to one of these
# calls before it, since the first saved prefix answers. `reset_gh` forgets every answer and call,
# for a class that shares one world.
def github_ok(world: World, repo: str = "owner/repo", branch: str = "main") -> None:
    world.gh_answer(["auth", "token"], stdout="stand-in-token\n")
    world.gh_answer(["repo", "view"], stdout=json.dumps({
        "nameWithOwner": repo, "defaultBranchRef": {"name": branch}, "viewerPermission": "ADMIN",
        "hasIssuesEnabled": True,
    }))
    world.gh_answer(["api", f"repos/{repo}/rules/branches/{branch}"], stdout="[]")


def reset_gh(world: World) -> None:
    (world.root / "gh-answers.json").write_text("[]", encoding="utf-8")
    (world.root / "gh-calls.jsonl").unlink(missing_ok=True)
