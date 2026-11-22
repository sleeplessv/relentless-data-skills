# Installs what pbi-vm.sh needs inside the VM: the Power BI Desktop Bridge CLI (npm) and the TOM library
# (NuGet) that sync-model.ps1 loads. Safe to repeat: it skips what is already there.
# Output: one JSON object, with status "ok" or "error".
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$tomVersion = '19.120.1'   # the version sync-model.ps1 was proven against
try {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
  $cli = Join-Path $env:APPDATA 'npm\powerbi-desktop.cmd'
  $cliInstalled = $false
  if (-not (Test-Path $cli)) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js is not installed in the VM. Install it there, then run setup again.' }
    $ErrorActionPreference = 'Continue'   # npm writes notices to stderr
    npm install -g '@microsoft/powerbi-desktop-bridge-cli' 2>&1 | Out-Null
    $ErrorActionPreference = 'Stop'
    if (-not (Test-Path $cli)) { throw 'npm install -g @microsoft/powerbi-desktop-bridge-cli did not produce powerbi-desktop.cmd' }
    $cliInstalled = $true
  }

  $dst = Join-Path $env:LOCALAPPDATA 'pbi-desktop-bridge\tom'
  $dll = Join-Path $dst 'pkg\lib\net472\Microsoft.AnalysisServices.Tabular.dll'
  $tomInstalled = $false
  if (-not (Test-Path $dll)) {
    New-Item -ItemType Directory -Force $dst | Out-Null
    $zip = Join-Path $dst "tom.$tomVersion.zip"
    Invoke-WebRequest -UseBasicParsing "https://api.nuget.org/v3-flatcontainer/microsoft.analysisservices/$tomVersion/microsoft.analysisservices.$tomVersion.nupkg" -OutFile $zip
    Expand-Archive $zip -DestinationPath (Join-Path $dst 'pkg') -Force
    if (-not (Test-Path $dll)) { throw "The TOM package did not contain $dll" }
    $tomInstalled = $true
  }

  $pkg = Get-AppxPackage Microsoft.MicrosoftPowerBIDesktop
  [pscustomobject]@{
    status       = 'ok'
    bridgeCli    = $cli
    cliInstalled = $cliInstalled
    tomPackage   = $tomVersion
    tomInstalled = $tomInstalled
    storeDesktop = if ($pkg) { "$($pkg.Version)" } else { $null }
  } | ConvertTo-Json
} catch {
  [pscustomobject]@{ status = 'error'; message = "$($_.Exception.Message)" } | ConvertTo-Json
  exit 1
}
