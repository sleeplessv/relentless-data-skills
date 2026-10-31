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
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

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
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "check.sh: unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [ -z "$base" ]; then
  base="$(git merge-base HEAD origin/main 2>/dev/null || echo main)"
fi

run() {
  local name="$1"
  shift
  echo "==> $name"
  local rc=0
  "$@" || rc=$?
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
