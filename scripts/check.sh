#!/usr/bin/env bash
# Run the repo's local checks; stop at the first failure.
#
# Usage: scripts/check.sh [--fast] [--network] [--base <commit-or-ref>]
#   --fast     skip the unit test suite (used by the pre-commit hook)
#   --network  also run scripts/check_doc_urls.py (needs network access)
#   --base     baseline for skill_versions.py; also settable via CHECK_BASE.
#              Default: git merge-base HEAD origin/main, falling back to main.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fast=0
network=0
base="${CHECK_BASE:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --fast) fast=1 ;;
    --network) network=1 ;;
    --base)
      [ $# -ge 2 ] || { echo "check.sh: --base needs a value" >&2; exit 2; }
      base="$2"
      shift
      ;;
    --base=*) base="${1#--base=}" ;;
    -h | --help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
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

echo "All checks passed."
