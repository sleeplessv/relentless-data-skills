---
name: statusline
description: Installs a Claude Code status line that shows the current model, context window usage, directory, and git branch. Use when the user asks to show the model or context usage under the prompt, or to set up the Relentless Data status line.
---

# Status line

Installs `scripts/statusline.sh` as the Claude Code status line. The rendered line looks like:

```text
Opus 5.5 | 42k/200k (21%) | data-fabric-dwh (dwh)
```

The context percentage is green below 50%, yellow from 50%, and red from 80%.

## Workflow

### Step 1: Check prerequisites

- Run `command -v jq`. If it is missing, tell the user to install it (`brew install jq` on macOS, the distro package elsewhere) and stop.
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

Change only that key. Keep every other setting and keep the file valid JSON (check with `jq empty <file>`).

### Step 4: Prove it works

Pipe sample input through the installed script from inside a git repo:

```bash
echo '{"model":{"display_name":"Opus 5.5"},"context_window":{"total_input_tokens":42000,"context_window_size":200000,"used_percentage":21.4},"workspace":{"current_dir":"'"$PWD"'"}}' | ~/.claude/statusline.sh
```

Done when the output shows the model, `42k/200k (21%)`, the directory name, and the branch. Report the rendered line to the user.

Tell the user the line appears from their next message, and to restart Claude Code if it does not. Before the first message of a session it shows `0/0 (0%)`, because no usage exists yet.
