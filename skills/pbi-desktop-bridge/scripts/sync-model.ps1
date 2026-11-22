param(
  [Parameter(Mandatory = $true)] [int] $DesktopPid,
  [string] $Pbip,
  [string] $Definition,
  [switch] $Apply
)
# Push measure edits from a TMDL definition folder into the model of a running Power BI Desktop.
# The Bridge's file.reload reports success but leaves TMDL edits unapplied (seen in Desktop 2.159), so this
# writes them through Desktop's local Analysis Services instance, the path external tools use.
# Scope: measures only (add, change, remove) in tables that exist on both sides. A table on one side only
# is listed under "unsupported". Edits to columns, relationships and Power Query are not compared at all.
# -Pbip is the .pbip Desktop has open; the definition folder is found from it. -Definition names it directly.
# Without -Apply it only reports. Output: one JSON object, with status "ok" or "error".
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
  if (-not $Definition) {
    if ($Pbip -notlike '*.pbip') { throw "Desktop has '$Pbip' open. A model write needs a .pbip project with TMDL files." }
    $reportDir = Join-Path (Split-Path -Parent $Pbip) (Get-Content -Raw -LiteralPath $Pbip | ConvertFrom-Json).artifacts[0].report.path
    $ref = (Get-Content -Raw -LiteralPath (Join-Path $reportDir 'definition.pbir') | ConvertFrom-Json).datasetReference
    if (-not $ref.byPath) { throw 'The report is bound to a published semantic model, so there are no local TMDL files to write.' }
    $Definition = [IO.Path]::GetFullPath((Join-Path (Join-Path $reportDir $ref.byPath.path) 'definition'))
  }
  if (-not (Test-Path -LiteralPath $Definition)) { throw "No TMDL definition folder at $Definition" }

  $lib = Join-Path $env:LOCALAPPDATA 'pbi-desktop-bridge\tom\pkg\lib\net472'
  if (-not (Test-Path (Join-Path $lib 'Microsoft.AnalysisServices.Tabular.dll'))) { throw 'The TOM library is not installed in the VM. Run: pbi-vm.sh setup' }
  # LoadFrom, not Add-Type: Add-Type enumerates every type and fails on the Azure sign-in types,
  # whose dependency (Microsoft.Identity.Client) a localhost connection does not need.
  foreach ($n in 'Core', 'Tabular.Json', 'Tabular') { [void][Reflection.Assembly]::LoadFrom((Join-Path $lib "Microsoft.AnalysisServices.$n.dll")) }

  # Desktop's model server (msmdsrv) is its child process; find the port it listens on.
  $child = Get-CimInstance Win32_Process -Filter "Name='msmdsrv.exe' AND ParentProcessId=$DesktopPid" | Select-Object -First 1
  if (-not $child) { throw "No msmdsrv.exe child of Desktop pid $DesktopPid" }
  $port = (Get-NetTCPConnection -State Listen -OwningProcess $child.ProcessId | Select-Object -First 1).LocalPort

  $fdb = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeDatabaseFromFolder($Definition)
  $srv = New-Object Microsoft.AnalysisServices.Tabular.Server
  $srv.Connect("Data Source=localhost:$port")
  try {
    $db = $srv.Databases[0]
    $changes = @(); $unsupported = @()
    $props = 'Expression', 'FormatString', 'DisplayFolder', 'Description', 'IsHidden'
    foreach ($ft in $fdb.Model.Tables) {
      $lt = $db.Model.Tables.Find($ft.Name)
      if (-not $lt) { $unsupported += "table only in files: $($ft.Name)"; continue }
      foreach ($fm in $ft.Measures) {
        $lm = $lt.Measures.Find($fm.Name)
        if (-not $lm) {
          $changes += [pscustomobject]@{ action = 'add'; table = $ft.Name; measure = $fm.Name }
          if ($Apply) { $lt.Measures.Add($fm.Clone()) }
          continue
        }
        # -cne: a change of letter case alone is a change. FormatStringDefinition is the dynamic format string.
        $diff = @($props | Where-Object { [string]$lm.$_ -cne [string]$fm.$_ })
        if ([string]$lm.FormatStringDefinition.Expression -cne [string]$fm.FormatStringDefinition.Expression) { $diff += 'FormatStringDefinition' }
        if ($diff.Count) {
          $changes += [pscustomobject]@{ action = 'change'; table = $ft.Name; measure = $fm.Name; properties = $diff }
          if ($Apply) { foreach ($p in $diff) { $lm.$p = if ($p -eq 'FormatStringDefinition' -and $fm.$p) { $fm.$p.Clone() } else { $fm.$p } } }
        }
      }
      foreach ($lm in @($lt.Measures)) {
        if (-not $ft.Measures.Find($lm.Name)) {
          $changes += [pscustomobject]@{ action = 'remove'; table = $ft.Name; measure = $lm.Name }
          if ($Apply) { [void]$lt.Measures.Remove($lm) }
        }
      }
    }
    foreach ($lt in $db.Model.Tables) { if (-not $fdb.Model.Tables.Find($lt.Name)) { $unsupported += "table only in Desktop: $($lt.Name)" } }
    $saved = $false
    if ($Apply -and $changes.Count) { [void]$db.Model.SaveChanges(); $saved = $true }
    [pscustomobject]@{ status = 'ok'; definition = $Definition; port = $port; database = $db.Name; applied = [bool]$Apply; saved = $saved; changes = $changes; unsupported = $unsupported } | ConvertTo-Json -Depth 5
  } finally { $srv.Disconnect() }
} catch {
  [pscustomobject]@{ status = 'error'; message = "$($_.Exception.Message)" } | ConvertTo-Json
  exit 1
}
