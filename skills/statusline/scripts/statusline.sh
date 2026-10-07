#!/bin/sh
# Claude Code status line: model | bar used/size (pct) | dir (branch).
# Reads the status line JSON from stdin. Requires jq and a truecolor terminal.
#
# Context thresholds, in tokens: green up to GREEN_UNTIL, then a gradient
# through amber (midway) to red at GREEN_UNTIL + FADE_SPAN and above. The
# ten-cell bar fills one cell per CELL tokens, rounded to the nearest cell.
GREEN_UNTIL=90000
FADE_SPAN=80000
CELL=20000

if ! command -v jq >/dev/null 2>&1; then
  printf 'statusline: install jq'
  exit 0
fi

input=$(cat)
eval "$(printf '%s' "$input" | jq -r '@sh "
  model=\(.model.display_name // "?")
  used=\(.context_window.total_input_tokens // 0)
  size=\(.context_window.context_window_size // 0)
  pct=\((.context_window.used_percentage // 0) | floor)
  cwd=\(.workspace.current_dir // .cwd // "")
"' 2>/dev/null)"
: "${model:=?}" "${used:=0}" "${size:=0}" "${pct:=0}"

# Round to the nearest 1k first, so the label, bar, and colour agree.
used=$(awk -v n="$used" 'BEGIN{ printf "%d", int(n / 1000 + 0.5) * 1000 }')

fmt_tokens() {
  awk -v n="$1" 'BEGIN{ if (n>=999500) printf "%.1fM", n/1000000; else if (n>=1000) printf "%.0fk", n/1000; else printf "%d", n }'
}

colour=$(awk -v u="$used" -v start="$GREEN_UNTIL" -v span="$FADE_SPAN" 'BEGIN{
  t = (u - start) / span; if (t < 0) t = 0; if (t > 1) t = 1
  amber_at = 0.5
  if (t < amber_at) { s = t / amber_at;                r = 46 + 209*s;  g = 204 - 13*s;  b = 64 - 64*s }
  else              { s = (t - amber_at) / (1 - amber_at); r = 255 - 24*s; g = 191 - 115*s; b = 60*s }
  printf "38;2;%d;%d;%d", r, g, b
}')

bar=$(awk -v u="$used" -v cell="$CELL" 'BEGIN{
  n = int(u / cell + 0.5); if (n < 0) n = 0; if (n > 10) n = 10
  for (i = 0; i < 10; i++) printf (i < n ? "▰" : "▱")
}')

printf '\033[36m%s\033[0m | \033[%sm%s %s/%s (%s%%)\033[0m' \
  "$model" "$colour" "$bar" "$(fmt_tokens "$used")" "$(fmt_tokens "$size")" "$pct"

if [ -n "$cwd" ]; then
  printf ' | %s' "$(basename "$cwd")"
  branch=$(git --no-optional-locks -C "$cwd" symbolic-ref --short HEAD 2>/dev/null \
    || git --no-optional-locks -C "$cwd" rev-parse --short HEAD 2>/dev/null)
  [ -n "$branch" ] && printf ' \033[35m(%s)\033[0m' "$branch"
fi
