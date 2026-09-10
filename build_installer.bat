@echo off
setlocal
cd /d "%~dp0"

REM ---- SoftMacro build: PyInstaller one-folder + Inno Setup installer ----
REM Output: dist\SoftMacro\              (application bundle)
REM         dist\installer\SoftMacroSetup.exe (installer)

if not exist "venv\Scripts\python.exe" (
    echo [build] Creating virtual environment ...
    python -m venv venv
    if errorlevel 1 goto :fail
)

call "venv\Scripts\activate.bat"

echo [build] Installing dependencies ...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet pyinstaller
if errorlevel 1 goto :fail

if not exist "softmacro.ico" (
    echo [build] Generating icon ...
    python tools\make_icon.py
    if errorlevel 1 goto :fail
)

echo [build] Freezing the application with PyInstaller ...
python -m PyInstaller --noconfirm --clean SoftMacro.spec
if errorlevel 1 goto :fail

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo.
    echo [build] Inno Setup 6 was not found. Install it from:
    echo         https://jrsoftware.org/isdl.php
    echo [build] The application bundle is ready in dist\SoftMacro\.
    goto :fail
)

echo [build] Compiling the installer with Inno Setup ...
"%ISCC%" "installer\SoftMacro.iss"
if errorlevel 1 goto :fail

echo.
echo [build] Done!
echo [build]   App bundle: dist\SoftMacro\
echo [build]   Installer : dist\installer\SoftMacroSetup.exe
pause
exit /b 0

:fail
echo.
echo [build] Build failed.
pause
exit /b 1
