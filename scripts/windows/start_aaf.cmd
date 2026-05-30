@echo off
chcp 65001 >nul
title Academic Assistant — Starting
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_aaf.ps1"
echo.
echo Press any key to close this window (services keep running in background).
pause >nul
