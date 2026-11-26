#!/usr/bin/env bash
# Run only after the CI gate. Both plain and auto merge use the same head checks.
set -eu
host=$1 repo=$2 number=$3 branch=$4 default_branch=$5 sha=$6
shift 6
[[ $# == 0 || ( $# == 1 && $1 == --auto ) ]]
local_head=$(git rev-parse --verify "refs/heads/$branch")
[[ $local_head == "$sha" ]] || { echo "Local $branch tip $local_head differs from checked PR head $sha" >&2; exit 1; }
fresh=$(gh api --hostname "$host" "repos/$repo/pulls/$number" \
    --jq '[.state, .head.repo.full_name, .head.ref, .base.ref, .head.sha] | @tsv')
expected=$(printf '%s\t%s\t%s\t%s\t%s' open "$repo" "$branch" "$default_branch" "$sha")
[[ $fresh == "$expected" ]] || { echo "PR identity, base, state or head changed: $fresh" >&2; exit 1; }
gh pr merge "$number" --repo "$host/$repo" --squash --match-head-commit "$sha" "$@"
