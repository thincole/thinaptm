@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm - Tao Video Google Flow
echo Dang kiem tra cap nhat tu GitHub (thincole/thinaptm)...
python update.py
start "" pythonw thin_aptm.py

