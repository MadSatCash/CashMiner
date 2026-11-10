@echo off
REM Inicio CON CONSOLA para diagnostico. Para uso normal, doble clic en CashMiner.pyw.
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"
where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 -m cashminer gui
) else (
    python -m cashminer gui
)
if errorlevel 1 (
    echo.
    echo ERROR: verifica Python 3.10+ y las dependencias de requirements.txt.
    echo Para instalar cryptography: py -3 -m pip install -r requirements.txt
    pause
)
endlocal
