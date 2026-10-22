@echo off
setlocal EnableExtensions
chcp 65001 >nul
title pixnex - Building...

pushd "%~dp0"
if errorlevel 1 (
    echo [FAIL] Cannot enter project directory.
    pause
    exit /b 1
)

set "PYINST=.venv\Scripts\pyinstaller.exe"
set "SPEC=pixnex.spec"
set "WORK=build\pyinstaller"
set "DIST=dist"
set "LOG=%TEMP%\pixnex-build.log"

echo ========================================
echo  pixnex - PyInstaller onedir Build
echo ========================================
echo.

if not exist "%PYINST%" (
    echo [FAIL] PyInstaller not found: %PYINST%
    echo        Run: .venv\Scripts\pip install pyinstaller
    pause
    exit /b 1
)
if not exist "%SPEC%" (
    echo [FAIL] %SPEC% not found.
    pause
    exit /b 1
)

rem A running pixnex.exe would prevent overwriting dist; check first.
tasklist /FI "IMAGENAME eq pixnex.exe" 2>nul | find /I "pixnex.exe" >nul
if not errorlevel 1 (
    echo [FAIL] pixnex.exe is running. Close it and run this script again.
    pause
    exit /b 1
)

echo [1/3] Cleaning previous build artifacts...
if exist "%WORK%" rmdir /s /q "%WORK%"
if exist "%DIST%" rmdir /s /q "%DIST%"
echo   done.

echo [2/3] Running PyInstaller (this may take several minutes)...
echo        log: %LOG%
"%PYINST%" "%SPEC%" --clean --noconfirm --workpath "%WORK%" --distpath "%DIST%" > "%LOG%" 2>&1
if errorlevel 1 (
    echo [FAIL] PyInstaller build failed.
    echo -------- last 40 log lines --------
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 40"
    echo -----------------------------------
    echo Full log: %LOG%
    pause
    exit /b 1
)

echo [3/3] Verifying output...
if not exist "%DIST%\pixnex\pixnex.exe" (
    echo [FAIL] %DIST%\pixnex\pixnex.exe not found.
    echo Full log: %LOG%
    pause
    exit /b 1
)

for %%I in ("%DIST%\pixnex\pixnex.exe") do echo   OK - %DIST%\pixnex\pixnex.exe  (%%~zI bytes)

echo ========================================
echo  Build Complete!
echo  Output: %DIST%\pixnex\pixnex.exe
echo  NOTE: copy the whole %DIST%\pixnex folder when distributing.
echo ========================================
echo.
popd
pause