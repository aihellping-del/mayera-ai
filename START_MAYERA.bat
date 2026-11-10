@echo off
REM =====================================================================
REM  MAYERA AI - one-click startup
REM
REM  API key ka tareeka:
REM   * Pehli baar key puchhi jayegi (chipi hui, Ctrl+V se paste karein).
REM   * Key is PC par Windows ki encryption (DPAPI) se save ho jayegi -
REM     sirf aapke Windows account se khulegi, saaf text me kabhi nahi.
REM   * Agli baar se key nahi dalna padega - MAYERA seedha chalegi.
REM   * Key badalna ho to KEY_CHANGE.bat chalakar phir se start karein.
REM =====================================================================
title JARVIS AI - Voice Companion
cd /d "%~dp0"

REM --- use the project virtual environment if it exists ----------------
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

REM --- check Python -----------------------------------------------------
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Python nahi mila. Pehle INSTALL.bat chalayein,
    echo          ya python.org se Python 3.10+ install karein.
    echo.
    pause
    exit /b 1
)

REM --- auto-update check: naya version ho to khud lag jayega ----------
REM     (internet na ho to ye chup-chaap aage badh jata hai,
REM      MAYERA kabhi update ki wajah se nahi rukti)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" core\updater.py
) else (
    python core\updater.py
)

echo.
echo  MAYERA shuru ho rahi hai... browser khud khul jayega.
echo  Band karne ke liye is window me Ctrl+C dabayein.
echo.
python main.py

echo.
echo  MAYERA band ho gayi. Dhanyavaad!
pause
