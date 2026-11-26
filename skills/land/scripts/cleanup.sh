#!/usr/bin/env bash
# Called on the updated default branch after GitHub confirms this SHA was merged.
set -eu
branch=$1 sha=$2 merge_commit=$3 default_branch=$4
ref=refs/heads/$branch
[[ $branch != "$default_branch" ]]
git merge-base --is-ancestor "$merge_commit" "refs/heads/$default_branch"
require_free_branch() {
    local worktrees
    worktrees=$(git worktree list --porcelain)
    if [[ $'\n'${worktrees}$'\n' == *$'\n'"branch $ref"$'\n'* ]]; then
        echo "$branch is checked out in a worktree" >&2
        exit 1
    fi
}
require_free_branch
if local_tip=$(git rev-parse --verify --quiet "$ref"); then
    [[ $local_tip == "$sha" ]] || { echo "$branch moved to $local_tip" >&2; exit 1; }
else
    [[ $? == 1 ]]
fi
remote=$(git ls-remote --heads origin "$ref")
if [[ -n $remote ]]; then
    [[ $remote == "$sha"$'\t'"$ref" ]] || { echo "Remote branch moved: $remote" >&2; exit 1; }
    git push --force-with-lease="$ref:$sha" origin ":$ref"
fi
if [[ -n $local_tip ]]; then
    require_free_branch
    git update-ref -d "$ref" "$sha"
fi
