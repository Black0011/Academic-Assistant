@echo off
set VENV=E:\Academic-Agent-F\academic-agent-framework\.venv\Scripts
set ROOT=E:\Academic-Agent-F\academic-agent-framework

REM Kill existing backend
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8000.*LISTENING') do taskkill /F /PID %%p 2>nul

REM Start backend with venv python
start /B "" "%VENV%\python.exe" -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000 > "%ROOT%\logs\backend.out.log" 2> "%ROOT%\logs\backend.err.log"

echo Backend starting with venv Python: %VENV%\python.exe
