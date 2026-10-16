@echo off
setlocal enabledelayedexpansion

title PINORA-Like Local Lead Workspace

cd /d "%~dp0"

echo ======================================================================
echo    PINORA-LIKE LOCAL LEAD WORKSPACE
echo    Windows Desktop - Zero Paid API Cost - Local-First Architecture
echo ======================================================================
echo.

:: Detect Python executable
set "PYTHON_CMD="

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PYTHON_CMD=python"
) else if exist "C:\Python314\python.exe" (
    set "PYTHON_CMD=C:\Python314\python.exe"
) else if exist "C:\Python313\python.exe" (
    set "PYTHON_CMD=C:\Python313\python.exe"
) else if exist "C:\Python312\python.exe" (
    set "PYTHON_CMD=C:\Python312\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python was not found on your system.
    echo Please install Python from https://www.python.org/
    echo and ensure "Add Python to PATH" is checked during setup.
    echo.
    pause
    exit /b 1
)

echo [+] Using Python: %PYTHON_CMD%
echo [+] Initializing local SQLite database and verifying environment...
echo [+] Starting local HTTP server on http://127.0.0.1:3847 ...
echo [+] Opening dashboard in your default browser...
echo.
echo ======================================================================
echo  Press Ctrl+C in this window or run stop.bat to exit gracefully.
echo ======================================================================
echo.

"%PYTHON_CMD%" app\server.py 3847

if %ERRORLEVEL% neq 0 (
    echo.
    echo [!] Server closed with exit code %ERRORLEVEL%.
    pause
)
