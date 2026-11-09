@echo off
REM ============================================================
REM  Stratig - تحديث المشروع إلى آخر نسخة من GitHub
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo [X] git غير مثبت. نزّله من: https://git-scm.com/downloads
    pause
    exit /b 1
)

echo.
echo ============ جارٍ التحديث ============
git pull
echo.
if errorlevel 1 (
    echo [X] فشل التحديث. أرسل لي ناتج هذه النافذة.
) else (
    echo  تم التحديث بنجاح. أعد تشغيل run.bat إن كان يعمل.
)
echo.
pause
