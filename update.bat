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

REM --- 1) احتياط لإعداداتك المحلية قبل السحب -------------------
REM config.toml ملف يخصّك (البوت يكتب فيه). نرفعه مؤقتاً عن الطريق
REM حتى لا يرفض git السحب، ثم نعيده — فلا تضيع إعداداتك أبداً.
set "HAD_CFG=0"
set "HAD_LOCAL=0"
if exist "config.toml" (
    set "HAD_CFG=1"
    copy /Y "config.toml" "config.toml.bak" >nul
    git diff --quiet -- config.toml
    if errorlevel 1 set "HAD_LOCAL=1"
)
if "%HAD_LOCAL%"=="1" (
    echo  [i] config.toml معدّل محلياً - سأحتفظ بنسخة config.toml.mine وأعيدها بعد التحديث.
    copy /Y "config.toml" "config.toml.mine" >nul
    git checkout -- config.toml
)

echo.
echo ============ جارٍ التحديث ============
git pull
set "PULL_OK=0"
if not errorlevel 1 set "PULL_OK=1"
echo.

REM --- 2) إعادة الإعدادات --------------------------------------
if "%HAD_LOCAL%"=="1" (
    if exist "config.toml.mine" (
        copy /Y "config.toml.mine" "config.toml" >nul
        echo  [i] أعدتُ نسختك من config.toml ^(المفاتيح الجديدة تأتي من الإعدادات الافتراضية^).
    )
)

if "%PULL_OK%"=="1" (
    echo  تم التحديث بنجاح.
    echo  أعد تشغيل run.bat إن كان يعمل.
) else (
    echo [X] فشل التحديث. أرسل لي ناتج هذه النافذة.
    if "%HAD_CFG%"=="1" (
        echo     أعدتُ config.toml من النسخة الاحتياطية config.toml.bak
        copy /Y "config.toml.bak" "config.toml" >nul
    )
)
echo.
pause
