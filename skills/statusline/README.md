# statusline

The **`statusline`** agent skill installs a two-line Claude Code status line.
It shows how full the context window is, which branch you are on and how much it
changes, and the state of every open PR in the repo.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/overview-dark.png">
  <img alt="Two-line status line. Line 1: Opus 5.5 · high | 42k/200k (21%) | my-project (ticket-46-preflight +120 −34). Line 2: #48 ∅ [#47 46] #45 39 41 #44 ∅ #42 37 +2 | PRs ✓3 ⧗1 ✗1 ✎2" src="assets/overview-light.png" width="844">
</picture>

## Read the status line

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/anatomy-dark.png">
  <img alt="The same status line with each part labelled: model, effort, context bar, tokens used / window, directory, git branch, branch diff; then PR, no issue, your branch's PR, issue it closes, draft, more, open PRs by state" src="assets/anatomy-light.png" width="844">
</picture>

The first line shows the model and effort, the context window, and the
directory and git branch. The bar fills one cell per 20k tokens. The bar and
the token count are green up to 90k tokens, sand at 130k, and coral from 170k,
whatever the size of the window.

After the branch, `+120 −34` is the branch diff: the lines the branch adds and
removes, counted from where it split from the default branch to your working
tree. It includes uncommitted changes and new files that git does not ignore, so
it matches what the branch's PR would show if you committed everything now.
Binary files and files over 10 MB count as zero lines, so a big data file can
make the count differ from the PR's. Untracked nested repos count as zero lines
too. Added lines are sage and removed lines coral.
Large counts shorten, such as `+1.2k`, `+58k`, or `+1.3M`. The default branch is
`origin/HEAD`, or local `main` or `master` when `origin/HEAD` is missing or
points at a deleted branch. The diff is hidden on the default branch, on a
detached HEAD, outside a git repo, when no default branch is found, and when the
branch changes nothing. The script recounts it each time the status line
redraws. Counting new files needs git 2.26 or later; older git leaves them out.

The second line lists the five newest open PRs. Each `#number` is a link,
coloured by the PR's state. The numbers on orange chips after a PR are the
issues it closes, and `∅` means it closes none. Brackets mark the PR from your
branch. On a branch with no PR, the line starts with the issue in the branch
name, such as `on 51 (no PR)` for `ticket-51-x`. The counts at the end cover
every open PR in the repo:

| Symbol | Colour | Meaning |
| --- | --- | --- |
| `✓` | Green | Ready, and every check passed, or the PR has no checks. |
| `⧗` | Sand | Ready, and at least one check is still running. |
| `✗` | Coral | Ready, and at least one check failed. |
| `✎` | Dim | Draft, whatever its checks. |

The script refreshes the PR line in the background about every 20 seconds.
When a refresh fails, the line keeps the last counts and shows their age once
they are two minutes old, such as `(5m old)`.

## Install

See the [repo root README](../../README.md) for the general install patterns.
To install this skill:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/statusline
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install statusline@relentless-data-skills
```

Then run `/statusline`. The status line needs `jq` and a terminal with 24-bit
colour. The PR line also needs `gh`, signed in to an account that can read the
repo. Without `gh`, the script leaves the PR line out.

## Change the status line

The thresholds, the number of PRs listed, the refresh timing, and the file size
above which the branch diff counts a file as binary are variables at the top of
`scripts/statusline.sh`. After you change the colours, run
`python3 scripts/statusline_screenshots.py` from the repo root to regenerate
the screenshots in `assets/`. The screenshot script needs Google Chrome.
