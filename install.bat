@echo off
chcp 65001 >nul
title Academic Assistant - One-Click Setup

set "HAS_ERROR=0"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║    Academic Assistant — One-Click Installer  ║
echo ╚══════════════════════════════════════════════╝
echo.
echo This will install and configure everything automatically.
echo.

:: ── Step 1: Check Python ──────────────────────────────────
echo [1/7] Checking Python...
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

:: ── Step 2: Check Node.js ─────────────────────────────────
echo [2/7] Checking Node.js...
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Node.js not found — frontend will be skipped.
    echo   Install Node.js 18+ from: https://nodejs.org/
    echo   Or: https://npmmirror.com/mirrors/node/ (faster in China)
    set NO_FRONTEND=1
) else (
    for /f "tokens=1,2,3 delims=." %%a in ('node -v') do set NODE_VER=%%a %%b %%c
    echo   Found Node.js
)

:: ── Step 3: Configure mirrors (for users in China) ────────
echo [3/7] Configuring package mirrors...
:: npm — use npmmirror (Alibaba) for faster downloads in China
call npm config set registry https://registry.npmmirror.com >nul 2>&1
:: pip — use Tsinghua mirror
.venv\Scripts\python -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
echo   Mirrors configured (npmmirror + Tsinghua).

:: ── Step 4: Create virtual environment ────────────────────
echo [4/7] Setting up Python virtual environment...
if not exist ".venv" (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo   Virtual environment created.
) else (
    echo   Virtual environment already exists.
)

:: ── Step 5: Install Python dependencies ──────────────────
echo [5/7] Installing Python packages (this may take a few minutes)...
echo.
.venv\Scripts\python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo [WARN] pip upgrade failed, continuing anyway...
)
echo.
echo   Installing core dependencies...
.venv\Scripts\pip install -e .
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python package install failed!
    echo   This usually means a dependency needs a C++ compiler.
    echo   Try installing Visual Studio Build Tools:
    echo     https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo   Or install Microsoft C++ Build Tools via:
    echo     winget install Microsoft.VisualStudio.2022.BuildTools
    echo.
    set HAS_ERROR=1
) else (
    echo   Python packages installed successfully.
)
echo.

:: ── Step 6: Install frontend dependencies ─────────────────
echo [6/7] Setting up frontend...
if "%NO_FRONTEND%"=="1" (
    echo   [SKIP] Node.js not available. Frontend cannot be installed.
    echo   The backend API will still work at http://127.0.0.1:8000
) else (
    if not exist "frontend\node_modules" (
        echo   Installing frontend dependencies (one-time, 1-3 minutes)...
        echo.
        cd frontend
        call npm install
        set NPM_EXIT=%errorlevel%
        cd ..
        echo.
        if %NPM_EXIT% neq 0 (
            echo [ERROR] npm install failed (exit code: %NPM_EXIT%).
            echo.
            echo   Common fixes:
            echo   1. Delete node_modules and retry:
            echo      rmdir /s /q frontend\node_modules
            echo      npm cache clean --force
            echo      cd frontend ^&^& npm install
            echo.
            echo   2. Try a different npm mirror:
            echo      npm config set registry https://registry.npmjs.org
            echo      cd frontend ^&^& npm install
            echo.
            echo   3. Use --legacy-peer-deps:
            echo      cd frontend ^&^& npm install --legacy-peer-deps
            echo.
            set HAS_ERROR=1
        ) else (
            :: Verify node_modules actually exists
            if exist "frontend\node_modules\*" (
                echo   Frontend installed successfully.
            ) else (
                echo [ERROR] npm install completed but node_modules is missing.
                echo   Try: cd frontend ^&^& npm install --legacy-peer-deps
                set HAS_ERROR=1
            )
        )
    ) else (
        echo   Frontend dependencies already installed.
    )
)

:: ── Step 7: Create config files ───────────────────────────
echo [7/7] Creating configuration files...

:: .env
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo   Created .env from .env.example
        echo.
        echo   ╔══════════════════════════════════════════════╗
        echo   ║  ^>^>^>  IMPORTANT: Edit .env NOW!  ^<^<^<        ║
        echo   ║                                            ║
        echo   ║  Open .env in Notepad and replace:         ║
        echo   ║  OPENAI_API_KEY=sk-your-key-here           ║
        echo   ║  with your actual DeepSeek API key.        ║
        echo   ║                                            ║
        echo   ║  Get a key at:                             ║
        echo   ║  https://platform.deepseek.com             ║
        echo   ║                                            ║
        echo   ║  Without a real key, the assistant         ║
        echo   ║  will NOT work!                            ║
        echo   ╚══════════════════════════════════════════════╝
        echo.
    ) else (
        echo   [WARN] .env.example not found.
    )
) else (
    :: Check if .env still has placeholder API key
    findstr /C:"sk-your-key-here" ".env" >nul 2>&1
    if %errorlevel% equ 0 (
        echo.
        echo   ╔══════════════════════════════════════════════╗
        echo   ║  ^>^>^>  WARNING: API key not set!  ^<^<^<        ║
        echo   ║                                            ║
        echo   ║  .env still has placeholder key:           ║
        echo   ║  OPENAI_API_KEY=sk-your-key-here           ║
        echo   ║                                            ║
        echo   ║  Edit .env and paste your real key.        ║
        echo   ║  Get one at: platform.deepseek.com         ║
        echo   ║                                            ║
        echo   ║  Without a real key, the assistant         ║
        echo   ║  will NOT work!                            ║
        echo   ╚══════════════════════════════════════════════╝
        echo.
    ) else (
        echo   .env already configured.
    )
)

:: MCP config
if not exist "config\mcp_servers.yaml" (
    if exist "config\mcp_servers.example.yaml" (
        copy "config\mcp_servers.example.yaml" "config\mcp_servers.yaml" >nul
        echo   Created MCP config from example.
    )
)

:: Create data directories
if not exist "data" mkdir data
if not exist "data\knowledge" mkdir data\knowledge
if not exist "data\manuscripts" mkdir data\manuscripts
if not exist "logs" mkdir logs

:: ── Desktop shortcuts ─────────────────────────────────────
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\install_shortcuts.ps1" 2>nul
if %errorlevel% equ 0 (
    echo   Desktop shortcuts created.
) else (
    echo   [WARN] Could not create desktop shortcuts (non-critical).
)

:: ── Done ──────────────────────────────────────────────────
echo.
if "%HAS_ERROR%"=="1" (
    echo ╔══════════════════════════════════════════════╗
    echo ║  Installation completed WITH WARNINGS.      ║
    echo ║  Please fix the errors above, then re-run   ║
    echo ║  install.bat before starting.               ║
    echo ╚══════════════════════════════════════════════╝
) else (
    echo ╔══════════════════════════════════════════════╗
    echo ║       Installation complete!                 ║
    echo ╚══════════════════════════════════════════════╝
)
echo.
echo   To start: double-click AAF-Start on your desktop
echo   Frontend: http://127.0.0.1:5173
echo   Backend:  http://127.0.0.1:8000/api/health
echo.
echo   API Key setup (REQUIRED):
echo     Get a key: https://platform.deepseek.com
echo     Edit .env: OPENAI_API_KEY=sk-your-real-key
echo.
pause
