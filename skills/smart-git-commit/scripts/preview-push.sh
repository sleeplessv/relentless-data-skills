#!/usr/bin/env bash
# Print each changing branch and its push URL only after the whole preview passes.
set -eu
branch=$(git branch --show-current)
[[ -n $branch ]] || { echo "A local branch is required" >&2; exit 1; }
case "${1:-tracked}" in
    tracked)
        set --
        remote=$(git for-each-ref --format='%(push:remotename)' "refs/heads/$branch")
        [[ -n $remote ]] || { echo "Cannot resolve push remote" >&2; exit 1; }
        # A '+' can look fast-forward in a dry run, then overwrite a racing update.
        refspecs=$(git config --get-all "remote.$remote.push") || [[ $? == 1 ]]
        while IFS= read -r spec; do
            case "$spec" in
                +*|:?*) echo "Unsafe push refspec: $spec" >&2; exit 1 ;;
            esac
        done <<< "$refspecs"
        mirror=$(git config --type=bool --get "remote.$remote.mirror") || [[ $? == 1 ]]
        [[ $mirror != true ]] || { echo "Mirror pushes can force or delete refs" >&2; exit 1; }
        ;;
    new) set -- origin "HEAD:refs/heads/$branch" ;;
    *) echo "Expected tracked or new" >&2; exit 1 ;;
esac
preview=$(LC_ALL=C git push --dry-run --porcelain --no-verify "$@")
destinations=$(awk -F '\t' '
    /^To .+/ && NF == 1 && !url { url = substr($0, 4); rows = 0; next }
    $0 == "Done" && url && rows { url = ""; done++; next }
    url && NF == 3 && ($1 == "+" || $1 == "-") {
        print "Forced update or deletion: " $0 > "/dev/stderr"; exit 1
    }
    url && NF == 3 && $1 == "=" && $2 ~ /^[^:]+:refs\/.+/ { rows++; next }
    url && NF == 3 && ($1 == " " || $1 == "*") {
        if (split($2, refs, ":") == 2 && refs[1] != "" && refs[2] ~ /^refs\/heads\/.+/) {
            rows++
            print url "\t" substr(refs[2], 12)
            next
        }
    }
    { print "Unsafe or unknown push preview: " $0 > "/dev/stderr"; exit 1 }
    END { if (url || !done) exit 1 }
' <<< "$preview")
if [[ -n $destinations ]]; then printf '%s\n' "$destinations"; fi
