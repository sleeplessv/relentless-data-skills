# Setup

Read this when `pbi-vm.sh status` is anything but ready. Find the row that matches what it printed, apply
the fix, and run `pbi-vm.sh status` again. Read each instance's `bridgeStatus` before its
`currentFilePath`. Setup is done when a connected instance shows the project's `.pbip`.

| What `status` printed | Fix |
|---|---|
| `prlctl is not on PATH` or `jq is not on PATH` | Ask the user to install Parallels Desktop or `jq` on the Mac. |
| `expected exactly one running Parallels VM, found: none` | Ask the user to start the Windows VM and sign in to Windows. The wrapper runs in the signed-in session. |
| The same message with several VM names | Put `PBI_VM="<name>"` in front of each command. |
| `... is outside ..., the folder the VM can see` | The project must sit in a Mac folder that Parallels shares with the VM. See [the share](#the-share). |
| `The Bridge CLI is not installed in the VM` | Run `pbi-vm.sh setup`. See [the VM tools](#the-vm-tools). |
| `bridgeStatus: "not_connected"` or `"error"` | Report the PID and `unavailableReason` or `error`. Check [Desktop Bridge access](#desktop-bridge-access) in the VM. |
| No running instance, or a connected instance without a `currentFilePath` | [Open the project](#open-the-project). |
| A connected instance whose `currentFilePath` is not the `.pbip` you are editing, such as another checkout or worktree of the same project | [Open the project](#open-the-project) yourself. Desktop starts a second instance and leaves the user's instance and its unsaved work alone. Ask the user only when it is unclear which project they want. |

A `sync-model` or `safe-reload --model` answer of `The TOM library is not installed in the VM` has the
same fix as the Bridge CLI row.

## Desktop Bridge access

In Desktop, open File → Options and settings → Options → Security → Desktop Bridge.
Check that external tool access through secure local APIs is enabled. On managed devices,
ask the administrator about the `DesktopNamedPipeBridge` policy if access is disabled.
[Microsoft's Desktop Bridge prerequisites](https://learn.microsoft.com/en-us/power-bi/developer/agentic/power-bi-desktop-bridge-overview#prerequisites)

## The VM tools

```bash
<skill-dir>/scripts/pbi-vm.sh setup
```

Done when it prints JSON with `"status": "ok"`. It installs the Power BI Desktop Bridge CLI with npm and
downloads the TOM library from NuGet, both inside the VM, and skips whichever is already there. It needs
Node.js 20+ with npm in the VM. Install Power BI Desktop there before opening a project.
[Microsoft's Bridge CLI 1.1.0 package metadata](https://registry.npmjs.org/@microsoft%2fpowerbi-desktop-bridge-cli/1.1.0)

## The share

The wrapper turns each Mac path into the path the VM sees. By default it expects Parallels to share the
Mac home folder as `\\Mac\Home`. For a narrower share, set both `PBI_SHARE_ROOT` (the Mac folder) and
`PBI_SHARE_UNC` (the same folder as the VM sees it) in front of each command.

The VM can read everything in the shared folder. Which folder to share is the user's decision.

## Open the project

```bash
<skill-dir>/scripts/pbi-vm.sh open <path/to/project.pbip>
```

Opening takes minutes, and the call can outlive a 360-second tool timeout while Desktop still finishes
opening. Run it in the background or with a tool timeout of at least 10 minutes. Done when
`pbi-vm.sh status` shows an instance with `bridgeStatus: "connected"` and the expected `currentFilePath`;
the exit of the call does not tell you.

With two instances open, every per-instance command (`shot`, `shots`, `sync-model`, `safe-reload`) needs
`--pid <pid>` from `status`; without it the script exits 4.

Then hand over to the user for three things in Desktop: sign in to the data sources, refresh, and save
(Ctrl+S). Desktop can mark a freshly opened project as unsaved, and that first save is what lets the first
`safe-reload` run. A project opened from disk already carries the current model and report, so "Apply
external changes" is not needed. Until the refresh, every card shows "--" under the banner "Some of the
tables have incomplete or no data." with a "Refresh now" button.
