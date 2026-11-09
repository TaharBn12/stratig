@echo off
REM ============================================================
REM  Stratig - تنزيل المشروع عبر git ثم التحضير والتشغيل
REM  ضع هذا الملف في أي مكان (مثلاً سطح المكتب) وشغّله
REM ============================================================
chcp 65001 >nul
setlocal

set REPO=https://github.com/TaharBn12/stratig.git
set DEST=%~dp0stratig

where git >nul 2>nul
if errorlevel 1 (
    echo [X] git غير مثبت على الجهاز.
    echo     نزّله من: https://git-scm.com/downloads
    echo     ^(أو حمّل المشروع كملف ZIP من GitHub وشغّل setup.bat داخله^)
    echo.
    pause
    exit /b 1
)

if exist "%DEST%\.git" (
    echo [*] المشروع موجود مسبقاً - جارٍ التحديث...
    cd /d "%DEST%"
    git pull
) else (
    echo [*] جارٍ تنزيل المشروع عبر git...
    git clone %REPO% "%DEST%"
    if errorlevel 1 ( echo [X] فشل التنزيل. & pause & exit /b 1 )
    cd /d "%DEST%"
)

echo.
call setup.bat
