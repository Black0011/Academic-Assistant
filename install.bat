@echo off
chcp 65001 >nul
title Academic Assistant - One-Click Setup

echo.
echo ╔══════════════════════════════════════════════╗
echo ║    Academic Assistant — One-Click Installer  ║
echo ╚══════════════════════════════════════════════╝
echo.
echo This will install and configure everything automatically.
echo.

:: ── Check Python ──────────────────────────────────────────
echo [1/6] Checking Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.11+ from:
    echo   https://www.python.org/downloads/
    echo   Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python -c "import sys; print(sys.version_info[0])"') do set PYVER=%%v
for /f "tokens=2" %%v in ('python -c "import sys; print(sys.version_info[1])"') do set PYMINOR=%%v
for /f "tokens=2" %%v in ('python -c "import sys; print(sys.version_info[2])"') do set PYMICRO=%%v
echo   Found Python %PYVER%.%PYMINOR%.%PYMICRO%

:: ── Check Node.js ─────────────────────────────────────────
echo [2/6] Checking Node.js...
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Node.js not found — frontend build will be skipped.
    echo   Install from: https://nodejs.org/
    set NO_FRONTEND=1
) else (
    echo   Found Node.js
)

:: ── Create virtual environment ────────────────────────────
echo [3/6] Setting up Python environment...
if not exist ".venv" (
    python -m venv .venv
    echo   Virtual environment created.
) else (
    echo   Virtual environment already exists.
)

:: ── Install Python dependencies ──────────────────────────
echo [4/6] Installing Python packages (this may take a few minutes)...
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet -e .
.venv\Scripts\pip install --quiet mcp scholarly requests beautifulsoup4
echo   Python packages installed.

:: ── Create .env if missing ────────────────────────────────
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo   Created .env from .env.example
        echo   [IMPORTANT] Edit .env to set your API key:
        echo     OPENAI_API_KEY=sk-your-key-here
    ) else (
        echo   [IMPORTANT] Create .env with your API key.
    )
) else (
    echo   .env already exists.
)

:: ── MCP config ────────────────────────────────────────────
if not exist "config\mcp_servers.yaml" (
    if exist "config\mcp_servers.example.yaml" (
        copy "config\mcp_servers.example.yaml" "config\mcp_servers.yaml" >nul
        echo   Created MCP config.
    )
)

:: ── Install frontend deps ─────────────────────────────────
echo [5/6] Setting up frontend...
if "%NO_FRONTEND%"=="1" (
    echo   [SKIP] Node.js not available.
) else (
    if not exist "frontend\node_modules" (
        echo   Installing frontend dependencies (one-time, may take a while)...
        cd frontend
        call npm install --silent
        cd ..
    )
    echo   Frontend ready.
)

:: ── Desktop shortcuts ─────────────────────────────────────
echo [6/6] Creating desktop shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\install_shortcuts.ps1"

:: ── Done ──────────────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════════╗
echo ║          Installation complete!              ║
echo ╚══════════════════════════════════════════════╝
echo.
echo   Desktop shortcuts created:
echo     AAF-Start — Launch Academic Assistant
echo     AAF-Stop  — Stop all services
echo.
echo   To start: double-click AAF-Start on your desktop
echo   Frontend: http://127.0.0.1:5173
echo   Backend:  http://127.0.0.1:8000
echo.
echo   If using DeepSeek (recommended for users in China):
echo     OPENAI_API_KEY=sk-your-deepseek-key
echo     OPENAI_BASE_URL=https://api.deepseek.com/v1
echo     OPENAI_DEFAULT_MODEL=deepseek-v4-flash
echo.
pause
