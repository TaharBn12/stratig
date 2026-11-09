@echo off
REM ============================================================
REM  Stratig - عرض توضيحي ببيانات اصطناعية (بدون إنترنت ولا مفاتيح)
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [X] لا توجد بيئة افتراضية - شغّل setup.bat أولاً.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\demo_scan.py
echo.
pause
