$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$LogsDir = Join-Path $RepoRoot "logs"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $RepoRoot "frontend"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Get-FreePort([int[]]$Ports) {
    foreach ($p in $Ports) {
        $inUse = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if (-not $inUse) { return $p }
    }
    return $null
}

# ── Backend ────────────────────────────────────────────────────────────────

if (-not (Test-Path $VenvPython)) {
    Write-Host "Missing venv python: $VenvPython"
    Write-Host "Create it first: py -3.11 -m venv .venv"
    exit 1
}

$backendPort = 8000
$backendInUse = Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue
if ($backendInUse) {
    Write-Host "[WARN] Backend port $backendPort is already in use — reusing existing backend."
} else {
    $backendOut = Join-Path $LogsDir "backend.out.log"
    $backendErr = Join-Path $LogsDir "backend.err.log"
    Start-Process -FilePath $VenvPython -ArgumentList @(
        "-m", "uvicorn", "backend.app:create_app",
        "--factory", "--host", "127.0.0.1", "--port", $backendPort
    ) -WorkingDirectory $RepoRoot -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
    Write-Host "Backend starting: http://127.0.0.1:$backendPort"
}

# Frontend

$frontendPort = Get-FreePort @([int]5173, [int]5174)
if (-not $frontendPort) {
    Write-Host "[WARN] Frontend ports 5173/5174 are in use. Checking if Vite is already running on one of them..."
    $frontendPort = 5173  # re-check below
}
$feInUse = Get-NetTCPConnection -LocalPort $frontendPort -State Listen -ErrorAction SilentlyContinue
if ($feInUse) {
    Write-Host "Frontend already running on http://127.0.0.1:$frontendPort"
} else {
    # Use npx vite directly instead of npm run dev.
    # On Windows, npm's process manager can hit ENOSPC when stdout/stderr
    # are redirected to log files, so npx vite is safer here.
    $viteCmd = Join-Path $FrontendDir "node_modules\.bin\vite.cmd"
    if (-not (Test-Path $viteCmd)) {
        Write-Host "vite.cmd not found, trying npx..."
        $viteCmd = "npx"
        $viteArgs = @("vite", "--host", "127.0.0.1", "--port", $frontendPort)
    } else {
        $viteArgs = @("--host", "127.0.0.1", "--port", $frontendPort)
    }
    $frontendOut = Join-Path $LogsDir "frontend.out.log"
    $frontendErr = Join-Path $LogsDir "frontend.err.log"
    Start-Process -FilePath $viteCmd `
        -ArgumentList $viteArgs `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr
    Write-Host "Frontend starting: http://127.0.0.1:$frontendPort"
}

Write-Host "Logs: $LogsDir"
Write-Host ""

# Open browser when the frontend is ready.

$frontendUrl = "http://127.0.0.1:$frontendPort"
function Wait-ForPort {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 60
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listening) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

try {
    if (Wait-ForPort -Port $frontendPort -TimeoutSeconds 60) {
        Start-Process $frontendUrl
        Write-Host "Opened $frontendUrl in your default browser."
    } else {
        Write-Host "Frontend did not become ready within 60s. Open $frontendUrl manually if needed."
    }
} catch {
    Write-Host "Open $frontendUrl in your browser to start."
}