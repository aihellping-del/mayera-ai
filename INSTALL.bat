@echo off
REM =====================================================================
REM  MAYERA AI - one-time installation
REM  Creates a private Python environment (.venv) for MAYERA and
REM  installs everything from requirements.txt into it. Your system
REM  Python is not touched.
REM =====================================================================
title MAYERA AI - Install
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Python nahi mila.
    echo  Pehle https://www.python.org/downloads/ se Python 3.10 ya
    echo  usse naya install karein. Install karte waqt
    echo  "Add python.exe to PATH" wala tick zaroor lagayein.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo  Python %PYVER% mila. 

if not exist ".venv" (
    echo  MAYERA ke liye alag environment banaya ja raha hai...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo  [ERROR] venv nahi ban paya.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
echo  Packages install ho rahe hain (internet chahiye, 1-2 minute)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Kuch packages install nahi hue. Internet check karke
    echo  INSTALL.bat dobara chalayein.
    echo.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   Install ho gaya!  Ab START_MAYERA.bat dabakar MAYERA chalayein.
echo  ============================================================
echo.
pause
