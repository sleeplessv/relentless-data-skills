"""The PR description renderer and its mask, from record fixtures (render.py, mask.py).

The render tests write a branch's records folder by hand, as start, save and check will, and
compare the whole description. The mask tests hold mask.py to the run's mask measure.

    python3 -m unittest tests.test_deliver_render
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver_kit  # noqa: E402

render = deliver_kit.load("render")
mask = deliver_kit.load("mask")

SUMMARY = "```diff\n scripts/\n+└── pr.py   # pushes and opens the draft\n```\n"
PLAN = """\
| # | Requirement | Proof |
|---|---|---|
| R1 | `pr` opens a draft PR | `python3 -m unittest tests.test_deliver_pr` |
| R2 | The layout matches \\| rule 19 | `python3 -m unittest tests.test_deliver_render` |
| R3 | The README is unchanged | no check exists, meaning unchanged |

Assumptions
- A1 (R1): the stand-in gh records the body file. Tested by reading gh-calls.jsonl: held.

door: two-way, a new script and its tests; nothing deploys on merge
"""
TICKET_REQUEST = "Source: ticket #415\n\nPush the branch and open the draft PR.\nThanks @octocat, see /Users/jane/notes.\n"
CHECKS = [
    {"event": "check", "at": "t", "command": "python3 -m unittest tests.test_deliver_pr", "exit": 1,
     "commit": "1111111aaaa", "selected_nothing": False},
    {"event": "check", "at": "t", "command": "python3 -m unittest tests.test_deliver_pr", "exit": 0,
     "commit": "2222222bbbb", "selected_nothing": False},
]
TOP = """\
## Summary

```diff
 scripts/
+└── pr.py   # pushes and opens the draft
```

## Evidence

- R1: pass at 2222222
- R2: pending
- R3: no check run

## Merge Danger

**Door:** two-way. A new script and its tests; nothing deploys on merge

"""
PLAN_PART = """\
## Requirements and check plan

| # | Requirement | Proof |
|---|---|---|
| R1 | `pr` opens a draft PR | `python3 -m unittest tests.test_deliver_pr` |
| R2 | The layout matches \\| rule 19 | `python3 -m unittest tests.test_deliver_render` |
| R3 | The README is unchanged | no check exists, meaning unchanged |

Assumptions

- A1 (R1): the stand-in gh records the body file. Tested by reading gh-calls.jsonl: held.

## Findings

No review: small edit.
"""
PENDING = "**Blast Radius:** pending. `deliver.py ready` runs the small test.\n\n"


def write_records(folder: Path, request: str, summary: str = SUMMARY, plan: str = PLAN,
                  records: list[dict] = CHECKS, **more: str) -> Path:
    """A branch's records folder in the layout spec #407 fixes, written without the program."""
    folder.mkdir(parents=True, exist_ok=True)
    for kind, text in {"request": request, "summary": summary, "plan": plan, **more}.items():
        (folder / f"{kind}.md").write_text(text, encoding="utf-8")
    (folder / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return folder


class Description(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="deliver-render-")) / "records"
        self.addCleanup(shutil.rmtree, self.folder.parent, True)

    def render(self, request: str, **kwargs) -> str:
        options = {k: kwargs.pop(k) for k in ("blast", "door", "measurement") if k in kwargs}
        return render.description(write_records(self.folder, request, **kwargs), **options)

    def test_a_ticket_source_renders_the_whole_small_edit_layout_masked(self):
        self.assertEqual(self.render(TICKET_REQUEST), TOP + PENDING + f"""\
Closes #415

{render.MARKER}

## Request

Source: ticket #415 (masked: @ mentions and private paths)

> Push the branch and open the draft PR.
> Thanks [mention], see [private path]

""" + PLAN_PART)

    def test_a_conversation_source_renders_its_quote(self):
        request = "Source: conversation\n\nAdd a --json flag.\n\nKeep the old output too.\n"
        self.assertEqual(self.render(request, requirements="R1: a --json flag\n"), TOP + PENDING + f"""\
{render.MARKER}

## Request

Source: conversation

> Add a --json flag.
>
> Keep the old output too.

""" + PLAN_PART)

    def test_a_working_tree_source_has_no_quote(self):
        request = "Source: working tree, requirements written from the diff\n"
        self.assertEqual(self.render(request), TOP + PENDING + f"""\
{render.MARKER}

## Request

Source: working tree, requirements written from the diff

""" + PLAN_PART)

    def test_a_given_blast_radius_door_and_measurement_block_are_rendered(self):
        text = self.render(
            "Source: conversation\n\nFix the typo.\n", blast=("low", "12 lines; no critical path; no dependents"),
            door=("one-way", "a one-way path changed: .github/workflows/release.yml"),
            measurement={"version": "0.1.0", "path": "small edit", "door": "one-way"})
        self.assertEqual(text.split("## Merge Danger\n\n", 1)[1].split(render.MARKER)[0], """\
**Door:** one-way. A one-way path changed: .github/workflows/release.yml

**Blast Radius:** low. 12 lines; no critical path; no dependents

""")
        self.assertTrue(text.endswith("""\
No review: small edit.

<details><summary>Measurement</summary>

```text
version: 0.1.0
path: small edit
door: one-way
```

</details>
"""), text)

    def test_results_are_in_evidence_only(self):
        text = self.render(TICKET_REQUEST)
        self.assertNotIn("pass at", text.split(render.MARKER)[1])

    def test_a_plan_with_no_door_line_is_one_way(self):
        text = self.render(TICKET_REQUEST, plan=PLAN.replace("door: two-way", "Door is two-way"))
        self.assertIn("**Door:** one-way. The plan has no door line, so it counts as one-way\n", text)

    def test_a_door_line_with_another_word_is_one_way(self):
        text = self.render(TICKET_REQUEST, plan=PLAN.replace("door: two-way,", "door: probably two-way,"))
        self.assertIn("**Door:** one-way. The plan's door line says neither two-way nor one-way, so it counts as one-way\n",
                      text)

    def test_evidence_counts_only_a_pass_tied_to_a_commit_that_selected_something(self):
        rows = [render.Requirement("R1", "x", "`make test`")]
        cases = [
            ([], "R1: pending"),
            ([{"event": "check", "command": "make test", "exit": 0, "commit": None}], "R1: pending"),
            ([{"event": "check", "command": "make test", "exit": 0, "commit": "abcdef12", "selected_nothing": True}],
             "R1: pending"),
            ([{"event": "check", "command": "make test", "exit": 0, "commit": "abcdef12"}], "R1: pass at abcdef1"),
            ([{"event": "check", "command": "make test", "exit": 2, "commit": "abcdef12"}], "R1: fail at abcdef1"),
            ([{"event": "check", "command": "make lint", "exit": 0, "commit": "abcdef12"}], "R1: pending"),
        ]
        for records, line in cases:
            with self.subTest(line=line, records=records):
                self.assertEqual(render.evidence_lines(rows, records), [line])

    def test_a_row_without_a_trailing_pipe_is_read_as_plan_parse_reads_it(self):
        plan = render.read_plan("| R1 | a \\| b | `make test`\n")
        self.assertEqual(plan.requirements, [render.Requirement("R1", "a | b", "`make test`")])

    def test_assumptions_stop_at_the_next_other_line(self):
        plan = render.read_plan(PLAN + "\n## Notes\n- a note, not an assumption\n")
        self.assertEqual(plan.assumptions, [
            "- A1 (R1): the stand-in gh records the body file. Tested by reading gh-calls.jsonl: held."])
        self.assertEqual(plan.door, "two-way")

    def test_evidence_matches_the_unmasked_command_and_shows_it_masked(self):
        plan = PLAN.replace("`python3 -m unittest tests.test_deliver_pr`", "`pytest ~/work/repo/tests`")
        records = [{"event": "check", "command": "pytest ~/work/repo/tests", "exit": 0, "commit": "2222222b",
                    "selected_nothing": False}]
        text = self.render("Source: conversation\n\nx\n", plan=plan, records=records)
        self.assertIn("- R1: pass at 2222222\n", text)
        self.assertIn("| R1 | `pr` opens a draft PR | `pytest [private path]` |\n", text)
        self.assertIn("Source: conversation (masked: private paths)\n", text)

    def test_given_reasons_and_values_are_masked(self):
        text = self.render("Source: conversation\n\nx\n", door=("two-way", "asked @octocat"),
                           blast=("low", "only /Users/jane/work"), measurement={"path": "~/work/x"})
        self.assertIn("**Door:** two-way. Asked [mention]\n", text)
        self.assertIn("**Blast Radius:** low. Only [private path]\n", text)
        self.assertIn("path: [private path]\n", text)
        self.assertIn("Source: conversation (masked: @ mentions and private paths)\n", text)

    def test_a_secret_in_a_given_reason_or_value_is_a_question(self):
        for options in ({"door": ("two-way", "password = hunter2hunter2")},
                        {"blast": ("low", "ghp_" + "x" * 36)},
                        {"measurement": {"merge": "token: abcdefgh1234"}}):
            with self.subTest(options), self.assertRaises(render.core.Question):
                self.render("Source: conversation\n\nx\n", **options)

    def test_a_secret_is_a_question_and_nothing_is_rendered(self):
        token = "ghp_" + "a1" * 18
        with self.assertRaises(render.core.Question) as caught:
            self.render(f"Source: conversation\n\nUse {token} for the push.\n")
        self.assertEqual(str(caught.exception), (
            "The saved request.md looks like it holds a secret (a GitHub token) on line 3, so nothing was "
            "pushed or sent to gh. Is it a real secret that should be taken out of the request before the "
            "run goes on?"))
        self.assertNotIn(token, str(caught.exception))

    def test_a_secret_in_the_summary_or_the_plan_is_a_question_too(self):
        for kind in ("summary", "plan"):
            with self.subTest(kind), self.assertRaises(render.core.Question):
                self.render("Source: conversation\n\nx\n", **{kind: PLAN + "password = hunter2hunter2\n"})

    def test_a_request_without_a_source_line_is_unreadable(self):
        for first in ("Ticket 415", "Source: an email", "Source: ticket 415"):
            with self.subTest(first), self.assertRaises(render.Unreadable) as caught:
                self.render(f"{first}\n\nx\n")
            self.assertEqual(caught.exception.kind, "request")

    def test_a_plan_without_a_readable_row_is_unreadable(self):
        for plan in ("Just prose.\ndoor: two-way\n", "| R1 | only two |\n", "| R1 | a | b | c |\n"):
            with self.subTest(plan), self.assertRaises(render.Unreadable) as caught:
                self.render("Source: conversation\n\nx\n", plan=plan)
            self.assertEqual(caught.exception.kind, "plan")


class Mask(unittest.TestCase):
    """The run's mask measure, case by case."""

    def assert_masked(self, text: str, masked: str, kinds: list[str]):
        self.assertEqual(mask.mask(text), (masked, kinds))

    def test_mentions_are_masked(self):
        for text, masked in [
            ("@octocat", "[mention]"),
            ("thanks @some-user.", "thanks [mention]."),
            ("(@a_b)", "([mention])"),
            ("ask @Org/team-name now", "ask [mention] now"),
            ("first line\n@octocat at line start", "first line\n[mention] at line start"),
            ("+@octocat", "+[mention]"),
            ("in code `@octocat`", "in code `[mention]`"),
        ]:
            with self.subTest(text):
                self.assert_masked(text, masked, ["@ mentions"])

    def test_home_folder_paths_are_masked(self):
        for path in [
            "/Users/jane/projects/x", "/home/jane/.config/y", "~/work/repo", "~/.ssh/config",
            "C:\\Users\\jane\\Desktop", "/root/.netrc", "/private/var/folders/ab/T/x", "/var/folders/ab/T/x",
        ]:
            with self.subTest(path):
                self.assert_masked(f"see {path} here", "see [private path] here", ["private paths"])

    def test_a_path_in_a_file_link_or_after_a_short_option_is_masked(self):
        for text, masked in [
            ("[trace](file:///Users/jane/projects/x)", "[trace](file://[private path])"),
            ("cc -I/home/jane/include x.c", "cc -I[private path] x.c"),
        ]:
            with self.subTest(text):
                self.assert_masked(text, masked, ["private paths"])

    def test_paths_in_a_fenced_block_are_masked(self):
        self.assert_masked("```\ncd /Users/jane/x\n```", "```\ncd [private path]\n```", ["private paths"])

    def test_closing_words_emails_and_repo_paths_pass_unchanged(self):
        for text in [
            "Closes #415", "Fixes #12", "Resolves owner/repo#3", "someone@example.com",
            "skills/deliver/scripts/pr.py", "./scripts/check.sh", "/usr/bin/env", "/tmp/x", "docs/home/x",
            "the token is read from gh", "a secret-shaped string",
        ]:
            with self.subTest(text):
                self.assert_masked(text, text, [])
                self.assertIsNone(mask.find_secret(text))

    def test_secrets_are_found(self):
        for text, kind in [
            ("AKIA" + "ABCDEFGHIJ234567", "an AWS key id"),
            ("ghp_" + "x" * 36, "a GitHub token"),
            ("gho_" + "x" * 40, "a GitHub token"),
            ("ghu_" + "x" * 36, "a GitHub token"),
            ("ghs_" + "x" * 36, "a GitHub token"),
            ("ghr_" + "x" * 36, "a GitHub token"),
            ("github_pat_" + "x" * 30, "a GitHub token"),
            ("-----BEGIN OPENSSH PRIVATE KEY-----", "a private key"),
            ("-----BEGIN PRIVATE KEY-----", "a private key"),
            ("xoxb-" + "123-abc", "a Slack token"),
            ("xoxp-" + "123-abc", "a Slack token"),
            ("xoxa-" + "123-abc", "a Slack token"),
            ("xoxs-" + "123-abc", "a Slack token"),
            ("sk-" + "a" * 20, "an API key"),
            ("sk-" + "proj-abc_def-123456789", "an API key"),
            ("password = hunter2hunter2", "a password or token assignment"),
            ('API_KEY: "abc123def456ghi789"', "a password or token assignment"),
            ("db_passwd=s3cr3tvalue", "a password or token assignment"),
            ("apikey: abcdefgh1234", "a password or token assignment"),
            ("SECRET=abcdefgh1234", "a password or token assignment"),
            ("`token: abcdefgh1234`", "a password or token assignment"),
            ('password = "four ordinary test words"', "a password or token assignment"),
            ("secret: 'two words here'", "a password or token assignment"),
        ]:
            with self.subTest(text):
                self.assertEqual(mask.find_secret(f"line one\n{text}"), (kind, 2))

    def test_a_short_or_placeholder_value_is_not_a_secret(self):
        for text in ["password = x", "token: ${{ secrets.GH_TOKEN }}", 'password: "${DB_PASSWORD} here"',
                     'token = "<your token here>"', "sk-short", "task-" + "a" * 30]:
            with self.subTest(text):
                self.assertIsNone(mask.find_secret(text))


if __name__ == "__main__":
    unittest.main()
