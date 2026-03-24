@echo off
title Discord Media Downscaler - Build
cd /d "%~dp0"

echo.
echo  ================================================
echo   Discord Media Downscaler - build script
echo  ================================================
echo.

:: Create venv if it doesn't exist
if not exist "venv\Scripts\python.exe" (
    echo Creating virtualenv...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Could not create venv. Make sure Python 3.9+ is on PATH.
        pause & exit /b 1
    )
)

:: Install / upgrade dependencies into the venv
echo [1/2] Installing dependencies into venv...
venv\Scripts\pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause & exit /b 1
)

echo.
echo [2/2] Building .exe with PyInstaller...
venv\Scripts\python -m PyInstaller DiscordMediaDownscaler.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause & exit /b 1
)

echo.
echo  ================================================
echo   SUCCESS:  dist\DiscordMediaDownscaler.exe
echo  ================================================
echo.
explorer dist
pause
