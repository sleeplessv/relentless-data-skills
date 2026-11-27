#!/usr/bin/env bash
# Run the repo's local checks; stop at the first failure.
#
# Usage: scripts/check.sh [--fast] [--network] [--browser] [--base <commit-or-ref>]
#   --fast     skip the unit test suite (used by the pre-commit hook)
#   --network  also run scripts/check_doc_urls.py (needs network access)
#   --browser  also run the dossier tests with Playwright and Chromium, via uv
#              (needs uv and network access); a skipped test fails the run
#   --base     baseline for skill_versions.py; also settable via CHECK_BASE.
#              Default: git merge-base HEAD origin/main, falling back to main.
#
# One full run at a time: a run without --fast takes a lock before its first
# check and holds it until it exits, so it waits while another run of this
# clone holds the lock. A run with --fast, --help or a usage error takes no
# lock and never waits.
#
# The lock is fcntl.flock on one file, taken through python3 by
# scripts/check_lock.py. The file is check.sh.lock in the clone's shared git
# directory (git rev-parse --git-common-dir), so every worktree of the clone
# uses the same lock. Only the system says whether the lock is held. The file's
# presence and content decide nothing, so a killed run, even one killed with
# SIGKILL, blocks no later run. The script's own process holds the lock and the
# checks it starts do not, so a process that a check leaves running cannot keep
# it. The holder writes its process id and the time its run started into the
# file, and only the waiting line reads them.
#
# A run that has to wait prints one line at once. The line names the holder's
# process id and start time where the file gives them, and the longest the run
# will wait. The run then asks the system for the lock and blocks until the
# system gives it. When several runs wait, the system picks the next holder in
# no fixed order, so the first to wait is not always the first served. When its
# turn comes the run prints how long it waited. CHECK_LOCK_WAIT sets that bound
# in whole seconds from 0 to 100000000 (default 1800). At the bound the run
# prints one line on standard error, saying how long it waited and that no
# check was run, and exits 75. A run that cannot open or lock the file for any
# reason other than another holder prints one line and runs without the lock.
# CHECK_LOCK_FILE names another lock file, for the tests or for one deliberate
# run beside another. No switch skips the lock.
#
# Limits: a second clone on this machine has its own lock. A run killed with
# SIGKILL frees the lock while processes it started may still be finishing.
#
# Exit status: 0 when every check passes, the failing check's own status, 2 for
# bad usage or a bad CHECK_LOCK_WAIT, 75 when the wait ran out.
set -euo pipefail
started="$(date '+%Y-%m-%d %H:%M:%S')"

fast=0
network=0
browser=0
base="${CHECK_BASE:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --fast) fast=1 ;;
    --network) network=1 ;;
    --browser) browser=1 ;;
    --base)
      [ $# -ge 2 ] || { echo "check.sh: --base needs a value" >&2; exit 2; }
      base="$2"
      shift
      ;;
    --base=*) base="${1#--base=}" ;;
    -h | --help)
      awk 'NR > 1 && !/^#/ { exit } NR > 1' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "check.sh: unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

# After the arguments, so --help reads "$0" from the caller's directory.
cd "$(git rev-parse --show-toplevel)"

if [ -z "$base" ]; then
  base="$(git merge-base HEAD origin/main 2>/dev/null || echo main)"
fi

if [ "$fast" -eq 0 ]; then
  # This process holds the lock on fd 9 until it exits. run() starts each check
  # in a subshell that closes fd 9 first, so nothing a check starts holds it.
  lock_file="${CHECK_LOCK_FILE:-$(git rev-parse --path-format=absolute --git-common-dir)/check.sh.lock}"
  if { exec 9>>"$lock_file"; } 2>/dev/null; then
    lock_rc=0
    python3 scripts/check_lock.py 9 "$lock_file" "$$" "$started" || lock_rc=$?
    case "$lock_rc" in
      0) ;;
      3) exec 9>&- ;;
      *) exit "$lock_rc" ;;
    esac
  else
    echo "check.sh: cannot open $lock_file; running without the lock." >&2
  fi
fi

run() {
  local name="$1"
  shift
  echo "==> $name"
  local rc=0
  # A redirection (`"$@" 9>&-`) is not enough: bash 3.2 runs a shell function
  # with a saved copy of fd 9 open, which the programs it starts inherit.
  (exec 9>&-; "$@") || rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "PASS: $name"
  else
    echo "FAIL: $name (exit $rc)" >&2
    exit "$rc"
  fi
}

run "skill lint" python3 scripts/lint_skill.py
run "registry check" python3 scripts/sync_registry.py --check
run "skill versions (base $base)" python3 scripts/skill_versions.py --check --base "$base"

if [ "$fast" -eq 1 ]; then
  echo "SKIP: unit tests (--fast)"
else
  run "unit tests" python3 -m unittest discover -s tests
fi

if command -v claude >/dev/null 2>&1; then
  run "claude plugin validate" claude plugin validate .
else
  echo "SKIP: claude plugin validate (claude CLI not on PATH; CI runs it)"
fi

if [ "$network" -eq 1 ]; then
  run "doc URL liveness" python3 scripts/check_doc_urls.py
fi

if [ "$browser" -eq 1 ]; then
  command -v uv >/dev/null 2>&1 || { echo "FAIL: --browser needs uv on PATH" >&2; exit 2; }
  pw=(uv run --python 3.13 --no-project --with playwright)
  run "install Chromium" "${pw[@]}" playwright install chromium
  # unittest passes skipped tests, but here a skip means the browser never ran.
  browser_tests() {
    local out
    out="$("${pw[@]}" python -m unittest -v tests.test_dossier 2>&1)" || { echo "$out"; return 1; }
    if grep -q "\.\.\. skipped" <<<"$out"; then
      grep "\.\.\. skipped" <<<"$out" >&2
      return 1
    fi
  }
  run "dossier browser tests" browser_tests
fi

echo "All checks passed."
