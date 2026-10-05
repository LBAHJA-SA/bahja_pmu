@echo off
REM deploy-all.bat — Publish frontend + backend in ONE action.
REM Tokens are read from .deploy-env (local only, never committed, never shared).
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist ".deploy-env" (
  echo [ERROR] Missing .deploy-env file. Copy .deploy-env.TEMPLATE to .deploy-env and fill tokens.
  exit /b 1
)
for /f "usebackq tokens=1,* delims==" %%A in (".deploy-env") do (
  set "line=%%A"
  if not "!line!"=="" if not "!line:~0,1!"=="#" set "%%A=%%B"
)
if "%VERCEL_TOKEN%"=="" ( echo [ERROR] VERCEL_TOKEN missing in .deploy-env & exit /b 1 )
if "%RAILWAY_TOKEN%"=="" ( echo [ERROR] RAILWAY_TOKEN missing in .deploy-env & exit /b 1 )

echo === [1/2] Frontend : Vercel --prod ===
call npx -y vercel@59 deploy --prod --yes --token %VERCEL_TOKEN%
if errorlevel 1 ( echo [FAILED] Frontend & exit /b 1 )
echo [OK] Frontend live: https://bahja-pmu.vercel.app/

echo === [2/2] Backend : Railway up ===
cd /d "%~dp0backend"
call railway up -y -d -s 6d28633d-9998-46a2-bcec-119700da189b -e 656ece57-dc7c-40a3-9ea4-3979612d89cd
if errorlevel 1 ( echo [FAILED] Backend & exit /b 1 )
echo [OK] Backend deploy started: https://bahja-turf-api-production.up.railway.app/
echo === DONE ===
