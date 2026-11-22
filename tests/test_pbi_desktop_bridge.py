"""Tests for skills/pbi-desktop-bridge/scripts/pbi-vm.sh.

Runs the wrapper as an agent does, with a stub prlctl on PATH standing in for
the Parallels VM. The stub logs each call and answers the Bridge and
sync-model calls from files the test writes, so nothing here needs Parallels,
Windows or Power BI Desktop. Run from the repo root:

    python3 -m unittest tests.test_pbi_desktop_bridge -v
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "pbi-desktop-bridge" / "scripts" / "pbi-vm.sh"
PBIP = "\\\\Mac\\Home\\proj\\Sales.pbip"

# $STUB holds the canned answers; $STUB_SHARE is the Mac folder behind \\Mac\Home.
STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB/log"
if [[ "$1" == list ]]; then cat "$STUB/vms"; exit 0; fi
to_mac() { local p="${1#\\\\Mac\\Home\\}"; echo "$STUB_SHARE/${p//\\//}"; }
case "$*" in
  *'bridge.ps1 status'*) echo 'Connecting...'; cat "$STUB/status.json" ;;
  *'bridge.ps1 reload'*)
    n=$(( $(cat "$STUB/reloads") + 1 )); echo "$n" > "$STUB/reloads"
    if (( n <= $(cat "$STUB/reload_fails") )); then echo 'Desktop is busy'; exit 1; fi
    echo '{"result": {"success": true}}' ;;
  *'sync-model.ps1'*) cat "$STUB/sync.json"; exit "$(cat "$STUB/sync_exit")" ;;
  *'bridge.ps1 screenshot-all'*)
    while (($#)); do [[ "$1" == --output-dir ]] && out="$(to_mac "$2")"; shift; done
    echo png > "$out/AWS.png"; echo png > "$out/Azure.png" ;;
  *'bridge.ps1 screenshot'*)
    while (($#)); do [[ "$1" == --output ]] && out="$(to_mac "$2")"; shift; done
    [[ "$out" == */missing.png ]] || echo png > "$out"
    echo '{"status": "ok"}' ;;
esac
"""


def instance(pid, unsaved, path=PBIP):
    return {"pid": pid, "currentFilePath": path, "hasUnsavedChanges": unsaved}


class PbiVmTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.share = self.tmp / "home"
        self.proj = self.share / "proj"
        self.proj.mkdir(parents=True)
        self.stub = self.tmp / "stub"
        self.stub.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        prlctl = bin_dir / "prlctl"
        prlctl.write_text(STUB)
        prlctl.chmod(0o755)
        self.work = self.proj / ".pbi-desktop"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB": str(self.stub),
            "STUB_SHARE": str(self.share),
            "PBI_SHARE_ROOT": str(self.share),
            "PBI_SHARE_UNC": "",
            "PBI_WORK": str(self.work),
            "PBI_VM": "",
            "PBI_SETTLE_MS": "0",
            "PBI_RETRY_SLEEP": "0",
        }
        self.answers(vms="Windows 11\n", status=[instance(100, False)])

    def answers(self, vms=None, status=None, sync=None, sync_exit=0, reload_fails=0):
        if vms is not None:
            (self.stub / "vms").write_text(vms)
        if status is not None:
            (self.stub / "status.json").write_text(json.dumps({"instances": status}, indent=2) + "\n")
        (self.stub / "sync.json").write_text(json.dumps(
            sync or {"status": "ok", "changes": [], "unsupported": []}, indent=2) + "\n")
        (self.stub / "sync_exit").write_text(str(sync_exit))
        (self.stub / "reload_fails").write_text(str(reload_fails))
        (self.stub / "reloads").write_text("0")

    def run_vm(self, *args, **env):
        return subprocess.run(
            ["bash", str(SCRIPT), *args], cwd=self.proj, env={**self.env, **env},
            capture_output=True, text=True, timeout=60,
        )

    def calls(self, needle):
        log = self.stub / "log"
        return [line for line in log.read_text().splitlines() if needle in line] if log.exists() else []

    def marker(self, pid=100):
        return self.work / "state" / f"reloaded-{pid}"

    # --- reaching the VM

    def test_runs_the_copied_script_in_the_only_running_vm(self):
        result = self.run_vm("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "exec Windows 11 --current-user powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass "
            "-File \\\\Mac\\Home\\proj\\.pbi-desktop\\bin\\bridge.ps1 status",
            self.calls("bridge.ps1")[0],
        )
        for name in ("bridge.ps1", "sync-model.ps1", "setup-vm.ps1"):
            self.assertTrue((self.work / "bin" / name).is_file(), name)

    def test_two_running_vms_need_pbi_vm(self):
        self.answers(vms="Windows 11\nUbuntu\n")
        result = self.run_vm("status")
        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly one running Parallels VM", result.stderr)
        self.assertEqual(self.run_vm("status", PBI_VM="Ubuntu").returncode, 0)
        self.assertIn("exec Ubuntu --current-user", self.calls("bridge.ps1")[-1])

    def test_work_folder_outside_the_share_is_refused_before_it_is_created(self):
        outside = self.tmp / "elsewhere" / ".pbi-desktop"
        outside.parent.mkdir()
        result = self.run_vm("status", PBI_WORK=str(outside))
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside", result.stderr)
        self.assertFalse(outside.exists())
        self.assertEqual(self.calls("exec"), [])

    def test_a_custom_share_maps_to_its_own_unc_path(self):
        result = self.run_vm("status", PBI_SHARE_ROOT=str(self.proj), PBI_SHARE_UNC="\\\\Mac\\proj")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-File \\\\Mac\\proj\\.pbi-desktop\\bin\\bridge.ps1 status", self.calls("bridge.ps1")[0])

    def test_open_maps_the_mac_path(self):
        (self.proj / "Sales.pbip").write_text("{}")
        self.assertEqual(self.run_vm("open", "Sales.pbip").returncode, 0)
        self.assertIn("bridge.ps1 open \\\\Mac\\Home\\proj\\Sales.pbip --timeout 240", self.calls("bridge.ps1 open")[0])
        self.assertEqual(self.run_vm("open", "Missing.pbip").returncode, 2)

    # --- safe-reload

    def test_reload_with_no_unsaved_changes_writes_the_marker(self):
        result = self.run_vm("safe-reload")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bridge.ps1 reload --pid 100", self.calls("bridge.ps1 reload")[0])
        self.assertEqual(self.calls("sync-model.ps1"), [])
        self.assertTrue(self.marker().is_file())

    def test_unsaved_changes_from_someone_else_are_refused(self):
        self.answers(status=[instance(100, True)])
        result = self.run_vm("safe-reload", "--model")
        self.assertEqual(result.returncode, 3)
        self.assertIn("REFUSED", result.stderr)
        self.assertEqual(self.calls("bridge.ps1 reload") + self.calls("sync-model.ps1"), [])

    def test_unsaved_flag_from_our_own_reload_is_allowed(self):
        self.assertEqual(self.run_vm("safe-reload").returncode, 0)
        self.answers(status=[instance(100, True)])
        self.assertEqual(self.run_vm("safe-reload").returncode, 0)
        self.assertEqual(len(self.calls("bridge.ps1 reload")), 2)

    def test_a_save_in_desktop_clears_the_marker(self):
        self.assertEqual(self.run_vm("safe-reload").returncode, 0)
        self.answers(reload_fails=3)
        self.assertEqual(self.run_vm("safe-reload").returncode, 5)
        self.assertFalse(self.marker().exists())

    def test_reload_is_retried_while_desktop_is_busy(self):
        self.answers(reload_fails=2)
        result = self.run_vm("safe-reload")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls("bridge.ps1 reload")), 3)
        self.assertIn("reload attempt 2 failed", result.stderr)

    def test_three_failed_reloads_exit_5_without_a_marker(self):
        self.answers(reload_fails=3)
        result = self.run_vm("safe-reload")
        self.assertEqual(result.returncode, 5)
        self.assertEqual(len(self.calls("bridge.ps1 reload")), 3)
        self.assertFalse(self.marker().exists())

    def test_several_open_files_need_a_pid(self):
        self.answers(status=[instance(100, False), instance(200, False), instance(300, False, path="")])
        result = self.run_vm("safe-reload")
        self.assertEqual(result.returncode, 4)
        self.assertEqual(self.calls("bridge.ps1 reload"), [])
        self.assertEqual(self.run_vm("safe-reload", "--pid", "200").returncode, 0)
        self.assertIn("reload --pid 200", self.calls("bridge.ps1 reload")[0])
        self.assertTrue(self.marker(200).is_file())

    def test_an_unknown_pid_is_refused(self):
        result = self.run_vm("safe-reload", "--pid", "999")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.calls("bridge.ps1 reload"), [])

    # --- model write

    def test_model_reload_writes_the_model_first(self):
        result = self.run_vm("safe-reload", "--model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"sync-model.ps1 -DesktopPid 100 -Pbip {PBIP} -Apply", self.calls("sync-model.ps1")[0])
        log = (self.stub / "log").read_text()
        self.assertLess(log.index("sync-model.ps1"), log.index("bridge.ps1 reload"))

    def test_a_failed_model_write_stops_before_the_reload(self):
        self.answers(sync={"status": "error", "message": "No msmdsrv.exe child"}, sync_exit=1)
        result = self.run_vm("safe-reload", "--model")
        self.assertEqual(result.returncode, 5)
        self.assertIn("No msmdsrv.exe child", result.stdout)
        self.assertEqual(self.calls("bridge.ps1 reload"), [])

    def test_table_differences_warn_and_still_reload(self):
        self.answers(sync={"status": "ok", "changes": [], "unsupported": ["table only in files: Budget"]})
        result = self.run_vm("safe-reload", "--model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING", result.stderr)

    def test_sync_model_is_a_dry_run(self):
        result = self.run_vm("sync-model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ok")
        self.assertTrue(self.calls("sync-model.ps1")[0].endswith(f"-Pbip {PBIP}"))
        self.answers(sync={"status": "error", "message": "boom"}, sync_exit=1)
        self.assertEqual(self.run_vm("sync-model").returncode, 5)

    # --- screenshots

    def test_shot_prints_the_png_path(self):
        result = self.run_vm("shot", "page1", "run1")
        self.assertEqual(result.returncode, 0, result.stderr)
        png = self.work / "shots" / "run1" / "page1.png"
        self.assertEqual(result.stdout.strip(), str(png))
        self.assertTrue(png.is_file())
        self.assertIn(
            "screenshot page1 --output \\\\Mac\\Home\\proj\\.pbi-desktop\\shots\\run1\\page1.png --scale 1",
            self.calls("bridge.ps1 screenshot")[0],
        )

    def test_shot_without_a_png_exits_5(self):
        result = self.run_vm("shot", "missing", "run1")
        self.assertEqual(result.returncode, 5)
        self.assertIn("no screenshot", result.stderr)

    def test_shots_lists_every_png(self):
        result = self.run_vm("shots", "run2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.split(),
            [str(self.work / "shots" / "run2" / name) for name in ("AWS.png", "Azure.png")],
        )


if __name__ == "__main__":
    unittest.main()
