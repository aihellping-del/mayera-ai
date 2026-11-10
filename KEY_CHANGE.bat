@echo off
REM =====================================================================
REM  MAYERA AI - save ki hui API key hatayein / badlein
REM  Ye sirf key.dat (encrypted key file) delete karta hai.
REM  Agli baar START_MAYERA.bat chalane par nayi key maangi jayegi
REM  aur wahi nayi key save ho jayegi. Yaadein (memory) safe rahengi.
REM =====================================================================
title JARVIS AI - Key Change
cd /d "%~dp0"

if exist "key.dat" (
    del "key.dat"
    echo.
    echo  Save ki hui key hata di gayi hai.
) else (
    echo.
    echo  Koi saved key mili hi nahi - hatane ko kuch nahi hai.
)
echo  Agli baar START_MAYERA.bat chalane par nayi key daalni padegi,
echo  aur wahi save ho jayegi.
echo.
pause
