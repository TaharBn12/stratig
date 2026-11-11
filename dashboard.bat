@echo off
REM ============================================================
REM  Stratig - لوحة التحكم (قراءة من سجل الصفقات، بلا مفاتيح)
REM  الاستخدام:  dashboard.bat
REM             dashboard.bat --port 8080
REM             dashboard.bat --once      (لقطة واحدة كـ JSON)
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [X] لا توجد بيئة افتراضية - شغّل setup.bat أولاً.
    pause
    exit /b 1
)

echo.
echo  لوحة التحكم... أغلق النافذة أو اضغط Ctrl+C للإيقاف.
echo.

".venv\Scripts\python.exe" scripts\dashboard.py %*

echo.
echo  توقفت اللوحة.
pause
