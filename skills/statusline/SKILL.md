---
name: statusline
description: Installs a Claude Code status line that shows the current model, context window usage, directory, and git branch. Use when the user asks to show the model or context usage under the prompt, or to set up the Relentless Data status line.
---

# Status line

Installs `scripts/statusline.sh` as the Claude Code status line. The rendered line looks like:

```text
Opus 5.5 | ▰▰▱▱▱▱▱▱▱▱ 42k/200k (21%) | data-fabric-dwh (dwh)
```

Each bar cell is 20k tokens, rounded to the nearest cell, so the bar is full from 190k whatever the size of the context window. The context usage is green up to 90k tokens. Above 90k, it shades to amber at 130k and to red at 170k.

The gradient needs a terminal with 24-bit colour, such as iTerm2, Ghostty, Warp, or the VS Code terminal. Older versions of macOS Terminal.app do not show it.

## Workflow

### Step 1: Check prerequisites

- Run `command -v jq`. If `jq` is missing, tell the user to install it and stop. On macOS, the command is `brew install jq`. On Linux, use the distribution's package.
- Resolve the absolute path of this skill's `scripts/statusline.sh`.

### Step 2: Copy the script

Copy the script to `~/.claude/statusline.sh` and make it executable (`chmod +x`). Copy it rather than pointing settings at the skill folder, because plugin and `npx skills` updates can move that folder.

If `~/.claude/statusline.sh` already exists and differs, show the diff and ask before overwriting.

### Step 3: Register it in settings

Use `~/.claude/settings.json` by default, so it applies to every project. Use the project's `.claude/settings.json` only when the user asks for a project-level status line.

Read the file first. If a `statusLine` key already exists and does not point to `~/.claude/statusline.sh`, show it and ask before replacing it. Otherwise set:

```json
"statusLine": { "type": "command", "command": "~/.claude/statusline.sh" }
```

Change only that key and keep every other setting. Run `jq empty <file>` to confirm that the file is still valid JSON.

### Step 4: Prove it works

Pipe sample input through the installed script from inside a git repo:

```bash
echo '{"model":{"display_name":"Opus 5.5"},"context_window":{"total_input_tokens":42000,"context_window_size":200000,"used_percentage":21.4},"workspace":{"current_dir":"'"$PWD"'"}}' | ~/.claude/statusline.sh
```

Done when the output shows the model, `▰▰▱▱▱▱▱▱▱▱ 42k/200k (21%)`, the directory name, and the branch. Report the rendered line to the user.

Tell the user that the status line appears from their next message. If it does not appear, tell them to restart Claude Code. Before the first message of a session, the line shows `0/0 (0%)` because Claude Code has no usage to report yet.
