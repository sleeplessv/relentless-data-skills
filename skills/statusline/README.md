# statusline

The **`statusline`** agent skill: install a Claude Code status line that shows
the current model, context window usage, directory, and git branch under the
prompt.

```text
Opus 5.5 | 42k/200k (21%) | data-fabric-dwh (dwh)
```

## What it does

- **Model.** Shows the display name of the model in use.
- **Context usage.** Shows input tokens used against the context window size,
  colored by tokens used: green below 100k, amber from 100k, and red
  from 175k.
- **Location.** Shows the current directory name and git branch, or the short
  commit hash on a detached HEAD.
- **Safe install.** Copies the script to `~/.claude/statusline.sh`, sets only
  the `statusLine` key in `~/.claude/settings.json`, and asks before replacing
  an existing status line or script.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/statusline
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install statusline@relentless-data-skills
```

It activates when you ask to show the model or context usage under the prompt,
or to set up the status line.

To install without the skill, copy `scripts/statusline.sh` to
`~/.claude/statusline.sh`, run `chmod +x` on it, and add this to
`~/.claude/settings.json`:

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
- `jq` and a POSIX shell.
- `git`, for the branch segment. It is omitted outside a repo.
