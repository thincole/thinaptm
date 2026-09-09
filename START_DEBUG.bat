@echo off
:: Kill instance cu neu con chay
taskkill /f /im pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul

cd /d E:\ThinAptm0707
python thin_aptm.py 2> "%~dp0crash_log.txt"
echo Exit code: %ERRORLEVEL% >> "%~dp0crash_log.txt"
pause
