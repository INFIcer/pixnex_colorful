@echo off
pushd "%~dp0"
set "scriptDir=%~dp0"
set "pyFile=%scriptDir%%~n0.py"
set "args=%*"

if not exist "%pyFile%" (echo 错误: 找不到Python文件 & pause & exit /b 1)

if exist "%scriptDir%.venv\Scripts\pythonw.exe" (
    start "" "%scriptDir%.venv\Scripts\pythonw.exe" "%pyFile%" %args%
    exit /b 0
)

if exist "%scriptDir%.conda\pythonw.exe" (
    start "" "%scriptDir%.conda\pythonw.exe" "%pyFile%" %args%
    exit /b 0
)

if exist "%scriptDir%.conda\Scripts\pythonw.exe" (
    start "" "%scriptDir%.conda\Scripts\pythonw.exe" "%pyFile%" %args%
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw "%pyFile%" %args%
    exit /b 0
) else (
    echo 错误: 找不到Python环境 & pause & exit /b 1
)
