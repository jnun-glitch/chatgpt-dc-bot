@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo   ScratchAI - Requirement Installer
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
        echo Bitte Python 3.12+ installieren und erneut starten.
        pause
        exit /b 1
    )
)

echo [1/3] Python-Version:
%PYTHON% --version
if errorlevel 1 goto :python_error

echo.
echo [2/3] pip aktualisieren...
%PYTHON% -m pip install --upgrade pip
if errorlevel 1 goto :pip_error

echo.
echo [3/3] Requirements installieren...
if not exist "_inner_bot\requirements.txt" (
    echo [FEHLER] _inner_bot\requirements.txt wurde nicht gefunden.
    pause
    exit /b 1
)

%PYTHON% -m pip install -r "_inner_bot\requirements.txt"
if errorlevel 1 goto :requirements_error

echo.
echo ================================================
echo   Installation erfolgreich abgeschlossen!
echo ================================================
echo.
echo Der Bot kann jetzt mit start.bat oder dem
 echo jeweiligen Startbefehl gestartet werden.
echo.
pause
exit /b 0

:python_error
echo [FEHLER] Python konnte nicht gestartet werden.
pause
exit /b 1

:pip_error
echo [FEHLER] pip konnte nicht aktualisiert werden.
pause
exit /b 1

:requirements_error
echo [FEHLER] Mindestens ein Requirement konnte nicht installiert werden.
echo Siehe die Fehlermeldung oben.
pause
exit /b 1
