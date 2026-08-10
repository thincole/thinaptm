@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm 2026 - BO CAI DAT MOI TRUONG MULTI-PC
color 0B

echo ====================================================================
echo    BO CAI DAT MOI TRUONG PHAN MEM THIN APTM 2026 (MULTI-PC)
echo ====================================================================
echo.

set ERRORS=0

echo [1/5] Kiem tra Python...
set PYTHON_EXE=python
%PYTHON_EXE% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] Khong tim thay Python trong PATH! Dang thu dung winget...
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo   [FAIL] Khong the cai Python tu dong. Vui long tai Python 3.10+ tai https://www.python.org/
        echo   NHO TICH VAV "Add Python to PATH" KHI CAI!
        pause
        exit /b 1
    )
    set PYTHON_EXE=python
)
for /f "tokens=*" %%V in ('%PYTHON_EXE% --version 2^>^&1') do echo   [OK] %%V

echo.
echo [2/5] Nang cap pip...
%PYTHON_EXE% -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (echo   [WARN] Khong the upgrade pip, tiep tuc dung pip hien tai...) else (echo   [OK] Pip da duoc nang cap)

echo.
echo [3/5] Dang cai dat cac thu vien Python (requirements.txt)...
%PYTHON_EXE% -m pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo   [WARN] Co loi trong qua trinh cai requirements.txt, dang thu cai le tung thu vien...
    %PYTHON_EXE% -m pip install customtkinter curl_cffi pyreqwest_impersonate pillow edge-tts groq google-genai google-generativeai google-auth DrissionPage cryptography pyotp psutil requests
)

echo.
echo [4/5] Kiem tra FFmpeg (Bat buoc de tao Video)...
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] FFmpeg da duoc cai dat va co trong PATH.
) else (
    echo   [WARN] FFmpeg CHUA CO trong PATH! Dang cai bang winget...
    winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    if %errorlevel% equ 0 (
        echo   [OK] FFmpeg da cai thanh cong qua winget!
    ) else (
        echo   [FAIL] Khong the cai FFmpeg tu dong qua winget.
        echo   Vui long tai FFmpeg tu https://www.gyan.dev/ffmpeg/builds/ va giai nen vao C:\ffmpeg\bin roi them vao PATH.
        set /a ERRORS+=1
    )
)

echo.
echo [5/5] Kiem tra Diagnostic cac thu vien...
set MOD_FAIL=0

%PYTHON_EXE% -c "import customtkinter, curl_cffi, pyreqwest_impersonate, PIL, edge_tts, groq, google.genai, google.auth, DrissionPage, cryptography, pyotp, psutil, requests, tkinter; print('   [OK] TOAN BO THU VIEN PYTHON DA SAN SANG 100%!')" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] Phat hien thieu thu vien. Dang kiem tra chi tiet...
    for %%M in (customtkinter curl_cffi pyreqwest_impersonate PIL edge_tts groq google.genai google.auth DrissionPage cryptography pyotp psutil requests tkinter) do (
        %PYTHON_EXE% -c "import %%M" >nul 2>&1
        if errorlevel 1 (
            echo      [FAIL] THIEU: %%M
            set /a MOD_FAIL+=1
        ) else (
            echo      [OK] DA CO: %%M
        )
    )
) else (
    echo   [OK] TOAN BO 14/14 THU VIEN PYTHON CHUAN DA DUOC CAI DAT HOAN HAO!
)

echo.
echo ====================================================================
if %MOD_FAIL% equ 0 (
    color 0A
    echo    CAI DAT MOI TRUONG HOAN TAT! MAY TINH SAN SANG CHAY TOOL!
    echo ====================================================================
    echo    Chay phan mem: Nhan kep vao CHAY.bat
) else (
    color 0C
    echo    PHAT HIEN %MOD_FAIL% THU VIEN CHUA CAI DU. XEM CHI TIET O TREN.
    echo ====================================================================
)
echo.
pause
