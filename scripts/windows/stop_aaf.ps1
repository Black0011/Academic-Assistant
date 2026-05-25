$ErrorActionPreference = "Stop"

function Stop-ByPort([int]$Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        try {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        } catch {
            # Ignore processes that already exited
        }
    }
}

Stop-ByPort 8000
Stop-ByPort 5173
Stop-ByPort 5174

Write-Host "Stopped any AAF processes listening on 8000/5173/5174."