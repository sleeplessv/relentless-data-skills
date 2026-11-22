# Setup

Read this when `pbi-vm.sh status` is anything but ready. Find the row that matches what it printed, apply
the fix, and run `pbi-vm.sh status` again. Setup is done when status lists one instance whose
`currentFilePath` is the project's `.pbip`.

| What `status` printed | Fix |
|---|---|
| `prlctl is not on PATH` or `jq is not on PATH` | Ask the user to install Parallels Desktop or `jq` on the Mac. |
| `expected exactly one running Parallels VM, found: none` | Ask the user to start the Windows VM and sign in to Windows. The wrapper runs in the signed-in session. |
| The same message with several VM names | Put `PBI_VM="<name>"` in front of each command. |
| `... is outside ..., the folder the VM can see` | The project must sit in a Mac folder that Parallels shares with the VM. See [the share](#the-share). |
| `The Bridge CLI is not installed in the VM` | Run `pbi-vm.sh setup`. See [the VM tools](#the-vm-tools). |
| JSON with no instance, or none with a `currentFilePath` | Open the project. See [open the project](#open-the-project). |
| An instance with another project's `currentFilePath` | Ask the user which project they want open, then open it. |

A `sync-model` or `safe-reload --model` answer of `The TOM library is not installed in the VM` has the
same fix as the Bridge CLI row.

## The VM tools

```bash
<skill-dir>/scripts/pbi-vm.sh setup
```

Done when it prints JSON with `"status": "ok"`. It installs the Power BI Desktop Bridge CLI with npm and
downloads the TOM library from NuGet, both inside the VM, and skips whichever is already there. It needs
Node.js and Power BI Desktop in the VM: when its message says one is missing, ask the user to install it.

## The share

The wrapper turns each Mac path into the path the VM sees. By default it expects Parallels to share the
Mac home folder as `\\Mac\Home`. For a narrower share, set both `PBI_SHARE_ROOT` (the Mac folder) and
`PBI_SHARE_UNC` (the same folder as the VM sees it) in front of each command.

The VM can read everything in the shared folder. Which folder to share is the user's decision.

## Open the project

```bash
<skill-dir>/scripts/pbi-vm.sh open <path/to/project.pbip>
```

Opening takes minutes. Then hand over to the user for three things in Desktop: sign in to the data
sources, refresh, and save (Ctrl+S). Desktop can mark a freshly opened project as unsaved, and that
first save is what lets the first `safe-reload` run.
