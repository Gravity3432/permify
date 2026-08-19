@echo off
REM ============================================================
REM  Permify - ONE-CLICK build
REM  Double-click this. It sets everything up and leaves you a
REM  ready-to-run Permify.exe in the "dist" folder.
REM  made with heart by @johnthemailboy
REM ============================================================
cd /d "%~dp0"
title Building Permify...

echo.
echo   Welcome! I'll build the Permify app for you.
echo   This takes a few minutes the first time.
echo.

REM ---- find python ----
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo   Could not find Python. Install Python 3.10+ from https://python.org
  echo   (tick "Add to PATH"), then run this again.
  pause & exit /b 1
)

REM ---- private env ----
if not exist .venv\Scripts\python.exe (
  echo   [1/4] Creating a private environment...
  %PY% -m venv .venv
  if errorlevel 1 ( echo   Could not create env. & pause & exit /b 1 )
)

REM ---- deps + builder ----
echo   [2/4] Installing dependencies...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo   Could not install deps. Check internet. & pause & exit /b 1 )

REM ---- build exe ----
echo   [3/4] Building Permify.exe (the slow part)...
.venv\Scripts\python -m PyInstaller --noconfirm --clean permify.spec
if errorlevel 1 ( echo   Build failed. See above. & pause & exit /b 1 )

REM ---- done ----
echo   [4/4] Done!
echo.
echo   Your app is ready:  dist\Permify.exe
echo   Copy it anywhere, double-click it, pin it to the taskbar.
echo.
pause
