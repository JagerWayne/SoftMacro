@echo off
setlocal

REM ---- SoftMacro launcher -------------------------------------------------
REM Creates a venv on first run, installs dependencies, then starts the app.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [SoftMacro] Creating virtual environment in .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo [SoftMacro] Failed to create venv. Make sure Python is on PATH.
        pause
        exit /b 1
    )
)

call "venv\Scripts\activate.bat"

echo [SoftMacro] Installing dependencies ...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [SoftMacro] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   SoftMacro
echo.
echo   Hotkeys:
echo     Ctrl + Z         open macro keyboard for current app
echo     Esc              close macro keyboard
echo.
echo   Change the hotkey any time in the web UI.
echo   The exact address is printed below once the web server starts
echo   (default: http://localhost:5000).
echo.
echo   Close this window or press Ctrl+C to quit.
echo ============================================================
echo.

python app.py
endlocal

pause