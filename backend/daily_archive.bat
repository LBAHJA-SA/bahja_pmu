@echo off
REM daily_archive.bat — يُشغل عبر Task Scheduler كل 24 ساعة (06:30 صباحا، بعد انتهاء السباقات بساعات)
REM يحفظ سباقات الأمس بالنتائج النهائية في archive.db (PMU أولا، Geny احتياط)

set LOG_DIR=C:\bahja-pmu\backend\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM تاريخ اليوم للوغ
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set dt=%%I
set LOG=%LOG_DIR%\daily_archive_%dt:~0,8%.log

echo [%date% %time%] Starting daily archive... >> "%LOG%"
C:\Python314\python.exe "C:\bahja-pmu\backend\daily_archive.py" >> "%LOG%" 2>&1
echo [%date% %time%] Finished with code %errorlevel% >> "%LOG%"

REM احتفظ بآخر 30 لوج فقط
forfiles /p "%LOG_DIR%" /m daily_archive_*.log /d -30 /c "cmd /c del @path" 2>nul
