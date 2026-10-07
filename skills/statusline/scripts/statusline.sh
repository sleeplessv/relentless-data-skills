#!/bin/sh
# Claude Code status line: model | bar used/size (pct) | dir (branch).
# Reads the status line JSON from stdin. Requires jq and a truecolor terminal.
input=$(cat)
model=$(echo "$input" | jq -r '.model.display_name // "?"')
used=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
size=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0 | floor')
cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // empty')

fmt() {
  awk -v n="$1" 'BEGIN{ if (n>=1000000) printf "%.1fM", n/1000000; else if (n>=1000) printf "%.0fk", n/1000; else printf "%d", n }'
}

# Context colour by tokens used: a gradient from green (0) through amber
# (100k) to red (175k and above).
colour=$(awk -v u="$used" 'BEGIN{
  t = u / 175000; if (t < 0) t = 0; if (t > 1) t = 1
  a = 100000 / 175000
  if (t < a) { s = t / a;           r = 46 + 209*s;  g = 204 - 13*s;  b = 64 - 64*s }
  else       { s = (t - a) / (1 - a); r = 255 - 24*s; g = 191 - 115*s; b = 60*s }
  printf "38;2;%d;%d;%d", r, g, b
}')

# Ten-cell bar for tokens used out of 200k, whatever the window size.
bar=$(awk -v u="$used" 'BEGIN{
  n = int(u / 20000 + 0.5); if (n < 0) n = 0; if (n > 10) n = 10
  for (i = 0; i < 10; i++) printf (i < n ? "▰" : "▱")
}')

printf '\033[36m%s\033[0m | \033[%sm%s %s/%s (%s%%)\033[0m' \
  "$model" "$colour" "$bar" "$(fmt "$used")" "$(fmt "$size")" "$pct"

if [ -n "$cwd" ]; then
  printf ' | %s' "$(basename "$cwd")"
  b=$(git --no-optional-locks -C "$cwd" symbolic-ref --short HEAD 2>/dev/null \
    || git --no-optional-locks -C "$cwd" rev-parse --short HEAD 2>/dev/null)
  [ -n "$b" ] && printf ' \033[35m(%s)\033[0m' "$b"
fi
