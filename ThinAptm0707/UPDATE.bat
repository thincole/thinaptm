@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm - Cap Nhat Online Tu GitHub

echo ====================================================
echo    THIN APTM - CAP NHAT CHUYEN DOI SANG GITHUB
echo    Repo: https://github.com/thincole/thinaptm
echo ====================================================
echo.
echo [*] Dang tai file update.py moi nhat tu GitHub...

python -c "import urllib.request; open('update.py','wb').write(urllib.request.urlopen('https://raw.githubusercontent.com/thincole/thinaptm/main/update.py').read())"

if errorlevel 1 (
    echo.
    echo [!] Tai update.py that bai! Vui long kiem tra lai ket noi Internet.
    echo.
    pause
    exit /b
)

echo.
echo [*] Dang tien hanh dong bo tat ca cac file code moi nhat tu GitHub...
python update.py

echo.
echo ====================================================
echo    [=== CAP NHAT HOAN TAT! ===]
echo    Tu bay gio, ban chi cun chay file CHAY.bat 
echo    de mo tool va tu dong cap nhat online!
echo ====================================================
echo.
pause
