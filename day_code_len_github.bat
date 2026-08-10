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

echo [1/3] Dang kiem tra va them cac file vao Git...
git add .
echo.

echo [2/3] Dang tao Commit...
git commit -m "Update ThinAPTM 1.2.0"

echo.
echo [3/3] Dang day code len GitHub (thincole/thinaptm - main)...
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
    echo [=== CHUC MUNG! DAY CODE LEN GITHUB THANH CONG! ===]
    echo ====================================================
)

echo.
pause
