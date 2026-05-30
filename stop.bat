@echo off
chcp 65001 >nul
echo Stopping Academic Assistant...

:: Kill backend (port 8000)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8000.*LISTENING') do (
    taskkill /F /PID %%p >nul 2>&1
    echo   Backend stopped.
)

:: Kill frontend (port 5173)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :5173.*LISTENING') do (
    taskkill /F /PID %%p >nul 2>&1
    echo   Frontend stopped.
)

echo Done.
pause
