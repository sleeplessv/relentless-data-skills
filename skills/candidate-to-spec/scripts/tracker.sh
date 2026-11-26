# Sourced by the setup and worker Bash blocks.
require_tracker() {
  if [[ ! ${GH_REPO:-} =~ ^[[:alnum:].-]+(:[0-9]+)?/[[:alnum:]_.-]+/[[:alnum:]_.-]+$ ]]; then
    echo "expected a host-qualified tracker: ${GH_REPO:-<missing>}" >&2
    return 1
  fi
}

issue_number() (
  local url=$1 number=${1##*/}
  shopt -s nocasematch
  if [[ ! $number =~ ^[1-9][0-9]*$ || $url != "https://$GH_REPO/issues/$number" ||
        $number != "${2-$number}" ]]; then
    echo "bad issue url for $GH_REPO: $url (expected #${2-$number})" >&2
    return 1
  fi
  printf '%s\n' "$number"
)

resolve_tracker() (
  local saved=$1 metadata url name host
  shift
  metadata=$(gh repo view --json url,nameWithOwner --jq '[.url, .nameWithOwner] | @tsv') || return 1
  IFS=$'\t' read -r url name <<< "$metadata"
  shopt -s nocasematch
  if [[ ! $url =~ ^https://([^/]+)/(.+)$ || ${BASH_REMATCH[2]} != "$name" ]]; then
    echo "inconsistent tracker metadata: $metadata" >&2
    return 1
  fi
  host=${BASH_REMATCH[1]}
  GH_REPO=$host/$name
  require_tracker || return 1
  if [[ -n $saved && $saved != "$name" && $saved != "$GH_REPO" ]]; then
    echo "saved tracker $saved disagrees with $GH_REPO" >&2
    return 1
  fi
  while (( $# )); do
    issue_number "$1" "${2:-}" >/dev/null || return 1
    shift 2
  done
  printf '%s\n' "$GH_REPO"
)
