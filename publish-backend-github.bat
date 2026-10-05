@echo off
REM publish-backend-github.bat
REM One action: put the backend on GitHub so Railway can build it from the repo.
REM No tokens. Railway watches the branch and rebuilds on every push.
REM
REM Git is not installed on this machine, so this script says so rather than
REM failing halfway. Install it once, run this, and the backend is deployed
REM from then on by pushing.
setlocal
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  echo [STOP] git is not installed.
  echo.
  echo   winget install --id Git.Git -e --source winget
  echo.
  echo Run that, open a new terminal, then run this script again.
  exit /b 1
)

if not exist ".git" (
  echo === [1/4] first commit, the repo does not exist yet ===
  git init -b main
  git add .
  echo.
  echo === what will be committed, the two databases are the only large files ===
  git status --short | findstr /v "^A  node_modules"
  echo.
  set /p ok=Commit and continue? (y/N)
  if /i not "%ok%"=="y" exit /b 1
  git commit -m "Backend: engine, archive readers, FLIP, /api/synthese/signals"
)

if "%BAHJA_GITHUB%"=="" (
  echo.
  echo [STOP] Set BAHJA_GITHUB to the repo, with your user and the backend folder.
  echo.
  echo   set BAHJA_GITHUB=https://github.com/YOUR-USER/YOUR-REPO.git
  echo   publish-backend-github.bat
  echo.
  echo Then in Railway: New Project ^> Deploy from GitHub repo, pick that repo,
  echo and set the root directory to: backend
  exit /b 1
)

echo.
echo === [2/4] remote ===
git remote remove origin 2>nul
git remote add origin %BAHJA_GITHUB%

echo.
echo === [3/4] push ===
git push -u origin main
if errorlevel 1 ( echo [FAILED] push & exit /b 1 )

echo.
echo === [4/4] done ===
echo [OK] Pushed. Railway builds from the push.
echo.
echo In Railway: New Project ^> Deploy from GitHub repo
echo   repo            : %BAHJA_GITHUB%
echo   root directory  : backend
echo   builder         : detected, Nixpacks, reads backend/railway.json
echo
echo The two large files that travel with it:
echo   backend/archive_slim.db   48 MB   database.py falls back to this
echo   backend/dna_archive.db    84 MB   engine.py will not start without it
echo Both are under GitHub's 100 MB per-file ceiling.
echo.
echo Then set the VITE_API_BASE, if the frontend points at the old host:
echo   the frontend reads src/services/api.js, line 1, REMOTE_API
echo
endlocal
