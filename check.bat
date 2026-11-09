@echo off
REM ============================================================
REM  Stratig - فحص المفاتيح والاتصال بالمنصة (بدون تليجرام)
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [X] لا توجد بيئة افتراضية - شغّل setup.bat أولاً.
    pause
    exit /b 1
)

echo.
echo ============ فحص الاتصال ============
echo.
".venv\Scripts\python.exe" main.py --check
echo.
pause
