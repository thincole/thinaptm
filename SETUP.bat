@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm - CAI DAT (chay 1 lan)
echo ============================================
echo    Thin Aptm - Cai dat cho may moi
echo ============================================
echo.
echo [1/3] Kiem tra Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo   !!! CHUA CO PYTHON.
  echo   -> Tai Python 3.10+ tai  https://www.python.org/downloads/
  echo   -> Khi cai NHO TICH "Add Python to PATH".
  echo   Cai xong chay lai SETUP.bat.
  pause & exit /b
)
python --version
echo.
echo [2/3] Nang cap pip...
python -m pip install --upgrade pip -q
echo.
echo [3/3] Cai thu vien cho phan mem...
python -m pip install -r requirements.txt
echo.
echo LUU Y MOI TRUONG:
echo 1. Tinh nang "Tu login/DrissionPage" CAN CO Google Chrome cai san tren may.
echo 2. Tinh nang "Ghep video / Phu de / Nhac nen" CAN CO FFmpeg trong PATH.
echo.
echo ============================================
echo    CAI XONG! Chay  CHAY.bat  de mo tool.
echo ============================================
pause

