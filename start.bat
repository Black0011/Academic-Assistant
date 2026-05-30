@echo off
chcp 65001 >nul
title Academic Assistant — Running

echo.
echo ╔══════════════════════════════════════════════╗
echo ║      Academic Assistant — Starting...        ║
echo ╚══════════════════════════════════════════════╝
echo.

:: ── Check .env ────────────────────────────────────────────
if not exist ".env" (
    echo [ERROR] .env not found. Run install.bat first.
    pause
    exit /b 1
)

:: ── Check .venv ───────────────────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

:: ── Start backend ─────────────────────────────────────────
echo [1/2] Starting backend...
if exist "logs\backend.out.log" type "logs\backend.out.log" > "logs\backend.out.log"

start "Academic-Assistant-Backend" /MIN .venv\Scripts\python.exe -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000

:: Wait for backend to be ready
echo   Waiting for backend...
set /a COUNT=0
:wait_backend
timeout /t 1 /nobreak >nul
set /a COUNT+=1
curl -s http://127.0.0.1:8000/api/health >nul 2>&1
if %errorlevel% neq 0 (
    if %COUNT% lss 30 goto wait_backend
    echo   [WARN] Backend may not be ready. Check logs/backend.out.log
) else (
    echo   Backend: http://127.0.0.1:8000 [OK]
)

:: ── Start frontend ────────────────────────────────────────
echo [2/2] Starting frontend...
if not exist "frontend\node_modules" (
    echo   [SKIP] Frontend not installed (Node.js not available).
    echo   Open http://127.0.0.1:8000/api/health for backend health check.
) else (
    start "Academic-Assistant-Frontend" /MIN cmd /c "cd frontend && npx vite --host 127.0.0.1 --port 5173"
    echo   Frontend: starting on http://127.0.0.1:5173
)

:: ── Open browser ──────────────────────────────────────────
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5173

echo.
echo ╔══════════════════════════════════════════════╗
echo ║     Academic Assistant is now running!       ║
echo ║     Frontend: http://127.0.0.1:5173          ║
echo ║     Close this window to keep services on    ║
echo ╚══════════════════════════════════════════════╝
echo.
echo  To stop: close the "Academic-Assistant-*" windows
echo          or run stop.bat
echo.
pause
