$ErrorActionPreference = "Continue"

function Stop-ByPort([int]$Port) {
    $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($conns.Count -eq 0) {
        Write-Host "  Port $Port : not in use"
        return
    }
    foreach ($c in $conns) {
        try {
            $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            $name = if ($proc) { $proc.ProcessName } else { "unknown" }
            Write-Host "  Stopping $name (PID $($c.OwningProcess)) on port $Port..."
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        } catch {
            # process already gone
        }
    }
    Start-Sleep -Milliseconds 500
}

Write-Host "======================================"
Write-Host "  Academic Assistant — Stopping..."
Write-Host "======================================"
Write-Host ""

Stop-ByPort 8000
Stop-ByPort 5173
Stop-ByPort 5174

# Verify ports are free
Start-Sleep -Seconds 1
$backendGone = -not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
$frontendGone = -not (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue)

Write-Host ""
if ($backendGone -and $frontendGone) {
    Write-Host "All services stopped."
} else {
    if (-not $backendGone) { Write-Host "[WARN] Port 8000 still in use." }
    if (-not $frontendGone) { Write-Host "[WARN] Port 5173 still in use." }
}
Write-Host ""
