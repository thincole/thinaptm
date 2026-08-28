@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm - Tao Video Google Flow

:: Kill instance cu neu con chay
taskkill /f /im pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo Dang kiem tra cap nhat tu GitHub (thincole/thinaptm)...
pythonw update.py
start "" pythonw thin_aptm.py
