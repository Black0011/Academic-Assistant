@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Academic Assistant — Running

echo.
echo ╔══════════════════════════════════════════════╗
echo ║      Academic Assistant — Starting...        ║
echo ╚══════════════════════════════════════════════╝
echo.

:: ── Check prerequisites ───────────────────────────────────
if not exist ".env" (
    echo [ERROR] .env not found. Run install.bat first.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

:: Warn if API key is still the placeholder
findstr /C:"sk-your-key-here" ".env" >nul 2>&1
if !errorlevel! equ 0 (
    echo [WARN] .env still has placeholder API key — assistant will NOT work.
    echo   Get a key at https://platform.deepseek.com and edit .env
    echo.
)

:: ── Start backend ─────────────────────────────────────────
echo [1/2] Starting backend...

:: Clear old log (avoid "type log > log" which truncates before reading)
if exist "logs\backend.out.log" break > "logs\backend.out.log"

start "Academic-Assistant-Backend" /MIN .venv\Scripts\python.exe -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000

:: Wait for backend
echo   Waiting for backend...
set COUNT=0
:wait_backend
timeout /t 1 /nobreak >nul
set /a COUNT+=1
curl -s http://127.0.0.1:8000/api/health >nul 2>&1
if !errorlevel! equ 0 goto backend_ok
if !COUNT! lss 30 goto wait_backend
echo   [WARN] Backend did not respond in 30s. Check logs\backend.out.log
goto frontend_start

:backend_ok
echo   Backend ready: http://127.0.0.1:8000

:: ── Start frontend ────────────────────────────────────────
:frontend_start
echo [2/2] Starting frontend...
if not exist "frontend\node_modules" (
    echo   [SKIP] Frontend dependencies not found.
    echo   Run install.bat first, or run:
    echo     cd frontend ^&^& npm install
    echo.
    echo   Backend API available at: http://127.0.0.1:8000/api/health
    goto done
)

:: Use pushd/popd to avoid && inside start command (causes ". was unexpected" error)
pushd frontend
start "Academic-Assistant-Frontend" /MIN npx vite --host 127.0.0.1 --port 5173
popd
echo   Frontend: starting on http://127.0.0.1:5173

:: ── Open browser ──────────────────────────────────────────
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5173

:done
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
