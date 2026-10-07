# statusline

The **`statusline`** agent skill installs a Claude Code status line. The status
line shows the current model, context window usage, directory, git branch, and
open pull requests under the prompt.

```text
Opus 5.5 | ▰▰▱▱▱▱▱▱▱▱ 42k/200k (21%) | data-fabric-dwh (dwh) | PR ✓3 ⧗1 ✗1 ✎2
```

## What it does

- **Model.** Shows the display name of the model in use.
- **Context usage.** Shows a ten-cell bar, then tokens used against the size
  of the context window. The count rounds to the nearest 1k, and each cell is
  20k tokens rounded to the nearest cell, so the bar is full from 190k. The
  text is green up to 90k tokens. Above 90k, it shades to amber at 130k and to
  red at 170k. To change these thresholds, edit the variables at the top of
  the script.
- **Location.** Shows the current directory name and git branch, or the short
  commit hash on a detached HEAD.
- **Open pull requests.** Counts every open PR in the repo, by any author.
  Each count shows only when it is above zero. A ready PR is one that is not a
  draft. A failed check outranks a running one.

  | Symbol | Colour | Meaning |
  | --- | --- | --- |
  | `✓` | Green | Ready, and every check passed, or the PR has no checks. |
  | `⧗` | Amber | Ready, and at least one check is still running. |
  | `✗` | Red | Ready, and at least one check failed. |
  | `✎` | Grey | Draft, whatever its checks. |

  A background `gh pr list` refreshes the counts, so `gh` never delays the
  status line. The script caches the counts in
  `~/.cache/claude-statusline/` and refreshes them every minute. To change the
  interval, edit `PR_REFRESH_MIN` at the top of the script.
- **Settings.** Copies the script to `~/.claude/statusline.sh`, sets only
  the `statusLine` key in `~/.claude/settings.json`, and asks before replacing
  an existing status line or script.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). To install this skill:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/statusline
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install statusline@relentless-data-skills
```

The skill runs when you ask to show the model or context usage under the
prompt, or to set up the status line.

To install the status line without the skill, copy `scripts/statusline.sh` to
`~/.claude/statusline.sh` and run `chmod +x` on it. Then add the following key
to `~/.claude/settings.json`:

```json
"statusLine": { "type": "command", "command": "~/.claude/statusline.sh" }
```

## Files

- `SKILL.md`: the install workflow (prerequisites, copy, register, verify).
- `scripts/statusline.sh`: the status line script. It reads Claude Code's
  status line JSON from stdin.
- `plugin.json`: Claude Code plugin manifest.

## Requirements

- Claude Code.
- `jq` and a POSIX shell. Without `jq`, the status line shows
  `statusline: install jq`.
- A terminal with 24-bit colour for the gradient, such as iTerm2, Ghostty,
  Warp, or the VS Code terminal. Older versions of macOS Terminal.app do not
  show it.
- `git`, for the branch name. Outside a git repo, the script leaves the branch
  out.
- `gh`, for the PR counts. It must be signed in to an account that can read
  the repo. Otherwise, the script leaves the `PR` segment out.
