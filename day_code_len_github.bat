@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm - Day Code Len GitHub (thincole/thinaptm)

echo ====================================================
echo    THIN APTM - DAY CODE MOI LEN GITHUB
echo    Repo: https://github.com/thincole/thinaptm
echo ====================================================
echo.

REM Kiem tra va thiet lap identity Git neu chua co
git config user.name >nul 2>&1
if errorlevel 1 (
    git config user.name "thincole"
    git config user.email "thincole@gmail.com"
)

if not exist ".git" (
    echo [!] Chua khoi tao Git repository trong thu muc nay.
    echo [*] Dang khoi tao Git va ket noi voi repo thincole/thinaptm...
    git init
    git branch -M main
    git remote add origin https://github.com/thincole/thinaptm.git
    echo.
)

echo [1/4] Tu dong tang so Version trong thin_aptm.py...
python bump_version.py
if exist "new_version.txt" (
    set /p NEW_VER=<new_version.txt
    del new_version.txt >nul 2>&1
)
if "%NEW_VER%"=="" set NEW_VER=ThinAPTM Version Cap Nhat

echo.
echo [2/4] Dang kiem tra va gom cac file vao Git...
git add .
echo.

echo [3/4] Dang tao Commit tu dong: "%NEW_VER%"...
git commit -m "Update %NEW_VER%"

echo.
echo [4/4] Dang day code len GitHub (thincole/thinaptm - main)...
git push origin main

if errorlevel 1 (
    echo.
    echo ====================================================
    echo [!] DAY CODE THAT BAI!
    echo Neu GitHub bao loi conflict:
    echo   -> Mo CMD va chay: git pull origin main --rebase
    echo   -> Sau do chay lai day_code_len_github.bat
    echo ====================================================
) else (
    echo.
    echo ====================================================
    echo [=== CHUC MUNG! DAY CODE VERSION %NEW_VER% THANH CONG! ===]
    echo ====================================================
)

echo.
pause
