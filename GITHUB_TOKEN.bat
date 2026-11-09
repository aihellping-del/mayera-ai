@echo off
REM =====================================================================
REM  MAYERA - GitHub token ek baar save karein (sirf PRIVATE repo ho to)
REM
REM   * Token github.com par banta hai: Settings > Developer settings
REM     > Personal access tokens > Fine-grained tokens > Generate
REM   * Sirf mayera-ai repo chunein, Permission: Contents = Read-only
REM   * Yahan paste karne par token Windows encryption (DPAPI) se
REM     gh_token.dat me save hoga - saaf text me kabhi nahi.
REM   * PUBLIC repo ho to iski koi zaroorat nahi hai.
REM =====================================================================
title MAYERA - GitHub Token Save
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" github_token_setup.py
) else (
    python github_token_setup.py
)
echo.
pause
