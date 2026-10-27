"""Tests for skills/statusline/scripts/statusline.sh.

Runs the script as Claude Code does: status line JSON on stdin, output on
stdout. Each test builds a throwaway git repo on a chosen branch, a PR cache,
and a fresh refresh stamp, so the script does not refresh the cache unless the
test asks it to. A stub gh on PATH keeps everything off the network. Run from the repo root:

    python3 -m unittest tests.test_statusline -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "statusline" / "scripts" / "statusline.sh"
REPO_URL = "https://github.com/acme/widgets"
CHIP = "\x1b[48;2;215;119;87;38;2;26;26;26m"
ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")


def pr(number, closes=(), branch=None, draft=False, fork=False):
    """One entry of the cache, shaped like gh pr list --json output."""
    return {
        "number": number,
        "url": f"{REPO_URL}/pull/{number}",
        "isDraft": draft,
        "isCrossRepository": fork,
        "headRefName": branch or f"branch-{number}",
        "statusCheckRollup": [],
        "closingIssuesReferences": [
            {"number": n, "url": f"{REPO_URL}/issues/{n}"} for n in closes
        ],
    }


class StatuslineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        self.gh = bin_dir / "gh"
        self.gh.write_text("#!/bin/sh\nexit 1\n")
        self.gh.chmod(0o755)
        self.cache_dir = self.tmp / "cache" / "claude-statusline"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
        }

    def render(self, branch, prs, cache_age=0, stamp=True):
        """Run the script on `branch` with `prs` cached `cache_age` seconds ago.

        Without `stamp`, the refresh is due. Return the second line.
        """
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q", "-b", branch], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        key = subprocess.run(
            ["cksum"], input=str(self.repo), capture_output=True, text=True, check=True
        ).stdout.split()[0]
        self.cache_dir.mkdir(parents=True)
        self.cache = self.cache_dir / f"prs-v2-{key}.json"
        self.cache.write_text(json.dumps(prs))
        then = time.time() - cache_age
        os.utime(self.cache, (then, then))
        if stamp:
            (self.cache_dir / f"prs-v2-{key}.stamp").touch()
        stdin = json.dumps({"model": {"display_name": "M"}, "workspace": {"current_dir": str(self.repo)}})
        out = subprocess.run(
            ["sh", str(SCRIPT)], input=stdin, capture_output=True, text=True, env=self.env, check=True
        ).stdout
        lines = out.split("\n")
        return lines[1] if len(lines) > 1 else ""

    def git(self, *args, cwd=None):
        """Run git in the test repo, or in `cwd`. Return its stdout."""
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            capture_output=True, text=True, check=True,
        ).stdout

    def feature_repo(self, default="main", remote=True):
        """A repo whose `default` branch has a.txt with three lines, then a
        checked-out branch named feature. With `remote`, origin/HEAD points to
        origin/<default>, as after a clone."""
        self.git("init", "-q", "-b", default)
        (self.repo / "a.txt").write_text("one\ntwo\nthree\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "init")
        if remote:
            self.git("update-ref", f"refs/remotes/origin/{default}", "HEAD")
            self.git("symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{default}")
        self.git("checkout", "-q", "-b", "feature")

    def commit_all(self, message="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def first_line(self, cwd=None, **fields):
        """Run the script with `cwd` (default: the test repo) as the workspace,
        plus any other top-level status line `fields`. Return line 1."""
        stdin = json.dumps(
            {"model": {"display_name": "M"}, "workspace": {"current_dir": str(cwd or self.repo)}, **fields}
        )
        out = subprocess.run(
            ["sh", str(SCRIPT)], input=stdin, capture_output=True, text=True, env=self.env, check=True
        ).stdout
        return out.split("\n")[0]

    def test_branch_diff_shows_committed_lines_added_and_removed(self):
        self.feature_repo()
        (self.repo / "a.txt").write_text("one\nTWO\nthree\nfour\n")
        self.commit_all()
        line = self.first_line()
        self.assertIn("\x1b[38;2;127;183;126m+2\x1b[0m", line)
        self.assertIn("\x1b[38;2;224;108;117m\u22121\x1b[38;2;215;119;87m)", line)
        self.assertTrue(ANSI.sub("", line).endswith(" | repo (feature +2 \u22121)"), ANSI.sub("", line))

    def test_branch_diff_counts_staged_unstaged_and_untracked_lines(self):
        self.feature_repo()
        (self.repo / "a.txt").write_text("one\nthree\n")
        self.git("add", "a.txt")
        (self.repo / "b.txt").write_text("x\n")
        self.git("add", "b.txt")
        (self.repo / "b.txt").write_text("x\ny\n")
        (self.repo / "new").mkdir()
        (self.repo / "new" / "c.txt").write_text("1\n2\n3\n")
        (self.repo / "logo.png").write_bytes(b"\x89PNG\x00\x01\x02")
        (self.repo / ".gitignore").write_text("*.log\n")
        (self.repo / "debug.log").write_text("ignored\n" * 50)
        index = self.repo / ".git" / "index"
        before = index.read_bytes()
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        self.env["TMPDIR"] = str(scratch)
        line = ANSI.sub("", self.first_line())
        # b.txt 2, new/c.txt 3, .gitignore 1, logo.png 0 (binary); a.txt removes 1.
        self.assertTrue(line.endswith("(feature +6 \u22121)"), line)
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(list(scratch.iterdir()), [])
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "a.txt\nb.txt\n")
        self.assertEqual(self.git("ls-files", "--others", "--exclude-standard"), ".gitignore\nlogo.png\nnew/c.txt\n")

    def test_branch_diff_counts_untracked_files_named_like_pathspec_magic(self):
        self.feature_repo()
        (self.repo / "b.txt").write_text("tracked\n")
        self.commit_all()
        for name in (":(exclude)a", "[ab].txt", "ok.txt"):
            (self.repo / name).write_text("x\n")
        line = ANSI.sub("", self.first_line())
        self.assertTrue(line.endswith("(feature +4 \u22120)"), line)

    def test_branch_diff_removes_its_temp_index_when_killed(self):
        self.feature_repo()
        (self.repo / "new.txt").write_text("1\n")
        # A git that stalls on the diff and records the temp index it was given,
        # so the render is killed mid-count. macOS mktemp ignores TMPDIR, so the
        # test finds the index through git rather than in a scratch directory.
        seen = self.tmp / "index-path"
        git = self.tmp / "bin" / "git"
        git.write_text(
            f'#!/bin/sh\ncase " $* " in *" diff --shortstat "*)\n'
            f'  printf %s "$GIT_INDEX_FILE" >"{seen}.tmp"; mv "{seen}.tmp" "{seen}"; sleep 10 ;;\nesac\n'
            f'exec {shutil.which("git")} "$@"\n'
        )
        git.chmod(0o755)
        stdin = json.dumps({"model": {"display_name": "M"}, "workspace": {"current_dir": str(self.repo)}})
        proc = subprocess.Popen(
            ["sh", str(SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            env=self.env, start_new_session=True,
        )
        self.addCleanup(proc.wait)
        proc.stdin.write(stdin.encode())
        proc.stdin.close()
        for _ in range(50):
            if seen.exists():
                break
            time.sleep(0.1)
        index = Path(seen.read_text())
        self.addCleanup(index.unlink, missing_ok=True)
        self.assertTrue(index.exists(), index)
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
        self.assertFalse(index.exists(), index)
        self.assertFalse(Path(f"{index}.lock").exists())

    def test_branch_diff_is_hidden_on_the_default_branch(self):
        for remote in (True, False):
            with self.subTest(remote=remote):
                self.setUp()
                self.feature_repo(remote=remote)
                self.git("checkout", "-q", "main")
                (self.repo / "a.txt").write_text("changed\n")
                self.assertTrue(self.first_line().endswith(" repo \x1b[38;2;215;119;87m(main)\x1b[0m"))

    def test_branch_diff_is_hidden_on_the_default_branch_beside_a_local_origin_main(self):
        self.feature_repo()
        self.git("branch", "origin/main", "main")
        self.git("checkout", "-q", "main")
        (self.repo / "a.txt").write_text("one\ntwo\nthree\nfour\n")
        line = ANSI.sub("", self.first_line())
        self.assertTrue(line.endswith(" | repo (main)"), line)

    def test_branch_diff_is_hidden_on_a_detached_head(self):
        self.feature_repo()
        (self.repo / "a.txt").write_text("changed\n")
        self.commit_all()
        self.git("checkout", "-q", "--detach")
        short = self.git("rev-parse", "--short", "HEAD").strip()
        self.assertTrue(ANSI.sub("", self.first_line()).endswith(f" | repo ({short})"))

    def test_branch_diff_is_hidden_without_a_default_branch_ref(self):
        self.feature_repo(default="trunk", remote=False)
        (self.repo / "a.txt").write_text("changed\n")
        self.assertTrue(ANSI.sub("", self.first_line()).endswith(" | repo (feature)"))

    def test_branch_diff_is_hidden_when_the_branch_matches_its_base(self):
        self.feature_repo()
        self.assertTrue(ANSI.sub("", self.first_line()).endswith(" | repo (feature)"))

    def test_branch_diff_is_hidden_outside_a_git_repo(self):
        self.assertTrue(ANSI.sub("", self.first_line()).endswith(" | repo"))

    def test_branch_diff_falls_back_to_local_main_then_master(self):
        for default in ("main", "master"):
            with self.subTest(default=default):
                self.setUp()
                self.feature_repo(default=default, remote=False)
                (self.repo / "a.txt").write_text("one\n")
                self.assertTrue(ANSI.sub("", self.first_line()).endswith(" | repo (feature +0 \u22122)"))

    def test_branch_diff_falls_back_to_local_main_when_origin_head_is_stale(self):
        self.feature_repo()
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
        (self.repo / "a.txt").write_text("one\n")
        line = ANSI.sub("", self.first_line())
        self.assertTrue(line.endswith(" | repo (feature +0 \u22122)"), line)

    def test_branch_diff_shortens_large_counts(self):
        self.feature_repo()
        (self.repo / "big.txt").write_text("x\n" * 1234)
        self.commit_all()
        (self.repo / "huge.txt").write_text("y\n" * 56789)
        (self.repo / "a.txt").write_text("")
        self.assertTrue(ANSI.sub("", self.first_line()).endswith("(feature +58k \u22123)"))
        self.git("add", "-A")
        self.git("reset", "-q", "--hard")
        self.assertTrue(ANSI.sub("", self.first_line()).endswith("(feature +1.2k \u22120)"))

    def test_branch_diff_shortens_at_each_boundary(self):
        self.feature_repo()
        (self.repo / "a.txt").write_text("")
        cases = [(999, "+999"), (1000, "+1k"), (9949, "+9.9k"), (9950, "+10k"), (1_300_000, "+1.3M")]
        for lines, label in cases:
            with self.subTest(lines=lines):
                (self.repo / "new.txt").write_text("x\n" * lines)
                line = ANSI.sub("", self.first_line())
                self.assertTrue(line.endswith(f"(feature {label} \u22123)"), line)

    def test_token_label_shortens_used_and_window_size(self):
        cases = [
            ((42000, 200000), "42k/200k"),
            ((1500, 1500), "2k/2k"),
            ((999400, 1000000), "999k/1.0M"),
            ((999500, 2000000), "1.0M/2.0M"),
            ((400, 0), "0/0"),
        ]
        for (used, size), label in cases:
            with self.subTest(used=used, size=size):
                window = {"total_input_tokens": used, "context_window_size": size}
                line = ANSI.sub("", self.first_line(context_window=window))
                self.assertIn(f" {label} (0%) | ", line)

    def test_branch_diff_counts_untracked_files_in_a_linked_worktree(self):
        self.feature_repo()
        self.git("checkout", "-q", "main")
        tree = self.tmp / "tree"
        self.git("worktree", "add", "-q", "-b", "other", str(tree))
        (tree / "new.txt").write_text("1\n2\n")
        line = ANSI.sub("", self.first_line(cwd=tree))
        self.assertTrue(line.endswith(" | tree (other +2 \u22120)"), line)
        self.assertEqual(self.git("status", "--porcelain", cwd=tree), "?? new.txt\n")

    def test_branch_diff_covers_the_whole_repo_from_a_subdirectory(self):
        self.feature_repo()
        (self.repo / "sub").mkdir()
        (self.repo / "sub" / "s.txt").write_text("s\n")
        (self.repo / "top.txt").write_text("t\n")
        line = ANSI.sub("", self.first_line(cwd=self.repo / "sub"))
        self.assertTrue(line.endswith(" | sub (feature +2 \u22120)"), line)

    def test_closed_issue_shows_as_chip_after_its_pr(self):
        line = self.render("main", [pr(96, closes=[48])])
        self.assertIn(f"{CHIP}\x1b]8;;{REPO_URL}/issues/48\x1b\\ 48 ", line)
        self.assertEqual(ANSI.sub("", line), "#96  48  | PRs ✓1")

    def test_pr_that_closes_nothing_shows_a_dim_empty_set(self):
        line = self.render("main", [pr(97), pr(96, closes=[46, 49])])
        self.assertIn("\x1b[2m∅\x1b[0m", line)
        self.assertEqual(ANSI.sub("", line), "#97 ∅ #96  46   49  | PRs ✓2")

    def test_current_branch_pr_is_bracketed(self):
        line = self.render("ticket-48-trim", [pr(97), pr(96, closes=[48], branch="ticket-48-trim")])
        self.assertIn("\x1b[1m[\x1b[0m", line)
        self.assertEqual(ANSI.sub("", line), "#97 ∅ [#96  48 ] | PRs ✓2")

    def test_current_branch_pr_shows_past_the_list_limit(self):
        prs = [pr(n) for n in range(99, 93, -1)] + [pr(90, closes=[12], branch="mine")]
        line = self.render("mine", prs)
        self.assertEqual(
            ANSI.sub("", line), "#99 ∅ #98 ∅ #97 ∅ #96 ∅ #95 ∅ [#90  12 ] +1 | PRs ✓7"
        )

    def test_branch_without_pr_shows_issue_from_its_name(self):
        line = self.render("ticket-51-profile", [pr(97)])
        self.assertIn(f"{CHIP}\x1b]8;;{REPO_URL}/issues/51\x1b\\ 51 ", line)
        self.assertEqual(ANSI.sub("", line), "on  51  (no PR) | #97 ∅ | PRs ✓1")

    def test_branch_issue_shows_when_repo_has_no_prs(self):
        line = self.render("me/ticket-51-profile", [])
        self.assertEqual(ANSI.sub("", line), "on  51  (no PR)")

    def test_number_later_in_branch_name_is_not_an_issue(self):
        for branch in ("release-2026", "fix-2fa-login", "bump-node-20", "release/2026", "feature/2026-q1"):
            with self.subTest(branch=branch):
                self.setUp()
                self.assertEqual(ANSI.sub("", self.render(branch, [pr(97)])), "#97 ∅ | PRs ✓1")

    def test_fork_pr_from_a_same_named_branch_is_not_the_current_pr(self):
        line = self.render("main", [pr(97, closes=[5], branch="main", fork=True)])
        self.assertEqual(ANSI.sub("", line), "#97  5  | PRs ✓1")


    def test_counts_past_the_stale_age_show_how_old_they_are(self):
        line = self.render("main", [pr(97)], cache_age=5 * 60 + 10)
        self.assertIn("\x1b[2m(5m old)\x1b[0m", line)
        self.assertEqual(ANSI.sub("", line), "#97 ∅ | PRs ✓1 (5m old)")

    def test_old_counts_show_hours(self):
        line = self.render("main", [pr(97)], cache_age=3 * 3600 + 60)
        self.assertEqual(ANSI.sub("", line), "#97 ∅ | PRs ✓1 (3h old)")

    def test_recent_counts_show_no_age(self):
        line = self.render("main", [pr(97)], cache_age=90)
        self.assertEqual(ANSI.sub("", line), "#97 ∅ | PRs ✓1")

    def test_age_shows_when_old_cache_has_no_prs(self):
        line = self.render("main", [], cache_age=600)
        self.assertEqual(ANSI.sub("", line), "PRs (10m old)")

    def test_due_refresh_replaces_the_cache(self):
        self.gh.write_text(f"#!/bin/sh\nprintf '%s' '{json.dumps([pr(98)])}'\n")
        self.render("main", [pr(97)], cache_age=600, stamp=False)
        for _ in range(50):
            if json.loads(self.cache.read_text() or "[]") == [pr(98)]:
                break
            time.sleep(0.1)
        self.assertEqual(json.loads(self.cache.read_text()), [pr(98)])

    def test_failed_refresh_keeps_the_cache_and_its_age(self):
        self.render("main", [pr(97)], cache_age=600, stamp=False)
        for _ in range(50):
            if not (self.cache_dir / f"{self.cache.stem}.lock").exists():
                break
            time.sleep(0.1)
        self.assertEqual(json.loads(self.cache.read_text()), [pr(97)])
        self.assertGreaterEqual(time.time() - self.cache.stat().st_mtime, 600)


if __name__ == "__main__":
    unittest.main()
