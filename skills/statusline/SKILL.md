---
name: statusline
description: Installs a Claude Code status line that shows the current model, reasoning effort, context window usage, directory, git branch and its diff, and open pull requests.
disable-model-invocation: true
---

# Status line

Installs `scripts/statusline.sh` as the Claude Code status line. The rendered status line looks like:

```text
Opus 5.5 · high | ▰▰▱▱▱▱▱▱▱▱ 42k/200k (21%) | my-project (ticket-46-preflight +120 −34)
#48 ∅ [#47 46] #45 39 41 #44 ∅ #42 37 +2 | PRs ✓3 ⧗1 ✗1 ✎2
```

The bar fills by tokens used, whatever the size of the context window, and the text shades from sage green through sand to coral as usage grows. The thresholds are named variables at the top of the script, and the README describes them.

After the branch comes the branch diff: the lines the branch adds and removes, from where it split from the default branch to the working tree, untracked files included. The default branch is `origin/HEAD`, or local `main` or `master` when `origin/HEAD` is missing or points at a deleted branch. The diff is hidden on the default branch, on a detached HEAD, and when the branch changes nothing. It needs git 2.26 or later.

The PR line is the second line. It lists the repo's open pull requests as clickable numbers, such as `#42`, coloured by state. After each PR come the issues it closes, as numbers on an orange chip. The line ends with counts of the repo's open pull requests by state. The README lists the symbols and colours. The PR line needs `gh`, signed in to an account that can read the repo. Without `gh`, the status line leaves the PR line out.

The gradient needs a terminal with 24-bit colour, such as iTerm2, Ghostty, Warp, or the VS Code terminal. Older versions of macOS Terminal.app do not show it.

## Workflow

### Step 1: Check prerequisites

- Run `command -v jq`. If `jq` is missing, tell the user to install it and stop. On macOS, the command is `brew install jq`. On Linux, use the distribution's package.
- Run `gh auth status`. If `gh` is missing or signed out, tell the user that the PR line stays hidden until they install `gh` or run `gh auth login`. Then continue.
- Resolve the absolute path of this skill's `scripts/statusline.sh`.

### Step 2: Copy the script

Copy the script to `~/.claude/statusline.sh` and make it executable (`chmod +x`). Copy it rather than pointing settings at the skill folder, because plugin and `npx skills` updates can move that folder.

If `~/.claude/statusline.sh` already exists and differs, show the diff and ask before overwriting.

### Step 3: Register it in settings

Use `~/.claude/settings.json` by default, so it applies to every project. Use the project's `.claude/settings.json` only when the user asks for a project-level status line.

If the file does not exist, create it with only the `statusLine` key below. Otherwise, read the file first. If a `statusLine` key already exists and does not point to `~/.claude/statusline.sh`, show it and ask before replacing it. Otherwise set:

```json
"statusLine": { "type": "command", "command": "~/.claude/statusline.sh", "refreshInterval": 30 }
```

`refreshInterval` reruns the script every 30 seconds, so the PR line catches up while the session is idle. Without it, Claude Code reruns the script only on conversation events.

Change only that key and keep every other setting. Run `jq empty <file>` to confirm that the file is still valid JSON.

### Step 4: Prove it works

Pipe sample input through the installed script from inside a git repo:

```bash
echo '{"model":{"display_name":"Opus 5.5"},"effort":{"level":"high"},"context_window":{"total_input_tokens":42000,"context_window_size":200000,"used_percentage":21.4},"workspace":{"current_dir":"'"$PWD"'"}}' | ~/.claude/statusline.sh
```

Done when the output shows `Opus 5.5 · high`, `▰▰▱▱▱▱▱▱▱▱ 42k/200k (21%)`, the directory name, and the branch. Off the default branch, a branch with changes also shows its diff, such as `+120 −34`. Report the rendered lines to the user.

The first run starts a background fetch of the PR counts, so the PR line can appear only on a later run. Run the command again after a few seconds. If the repo has no open PRs, the line stays hidden.

Tell the user that the status line appears from their next message. If it does not appear, tell them to restart Claude Code. Before the first message of a session, the line shows `0/0 (0%)` because Claude Code has no usage to report yet.
