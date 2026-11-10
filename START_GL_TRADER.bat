@echo off
REM =====================================================================
REM  JARVIS GL TRADER - Binary Signal RESEARCH dashboard (v3.35)
REM
REM  * Ye sirf RESEARCH hai - koi real trade NAHI lagta, paper only.
REM  * Live data ke liye: pehle MetaTrader 5 terminal kholo aur
REM    DEMO account se login karo - tab data MT5-LIVE aayega.
REM  * MT5 band ho / login na ho to DEMO synthetic data chalega
REM    (dashboard par DEMO badge dikhega) - ghabrana nahi.
REM =====================================================================
title JARVIS GL TRADER - Research Only
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Python nahi mila. Pehle INSTALL.bat chalayein.
    echo.
    pause
    exit /b 1
)

echo.
echo  GL TRADER shuru ho raha hai...
echo  Dashboard: http://127.0.0.1:8771
echo  Band karne ke liye is window me Ctrl+C dabayein.
echo.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8771"
python -m JARVIS_GL_TRADER.main

echo.
echo  GL TRADER band ho gaya. Dhanyavaad!
pause
