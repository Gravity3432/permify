@echo off
setlocal
REM ============================================================
REM  Permify launcher (Windows)
REM  First run: auto-installs, then walks you through the one-time
REM  Spotify login. Always keeps the window open so it never just
REM  vanishes. Made with heart by @johnthemailboy
REM ============================================================
cd /d "%~dp0"
title Permify

REM --- find python (py launcher first, then python) ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :no_python

REM --- 1. create the private environment on first run ---
if exist .venv\Scripts\python.exe goto :venv_ok
echo.
echo  First run - setting Permify up for you...
echo  [1/2] Creating a private environment...
%PY% -m venv .venv
if errorlevel 1 goto :venv_fail
echo  [2/2] Installing dependencies (this downloads a few things)...
.venv\Scripts\python -m pip install --upgrade pip >nul 2>nul
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto :pip_fail
:venv_ok

REM --- 2. one-time Spotify login (only if not set up yet) ---
set "NEEDSETUP="
.venv\Scripts\python -c "import json,os,pathlib,sys; cfg=json.loads((pathlib.Path(os.path.expanduser('~'))/'.permify'/'config.json').read_text()) if (pathlib.Path(os.path.expanduser('~'))/'.permify'/'config.json').exists() else {}; sys.exit(0 if cfg.get('client_id') else 1)" >nul 2>nul
if errorlevel 1 set "NEEDSETUP=1"
if defined NEEDSETUP (
  echo.
  echo  Let's connect you to Spotify - it takes a minute.
  .venv\Scripts\python -m permify --setup
)

REM --- 3. launch ---
.venv\Scripts\python -m permify %*
set "EXITCODE=%errorlevel%"
echo.
echo  [permify] Permify closed (exit code %EXITCODE%).
echo  You can close this window.
echo.
pause
exit /b %EXITCODE%

:no_python
echo.
echo  [permify] Could not find Python.
echo  Please install Python 3.10+ from https://python.org
echo  and IMPORTANT: tick "Add python.exe to PATH" during install.
echo  Then run this file again.
echo.
pause
exit /b 1

:venv_fail
echo.
echo  [permify] Could not create the environment.
echo  Make sure Python 3.10+ is installed, then run this again.
echo.
pause
exit /b 1

:pip_fail
echo.
echo  [permify] Could not install the dependencies.
echo  Check your internet connection, then run this again.
echo.
pause
exit /b 1
