#!/bin/sh
# Claude Code status line: model and effort | bar used/size (pct) | dir (branch
# +added −removed), then open PRs, the issues each closes, and PR counts on a
# second line. The branch diff needs git 2.26 or later.
# Reads the status line JSON from stdin. Requires jq and a truecolor terminal.
# The PR counts also need gh, signed in to an account that can read the repo.
#
# Colours: Claude Code orange marks identity (model, branch, issue chips).
# Softened sage, sand, and coral mark status, and dim text marks the rest.
#
# Context thresholds, in tokens: sage up to GREEN_UNTIL, then a gradient
# through sand (midway) to coral at GREEN_UNTIL + FADE_SPAN and above. The
# ten-cell bar fills one cell per CELL tokens, rounded to the nearest cell.
GREEN_UNTIL=90000
FADE_SPAN=80000
CELL=20000
# Seconds between background refreshes of the open-PR counts.
PR_REFRESH_SEC=20
# Counts older than this many seconds, such as after failed refreshes, show
# their age.
PR_STALE_SEC=120
# Most open PR numbers to list, newest first. The rest show as +N, except the
# PR for the current branch, which always shows.
PR_LIST_MAX=5

if ! command -v jq >/dev/null 2>&1; then
  printf 'statusline: install jq'
  exit 0
fi

# Seconds since a file last changed. Empty when the file does not exist.
age() { m=$(date -r "$1" +%s 2>/dev/null) && echo $(($(date +%s) - m)); }

input=$(cat)
eval "$(printf '%s' "$input" | jq -r '@sh "
  model=\(.model.display_name // "?")
  effort=\(.effort.level // "")
  used=\(.context_window.total_input_tokens // 0)
  size=\(.context_window.context_window_size // 0)
  pct=\((.context_window.used_percentage // 0) | floor)
  cwd=\(.workspace.current_dir // .cwd // "")
"' 2>/dev/null)"
: "${model:=?}" "${used:=0}" "${size:=0}" "${pct:=0}"

# Round to the nearest 1k first, so the label, bar, and colour agree.
used=$(awk -v n="$used" 'BEGIN{ printf "%d", int(n / 1000 + 0.5) * 1000 }')

# Shorten a count like 980, 1.2k, 58k, 1.3M, dropping a trailing .0. With
# whole as the second argument, as for the token labels, thousands are always
# whole and millions keep their .0, like 2k and 1.0M.
fmt_count() {
  awk -v n="$1" -v whole="$2" 'BEGIN{
    if (n >= 999500) s = sprintf("%.1fM", n / 1000000)
    else if (n >= 9950 || (whole && n >= 1000)) s = sprintf("%.0fk", n / 1000)
    else if (n >= 1000) s = sprintf("%.1fk", n / 1000)
    else s = sprintf("%d", n)
    if (!whole) sub(/\.0/, "", s)
    print s
  }'
}

colour=$(awk -v u="$used" -v start="$GREEN_UNTIL" -v span="$FADE_SPAN" 'BEGIN{
  t = (u - start) / span; if (t < 0) t = 0; if (t > 1) t = 1
  amber_at = 0.5
  if (t < amber_at) { s = t / amber_at;                r = 127 + 90*s; g = 183 - 3*s;  b = 126 - 52*s }
  else              { s = (t - amber_at) / (1 - amber_at); r = 217 + 7*s;  g = 180 - 72*s; b = 74 + 43*s }
  printf "38;2;%d;%d;%d", r, g, b
}')

bar=$(awk -v u="$used" -v cell="$CELL" 'BEGIN{
  n = int(u / cell + 0.5); if (n < 0) n = 0; if (n > 10) n = 10
  for (i = 0; i < 10; i++) printf (i < n ? "▰" : "▱")
}')

sep=' \033[2m|\033[0m '

printf '\033[1;38;2;215;119;87m%s\033[0m' "$model"
# Claude Code leaves out effort when the model does not support it.
[ -n "$effort" ] && printf ' \033[2m· %s\033[0m' "$effort"
printf '%b\033[%sm%s %s/%s (%s%%)\033[0m' \
  "$sep" "$colour" "$bar" "$(fmt_count "$used" whole)" "$(fmt_count "$size" whole)" "$pct"

top=$([ -n "$cwd" ] && git --no-optional-locks -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
if [ -n "$cwd" ]; then
  printf '%b%s' "$sep" "$(basename "$cwd")"
  # On a detached HEAD, head_branch is empty and branch is the short commit hash.
  head_branch=$(git --no-optional-locks -C "$cwd" symbolic-ref --short HEAD 2>/dev/null)
  branch=${head_branch:-$(git --no-optional-locks -C "$cwd" rev-parse --short HEAD 2>/dev/null)}
  # The branch diff: lines added and removed from where the branch split from
  # the default branch to the working tree. Untracked files count as added,
  # through a throwaway copy of the index, so the real index never changes.
  diff=
  # The base is the default branch on origin, or local main or master when
  # origin/HEAD is missing or points at a branch that no longer exists. With no
  # base, on the base branch itself, or on a detached HEAD, mb stays empty and
  # the diff is hidden. base is a full ref, as --short can be ambiguous, such as
  # beside a local branch named origin/main.
  base=$(git --no-optional-locks -C "$cwd" symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null)
  git --no-optional-locks -C "$cwd" rev-parse -q --verify "$base^{commit}" >/dev/null 2>&1 || base=
  for b in main master; do
    [ -z "$base" ] && git --no-optional-locks -C "$cwd" show-ref -q --verify "refs/heads/$b" && base=refs/heads/$b
  done
  base_branch=${base#refs/remotes/origin/}
  mb=$([ -n "$head_branch" ] && [ "$head_branch" != "${base_branch#refs/heads/}" ] \
    && git --no-optional-locks -C "$cwd" merge-base HEAD "$base" 2>/dev/null)
  if [ -n "$mb" ] && [ -n "$top" ] && idx=$(mktemp "${TMPDIR:-/tmp}/claude-statusline-index.XXXXXX"); then
    # Remove the throwaway index even when Claude Code kills the script midway.
    trap 'rm -f "$idx" "$idx.lock"' EXIT
    trap 'exit 1' INT TERM HUP
    real=$(git --no-optional-locks -C "$top" rev-parse --git-path index)
    case $real in /*) ;; *) real="$top/$real" ;; esac
    # With no real index to copy, git creates the throwaway index from scratch.
    cp "$real" "$idx" 2>/dev/null || rm -f "$idx"
    # Literal pathspecs, so a file named like :(exclude)a or *.txt is one path.
    git --no-optional-locks -C "$top" ls-files -z --others --exclude-standard \
      | GIT_INDEX_FILE="$idx" git --literal-pathspecs --no-optional-locks -C "$top" add -N --pathspec-from-file=- --pathspec-file-nul >/dev/null 2>&1
    # The lines added and removed, as "added removed". An empty diff gives
    # nothing, and shows nothing.
    counts=$(GIT_INDEX_FILE="$idx" git --no-optional-locks -C "$top" diff --shortstat "$mb" 2>/dev/null | awk '{
      a = 0; d = 0
      for (i = 1; i < NF; i++) { if ($(i+1) ~ /^insertion/) a = $i; if ($(i+1) ~ /^deletion/) d = $i }
      if (a + d > 0) print a, d
    }')
    # The diff ends in the branch orange, for the closing parenthesis.
    [ -n "$counts" ] && diff=$(printf ' \033[38;2;127;183;126m+%s\033[0m \033[38;2;224;108;117m\342\210\222%s\033[38;2;215;119;87m' \
      "$(fmt_count "${counts% *}")" "$(fmt_count "${counts#* }")")
    rm -f "$idx" "$idx.lock"
    trap - EXIT INT TERM HUP
  fi
  [ -n "$branch" ] && printf ' \033[38;2;215;119;87m(%s%s)\033[0m' "$branch" "$diff"
fi

# Open PRs in the repo, on a second line, by state: ready with checks passed
# (or no checks), ready with checks running, ready with a failed check, and
# draft. Before the counts, each open PR shows as a clickable #number, coloured
# by its state, then the issues it closes as chips.
if [ -n "$top" ] && command -v gh >/dev/null 2>&1; then
  cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline"
  key=$(printf '%s' "$top" | cksum | cut -d' ' -f1)
  # The v2 cache adds each PR's branch, fork flag, and closing issues. The new
  # name stops the script from reading an old cache that lacks them.
  cache="$cache_dir/prs-v2-$key.json"
  lock="$cache_dir/prs-v2-$key.lock"
  stamp="$cache_dir/prs-v2-$key.stamp"
  mkdir -p "$cache_dir"

  # Refresh in the background, so gh never delays the status line. The stamp
  # marks the last attempt, so a failed refresh waits a full interval before
  # trying again. The cache changes only on success, so its age is the age of
  # the counts. The lock stops parallel refreshes. A lock older than two
  # minutes is from a refresh that died.
  [ -n "$(find "$lock" -maxdepth 0 -mmin +2 2>/dev/null)" ] && rmdir "$lock" 2>/dev/null
  stamp_age=$(age "$stamp")
  if [ "${stamp_age:-$PR_REFRESH_SEC}" -ge "$PR_REFRESH_SEC" ] && mkdir "$lock" 2>/dev/null; then
    touch "$stamp"
    (
      cd "$top" \
        && gh pr list --state open --limit 200 \
          --json number,url,isDraft,statusCheckRollup,headRefName,isCrossRepository,closingIssuesReferences >"$cache.tmp" \
        && mv "$cache.tmp" "$cache"
      rm -f "$cache.tmp"
      rmdir "$lock"
    ) </dev/null >/dev/null 2>&1 &
  fi

  prs=$(jq -r --argjson max "$PR_LIST_MAX" --arg head "$head_branch" '
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
    def colour: {passed: "38;2;127;183;126", running: "38;2;217;180;74",
                 failed: "38;2;224;108;117", draft: "2"}[.];
    # OSC 8 hyperlink, so the terminal opens the PR on click.
    def link($url; $text): "\u001b]8;;\($url)\u001b\\\($text)\u001b]8;;\u001b\\";
    # An issue, as a dark number on an orange chip. The chip links to the issue
    # when the URL is known.
    def chip: "\u001b[48;2;215;119;87;38;2;26;26;26m\(
      if .url then link(.url; " \(.number) ") else " \(.number) " end)\u001b[0m";
    # A PR, then the issues it closes, or a dim ∅ when it closes none.
    def entry: "\u001b[\(state | colour)m\(link(.url; "#\(.number)"))\u001b[0m"
      + ([.closingIssuesReferences[]? | " \(chip)"] | join("")
        | if . == "" then " \u001b[2m∅\u001b[0m" else . end);
    def bold($s): "\u001b[1m\($s)\u001b[0m";
    # True for the PR from the current branch. False for a fork PR, even from a
    # branch of the same name.
    def current: $head != "" and .headRefName == $head and (.isCrossRepository | not);
    # On a branch with no PR, the issue its name starts with, such as
    # ticket-51-x, issue-51-x, 51-x, or me/ticket-51-x. The URL comes from any PR.
    (map(select(.number)) as $prs
      | $head | capture("^(([^/]+/)?(ticket|issue)-)?(?<n>[0-9]+)(-|$)")? | .n as $n
      | select($prs | all(current | not))
      | {number: $n, url: ($prs[0].url // null
          | if . then sub("/pull/[0-9]+$"; "/issues/\($n)") else . end)}
      | "on \(chip) \u001b[2m(no PR)\u001b[0m |"),
    (map(select(.number))
      # The newest PRs, and also the PR for the current branch when it is older.
      | (.[:$max] + (.[$max:] | map(select(current)))) as $shown
      | (length - ($shown | length)) as $rest
      | ($shown | map(if current then bold("[") + entry + bold("]") else entry end))
        + (if $rest > 0 then ["+\($rest)"] else [] end)
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
  # Drop the trailing separator when no PR follows the issue from the branch name.
  prs=${prs% |}
  # Dim the separators. No other text on the line contains " | ".
  prs=$(printf '%s' "$prs" | sed "s/ | / $(printf '\033')[2m|$(printf '\033')[0m /g")
  # Add the age to old counts, such as (5m old), so nobody reads them as
  # current. With no PRs to show, the line is PRs (5m old).
  cache_age=$(age "$cache")
  if [ "${cache_age:-0}" -ge "$PR_STALE_SEC" ]; then
    if [ "$cache_age" -ge 3600 ]; then old="$((cache_age / 3600))h"; else old="$((cache_age / 60))m"; fi
    prs="${prs:-PRs} $(printf '\033[2m(%s old)\033[0m' "$old")"
  fi
  if [ -n "$prs" ]; then printf '\n%s' "$prs"; fi
fi
