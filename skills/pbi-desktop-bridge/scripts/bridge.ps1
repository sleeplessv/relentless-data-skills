param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Rest)
# Runs the Power BI Desktop Bridge CLI inside the VM. Called from pbi-vm.sh on the Mac.
$ProgressPreference = 'SilentlyContinue'
# The CLI cannot find the Microsoft Store build of Desktop by itself, so point it there.
$pkg = Get-AppxPackage Microsoft.MicrosoftPowerBIDesktop
if ($pkg) { $env:PBI_DESKTOP_PATH = Join-Path $pkg.InstallLocation 'bin\PBIDesktop.exe' }
$cli = Join-Path $env:APPDATA 'npm\powerbi-desktop.cmd'
if (-not (Test-Path $cli)) { Write-Output "The Bridge CLI is not installed in the VM. Run: pbi-vm.sh setup"; exit 2 }
& $cli @Rest 2>&1 | ForEach-Object { "$_" }
exit $LASTEXITCODE
