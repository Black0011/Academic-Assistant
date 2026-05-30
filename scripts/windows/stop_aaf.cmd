@echo off
chcp 65001 >nul
title Academic Assistant — Stopping
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_aaf.ps1"
echo.
echo Press any key to close this window.
pause >nul
