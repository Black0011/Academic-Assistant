$ErrorActionPreference = "Continue"

$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).ToString()
$Desktop = [Environment]::GetFolderPath("Desktop")

$StartCmd = Join-Path $ScriptDir "start_aaf.cmd"
$StopCmd = Join-Path $ScriptDir "stop_aaf.cmd"

if (-not (Test-Path $StartCmd)) {
    Write-Host "[ERROR] start_aaf.cmd not found at $StartCmd"
    exit 1
}
if (-not (Test-Path $StopCmd)) {
    Write-Host "[ERROR] stop_aaf.cmd not found at $StopCmd"
    exit 1
}

Write-Host "Creating desktop shortcuts..."
Write-Host "  Source: $ScriptDir"
Write-Host "  Desktop: $Desktop"
Write-Host ""

$WshShell = New-Object -ComObject WScript.Shell

# ── AAF-Start ──────────────────────────────────────────────
$StartLink = Join-Path $Desktop "AAF-Start.lnk"
if (Test-Path $StartLink) { Remove-Item $StartLink -Force }
$lnk = $WshShell.CreateShortcut($StartLink)
$lnk.TargetPath = $StartCmd
$lnk.WorkingDirectory = $RepoRoot
$lnk.Description = "Start Academic Assistant"
$lnk.IconLocation = "shell32.dll,14"
$lnk.Save()
Write-Host "  AAF-Start.lnk ✓"

# ── AAF-Stop ───────────────────────────────────────────────
$StopLink = Join-Path $Desktop "AAF-Stop.lnk"
if (Test-Path $StopLink) { Remove-Item $StopLink -Force }
$lnk = $WshShell.CreateShortcut($StopLink)
$lnk.TargetPath = $StopCmd
$lnk.WorkingDirectory = $RepoRoot
$lnk.Description = "Stop Academic Assistant"
$lnk.IconLocation = "shell32.dll,27"
$lnk.Save()
Write-Host "  AAF-Stop.lnk ✓"

Write-Host ""
Write-Host "Done. Double-click AAF-Start on your desktop to launch."
