#!/usr/bin/env bash
# Return one routing decision across every page and base for this source branch.
set -eu
host=$1 repo=$2 branch=$3 default_branch=$4
rows=$(gh api --hostname "$host" -X GET "repos/$repo/pulls" --paginate \
    -f state=all -f head="${repo%/*}:$branch" \
    --jq '.[] | [.head.repo.full_name, .head.ref, .base.ref, .state, .number, .head.sha, (.merged_at != null)] | @tsv')
awk -F '\t' -v repo="$repo" -v branch="$branch" -v base="$default_branch" '
    $1 == repo && $2 == branch {
        if ($4 == "open") {
            if ($3 != base) {
                print "PR #" $5 " targets " $3 ", expected " base > "/dev/stderr"
                unsafe = 1
            }
            opens++
            open_pr = "open " $5 " " $6
        } else if ($3 == base && $7 == "true") merged = 1
    }
    END {
        if (unsafe || opens > 1) exit 1
        if (opens) print open_pr
        else print (merged ? "merged" : "none")
    }
' <<< "$rows"
