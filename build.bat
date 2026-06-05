@echo off
chcp 65001 >nul
title pixnex - Building...

pushd "%~dp0"

set VENV=".venv\Scripts\pythonw.exe"
set PYINST=".venv\Scripts\pyinstaller.exe"
set SPEC="pixnex.spec"

echo ========================================
echo  pixnex - PyInstaller --onefile Build
echo ========================================
echo.

if not exist %PYINST% (
    echo [FAIL] PyInstaller not found in .venv. Run: .venv\Scripts\pip install pyinstaller
    pause & exit /b 1
)

if not exist %SPEC% (
    echo [FAIL] %SPEC% not found.
    pause & exit /b 1
)

echo [1/3] Cleaning previous build artifacts...
if exist build\ rmdir /s /q build
if exist dist\ rmdir /s /q dist
echo   done.

echo [2/3] Running PyInstaller (this may take several minutes)...
%PYINST% %SPEC% --clean >nul
if %errorlevel% neq 0 (
    echo [FAIL] PyInstaller build failed. Run manually to see errors:
    echo   %PYINST% %SPEC% --clean
    pause & exit /b 1
)

echo [3/3] Verifying output...
if exist "dist\pixnex.exe" (
    for %%I in ("dist\pixnex.exe") do set "size=%%~zI"
    call echo   OK - dist\pixnex.exe  (%%size%% bytes)
) else (
    echo [FAIL] dist\pixnex.exe not found
    pause & exit /b 1
)

echo ========================================
echo  Build Complete!
echo  Output: dist\pixnex.exe
echo ========================================
echo.

popd
pause
