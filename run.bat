@echo off
REM ============================================================
REM  Stratig - تشغيل البوت
REM  الاستخدام:  run.bat            (تشغيل عادي)
REM              run.bat --dry-run  (محاكاة بدون أوامر حقيقية)
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [X] لا توجد بيئة افتراضية - شغّل setup.bat أولاً.
    pause
    exit /b 1
)
if not exist "logs" mkdir logs

echo.
echo  البوت يعمل... أغلق النافذة أو اضغط Ctrl+C للإيقاف.
echo.
".venv\Scripts\python.exe" main.py %*

echo.
echo  توقف البوت.
pause
