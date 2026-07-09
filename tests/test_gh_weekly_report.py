"""Tests for skills/gh-weekly-report/scripts/{collect,render}.py.

Standard library only. Run from the repo root:

    python3 -m unittest discover -s tests -v

Nothing here ever talks to GitHub: every gh CLI call goes through
collect.run_gh, which the tests replace with a canned dispatcher. The
week.json shape is asserted deliberately: the agent and render.py parse
it, so it is an interface, not an implementation detail.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "gh-weekly-report" / "scripts"))

import collect  # noqa: E402
import render  # noqa: E402

TEMPLATE = (REPO_ROOT / "skills" / "gh-weekly-report" / "references"
            / "template.html")


class TestComputeWindow(unittest.TestCase):
    """Last complete Mon-Sun week, UTC, never the week in progress."""

    def test_midweek_returns_previous_monday_to_sunday(self):
        # Wed 2026-07-08 → last complete week is Mon Jun 29 .. Sun Jul 5.
        start, end = collect.compute_window(date(2026, 7, 8))
        self.assertEqual(start, date(2026, 6, 29))
        self.assertEqual(end, date(2026, 7, 5))

    def test_monday_returns_week_that_ended_yesterday(self):
        start, end = collect.compute_window(date(2026, 7, 6))
        self.assertEqual(start, date(2026, 6, 29))
        self.assertEqual(end, date(2026, 7, 5))

    def test_sunday_still_excludes_week_in_progress(self):
        # Sunday isn't over: the current week is not yet complete.
        start, end = collect.compute_window(date(2026, 7, 5))
        self.assertEqual(start, date(2026, 6, 22))
        self.assertEqual(end, date(2026, 6, 28))


class TestWindowDerivations(unittest.TestCase):
    def test_previous_window_shifts_back_seven_days(self):
        start, end = collect.previous_window(date(2026, 6, 29), date(2026, 7, 5))
        self.assertEqual(start, date(2026, 6, 22))
        self.assertEqual(end, date(2026, 6, 28))

    def test_iso_week_slug_uses_iso_year(self):
        self.assertEqual(collect.iso_week_slug(date(2026, 6, 29)), "2026-W27")
        # ISO year differs from calendar year at the boundary.
        self.assertEqual(collect.iso_week_slug(date(2025, 12, 29)), "2026-W01")


class TestParseRange(unittest.TestCase):
    """--from/--to override: both or neither, from <= to."""

    def test_explicit_range_is_honoured(self):
        start, end = collect.parse_range("2026-06-29", "2026-07-05")
        self.assertEqual((start, end), (date(2026, 6, 29), date(2026, 7, 5)))

    def test_one_sided_range_is_rejected(self):
        with self.assertRaises(SystemExit):
            collect.parse_range("2026-06-29", None)
        with self.assertRaises(SystemExit):
            collect.parse_range(None, "2026-07-05")

    def test_inverted_range_is_rejected(self):
        with self.assertRaises(SystemExit):
            collect.parse_range("2026-07-05", "2026-06-29")


def issue(number, closed_by, state_reason):
    return {
        "key": f"acme/data#{number}",
        "title": f"issue {number}",
        "closed_by": closed_by,
        "state_reason": state_reason,
    }


class TestSplitClosedIssues(unittest.TestCase):
    """Resolved = closed by the actor with reason `completed`; not-planned
    closes by the actor are a separate line; other people's closes vanish."""

    def test_actor_completed_close_is_resolved(self):
        resolved, not_planned = collect.split_closed_issues(
            [issue(1, "alice", "completed")], "alice"
        )
        self.assertEqual([i["key"] for i in resolved], ["acme/data#1"])
        self.assertEqual(not_planned, [])

    def test_actor_not_planned_close_is_separate(self):
        resolved, not_planned = collect.split_closed_issues(
            [issue(2, "alice", "not_planned")], "alice"
        )
        self.assertEqual(resolved, [])
        self.assertEqual([i["key"] for i in not_planned], ["acme/data#2"])

    def test_close_by_someone_else_is_dropped(self):
        resolved, not_planned = collect.split_closed_issues(
            [issue(3, "bob", "completed")], "alice"
        )
        self.assertEqual((resolved, not_planned), ([], []))

    def test_missing_state_reason_counts_as_resolved(self):
        # Issues closed via the API can carry no reason; a close is a close.
        resolved, _ = collect.split_closed_issues([issue(4, "alice", None)], "alice")
        self.assertEqual([i["key"] for i in resolved], ["acme/data#4"])


class TestAbandonedPrs(unittest.TestCase):
    def test_closed_prs_minus_merged_set(self):
        closed = [{"key": "acme/data#7"}, {"key": "acme/data#8"}]
        abandoned = collect.abandoned_prs(closed, merged_keys={"acme/data#7"})
        self.assertEqual([p["key"] for p in abandoned], ["acme/data#8"])


class TestReviewsInWindow(unittest.TestCase):
    """A review counts when the actor submitted it inside the window on
    someone else's PR."""

    WINDOW = (date(2026, 6, 29), date(2026, 7, 5))

    def review(self, user, submitted_at):
        return {"user": {"login": user}, "submitted_at": submitted_at, "state": "APPROVED"}

    def test_actor_review_inside_window_counts(self):
        kept = collect.reviews_in_window(
            [self.review("alice", "2026-07-01T10:00:00Z")], "alice", *self.WINDOW
        )
        self.assertEqual(len(kept), 1)

    def test_review_outside_window_or_by_other_user_is_dropped(self):
        kept = collect.reviews_in_window(
            [
                self.review("alice", "2026-06-28T23:59:59Z"),  # before
                self.review("alice", "2026-07-06T00:00:00Z"),  # after
                self.review("bob", "2026-07-01T10:00:00Z"),  # not the actor
            ],
            "alice",
            *self.WINDOW,
        )
        self.assertEqual(kept, [])

    def test_window_edges_are_inclusive(self):
        kept = collect.reviews_in_window(
            [
                self.review("alice", "2026-06-29T00:00:00Z"),
                self.review("alice", "2026-07-05T23:59:59Z"),
            ],
            "alice",
            *self.WINDOW,
        )
        self.assertEqual(len(kept), 2)


class TestAttributeCommits(unittest.TestCase):
    def test_commit_with_associated_pr_carries_pr_key(self):
        commits = [{"key": "abc123", "title": "feat: x"}]
        out = collect.attribute_commits(commits, {"abc123": "acme/data#9"})
        self.assertEqual(out[0]["pr"], "acme/data#9")
        self.assertFalse(out[0]["direct_push"])

    def test_commit_without_pr_is_a_direct_push(self):
        out = collect.attribute_commits([{"key": "def456", "title": "fix y"}], {})
        self.assertIsNone(out[0]["pr"])
        self.assertTrue(out[0]["direct_push"])


class TestClassifySignal(unittest.TestCase):
    """Conventional-commit prefixes become bucket hints; the agent makes
    the final call, so anything unrecognised is honestly None."""

    def test_known_prefixes_map_to_taxonomy(self):
        for title, bucket in [
            ("feat: add drill-down", "feature"),
            ("fix(collect): off-by-one window", "fix"),
            ("refactor: extract seam", "refactor"),
            ("docs: clarify scope", "docs"),
            ("chore: bump deps", "chore/infra"),
            ("ci: cache gh calls", "chore/infra"),
            ("build: pin python", "chore/infra"),
            ("test: pin window edges", "chore/infra"),
        ]:
            self.assertEqual(collect.classify_signal(title), bucket, title)

    def test_unrecognised_title_yields_none(self):
        self.assertIsNone(collect.classify_signal("Update README"))
        self.assertIsNone(collect.classify_signal("feature without colon"))


class TestRunGhRetry(unittest.TestCase):
    """run_gh retries a failed gh invocation once before raising; a
    rate-limited failure waits 60 s first (GitHub search allows 30
    req/min and one collect run makes ~14 search calls)."""

    @staticmethod
    def _completed(code, stdout="", stderr=""):
        return subprocess.CompletedProcess(
            args=["gh"], returncode=code, stdout=stdout, stderr=stderr)

    def _run(self, outcomes):
        """Run run_gh against canned outcomes; return (result, run, sleep)
        where result is the output or the raised RuntimeError."""
        with mock.patch.object(collect.time, "sleep") as sleep, \
                mock.patch.object(collect.subprocess, "run",
                                  side_effect=outcomes) as run:
            try:
                result = collect.run_gh(["api", "user"])
            except RuntimeError as exc:
                result = exc
        return result, run, sleep

    def test_success_does_not_retry(self):
        result, run, sleep = self._run([self._completed(0, stdout="ok")])
        self.assertEqual(result, "ok")
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_failure_then_success_returns_output(self):
        result, run, sleep = self._run([self._completed(1, stderr="flake"),
                                        self._completed(0, stdout="ok")])
        self.assertEqual(result, "ok")
        self.assertEqual(run.call_count, 2)
        sleep.assert_not_called()

    def test_two_failures_raise(self):
        result, run, _ = self._run([self._completed(1, stderr="down"),
                                    self._completed(1, stderr="down")])
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(run.call_count, 2)

    def test_rate_limited_failure_sleeps_60s_before_retry(self):
        result, run, sleep = self._run(
            [self._completed(1, stderr="HTTP 403: API rate limit exceeded"),
             self._completed(0, stdout="ok")])
        self.assertEqual(result, "ok")
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(60)

    def test_rate_limit_wording_without_403_also_sleeps(self):
        result, _, sleep = self._run(
            [self._completed(1, stderr="You have exceeded a secondary Rate Limit"),
             self._completed(0, stdout="ok")])
        self.assertEqual(result, "ok")
        sleep.assert_called_once_with(60)

    def test_rate_limited_retry_still_raises_after_second_failure(self):
        result, run, sleep = self._run(
            [self._completed(1, stderr="HTTP 403: rate limit"),
             self._completed(1, stderr="HTTP 403: rate limit")])
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(60)


@contextlib.contextmanager
def recorded_gh(response="[]"):
    """Patch collect.run_gh with a recorder; yields the list of gh arg
    lists. `response` is a canned string or a callable dispatching on
    the gh args (e.g. fake_run_gh)."""
    calls = []

    def recorder(gh_args):
        calls.append(gh_args)
        return response(gh_args) if callable(response) else response

    with mock.patch.object(collect, "run_gh", side_effect=recorder):
        yield calls


class TestSearchArgs(unittest.TestCase):
    """Owner is an optional narrowing filter: present means an --owner
    flag on the search, absent means no owner scoping at all."""

    def _search_args(self, owner):
        with recorded_gh() as calls:
            collect.search("issues", ["--author", "alice"], owner)
        (args,) = calls
        return args

    def test_owner_present_adds_owner_flag(self):
        args = self._search_args("acme")
        self.assertEqual(args[args.index("--owner") + 1], "acme")

    def test_owner_absent_omits_owner_flag(self):
        self.assertNotIn("--owner", self._search_args(None))

    def test_search_limit_is_1000(self):
        self.assertEqual(collect.SEARCH_LIMIT, 1000)
        args = self._search_args(None)
        self.assertEqual(args[args.index("--limit") + 1], "1000")

    def test_cap_warning_when_results_hit_limit(self):
        raw = json.dumps([{"number": i, "title": "t", "url": "u",
                           "repository": {"nameWithOwner": "acme/data"},
                           "labels": []} for i in range(collect.SEARCH_LIMIT)])
        stderr = io.StringIO()
        with mock.patch.object(collect, "run_gh", return_value=raw), \
                contextlib.redirect_stderr(stderr):
            collect.search("issues", [], "acme")
        self.assertIn("cap", stderr.getvalue())


CUR = "2026-06-29..2026-07-05"


def fake_run_gh(args):
    """Canned gh CLI: current week has one of everything, previous week is
    empty. Dispatches on the public gh syntax collect.py emits."""
    joined = " ".join(args)

    def only_current(payload):
        return json.dumps(payload if CUR in joined else [])

    if args[:2] == ["search", "issues"] and "--commenter" in joined:
        # Discussion candidates: #10 is someone else's thread alice
        # commented on; #11 is alice's own (must be excluded before any
        # comments API call, or the dispatcher raises on it).
        return json.dumps([
            {"number": 10, "title": "design debate",
             "url": "https://github.com/acme/tools/issues/10",
             "repository": {"nameWithOwner": "acme/tools"},
             "labels": [], "author": {"login": "bob"}, "state": "open",
             "createdAt": "2026-06-01T00:00:00Z"},
            {"number": 11, "title": "alice's own thread",
             "url": "https://github.com/acme/tools/issues/11",
             "repository": {"nameWithOwner": "acme/tools"},
             "labels": [], "author": {"login": "alice"}, "state": "open",
             "createdAt": "2026-06-01T00:00:00Z"},
        ])
    if args[:2] == ["search", "prs"] and "--commenter" in joined:
        return "[]"
    if joined.startswith("api repos/acme/tools/issues/10/comments"):
        # gh api --paginate emits each page's JSON array back to back
        # (not one valid document); the fake reproduces that shape.
        return json.dumps([
            {"user": {"login": "alice"}, "created_at": "2026-07-01T09:00:00Z"},
            {"user": {"login": "alice"}, "created_at": "2026-06-10T08:00:00Z"},
        ]) + "\n" + json.dumps([
            {"user": {"login": "bob"}, "created_at": "2026-07-01T11:00:00Z"},
        ])
    if args[:2] == ["search", "issues"] and "--author" in joined:
        return only_current([{
            "number": 1, "title": "feat: new thing",
            "url": "https://github.com/acme/data/issues/1",
            "repository": {"nameWithOwner": "acme/data"},
            "labels": [{"name": "enhancement"}],
            "createdAt": "2026-06-30T09:00:00Z", "state": "open",
        }])
    if args[:2] == ["search", "issues"] and "--involves" in joined:
        # Closed candidates: search has no closed-by qualifier, so
        # collect must cast the --involves net and filter by closer.
        return only_current([
            {"number": 3, "title": "fix: broken join",
             "url": "https://github.com/acme/data/issues/3",
             "repository": {"nameWithOwner": "acme/data"},
             "labels": [], "closedAt": "2026-07-02T12:00:00Z", "state": "closed"},
            {"number": 4, "title": "someone else's close",
             "url": "https://github.com/acme/data/issues/4",
             "repository": {"nameWithOwner": "acme/data"},
             "labels": [], "closedAt": "2026-07-03T12:00:00Z", "state": "closed"},
        ])
    if joined.startswith("api repos/acme/data/issues/3"):
        return json.dumps({"closed_by": {"login": "alice"}, "state_reason": "completed"})
    if joined.startswith("api repos/acme/data/issues/4"):
        return json.dumps({"closed_by": {"login": "bob"}, "state_reason": "completed"})
    if args[:2] == ["search", "prs"] and "--reviewed-by" in joined:
        # Returned for both periods: reviews_in_window must keep the
        # 2026-07-01 review out of the previous week on its own.
        return json.dumps([{
            "number": 5, "title": "bob's PR",
            "url": "https://github.com/acme/tools/pull/5",
            "repository": {"nameWithOwner": "acme/tools"},
            "labels": [], "author": {"login": "bob"}, "state": "open",
        }])
    if args[:2] == ["search", "prs"] and "--merged-at" in joined:
        return only_current([_pr(7, "feat: drill-down")])
    if args[:2] == ["search", "prs"] and "--closed" in joined:
        return only_current([_pr(7, "feat: drill-down"), _pr(8, "abandoned idea")])
    if args[:2] == ["search", "prs"] and "--created" in joined:
        return only_current([_pr(7, "feat: drill-down")])
    if joined.startswith("api repos/acme/tools/pulls/5/reviews"):
        return json.dumps([{"user": {"login": "alice"},
                            "submitted_at": "2026-07-01T10:00:00Z",
                            "state": "APPROVED"}])
    if args[:2] == ["search", "commits"]:
        # Author date deliberately differs from committer date: the window
        # and committed_at must follow the committer date (a squash merge
        # carries the merge moment there).
        return only_current([{
            "sha": "abc123",
            "url": "https://github.com/acme/data/commit/abc123",
            "repository": {"fullName": "acme/data"},
            "commit": {"message": "feat: new thing\n\nlong body",
                       "author": {"date": "2026-06-30T23:00:00Z"},
                       "committer": {"date": "2026-07-01T10:00:00Z"}},
        }])
    if joined.startswith("api repos/acme/data/commits/abc123/pulls"):
        return json.dumps([{"number": 7,
                            "base": {"repo": {"full_name": "acme/data"}}}])
    raise AssertionError(f"unexpected gh call: {joined}")


def _pr(number, title):
    return {"number": number, "title": title,
            "url": f"https://github.com/acme/data/pull/{number}",
            "repository": {"nameWithOwner": "acme/data"},
            "labels": [], "author": {"login": "alice"}, "state": "closed"}


class TestFetchCommitsSearch(unittest.TestCase):
    """Commits come from gh search commits windowed on committer date,
    not from enumerating an owner's repos."""

    WINDOW = (date(2026, 6, 29), date(2026, 7, 5))

    def _search_args(self, owner):
        with recorded_gh() as calls:
            collect.fetch_commits(owner, "alice", *self.WINDOW, attribute=False)
        (args,) = calls
        return args

    def test_windows_on_committer_date(self):
        args = self._search_args(owner=None)
        self.assertEqual(args[:2], ["search", "commits"])
        self.assertEqual(args[args.index("--author") + 1], "alice")
        self.assertEqual(args[args.index("--committer-date") + 1],
                         "2026-06-29..2026-07-05")

    def test_owner_flag_only_when_filtering(self):
        self.assertNotIn("--owner", self._search_args(owner=None))
        args = self._search_args(owner="acme")
        self.assertEqual(args[args.index("--owner") + 1], "acme")

    def test_normalises_and_attributes_from_search_payload(self):
        with mock.patch.object(collect, "run_gh", side_effect=fake_run_gh):
            (commit,) = collect.fetch_commits("acme", "alice", *self.WINDOW,
                                              attribute=True)
        self.assertEqual(commit["key"], "abc123")
        self.assertEqual(commit["repo"], "acme/data")
        self.assertEqual(commit["title"], "feat: new thing")
        # Committer date, not author date: squash merges carry the merge
        # moment as committer date.
        self.assertEqual(commit["committed_at"], "2026-07-01T10:00:00Z")
        self.assertEqual(commit["signal"], "feature")
        self.assertEqual(commit["pr"], "acme/data#7")
        self.assertFalse(commit["direct_push"])

    def test_no_attribution_calls_when_not_requested(self):
        with recorded_gh(fake_run_gh) as calls:
            commits = collect.fetch_commits("acme", "alice", *self.WINDOW,
                                            attribute=False)
        self.assertEqual([a for a in calls if a[0] == "api"], [])
        self.assertTrue(commits)
        self.assertNotIn("pr", commits[0])


class TestWeekJsonContract(unittest.TestCase):
    """week.json is the interface the agent and render.py parse."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(collect, "run_gh", side_effect=fake_run_gh), \
                contextlib.redirect_stdout(io.StringIO()):
            collect.main([
                "--owner", "acme", "--actor", "alice",
                "--from", "2026-06-29", "--to", "2026-07-05",
                "--out", cls.tmp.name,
            ])
        cls.week = json.loads((Path(cls.tmp.name) / "week.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_top_level_shape(self):
        self.assertEqual(self.week["actor"], "alice")
        self.assertEqual(self.week["owner"], "acme")
        self.assertEqual(self.week["window"],
                         {"from": "2026-06-29", "to": "2026-07-05",
                          "iso_week": "2026-W27"})
        self.assertIn("previous_window", self.week)
        for period in ("current", "previous"):
            self.assertEqual(
                set(self.week[period]),
                {"issues_created", "issues_resolved", "issues_not_planned",
                 "prs_created", "prs_merged", "prs_abandoned",
                 "reviews_given", "commits", "discussions"},
            )

    def test_current_period_applies_the_metric_rules(self):
        cur = self.week["current"]
        self.assertEqual([i["key"] for i in cur["issues_created"]], ["acme/data#1"])
        self.assertEqual([i["key"] for i in cur["issues_resolved"]], ["acme/data#3"])
        self.assertEqual(cur["issues_not_planned"], [])
        self.assertEqual([p["key"] for p in cur["prs_merged"]], ["acme/data#7"])
        self.assertEqual([p["key"] for p in cur["prs_abandoned"]], ["acme/data#8"])
        self.assertEqual([r["key"] for r in cur["reviews_given"]], ["acme/tools#5"])
        self.assertEqual([d["key"] for d in cur["discussions"]], ["acme/tools#10"])

    def test_items_carry_drilldown_fields_and_signal(self):
        item = self.week["current"]["issues_created"][0]
        for field in ("key", "repo", "number", "title", "url", "labels", "signal"):
            self.assertIn(field, item)
        self.assertEqual(item["signal"], "feature")

    def test_commits_are_attributed(self):
        commit = self.week["current"]["commits"][0]
        self.assertEqual(commit["key"], "abc123")
        self.assertEqual(commit["repo"], "acme/data")
        self.assertEqual(commit["title"], "feat: new thing")
        self.assertEqual(commit["pr"], "acme/data#7")
        self.assertFalse(commit["direct_push"])

    def test_discussion_items_carry_the_pinned_shape(self):
        # The render ticket depends on this exact contract: every
        # norm_item field plus commented_at and comments.
        (item,) = self.week["current"]["discussions"]
        self.assertEqual(
            set(item),
            {"key", "repo", "number", "title", "url", "labels", "author",
             "created_at", "closed_at", "signal", "commented_at", "comments"},
        )
        self.assertEqual(item["commented_at"], "2026-07-01T09:00:00Z")
        self.assertEqual(item["comments"], 1)

    def test_previous_period_is_empty(self):
        self.assertTrue(all(v == [] for v in self.week["previous"].values()))


class TestFetchDiscussions(unittest.TestCase):
    """Discussions = items the actor commented on but did not author,
    window-checked against the actor's own comment timestamps."""

    def _fetch(self, start, end):
        with mock.patch.object(collect, "run_gh", side_effect=fake_run_gh):
            return collect.fetch_discussions("acme", "alice", start, end)

    def test_keeps_commented_item_authored_by_someone_else(self):
        items = self._fetch(date(2026, 6, 29), date(2026, 7, 5))
        self.assertEqual([i["key"] for i in items], ["acme/tools#10"])

    def test_first_in_window_comment_time_and_count(self):
        (item,) = self._fetch(date(2026, 6, 29), date(2026, 7, 5))
        # Only the 2026-07-01 alice comment is in window; bob's comment
        # and alice's 2026-06-10 comment must not count.
        self.assertEqual(item["commented_at"], "2026-07-01T09:00:00Z")
        self.assertEqual(item["comments"], 1)

    def test_authored_items_are_excluded_before_the_comments_api(self):
        # fake_run_gh has no comments branch for #11 (alice's own thread)
        # and raises on unexpected calls, so reaching the API for it
        # would fail loudly. The result must not contain it either.
        items = self._fetch(date(2026, 6, 29), date(2026, 7, 5))
        self.assertNotIn("acme/tools#11", [i["key"] for i in items])

    def test_item_with_no_in_window_comments_is_dropped(self):
        self.assertEqual(self._fetch(date(2026, 6, 22), date(2026, 6, 28)), [])

    def test_comments_check_paginates_at_100_per_page(self):
        # REST default is 30/page; without --paginate a busy thread
        # silently undercounts the actor's in-window comments.
        with recorded_gh(fake_run_gh) as calls:
            collect.fetch_discussions("acme", "alice",
                                      date(2026, 6, 29), date(2026, 7, 5))
        comment_calls = [c for c in calls
                         if c[0] == "api" and "/comments" in c[1]]
        self.assertTrue(comment_calls)
        for args in comment_calls:
            self.assertIn("--paginate", args)
            self.assertIn("per_page=100", args[1])

    def test_multi_page_comment_payload_counts_all_pages(self):
        # fake_run_gh returns the comments as two concatenated JSON
        # arrays, the shape gh api --paginate actually emits; alice's
        # in-window comment sits on page one, bob's on page two, and
        # both pages must be read for the counts to be right.
        (item,) = self._fetch(date(2026, 6, 29), date(2026, 7, 5))
        self.assertEqual(item["comments"], 1)


class TestParseConcatenatedJson(unittest.TestCase):
    """gh api --paginate emits one JSON array per page, back to back;
    the parser must flatten them into a single list."""

    def test_single_page_is_a_plain_array(self):
        self.assertEqual(collect.parse_concatenated_json('[{"a": 1}]'),
                         [{"a": 1}])

    def test_multiple_pages_are_flattened(self):
        out = '[{"a": 1}, {"a": 2}]\n[{"a": 3}]'
        self.assertEqual(collect.parse_concatenated_json(out),
                         [{"a": 1}, {"a": 2}, {"a": 3}])

    def test_empty_output_is_an_empty_list(self):
        self.assertEqual(collect.parse_concatenated_json(""), [])
        self.assertEqual(collect.parse_concatenated_json("  \n"), [])


class TestOwnerlessEmptyWeek(unittest.TestCase):
    """No --owner: nothing is derived from the invoking repo (a gh repo
    view call would trip the dispatcher's unexpected-call assertion),
    week.json carries owner null, and an empty week is still a valid
    all-empty payload."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(collect, "run_gh", side_effect=fake_run_gh), \
                contextlib.redirect_stdout(io.StringIO()):
            collect.main([
                "--actor", "alice",
                "--from", "2026-06-22", "--to", "2026-06-28",
                "--out", cls.tmp.name,
            ])
        cls.week = json.loads((Path(cls.tmp.name) / "week.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_owner_is_null_when_no_filter_given(self):
        self.assertIsNone(self.week["owner"])

    def test_all_components_empty_in_both_periods(self):
        for period in ("current", "previous"):
            self.assertEqual(
                [k for k, v in self.week[period].items() if v != []], [],
                period)


def tiny_week():
    return {
        "current": {
            "prs_merged": [{"key": "acme/data#7", "repo": "acme/data",
                            "title": "feat: x"}],
            "commits": [{"key": "abc123", "repo": "acme/data",
                         "title": "tweak"}],
        },
        "previous": {
            "prs_merged": [{"key": "acme/data#2", "repo": "acme/data",
                            "title": "old"}],
        },
    }


class TestMergeBuckets(unittest.TestCase):
    def test_mapping_applied_and_unmapped_defaults_to_other(self):
        week = render.merge_buckets(tiny_week(), {"acme/data#7": "feature"})
        self.assertEqual(week["current"]["prs_merged"][0]["bucket"], "feature")
        self.assertEqual(week["current"]["commits"][0]["bucket"], "other")

    def test_previous_period_is_left_alone(self):
        week = render.merge_buckets(tiny_week(), {})
        self.assertNotIn("bucket", week["previous"]["prs_merged"][0])

    def test_bucket_outside_taxonomy_is_rejected(self):
        with self.assertRaises(SystemExit):
            render.merge_buckets(tiny_week(), {"acme/data#7": "misc"})


class TestMergeNarratives(unittest.TestCase):
    """narratives.json ({repo full name: text}) is merged into the payload
    verbatim under `narratives`; a key naming a repo with no activity in the
    data is an authoring slip, so it warns on stderr but never fails."""

    def test_narratives_land_in_payload(self):
        week = render.merge_narratives(
            tiny_week(), {"acme/data": "Shipped the drill-down."}
        )
        self.assertEqual(week["narratives"],
                         {"acme/data": "Shipped the drill-down."})

    def test_absent_narratives_yield_empty_object(self):
        week = render.merge_narratives(tiny_week(), {})
        self.assertEqual(week["narratives"], {})

    def test_known_repo_key_does_not_warn(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            render.merge_narratives(tiny_week(), {"acme/data": "text"})
        self.assertEqual(stderr.getvalue(), "")

    def test_unknown_repo_key_warns_on_stderr(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            week = render.merge_narratives(tiny_week(), {"acme/ghost": "?"})
        self.assertIn("acme/ghost", stderr.getvalue())
        # Warned, not dropped: the payload stays a verbatim copy.
        self.assertIn("acme/ghost", week["narratives"])


class TestRenderMainNarratives(unittest.TestCase):
    """--narratives is optional end to end: with it the text reaches the
    report; without it the payload still carries an empty `narratives`."""

    def render_main(self, narratives=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "week.json").write_text(json.dumps(tiny_week()))
            (root / "buckets.json").write_text(
                json.dumps({"acme/data#7": "feature"})
            )
            out = root / "report.html"
            argv = ["--data", str(root / "week.json"),
                    "--buckets", str(root / "buckets.json"),
                    "--out", str(out)]
            if narratives is not None:
                (root / "narratives.json").write_text(json.dumps(narratives))
                argv += ["--narratives", str(root / "narratives.json")]
            with contextlib.redirect_stdout(io.StringIO()):
                render.main(argv)
            return out.read_text()

    def test_narrative_text_reaches_the_report(self):
        html = self.render_main({"acme/data": "Landed the drill-down."})
        self.assertIn("Landed the drill-down.", html)

    def test_flag_is_optional_and_defaults_to_empty(self):
        html = self.render_main()
        self.assertIn('"narratives": {}', html)


class TestInject(unittest.TestCase):
    def test_data_lands_at_the_marker(self):
        html = render.inject("<script id=\"report-data\" "
                             "type=\"application/json\">__REPORT_DATA__</script>",
                             {"a": 1})
        self.assertIn('{"a": 1}', html)
        self.assertNotIn("__REPORT_DATA__", html)

    def test_script_closing_tag_in_data_cannot_break_out(self):
        html = render.inject("__REPORT_DATA__", {"title": "bad </script> title"})
        self.assertNotIn("</script>", html)


class TestTemplate(unittest.TestCase):
    """String-level assertions on the template source: no browser, so the
    contract is pinned where it lives, in the markup and inline script."""

    def setUp(self):
        self.text = TEMPLATE.read_text()

    def test_has_exactly_one_data_marker(self):
        self.assertEqual(self.text.count("__REPORT_DATA__"), 1)
        self.assertIn('id="report-data"', self.text)

    def test_loads_tailwind_and_chartjs_from_cdn(self):
        self.assertIn("cdn.tailwindcss.com", self.text)
        self.assertIn("cdn.jsdelivr.net/npm/chart.js", self.text)

    def test_degrades_without_the_chartjs_cdn(self):
        # All data is embedded; chart code must be guarded so the page
        # still renders its content when the CDN is unreachable.
        self.assertIn('typeof Chart === "undefined"', self.text)

    def test_discussions_counter_is_a_headline_metric(self):
        self.assertIn('["discussions", "Discussions"]', self.text)

    def test_narratives_are_read_from_the_payload(self):
        self.assertIn("DATA.narratives", self.text)

    def test_owner_wording_only_when_payload_has_an_owner(self):
        # The header keys on the actor; owner is an optional filter note.
        owner_lines = [line for line in self.text.splitlines()
                       if "repos owned by" in line]
        self.assertEqual(len(owner_lines), 1, owner_lines)
        self.assertIn("DATA.owner ?", owner_lines[0])

    def test_title_keys_on_actor(self):
        title_lines = [line for line in self.text.splitlines()
                       if "DATA.actor" in line]
        self.assertTrue(title_lines)
        for line in title_lines:
            self.assertNotIn("DATA.owner", line)

    def test_no_em_dash_anywhere(self):
        self.assertNotIn("\u2014", self.text)

    def test_narrative_markdown_links_are_rendered_as_anchors(self):
        # SKILL.md tells the agent to weave Markdown links into the
        # narratives; a bare textContent assignment would show literal
        # [title](url) brackets.
        self.assertIn("renderNarrative", self.text)
        self.assertIn("MD_LINK", self.text)
        self.assertNotIn("p.textContent = narrative", self.text)

    def test_narrative_renderer_never_uses_innerhtml(self):
        # The narrative is agent-authored data: DOM nodes only.
        self.assertNotIn("innerHTML", self.text)

    def test_narrative_preserves_line_structure(self):
        # The dominant-repo narrative carries a per-bucket breakdown,
        # one line per bucket; pre-line whitespace keeps those lines.
        self.assertIn("white-space: pre-line", self.text)


if __name__ == "__main__":
    unittest.main()
