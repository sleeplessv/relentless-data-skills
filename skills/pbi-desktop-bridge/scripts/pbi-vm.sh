#!/usr/bin/env bash
# Drive Power BI Desktop in a Parallels Windows VM from the Mac, through the Power BI Desktop Bridge CLI.
#   pbi-vm.sh status | manifest                 raw Bridge CLI output (JSON)
#   pbi-vm.sh setup                             install the Bridge CLI and the TOM library in the VM (safe to repeat)
#   pbi-vm.sh open <file.pbip>                  open a project in Desktop (a Mac path under the shared folder)
#   pbi-vm.sh sync-model [--pid N]              dry run: measure differences between the TMDL files and Desktop
#   pbi-vm.sh safe-reload [--model] [--pid N]   reload Desktop from the files; --model first writes measure edits
#                                               into the running model
#   pbi-vm.sh safe-reload --check [--pid N]     reload nothing: exit 0 when a safe-reload would run, 3 when not
#   pbi-vm.sh shot <page-id> <run> [--pid N]    one page; prints the PNG's Mac path
#   pbi-vm.sh shots <run> [--pid N]             every page; prints each PNG's Mac path
#   pbi-vm.sh <other Bridge CLI command> [args] passed through unchanged (reload is refused: use safe-reload)
#
# Environment:
#   PBI_VM           VM name (default: the only running Parallels VM)
#   PBI_WORK         Mac folder for state, the VM-side scripts and screenshots
#                    (default: .pbi-desktop at the git top level, or in the current directory outside a repo)
#   PBI_SHARE_ROOT   Mac folder the VM can see (default: $HOME)
#   PBI_SHARE_UNC    the same folder's path inside the VM (default: \\Mac\Home)
#   PBI_SETTLE_MS    wait before a screenshot, in ms (default 8000)
#   PBI_RETRY_SLEEP  seconds between reload attempts (default 10)
#
# Exit codes: 0 done; 2 usage or environment; 3 REFUSED, Desktop holds unsaved changes this script did not
# cause; 4 no single Desktop instance with a file open (pass --pid); 5 the Bridge, the model write or the
# reload failed.
#
# safe-reload: a reload itself leaves hasUnsavedChanges=true, and the Bridge has no save. So each successful
# reload writes a marker for that Desktop pid under $PBI_WORK/state, naming the VM and the open project. The
# next reload runs when the flag is false, or when it is true and the marker matches (the flag came from this
# script). Anything changed in Desktop after that reload and not saved is lost on the next one; a save in
# Desktop clears the marker.
set -euo pipefail

die() { local code="$1"; shift; echo "pbi-vm: $*" >&2; exit "$code"; }
if [[ $# -eq 0 || "$1" == -h || "$1" == --help ]]; then sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 2; fi
for tool in prlctl jq; do command -v "$tool" >/dev/null 2>&1 || die 2 "$tool is not on PATH"; done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SETTLE_MS="${PBI_SETTLE_MS:-8000}"
RETRY_SLEEP="${PBI_RETRY_SLEEP:-10}"
SHARE_ROOT="$(cd "${PBI_SHARE_ROOT:-$HOME}" && pwd -P)"
SHARE_UNC="${PBI_SHARE_UNC:-}"
[[ -n "$SHARE_UNC" ]] || SHARE_UNC='\\Mac\Home'

unc() {  # Mac path of an existing file or folder -> its path inside the VM
  [[ -e "$1" ]] || die 2 "no such file or folder: $1"
  local p
  if [[ -d "$1" ]]; then p="$(cd "$1" && pwd -P)"; else p="$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")"; fi
  case "$p" in
    "$SHARE_ROOT") echo "$SHARE_UNC"; return ;;
    "$SHARE_ROOT"/*) ;;
    *) die 2 "$p is outside $SHARE_ROOT, the folder the VM can see (PBI_SHARE_ROOT)" ;;
  esac
  local rel="${p#"$SHARE_ROOT"/}"
  printf '%s\\%s\n' "$SHARE_UNC" "${rel//\//\\}"
}

WORK="${PBI_WORK:-}"
if [[ -z "$WORK" ]]; then
  top="$(git rev-parse --show-toplevel 2>/dev/null)" || top="$PWD"
  WORK="$top/.pbi-desktop"
fi
unc "$(dirname "$WORK")" >/dev/null   # stop before creating anything outside the share
mkdir -p "$WORK/bin" "$WORK/state"
WORK="$(cd "$WORK" && pwd -P)"
GWORK="$(unc "$WORK")"
# The VM runs the .ps1 files from the share, so each run puts this version of them there.
cp "$HERE"/*.ps1 "$WORK/bin/"

VM="${PBI_VM:-}"
if [[ -z "$VM" ]]; then
  VM="$(prlctl list --no-header -o name | sed 's/[[:space:]]*$//')"
  [[ -n "$VM" && "$VM" != *$'\n'* ]] || die 2 "expected exactly one running Parallels VM, found: ${VM:-none}. Start the VM or set PBI_VM."
fi

# --current-user runs in the signed-in Windows session, the only one the Bridge's named pipe accepts.
vmps()   { local script="$1"; shift; prlctl exec "$VM" --current-user powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$GWORK\\bin\\$script" "$@"; }
bridge() { vmps bridge.ps1 "$@"; }
json()   { tr -d '\r' | sed -n '/^{/,$p'; }   # drop progress lines before the JSON

get_status() {
  local st
  st="$(bridge status | json)" && [[ -n "$st" ]] || die 5 "the Bridge gave no status; run 'pbi-vm.sh status' to see why"
  echo "$st"
}
pick_pid() {  # $1 = status JSON, $2 = optional pid
  local requested="${2:-}" instances pids unavailable
  [[ -z "$requested" || "$requested" =~ ^[0-9]+$ ]] || die 2 "--pid takes a number, got: $requested"
  instances="$(jq -c --arg pid "$requested" '[.instances[] | select($pid == "" or (.pid | tostring) == $pid)]' <<<"$1")"
  pids="$(jq -r '.[] | select((.bridgeStatus // "connected") == "connected" and (.currentFilePath // "") != "") | .pid' <<<"$instances")"
  if [[ -z "$pids" ]]; then
    unavailable="$(jq -r '.[] | select(.bridgeStatus == "not_connected" or .bridgeStatus == "error") |
      "pid \(.pid) \(.bridgeStatus): \(.unavailableReason // .error // "see status")"' <<<"$instances")"
    [[ -z "$unavailable" ]] || die 5 "$unavailable. Check Desktop Bridge access under Security in Power BI Desktop."
    die 4 "no matching Desktop instance with a file open. Run 'pbi-vm.sh status' and open the project in a connected instance."
  fi
  [[ "$pids" != *$'\n'* ]] || die 4 "several Desktop instances have a file open: $pids. Pass --pid."
  echo "$pids"
}
field()    { jq -r --argjson p "$2" --arg f "$3" '.instances[] | select(.pid == $p) | .[$f]' <<<"$1"; }
pid_arg()  { local p=""; while (($#)); do if [[ "$1" == --pid ]]; then p="${2:-missing}"; shift; fi; shift || true; done; echo "$p"; }
has_flag() { local f="$1" a; shift; for a in "$@"; do [[ "$a" == "$f" ]] && return 0; done; return 1; }
sync() {  # $1 = status JSON, $2 = pid, rest = extra arguments for sync-model.ps1
  local pbip; pbip="$(field "$1" "$2" currentFilePath)"
  [[ -n "$pbip" && "$pbip" != null ]] || die 4 "Desktop pid $2 has no file open"
  vmps sync-model.ps1 -DesktopPid "$2" -Pbip "$pbip" "${@:3}" | json
}

cmd="$1"; shift
case "$cmd" in
  setup)
    vmps setup-vm.ps1 | json
    ;;
  open)
    f="${1:?usage: pbi-vm.sh open <file.pbip>}"; shift
    gf="$(unc "$f")"   # its own line, so a path outside the share stops the script
    bridge open "$gf" --timeout 240 "$@"
    ;;
  sync-model)
    st="$(get_status)"; pid="$(pick_pid "$st" "$(pid_arg "$@")")"
    rc=0; s="$(sync "$st" "$pid")" || rc=$?
    echo "$s"
    [[ "$rc" == 0 && "$(jq -r '.status' <<<"$s" 2>/dev/null)" == ok ]] || exit 5
    ;;
  safe-reload)
    st="$(get_status)"; pid="$(pick_pid "$st" "$(pid_arg "$@")")"
    unsaved="$(field "$st" "$pid" hasUnsavedChanges)"
    marker="$WORK/state/reloaded-$pid"
    # Windows reuses pids, so the marker counts only for the VM and the project it was written for.
    key="$VM|$(field "$st" "$pid" currentFilePath)"
    if [[ "$unsaved" == false ]]; then
      rm -f "$marker"
    elif [[ "$unsaved" == true && -f "$marker" && "$(sed -n 1p "$marker")" == "$key" ]]; then
      echo "pbi-vm: the unsaved flag comes from this script's reload at $(sed -n 2p "$marker")" >&2
    else
      die 3 "REFUSED. Desktop pid $pid has unsaved changes this script did not cause (hasUnsavedChanges: '${unsaved:-pid not found}'). Save in Desktop (Ctrl+S), then run this again."
    fi
    if has_flag --check "$@"; then exit 0; fi
    if has_flag --model "$@"; then
      rc=0; s="$(sync "$st" "$pid" -Apply)" || rc=$?
      echo "$s"
      [[ "$rc" == 0 && "$(jq -r '.status' <<<"$s" 2>/dev/null)" == ok ]] || die 5 "the model write failed (exit $rc); Desktop was not reloaded"
      jq -e '.unsupported | length == 0' <<<"$s" >/dev/null || echo "pbi-vm: WARNING: table differences the model write does not apply (listed above)" >&2
    fi
    # Desktop can be busy for a few seconds after a model write, so the reload gets three attempts.
    out=""
    for try in 1 2 3; do
      if out="$(bridge reload --pid "$pid" 2>&1 | json)" && [[ "$(jq -r '.result.success // false' <<<"$out" 2>/dev/null)" == true ]]; then
        echo "$out"
        printf '%s\n%s\n' "$key" "$(date '+%Y-%m-%d %H:%M:%S')" > "$marker"
        exit 0
      fi
      echo "pbi-vm: reload attempt $try failed: ${out:-no JSON output}" >&2
      [[ "$try" == 3 ]] || sleep "$RETRY_SLEEP"
    done
    exit 5
    ;;
  shot)
    page="${1:?usage: pbi-vm.sh shot <page-id> <run>}"; run="${2:?usage: pbi-vm.sh shot <page-id> <run>}"; shift 2
    mkdir -p "$WORK/shots/$run"
    rm -f "$WORK/shots/$run/$page.png"   # an earlier capture under this label is not this one
    sleep $(( SETTLE_MS / 1000 ))
    bridge screenshot "$page" --output "$GWORK\\shots\\$run\\$page.png" --scale 1 "$@" >&2
    [[ -s "$WORK/shots/$run/$page.png" ]] || die 5 "no screenshot at $WORK/shots/$run/$page.png"
    echo "$WORK/shots/$run/$page.png"
    ;;
  shots)
    run="${1:?usage: pbi-vm.sh shots <run>}"; shift
    mkdir -p "$WORK/shots/$run"
    rm -f "$WORK/shots/$run"/*.png   # an earlier capture under this label is not this one
    bridge screenshot-all --output-dir "$GWORK\\shots\\$run" --scale 1 --settle "$SETTLE_MS" "$@" >&2
    ls "$WORK/shots/$run"/*.png 2>/dev/null || die 5 "no screenshots in $WORK/shots/$run"
    ;;
  reload) die 2 "use 'pbi-vm.sh safe-reload': a bare reload discards unsaved work in Desktop without checking whose it is" ;;
  *) bridge "$cmd" "$@" ;;
esac
