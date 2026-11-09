@echo off
REM ============================================================
REM  Stratig - التحضير لمرة واحدة فقط (ويندوز / CMD)
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   Stratig - التحضير
echo ============================================
echo.

REM --- 1) التحقق من وجود بايثون ---
where python >nul 2>nul
if errorlevel 1 (
    echo [X] لم يتم العثور على Python.
    echo     نزل النسخة من: https://www.python.org/downloads/
    echo     وفعّل خيار  "Add Python to PATH"  أثناء التثبيت.
    echo.
    pause
    exit /b 1
)
python -c "import sys;print('   Python', sys.version.split()[0])"

REM --- 2) البيئة الافتراضية ---
if exist ".venv" (
    echo [1/3] البيئة الافتراضية موجودة مسبقاً.
) else (
    echo [1/3] جارٍ إنشاء البيئة الافتراضية...
    python -m venv .venv
    if errorlevel 1 ( echo [X] فشل إنشاء البيئة. & pause & exit /b 1 )
)

REM --- 3) تثبيت المكتبات ---
echo [2/3] جارٍ تثبيت المكتبات ^(قد يستغرق دقيقة^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 ( echo [X] فشل تثبيت المكتبات. & pause & exit /b 1 )

REM --- 4) ملف الأسرار ---
if exist ".env" (
    echo [3/3] ملف .env موجود.
) else (
    echo [3/3] جارٍ إنشاء ملف .env من المثال...
    copy /Y .env.example .env >nul
    echo.
    echo  ****************************************************
    echo   مهم: املأ ملف .env الذي سيفتح الآن ثم احفظه:
    echo     TELEGRAM_BOT_TOKEN   من @BotFather
    echo     TELEGRAM_CHAT_IDS    اتركه فارغاً أولاً، ثم /id
    echo     BINANCE_TESTNET_API_KEY / _SECRET
    echo  ****************************************************
    echo.
    pause
    notepad .env
)

echo.
echo ============================================
echo   جاهز!  الخطوة التالية:  check.bat
echo   ^(للتحقق من المفاتيح^)  ثم  run.bat
echo ============================================
echo.
pause
