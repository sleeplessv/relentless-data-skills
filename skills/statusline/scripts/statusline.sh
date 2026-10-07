#!/bin/sh
# Claude Code status line: model | bar used/size (pct) | dir (branch) | open PRs and PR counts.
# Reads the status line JSON from stdin. Requires jq and a truecolor terminal.
# The PR counts also need gh, signed in to an account that can read the repo.
#
# Context thresholds, in tokens: green up to GREEN_UNTIL, then a gradient
# through amber (midway) to red at GREEN_UNTIL + FADE_SPAN and above. The
# ten-cell bar fills one cell per CELL tokens, rounded to the nearest cell.
GREEN_UNTIL=90000
FADE_SPAN=80000
CELL=20000
# Minutes between background refreshes of the open-PR counts.
PR_REFRESH_MIN=1
# Most open PR numbers to list, newest first. The rest show as +N.
PR_LIST_MAX=5

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

# Open PRs in the repo, by state: ready with checks passed (or no checks),
# ready with checks running, ready with a failed check, and draft. Before the
# counts, each open PR shows as a clickable #number, coloured by its state.
top=$([ -n "$cwd" ] && git --no-optional-locks -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
if [ -n "$top" ] && command -v gh >/dev/null 2>&1; then
  cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline"
  key=$(printf '%s' "$top" | cksum | cut -d' ' -f1)
  cache="$cache_dir/prs-$key.json"
  lock="$cache_dir/prs-$key.lock"
  mkdir -p "$cache_dir"

  # Refresh in the background, so gh never delays the status line. The lock
  # stops parallel refreshes. A lock older than two minutes is from a refresh
  # that died. On failure, touch the cache to wait a full interval before
  # trying again, and keep the last counts.
  [ -n "$(find "$lock" -maxdepth 0 -mmin +2 2>/dev/null)" ] && rmdir "$lock" 2>/dev/null
  if [ -z "$(find "$cache" -mmin -"$PR_REFRESH_MIN" 2>/dev/null)" ] && mkdir "$lock" 2>/dev/null; then
    (
      cd "$top" \
        && gh pr list --state open --limit 200 \
          --json number,url,isDraft,statusCheckRollup >"$cache.tmp" \
        && mv "$cache.tmp" "$cache" \
        || { rm -f "$cache.tmp"; touch "$cache"; }
      rmdir "$lock"
    ) </dev/null >/dev/null 2>&1 &
  fi

  prs=$(jq -r --argjson max "$PR_LIST_MAX" '
    def state:
      if .isDraft then "draft"
      else
        [.statusCheckRollup[]? |
          if .__typename == "StatusContext" then
            if .state == "FAILURE" or .state == "ERROR" then "failed"
            elif .state == "PENDING" or .state == "EXPECTED" then "running"
            else "passed" end
          elif .status != "COMPLETED" then "running"
          elif [.conclusion] | inside(["FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"]) then "failed"
          else "passed" end]
        | if any(. == "failed") then "failed"
          elif any(. == "running") then "running"
          else "passed" end
      end;
    def colour: {passed: "38;2;46;204;64", running: "38;2;255;191;0",
                 failed: "38;2;231;76;60", draft: "38;5;245"}[.];
    # OSC 8 hyperlink, so the terminal opens the PR on click.
    def link($url; $text): "\u001b]8;;\($url)\u001b\\\($text)\u001b]8;;\u001b\\";
    (map(select(.number))
      | (.[:$max] | map("\u001b[\(state | colour)m\(link(.url; "#\(.number)"))\u001b[0m"))
        + (if length > $max then ["+\(length - $max)"] else [] end)
      | join(" ")
      | select(. != "")
      | "\(.) |"),
    (map(state) as $states
      | [["passed", "✓"], ["running", "⧗"], ["failed", "✗"], ["draft", "✎"]]
      | map(. as [$name, $symbol]
          | ($states | map(select(. == $name)) | length) as $n
          | select($n > 0)
          | "\u001b[\($name | colour)m\($symbol)\($n)\u001b[0m")
      | join(" ")
      | select(. != "")
      | "PRs \(.)")
  ' "$cache" 2>/dev/null | paste -sd' ' -)
  if [ -n "$prs" ]; then printf ' | %s' "$prs"; fi
fi
