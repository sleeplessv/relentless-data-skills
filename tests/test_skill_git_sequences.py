"""Execute the git command sequences documented inside skills.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

Lint and the other tests read skill markdown as prose; they cannot tell when a
documented command sequence is wrong. These tests pull the fenced shell blocks
out of the skill files at run time and execute them, guard by guard, against
throwaway repositories with a local bare repo standing in for `origin`. Editing
a documented command therefore changes what runs here, and a broken command
fails the suite.

Nothing here touches the network or GitHub. Lines that call `gh` are dropped
before execution and the values they would supply are injected as variables.
The user's git configuration is isolated (GIT_CONFIG_GLOBAL, GIT_CONFIG_NOSYSTEM)
so signing, hooks paths, or pull settings on a developer machine cannot leak in.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPLEMENT_FEATURE_REF = REPO_ROOT / "skills" / "implement-feature" / "references" / "reference.md"
SHIP_SKILL = REPO_ROOT / "skills" / "ship" / "SKILL.md"
SMART_COMMIT_SKILL = REPO_ROOT / "skills" / "smart-git-commit" / "SKILL.md"

GIT = shutil.which("git")
BASH = shutil.which("bash")


# --------------------------------------------------------------------------
# Markdown extraction
# --------------------------------------------------------------------------

FENCE_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>```+|~~~+)(?P<info>[^\n`]*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def section(md_text: str, heading: str) -> str:
    """Return the text under `heading` up to the next heading of equal or higher level.

    Fenced blocks are skipped when scanning for headings, so a `#` comment in a
    shell block never ends a section.
    """
    lines = md_text.splitlines()
    start = level = None
    in_fence = None
    for i, line in enumerate(lines):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group("fence")
            if in_fence is None:
                in_fence = marker
            elif marker.startswith(in_fence[0]) and len(marker) >= len(in_fence):
                in_fence = None
            continue
        if in_fence is not None:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        if start is None:
            if m.group(2) == heading:
                start, level = i + 1, len(m.group(1))
        elif len(m.group(1)) <= level:
            return "\n".join(lines[start:i])
    if start is None:
        raise LookupError(f"heading not found: {heading!r}")
    return "\n".join(lines[start:])


def fenced_blocks(md_text: str, langs=("sh", "bash")) -> List[str]:
    """Return the bodies of fenced code blocks tagged with one of `langs`.

    Indented fences (inside list items) are dedented by the fence's own indent.
    """
    blocks: List[str] = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        indent, marker = m.group("indent"), m.group("fence")
        lang = m.group("info").strip().split(" ")[0] if m.group("info").strip() else ""
        body: List[str] = []
        i += 1
        while i < len(lines):
            close = FENCE_RE.match(lines[i])
            if close and close.group("fence").startswith(marker[0]) \
                    and len(close.group("fence")) >= len(marker) and not close.group("info").strip():
                break
            line = lines[i]
            body.append(line[len(indent):] if line.startswith(indent) else line.lstrip())
            i += 1
        i += 1
        if lang in langs:
            blocks.append("\n".join(body))
    return blocks


def doc_block(path: Path, heading: str, marker: str) -> str:
    """The single sh/bash block under `heading` whose text contains `marker`."""
    matches = [b for b in fenced_blocks(section(path.read_text(encoding="utf-8"), heading))
               if marker in b]
    if len(matches) != 1:
        raise LookupError(
            f"{path.name}: expected exactly one shell block under {heading!r} "
            f"containing {marker!r}, found {len(matches)}")
    return matches[0]


def split_commands(block: str) -> List[str]:
    """Split a shell block into complete commands, one per guard.

    Lines are joined until `bash -n` accepts the chunk, so heredocs and
    multi-line quoting stay whole. Blank and comment-only lines are dropped.
    """
    commands: List[str] = []
    pending: List[str] = []
    for line in block.splitlines():
        if not pending and (not line.strip() or line.lstrip().startswith("#")):
            continue
        pending.append(line)
        chunk = "\n".join(pending)
        check = subprocess.run([BASH, "-n", "-c", chunk], capture_output=True, text=True)
        if check.returncode == 0:
            commands.append(chunk)
            pending = []
    if pending:
        raise ValueError("incomplete shell command at end of block:\n" + "\n".join(pending))
    return commands


def substitute(block: str, values: Dict[str, str]) -> str:
    """Fill the doc's `<placeholder>`s; any left over fails loudly."""
    for key, val in values.items():
        if key not in block:
            raise AssertionError(f"placeholder {key!r} no longer in block:\n{block}")
        block = block.replace(key, val)
    left = re.findall(r"<[A-Za-z][^<>\n]*>", block)
    if left:
        raise AssertionError(f"unsubstituted placeholders {left} in:\n{block}")
    return block


def drop_gh(commands: List[str]) -> List[str]:
    """Drop commands that call the GitHub CLI; they cannot run offline."""
    return [c for c in commands if not re.search(r"(^|[\s$(])gh\s", c)]


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

class Step:
    def __init__(self, command: str, rc: int, out: str, err: str):
        self.command, self.rc, self.out, self.err = command, rc, out, err

    def __repr__(self) -> str:
        return f"Step(rc={self.rc}, cmd={self.command!r}, out={self.out!r}, err={self.err!r})"


class Run:
    def __init__(self, steps: List[Step], total: int):
        self.steps, self.total = steps, total

    @property
    def completed(self) -> bool:
        return len(self.steps) == self.total and (not self.steps or self.ran_ok(self.steps[-1]))

    @staticmethod
    def ran_ok(step: Step) -> bool:
        return getattr(step, "allowed", True)

    def step(self, needle: str) -> Step:
        hits = [s for s in self.steps if needle in s.command]
        if len(hits) != 1:
            raise AssertionError(f"{len(hits)} executed steps contain {needle!r}: {self.steps!r}")
        return hits[0]

    def ran(self, needle: str) -> bool:
        return any(needle in s.command for s in self.steps)

    def __repr__(self) -> str:
        return "\n".join(repr(s) for s in self.steps)


class Sandbox:
    """A temp dir with isolated git config and helpers for building repos."""

    def __init__(self, test: unittest.TestCase):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="skill-git-")))
        test.addCleanup(shutil.rmtree, str(self.root), True)
        home = self.root / "home"
        home.mkdir()
        gitconfig = home / ".gitconfig"
        gitconfig.write_text(
            "[user]\n\tname = Skill Test\n\temail = skill-test@example.invalid\n"
            "[init]\n\tdefaultBranch = main\n"
            "[advice]\n\tdetachedHead = false\n",
            encoding="utf-8")
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_TERMINAL_PROMPT": "0",
        }
        self._runs = 0

    def git(self, cwd: Path, *args: str, check: bool = True) -> str:
        proc = subprocess.run([GIT, *args], cwd=str(cwd), env=self.env,
                              capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr}")
        return proc.stdout.strip()

    def commit_file(self, repo: Path, name: str, content: str, message: str) -> str:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", message)
        return self.git(repo, "rev-parse", "HEAD")

    def origin_with_main(self) -> Path:
        """A bare `origin.git` whose `main` holds one commit."""
        origin = self.root / "origin.git"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(origin))
        seed = self.root / "seed"
        self.git(self.root, "clone", "-q", str(origin), str(seed))
        self.commit_file(seed, "README.md", "seed\n", "chore: seed")
        self.git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
        return origin

    def clone(self, origin: Path, name: str) -> Path:
        dest = self.root / name
        self.git(self.root, "clone", "-q", str(origin), str(dest))
        return dest

    def remote_sha(self, origin: Path, ref: str) -> Optional[str]:
        out = self.git(origin, "rev-parse", "--verify", "-q", ref, check=False)
        return out or None

    def run(self, cwd: Path, commands: List[str], variables: Optional[Dict[str, str]] = None,
            allow: Optional[Dict[str, Set[int]]] = None,
            before: Optional[Dict[str, str]] = None) -> Run:
        """Run `commands` in one bash process, stopping at the first failed guard.

        Each command's stdout/stderr/exit code is captured separately and shell
        variables persist between commands. `allow` maps a substring of a
        command to the exit codes the doc says pass for it (default {0}).
        `before` maps a substring of a command to a shell snippet run just
        before it (not recorded), to simulate a concurrent actor.
        """
        allow = allow or {}
        before = before or {}
        self._runs += 1
        work = self.root / f"run{self._runs}"
        work.mkdir()
        script = ["exec 3>" + _q(work / "status")]
        allowed_for: List[Set[int]] = []
        for i, cmd in enumerate(commands):
            codes = {0}
            for needle, ok in allow.items():
                if needle in cmd:
                    codes = set(ok)
            allowed_for.append(codes)
            for needle, snippet in before.items():
                if needle in cmd:
                    script.append(f"( {snippet} ) >/dev/null 2>&1 || {{ echo injection-failed >&2; exit 97; }}")
            script.append("{ " + cmd + "\n} >" + _q(work / f"{i}.out") + " 2>" + _q(work / f"{i}.err"))
            script.append(f"__rc=$?; echo \"{i} $__rc\" >&3")
            case = "|".join(str(c) for c in sorted(codes))
            script.append(f"case $__rc in {case}) ;; *) exit 0 ;; esac")
        env = dict(self.env)
        env.update(variables or {})
        proc = subprocess.run([BASH, "--noprofile", "--norc", "-c", "\n".join(script)],
                              cwd=str(cwd), env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"runner failed ({proc.returncode}): {proc.stderr}")
        steps: List[Step] = []
        status = (work / "status").read_text(encoding="utf-8").split("\n")
        for line in filter(None, status):
            i, rc = (int(x) for x in line.split())
            step = Step(commands[i], rc,
                        (work / f"{i}.out").read_text(encoding="utf-8"),
                        (work / f"{i}.err").read_text(encoding="utf-8"))
            step.allowed = rc in allowed_for[i]
            steps.append(step)
        return Run(steps, len(commands))


def _q(path: Path) -> str:
    return "'" + str(path).replace("'", "'\\''") + "'"


def first_word(text: str) -> str:
    return text.split()[0] if text.split() else ""


@unittest.skipUnless(GIT and BASH, "git and bash are required")
class ExtractionTests(unittest.TestCase):
    """The extractor itself, so a parsing bug cannot pass every sequence test."""

    def test_section_ignores_hash_comments_in_fences(self):
        md = "# A\n\n## B\n\n```sh\n# not a heading\necho b\n```\n\n## C\n\n```sh\necho c\n```\n"
        self.assertEqual(fenced_blocks(section(md, "B")), ["# not a heading\necho b"])

    def test_indented_fence_is_dedented(self):
        md = "## S\n\n- item\n\n  ```bash\n  echo one\n  echo two\n  ```\n"
        self.assertEqual(fenced_blocks(section(md, "S")), ["echo one\necho two"])

    def test_heredoc_stays_one_command(self):
        block = "git add x\ngit commit -m \"$(cat <<'EOF'\nsubject\n\nbody\nEOF\n)\"\n# trailing comment"
        cmds = split_commands(block)
        self.assertEqual(len(cmds), 2)
        self.assertIn("body\nEOF\n)\"", cmds[1])

    def test_drop_gh(self):
        cmds = ["sha=$(gh pr view 1 --json headRefOid -q .headRefOid)",
                "git grep -lwE x \"$sha\"", "gh run list --commit \"$sha\""]
        self.assertEqual(drop_gh(cmds), ["git grep -lwE x \"$sha\""])


# --------------------------------------------------------------------------
# implement-feature: Integration commands and Cleanup
# --------------------------------------------------------------------------

def if_block(marker: str, heading: str = "Integration commands") -> List[str]:
    return split_commands(doc_block(IMPLEMENT_FEATURE_REF, heading, marker))


@unittest.skipUnless(GIT and BASH, "git and bash are required")
class ImplementFeatureIntegrationTests(unittest.TestCase):
    """Run the reference's merge, push and cleanup blocks as a coordinator would."""

    INT = "spec-1-demo"

    def setUp(self):
        self.sb = Sandbox(self)
        self.origin = self.sb.origin_with_main()
        # Integration checkout: INT created locally from the pinned base, never pushed yet.
        self.ic = self.sb.clone(self.origin, "integration")
        self.base_sha = self.sb.git(self.ic, "rev-parse", "HEAD")
        self.sb.git(self.ic, "checkout", "-q", "-b", self.INT, self.base_sha)
        self.pre_merge = if_block("PRE_MERGE_HEAD")
        self.merge = if_block("git merge --no-ff")
        self.abort = if_block("git merge --abort")
        self.push = if_block("git push --porcelain")
        self.wt_remove = if_block("git worktree remove", "Cleanup")
        self.local_delete = if_block("git update-ref -d", "Cleanup")
        self.remote_delete = if_block("--force-with-lease", "Cleanup")

    # -- helpers ---------------------------------------------------------

    def make_ticket(self, n: int, filename: str, content: str = "work\n", push: bool = True):
        """Create a ticket worktree from the current integration tip, commit, and push TB."""
        tb = f"feat/ticket-{n}"
        wt = self.sb.root / f"wt-{n}"
        dispatch = self.sb.git(self.ic, "rev-parse", "HEAD")
        self.sb.git(self.ic, "worktree", "add", "-q", "-b", tb, str(wt), dispatch)
        sha = self.sb.commit_file(wt, filename, content, f"feat: ticket {n}")
        if push:
            self.sb.git(wt, "push", "-q", "origin", f"HEAD:refs/heads/{tb}")
        return {"N": str(n), "TB": tb, "WT": str(wt), "TICKET_SHA": sha, "BASE_SHA": dispatch}

    def variables(self, ticket, **extra):
        v = {"REMOTE": "origin", "INT": self.INT}
        v.update(ticket)
        v.update(extra)
        return v

    def integrate(self, ticket, int_pushed: bool):
        """Pre-merge guards, merge, push; returns VERIFIED_TIP."""
        v = self.variables(ticket)
        allow = {} if int_pushed else {f'"refs/heads/$INT"': {0, 2}}
        pre = self.sb.run(self.ic, self.pre_merge, v, allow=allow)
        self.assertTrue(pre.completed, pre)
        self.assertEqual(pre.step("--porcelain --untracked-files=all").out, "")
        int_guard = pre.step('"refs/heads/$INT"')
        if int_pushed:
            self.assertEqual(int_guard.rc, 0, int_guard)
        else:
            # First integration of a fresh run: the branch was never pushed.
            self.assertEqual(int_guard.rc, 2, int_guard)
            self.assertEqual(int_guard.out, "")
        tb_guard = pre.step('ls-remote --exit-code "$REMOTE" "refs/heads/$TB"')
        self.assertEqual(first_word(tb_guard.out), ticket["TICKET_SHA"])

        merged = self.sb.run(self.ic, self.merge, v)
        self.assertTrue(merged.completed, merged)
        self.assertEqual(self.sb.git(self.ic, "rev-parse", "HEAD^2"), ticket["TICKET_SHA"])
        self.assertEqual(self.sb.git(self.ic, "log", "-1", "--format=%s"),
                         f"Merge ticket #{ticket['N']} ({ticket['TB']}) into {self.INT}")

        pushed = self.sb.run(self.ic, self.push, v)
        self.assertTrue(pushed.completed, pushed)
        tested = pushed.step("git rev-parse HEAD").out.strip()
        self.assertEqual(first_word(pushed.step("git ls-remote").out), tested)
        self.assertEqual(self.sb.remote_sha(self.origin, f"refs/heads/{self.INT}"), tested)
        return tested

    # -- tests -----------------------------------------------------------

    def test_documented_guards_present(self):
        """Drift anchors: the guards these tests rely on still exist verbatim."""
        joined = "\n".join(self.pre_merge + self.push + self.wt_remove
                           + self.local_delete + self.remote_delete)
        for line in [
            'git ls-remote --exit-code "$REMOTE" "refs/heads/$INT"',
            'git merge-base --is-ancestor "$BASE_SHA" HEAD',
            'git push --porcelain "$REMOTE" "HEAD:refs/heads/$INT"',
            'git worktree remove "$WT"',
            '! git worktree list --porcelain | grep -qFx "branch refs/heads/$TB"',
            'git update-ref -d "refs/heads/$TB" "$LOCAL_TIP"',
            'git push --force-with-lease="refs/heads/$TB:$REMOTE_TIP" --delete "$REMOTE" "refs/heads/$TB"',
        ]:
            self.assertIn(line, joined)
        # The fresh-run tests accept exit 2 from the INT guard only because the
        # doc says so; if that allowance goes, the first integration dead-ends.
        prose = " ".join(section(IMPLEMENT_FEATURE_REF.read_text(encoding="utf-8"),
                                 "Integration commands").split())
        self.assertIn("Exit 2 (remote branch absent) also passes while the run record "
                      "has no successful `INT` push", prose)
        remove = [c for c in self.wt_remove if "git worktree remove" in c]
        self.assertEqual(len(remove), 1)
        self.assertNotIn("--force", remove[0].split("#")[0])
        self.assertIn('"$TICKET_SHA"', self.merge[0])

    def test_fresh_run_first_and_second_integration_with_cleanup(self):
        t1 = self.make_ticket(1, "one.txt")
        tip1 = self.integrate(t1, int_pushed=False)

        v = self.variables(t1, VERIFIED_TIP=tip1)
        rm = self.sb.run(self.ic, self.wt_remove, v)
        self.assertTrue(rm.completed, rm)
        self.assertFalse(Path(t1["WT"]).exists())

        local = self.sb.run(self.ic, self.local_delete, v)
        self.assertTrue(local.completed, local)
        self.assertEqual(self.sb.git(self.ic, "rev-parse", "--verify", "-q",
                                     f"refs/heads/{t1['TB']}", check=False), "")

        remote = self.sb.run(self.ic, self.remote_delete, v)
        self.assertTrue(remote.completed, remote)
        self.assertIsNone(self.sb.remote_sha(self.origin, f"refs/heads/{t1['TB']}"))

        # Second ticket: INT now exists remotely, so its guard must exit 0 and
        # report the last verified tip.
        t2 = self.make_ticket(2, "two.txt")
        pre = self.sb.run(self.ic, self.pre_merge, self.variables(t2))
        self.assertTrue(pre.completed, pre)
        self.assertEqual(first_word(pre.step('"refs/heads/$INT"').out), tip1)
        tip2 = self.integrate(t2, int_pushed=True)
        self.sb.git(self.ic, "merge-base", "--is-ancestor", tip1, tip2)

    def test_dirty_integration_checkout_is_reported(self):
        t1 = self.make_ticket(1, "one.txt")
        (self.ic / "stray.txt").write_text("x\n", encoding="utf-8")
        pre = self.sb.run(self.ic, self.pre_merge, self.variables(t1), allow={'"refs/heads/$INT"': {0, 2}})
        self.assertIn("stray.txt", pre.step("--porcelain --untracked-files=all").out)

    def test_moved_ticket_branch_fails_sha_guard(self):
        t1 = self.make_ticket(1, "one.txt")
        moved = self.sb.commit_file(Path(t1["WT"]), "late.txt", "late\n", "feat: late push")
        self.sb.git(Path(t1["WT"]), "push", "-q", "origin", f"HEAD:refs/heads/{t1['TB']}")
        pre = self.sb.run(self.ic, self.pre_merge, self.variables(t1), allow={'"refs/heads/$INT"': {0, 2}})
        got = first_word(pre.step('ls-remote --exit-code "$REMOTE" "refs/heads/$TB"').out)
        self.assertEqual(got, moved)
        self.assertNotEqual(got, t1["TICKET_SHA"])

    def test_diverged_dispatch_base_fails_guard(self):
        t1 = self.make_ticket(1, "one.txt")
        foreign = self.sb.clone(self.origin, "foreign")
        stray = self.sb.commit_file(foreign, "x.txt", "x\n", "chore: unrelated")
        self.sb.git(foreign, "push", "-q", "origin", "HEAD:refs/heads/other")
        self.sb.git(self.ic, "fetch", "-q", "origin", "other")
        pre = self.sb.run(self.ic, self.pre_merge, self.variables(t1, BASE_SHA=stray),
                          allow={'"refs/heads/$INT"': {0, 2}})
        self.assertFalse(pre.completed, pre)
        self.assertIn('git merge-base --is-ancestor "$BASE_SHA" HEAD', pre.steps[-1].command)

    def test_merge_abort_block_is_safe_with_and_without_a_merge(self):
        clean = self.sb.run(self.ic, self.abort, {})
        self.assertTrue(clean.completed, clean)

        # A ticket and a later INT commit edit the same file: the merge stops
        # in conflict and the block aborts only that active merge.
        t = self.make_ticket(3, "README.md", "ticket side\n")
        self.sb.commit_file(self.ic, "README.md", "int again\n", "chore: int edit 2")
        head = self.sb.git(self.ic, "rev-parse", "HEAD")
        merged = self.sb.run(self.ic, self.merge, self.variables(t))
        self.assertFalse(merged.completed, merged)
        aborted = self.sb.run(self.ic, self.abort, {})
        self.assertTrue(aborted.completed, aborted)
        self.assertEqual(aborted.step("git rev-parse HEAD").out.strip(), head)
        self.assertEqual(aborted.step("git status").out, "")

    def test_dirty_retained_worktree_keeps_worktree_and_branch(self):
        t1 = self.make_ticket(1, "one.txt")
        tip = self.integrate(t1, int_pushed=False)
        (Path(t1["WT"]) / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
        v = self.variables(t1, VERIFIED_TIP=tip)

        rm = self.sb.run(self.ic, self.wt_remove, v)
        # The status guard prints the dirty path; an operator stops there.
        # Even run blindly, `git worktree remove` without --force refuses.
        self.assertIn("scratch.txt", rm.step("status --porcelain").out)
        self.assertTrue(Path(t1["WT"]).exists())

        local = self.sb.run(self.ic, self.local_delete, v)
        self.assertFalse(local.completed, local)
        self.assertEqual(len(local.steps), 1, local)
        self.assertEqual(local.steps[0].rc, 1)
        self.assertFalse(local.ran("update-ref"))
        self.assertEqual(self.sb.git(self.ic, "rev-parse", f"refs/heads/{t1['TB']}"), t1["TICKET_SHA"])
        self.assertEqual(self.sb.git(Path(t1["WT"]), "branch", "--show-current"), t1["TB"])

    def test_unpreserved_worktree_head_is_retained(self):
        t1 = self.make_ticket(1, "one.txt")
        tip = self.integrate(t1, int_pushed=False)
        self.sb.commit_file(Path(t1["WT"]), "wip.txt", "wip\n", "wip: not integrated")
        rm = self.sb.run(self.ic, self.wt_remove, self.variables(t1, VERIFIED_TIP=tip))
        self.assertFalse(rm.completed, rm)
        self.assertFalse(rm.ran("git worktree remove"))
        self.assertTrue(Path(t1["WT"]).exists())

    def test_stale_remote_lease_is_rejected_and_branch_retained(self):
        t1 = self.make_ticket(1, "one.txt")
        tip = self.integrate(t1, int_pushed=False)
        v = self.variables(t1, VERIFIED_TIP=tip)
        late = self.sb.clone(self.origin, "late")
        self.sb.git(late, "checkout", "-q", t1["TB"])
        # Someone pushes to TB after REMOTE_TIP is read but before the delete.
        snippet = (f"cd {_q(late)} && echo late > late.txt && git add late.txt && "
                   f"git commit -q -m late && git push -q origin HEAD:refs/heads/{t1['TB']}")
        run = self.sb.run(self.ic, self.remote_delete, v, before={"--force-with-lease": snippet})
        self.assertFalse(run.completed, run)
        push = run.step("--force-with-lease")
        self.assertNotEqual(push.rc, 0)
        self.assertIn("(stale info)", push.err)
        new_tip = self.sb.git(late, "rev-parse", "HEAD")
        self.assertEqual(self.sb.remote_sha(self.origin, f"refs/heads/{t1['TB']}"), new_tip)

    def test_remote_branch_already_gone_stops_before_push(self):
        t1 = self.make_ticket(1, "one.txt")
        tip = self.integrate(t1, int_pushed=False)
        self.sb.git(self.ic, "push", "-q", "origin", "--delete", t1["TB"])
        run = self.sb.run(self.ic, self.remote_delete, self.variables(t1, VERIFIED_TIP=tip))
        self.assertEqual(run.step("REMOTE_TIP=$(").rc, 0)
        self.assertFalse(run.completed, run)
        self.assertFalse(run.ran("--force-with-lease"))


# --------------------------------------------------------------------------
# ship
# --------------------------------------------------------------------------

def ship_block(heading: str, marker: str, values: Optional[Dict[str, str]] = None) -> List[str]:
    """A ship block with `gh` lines dropped and `<placeholder>`s filled in.

    `gh` lines go first, line by line: their `<number>` placeholders are not
    valid shell, so they cannot reach the parser.
    """
    block = doc_block(SHIP_SKILL, heading, marker)
    offline = "\n".join(drop_gh(block.splitlines()))
    return split_commands(substitute(offline, values or {}))


@unittest.skipUnless(GIT and BASH, "git and bash are required")
class ShipTests(unittest.TestCase):

    def setUp(self):
        self.sb = Sandbox(self)
        self.origin = self.sb.origin_with_main()
        self.work = self.sb.clone(self.origin, "work")

    def inline_fresh_branch(self) -> str:
        text = section(SHIP_SKILL.read_text(encoding="utf-8"), "Step 2: Pick the branch")
        m = re.search(r"Fresh-branch mechanics: `([^`]+)`", text)
        self.assertIsNotNone(m, "Fresh-branch mechanics inline command not found")
        return m.group(1)

    def test_merged_detection(self):
        cmds = ship_block("Step 2: Pick the branch", "ancestor-merged")
        self.assertEqual(cmds, ["git fetch origin main",
                                "git merge-base --is-ancestor HEAD origin/main && echo ancestor-merged"])
        self.sb.git(self.work, "checkout", "-q", "-b", "feat/old")
        merged = self.sb.run(self.work, cmds)
        self.assertEqual(merged.steps[-1].out.strip(), "ancestor-merged")

        self.sb.commit_file(self.work, "new.txt", "new\n", "feat: new")
        live = self.sb.run(self.work, cmds, allow={"ancestor-merged": {0, 1}})
        self.assertEqual(live.steps[-1].rc, 1)
        self.assertEqual(live.steps[-1].out, "")

    def test_fresh_branch_carries_uncommitted_changes(self):
        cmd = self.inline_fresh_branch().replace("<branch>", "feat/carry")
        upstream = self.sb.clone(self.origin, "upstream")
        advanced = self.sb.commit_file(upstream, "up.txt", "up\n", "chore: advance main")
        self.sb.git(upstream, "push", "-q", "origin", "HEAD:main")
        self.sb.git(self.work, "checkout", "-q", "-b", "fix/stale")
        (self.work / "README.md").write_text("edited\n", encoding="utf-8")
        run = self.sb.run(self.work, split_commands(cmd))
        self.assertTrue(run.completed, run)
        self.assertEqual(self.sb.git(self.work, "branch", "--show-current"), "feat/carry")
        self.assertEqual(self.sb.git(self.work, "rev-parse", "HEAD"), advanced)
        self.assertIn("README.md", self.sb.git(self.work, "status", "--porcelain"))

    def test_push_sets_upstream(self):
        cmds = split_commands(doc_block(SHIP_SKILL, "Step 3: Commit", "git push"))
        self.assertEqual(cmds, ["git push -u origin HEAD"])
        self.sb.git(self.work, "checkout", "-q", "-b", "feat/x")
        sha = self.sb.commit_file(self.work, "x.txt", "x\n", "feat: x")
        run = self.sb.run(self.work, cmds)
        self.assertTrue(run.completed, run)
        self.assertEqual(self.sb.remote_sha(self.origin, "refs/heads/feat/x"), sha)
        self.assertEqual(self.sb.git(self.work, "rev-parse", "--abbrev-ref", "@{u}"), "origin/feat/x")

    def ci_detect(self, sha: str) -> Run:
        cmds = ship_block("Step 5: Merge and clean up", "git grep -lwE")
        self.assertEqual(len(cmds), 1, cmds)
        self.assertIn("\"$sha\" -- .github/workflows", cmds[0])
        return self.sb.run(self.work, cmds, {"sha": sha}, allow={"git grep": {0, 1}})

    def test_ci_detection_matches_pr_triggers_in_head_tree(self):
        cases = {
            "on:\n  pull_request:\n": True,
            "on: [push, pull_request]\n": True,
            "on:\n  pull_request_target:\n    types: [opened]\n": True,
            "on:\n  push:\n    branches: [main]\n": False,
            "on:\n  pull_request_review:\n": False,
        }
        for body, expected in cases.items():
            with self.subTest(workflow=body):
                sha = self.sb.commit_file(self.work, ".github/workflows/ci.yml", body, "ci: workflow")
                step = self.ci_detect(sha).steps[0]
                if expected:
                    self.assertEqual((step.rc, step.out.strip()),
                                     (0, f"{sha}:.github/workflows/ci.yml"))
                else:
                    self.assertEqual((step.rc, step.out), (1, ""), step)

    def test_ci_detection_without_workflows_and_ignores_worktree(self):
        sha = self.sb.git(self.work, "rev-parse", "HEAD")
        wf = self.work / ".github" / "workflows" / "ci.yml"
        wf.parent.mkdir(parents=True)
        wf.write_text("on: pull_request\n", encoding="utf-8")  # uncommitted: not in the PR head
        step = self.ci_detect(sha).steps[0]
        self.assertEqual((step.rc, step.out), (1, ""), step)

    def test_finish_on_main_confirms_merged_and_flags_leftover_branch(self):
        branch = "feat/done"
        self.sb.git(self.work, "checkout", "-q", "-b", branch)
        self.sb.commit_file(self.work, "done.txt", "done\n", "feat: done")
        self.sb.git(self.work, "push", "-q", "-u", "origin", "HEAD")
        # Simulate GitHub's squash merge on the server side.
        server = self.sb.clone(self.origin, "server")
        self.sb.git(server, "merge", "-q", "--squash", f"origin/{branch}")
        self.sb.git(server, "commit", "-q", "-m", "feat: done (#1)")
        merge_oid = self.sb.git(server, "rev-parse", "HEAD")
        self.sb.git(server, "push", "-q", "origin", "HEAD:main")

        cmds = ship_block("Step 5: Merge and clean up", "git checkout main && git pull",
                          {"<mergeCommit.oid>": merge_oid, "<branch>": branch})
        self.assertEqual(len(cmds), 4, cmds)
        allow = {"ls-remote": {0, 2}, "rev-parse --verify": {0, 1}}

        # Cleanup incomplete: remote and local branch still exist.
        partial = self.sb.run(self.work, cmds, allow=allow)
        self.assertTrue(partial.completed, partial)
        self.assertEqual(self.sb.git(self.work, "branch", "--show-current"), "main")
        self.assertEqual(partial.step("ls-remote").rc, 0)
        self.assertEqual(partial.step("rev-parse --verify").rc, 0)

        # gh's --delete-branch removes both; all three confirmations now pass.
        self.sb.git(server, "push", "-q", "origin", "--delete", branch)
        self.sb.git(self.work, "branch", "-q", "-D", branch)
        done = self.sb.run(self.work, cmds, allow=allow)
        self.assertTrue(done.completed, done)
        self.assertEqual(done.step("merge-base").rc, 0)
        self.assertEqual(done.step("ls-remote").rc, 2)
        self.assertNotEqual(done.step("rev-parse --verify").rc, 0)


# --------------------------------------------------------------------------
# smart-git-commit
# --------------------------------------------------------------------------

@unittest.skipUnless(GIT and BASH, "git and bash are required")
class SmartGitCommitTests(unittest.TestCase):

    def setUp(self):
        self.sb = Sandbox(self)
        self.origin = self.sb.origin_with_main()
        self.work = self.sb.clone(self.origin, "work")
        text = SMART_COMMIT_SKILL.read_text(encoding="utf-8")
        self.commit = doc_block(SMART_COMMIT_SKILL, "Step 4: Commit each group", "git commit")
        push_blocks = fenced_blocks(section(text, "Step 5: Push when asked"))
        self.push, self.push_upstream = (split_commands(b) for b in push_blocks)

    def test_commit_block_creates_one_local_commit_and_does_not_push(self):
        (self.work / "a.txt").write_text("a\n", encoding="utf-8")
        (self.work / "b.txt").write_text("b\n", encoding="utf-8")
        cmds = split_commands(substitute(self.commit, {"<files in group>": "a.txt"}))
        self.assertEqual(len(cmds), 2, cmds)
        before = self.sb.remote_sha(self.origin, "refs/heads/main")
        run = self.sb.run(self.work, cmds)
        self.assertTrue(run.completed, run)
        self.assertEqual(self.sb.git(self.work, "log", "-1", "--format=%B"),
                         "type: short imperative description\n\n"
                         "Optional body if the change needs explanation.")
        self.assertEqual(self.sb.git(self.work, "show", "--name-only", "--format=", "HEAD"), "a.txt")
        self.assertIn("?? b.txt", self.sb.git(self.work, "status", "--porcelain"))
        self.assertEqual(self.sb.remote_sha(self.origin, "refs/heads/main"), before)

    def test_push_on_tracked_branch(self):
        self.assertEqual(self.push, ["git push"])
        sha = self.sb.commit_file(self.work, "c.txt", "c\n", "feat: c")
        run = self.sb.run(self.work, self.push)
        self.assertTrue(run.completed, run)
        self.assertEqual(self.sb.remote_sha(self.origin, "refs/heads/main"), sha)

    def test_no_upstream_needs_documented_fallback(self):
        self.assertEqual(self.push_upstream, ["git push -u origin HEAD"])
        self.sb.git(self.work, "checkout", "-q", "-b", "feat/new")
        sha = self.sb.commit_file(self.work, "d.txt", "d\n", "feat: d")
        plain = self.sb.run(self.work, self.push)
        self.assertFalse(plain.completed)
        self.assertIn("no upstream", plain.steps[0].err)
        run = self.sb.run(self.work, self.push_upstream)
        self.assertTrue(run.completed, run)
        self.assertEqual(self.sb.remote_sha(self.origin, "refs/heads/feat/new"), sha)
        again = self.sb.run(self.work, self.push)
        self.assertTrue(again.completed, again)

    def test_rejected_non_fast_forward_push(self):
        other = self.sb.clone(self.origin, "other")
        self.sb.commit_file(other, "o.txt", "o\n", "feat: other")
        self.sb.git(other, "push", "-q", "origin", "HEAD:main")
        self.sb.commit_file(self.work, "w.txt", "w\n", "feat: mine")
        run = self.sb.run(self.work, self.push)
        self.assertFalse(run.completed)
        self.assertIn("rejected", run.steps[0].err)


if __name__ == "__main__":
    unittest.main()
