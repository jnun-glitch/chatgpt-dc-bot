@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo   ScratchAI Bot - Start
 echo ================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON=python"
    ) else (
        echo [FEHLER] Python wurde nicht gefunden.
        pause
        exit /b 1
    )
)

if not exist "_inner_bot\.env" (
    echo [FEHLER] _inner_bot\.env wurde nicht gefunden.
    echo Kopiere _inner_bot\.env.example nach _inner_bot\.env und trage DISCORD_TOKEN ein.
    echo.
    pause
    exit /b 1
)

if not exist "_inner_bot\bot.py" (
    echo [FEHLER] _inner_bot\bot.py wurde nicht gefunden.
    pause
    exit /b 1
)

cd /d "_inner_bot"
echo [INFO] Starte ScratchAI...
echo [INFO] Fehler bleiben sichtbar. Fenster nicht sofort schliessen.
echo.
%PYTHON% bot.py
set "EXITCODE=%errorlevel%"

echo.
echo ================================================
echo   Bot beendet - Exit-Code: %EXITCODE%
echo ================================================
pause
exit /b %EXITCODE%
