@echo off
chcp 65001 >nul
title Bahja PMU - USB (C:\turf)
cd /d "%~dp0"

echo ==========================================
echo   Bahja PMU - local (C:\turf\bahja-pmu)
echo ==========================================

REM --- backend deps (sans psycopg2: inutile en local, casse Python 3.14) ---
python -c "import flask_cors" 2>nul
if errorlevel 1 (
  echo [1/3] Installation deps backend...
  pip install Flask==3.1.1 flask-cors==5.0.1 requests==2.32.3 beautifulsoup4==4.15.0 numpy==2.5.1
)

REM --- libere les ports si relance ---
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1

echo [2/3] Backend (port 3000)...
start "Bahja Backend" cmd /k "cd /d "%~dp0backend" && python app.py"

echo [3/3] Frontend (port 5173)...
start "Bahja Frontend" cmd /k "cd /d "%~dp0" && npm run dev"

timeout /t 8 /nobreak >nul
start "" "http://localhost:5173"
echo [OK] Frontend: http://localhost:5173  Backend: http://127.0.0.1:3000
pause
