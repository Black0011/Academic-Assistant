$ErrorActionPreference = "Continue"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$LogsDir = Join-Path $RepoRoot "logs"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $RepoRoot "frontend"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Test-PortInUse([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $conn
}

function Stop-PortOwner([int]$Port) {
    $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($c in $conns) {
        try {
            $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "  Stopping $($proc.ProcessName) (PID $($c.OwningProcess)) on port $Port..."
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    Start-Sleep -Milliseconds 800
}

# ── Prerequisites ────────────────────────────────────────────
if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Python virtual environment not found."
    Write-Host "  Run install.bat first to set up the environment."
    Write-Host "  Expected: $VenvPython"
    exit 1
}
if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    Write-Host "[WARN] .env file not found. The assistant may not function without API keys."
}

# ── Clean up any running instances ─────────────────────────
Write-Host "======================================"
Write-Host "  Academic Assistant — Starting..."
Write-Host "======================================"
Write-Host ""
Write-Host "[1/4] Cleaning up previous instances..."
Stop-PortOwner 8000
Stop-PortOwner 5173
Stop-PortOwner 5174
Write-Host "  Done."

# ── Start Backend ──────────────────────────────────────────
Write-Host "[2/4] Starting backend (http://127.0.0.1:8000)..."
$backendOut = Join-Path $LogsDir "backend.out.log"
$backendErr = Join-Path $LogsDir "backend.err.log"

Start-Process -FilePath $VenvPython -ArgumentList @(
    "-m", "uvicorn", "backend.app:create_app",
    "--factory", "--host", "127.0.0.1", "--port", "8000"
) -WorkingDirectory $RepoRoot -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr

$backendReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($r.StatusCode -eq 200) {
            Write-Host "  Backend ready."
            $backendReady = $true
            break
        }
    } catch { }
}
if (-not $backendReady) {
    Write-Host "  [WARN] Backend may still be starting. Check logs if issues persist."
}

# ── Start Frontend ─────────────────────────────────────────
Write-Host "[3/4] Starting frontend (http://127.0.0.1:5173)..."
$frontendOut = Join-Path $LogsDir "frontend.out.log"
$frontendErr = Join-Path $LogsDir "frontend.err.log"

$hasNpm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $hasNpm) {
    Write-Host "  [SKIP] Node.js / npm not found. Frontend cannot start."
    Write-Host "  Backend API available at: http://127.0.0.1:8000/api/health"
} elseif (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "  [SKIP] Frontend dependencies not installed."
    Write-Host "  Run: cd frontend && npm install"
} else {
    Start-Process -FilePath "cmd.exe" -ArgumentList @(
        "/c", "npm", "--prefix", $FrontendDir, "run", "dev", "--",
        "--host", "127.0.0.1", "--port", "5173"
    ) -WorkingDirectory $RepoRoot -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr

    Start-Sleep -Seconds 5

    # ── Open Browser ──────────────────────────────────────────
    Write-Host "[4/4] Opening browser..."
    Start-Process "http://127.0.0.1:5173"
}

Write-Host ""
Write-Host "======================================"
Write-Host "  Academic Assistant is running!"
Write-Host "  Frontend : http://127.0.0.1:5173"
Write-Host "  Backend  : http://127.0.0.1:8000"
Write-Host "  Logs     : $LogsDir"
Write-Host "======================================"
Write-Host ""
Write-Host "  To stop: double-click AAF-Stop on your desktop"
Write-Host ""
