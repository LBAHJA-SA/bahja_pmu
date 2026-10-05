@echo off
REM start-shared-db.bat — Local backend using the SHARED production users DB.
REM 1. Opens an SSH tunnel: localhost:5433 -> Railway Postgres (no public proxy needed)
REM 2. Starts Flask with DATABASE_URL pointing at the tunnel.
REM Result: localhost admin manages the SAME subscribers as the external site, instantly both ways.
REM WARNING: every change here affects REAL production users.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist "..\.deploy-env" (
  echo [ERROR] Missing ..\.deploy-env
  exit /b 1
)
for /f "usebackq tokens=1,* delims==" %%A in ("..\.deploy-env") do (
  set "line=%%A"
  if not "!line!"=="" if not "!line:~0,1!"=="#" set "%%A=%%B"
)
if "%PGPASSWORD%"=="" ( echo [ERROR] PGPASSWORD missing in .deploy-env & exit /b 1 )

echo [1/2] Opening tunnel localhost:5433 -^> Railway Postgres...
REM -- python and node are found, not hard-coded: this file used to carry a
REM    path from another machine and failed with "pythonw not found" --
set "PY="
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Temp\opencode\Python312\python.exe"
  "%LOCALAPPDATA%\Temp\py-extract\python.exe"
  "%TEMP%\py-extract\python.exe"
) do if not defined PY if exist "%%~P" set "PY=%%~P"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY set "PY=python"
for %%F in ("%PY%") do set "PYD=%%~dpF"
set "PYW=pythonw"
if exist "%PYD%pythonw.exe" set "PYW=%PYD%pythonw.exe"

set "NODE_DIR="
for %%N in (
  "%LOCALAPPDATA%\Temp\opencode\node-v22.23.3-win-x64"
  "%LOCALAPPDATA%\Temp\node22-extract\node-v22.19.0-win-x64"
  "%LOCALAPPDATA%\Programs\nodejs"
) do if not defined NODE_DIR if exist "%%~N\node.exe" set "NODE_DIR=%%~N"
if defined NODE_DIR set "PATH=%NODE_DIR%;%PATH%"
set "PATH=%~dp0;%PATH%"
start "bahja-pg-tunnel" /min "%PYW%" tunnel_keep.py
:waitloop
timeout /t 5 /nobreak >nul
netstat -ano | findstr "127.0.0.1:5433" | findstr "LISTENING" >nul
if errorlevel 1 goto waitloop

set "DATABASE_URL=postgresql://postgres:%PGPASSWORD%@127.0.0.1:5433/railway"
echo [2/2] Starting backend with SHARED users DB...
"%PY%" app.py
