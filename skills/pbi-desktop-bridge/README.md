# pbi-desktop-bridge

The `pbi-desktop-bridge` agent skill lets an agent on a Mac see its own Power BI edits rendered. Power BI
Desktop runs only on Windows, so on a Mac it lives in a Parallels VM. The agent edits the PBIP files on
the Mac, pushes them into the running Desktop, and reads a screenshot of the page, with no click from a
person for report and measure edits.

## What it does

- **Reload and screenshot.** `scripts/pbi-vm.sh` runs Microsoft's Power BI Desktop Bridge CLI inside the
  VM through `prlctl exec`, and maps Mac paths to the paths the VM sees on the Parallels share.
- **Measure edits without a click.** The Bridge's reload reports success for a TMDL edit and leaves it
  unapplied (seen in Desktop 2.159). `scripts/sync-model.ps1` writes measure edits into Desktop's local
  Analysis Services model, the path external tools use. Without `-Apply` it is a dry run.
- **A reload that protects unsaved work.** `safe-reload` refuses (exit 3) when Desktop holds unsaved
  changes the wrapper did not cause. `safe-reload --check` asks the same question before an edit, and a
  bare `reload` is refused.
- **One setup command for the VM.** `pbi-vm.sh setup` installs the Bridge CLI and the TOM library.

## Limits

- Model edits other than measures (columns, tables, relationships, Power Query) still need the user:
  "Apply external changes" in Desktop, or a reopen.
- Data refresh and data source sign-in stay with the user.
- A reload leaves Desktop marked as unsaved. Whatever the user changes in Desktop after a reload and
  leaves unsaved is replaced by the next reload.
- Tested on one setup: Parallels Desktop 27.1, Windows 11 ARM64, the Microsoft Store build of Power BI
  Desktop 2.159.1231, Bridge CLI 1.1.0 and Microsoft.AnalysisServices 19.120.1, with the Mac home folder
  shared as `\\Mac\Home`. A narrower share (`PBI_SHARE_ROOT`, `PBI_SHARE_UNC`) is covered by a unit test
  only.

## Requirements

- macOS with Parallels Desktop (`prlctl`) and `jq`.
- A Windows VM with a signed-in user, Power BI Desktop and Node.js.
- The project in PBIP format, in a Mac folder shared with the VM.

## Install

See the [repo root README](../../README.md) for the general install patterns. For this skill:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/pbi-desktop-bridge
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install pbi-desktop-bridge@relentless-data-skills
```

## Files

- `SKILL.md`: the edit loop, what reaches Desktop and how, and the hand-back rules.
- `references/setup.md`: what to fix when the VM is not ready.
- `scripts/pbi-vm.sh`: the Mac-side wrapper. `pbi-vm.sh --help` lists the commands, the environment
  variables and the exit codes.
- `scripts/bridge.ps1`, `scripts/sync-model.ps1`, `scripts/setup-vm.ps1`: the VM side. The wrapper copies
  them to `.pbi-desktop/bin/` in the project on each run, because the VM runs them from the share.

## Maintenance / CI

`tests/test_pbi_desktop_bridge.py` runs the wrapper against a stub `prlctl`, so CI needs no VM. The
PowerShell scripts have no automated test: exercise a change to them against a real VM. Repo CI also runs
`scripts/lint_skill.py` against this skill's `SKILL.md`. See the
[root README](../../README.md#maintenance-and-ci).
