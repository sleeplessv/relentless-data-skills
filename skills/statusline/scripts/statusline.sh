#!/bin/sh
# Claude Code status line: model | context used/size (pct) | dir (branch).
# Reads the status line JSON from stdin. Requires jq.
input=$(cat)
model=$(echo "$input" | jq -r '.model.display_name // "?"')
used=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
size=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0 | floor')
cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // empty')

fmt() {
  awk -v n="$1" 'BEGIN{ if (n>=1000000) printf "%.1fM", n/1000000; else if (n>=1000) printf "%.0fk", n/1000; else printf "%d", n }'
}

# Context colour by tokens used: green < 100k, amber < 175k, red otherwise.
if [ "$used" -ge 175000 ]; then c=31; elif [ "$used" -ge 100000 ]; then c='38;5;214'; else c=32; fi

printf '\033[36m%s\033[0m | \033[%sm%s/%s (%s%%)\033[0m' \
  "$model" "$c" "$(fmt "$used")" "$(fmt "$size")" "$pct"

if [ -n "$cwd" ]; then
  printf ' | %s' "$(basename "$cwd")"
  b=$(git --no-optional-locks -C "$cwd" symbolic-ref --short HEAD 2>/dev/null \
    || git --no-optional-locks -C "$cwd" rev-parse --short HEAD 2>/dev/null)
  [ -n "$b" ] && printf ' \033[35m(%s)\033[0m' "$b"
fi
