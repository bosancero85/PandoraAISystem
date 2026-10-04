@echo off
setlocal EnableExtensions

rem ============================================================
rem  Build-Skript: Ollama Modell Installer -> Einzel-EXE
rem  Ergebnis: dist\OllamaModelInstaller.exe
rem  Aufruf:   build.bat          (mit Pause am Ende)
rem            build.bat nopause  (ohne Pause, z. B. fuer CI)
rem ============================================================

set "APP_NAME=OllamaModelInstaller"
set "ENTRY=ollama_model_installer.py"
set "ICON_PNG=ollama_model_installer_icon.png"
set "ICON_ICO=ollama_model_installer_icon.ico"
set "VENV_DIR=.venv"

cd /d "%~dp0"

echo.
echo ==== %APP_NAME% - Build ====
echo.

if not exist "%ENTRY%" (
    echo [FEHLER] %ENTRY% wurde nicht gefunden.
    goto :fail
)

rem --- Python finden ---
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [FEHLER] Python wurde nicht gefunden. Bitte Python 3.9+ installieren und zum PATH hinzufuegen.
    goto :fail
)

rem --- Virtuelle Umgebung anlegen ---
if exist "%VENV_DIR%\Scripts\python.exe" goto :venv_ok
echo [INFO] Erstelle virtuelle Umgebung in %VENV_DIR% ...
%PY% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [FEHLER] Virtuelle Umgebung konnte nicht erstellt werden.
    goto :fail
)
:venv_ok
set "VPY=%VENV_DIR%\Scripts\python.exe"

rem --- Abhaengigkeiten installieren ---
echo [INFO] Installiere Abhaengigkeiten ...
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo [FEHLER] Installation der Abhaengigkeiten fehlgeschlagen.
    goto :fail
)

"%VPY%" -c "import sys, PyInstaller; print('[INFO] Python', sys.version.split()[0], '| PyInstaller', PyInstaller.__version__)"

rem --- Icon (.ico) bei Bedarf aus der PNG erzeugen ---
if exist "%ICON_ICO%" goto :icon_ok
if not exist "%ICON_PNG%" (
    echo [FEHLER] Weder %ICON_ICO% noch %ICON_PNG% gefunden.
    goto :fail
)
echo [INFO] Erzeuge %ICON_ICO% aus %ICON_PNG% ...
"%VPY%" -c "from PIL import Image; im=Image.open(r'%ICON_PNG%').convert('RGBA'); im=im.crop(im.getchannel('A').getbbox() or im.getbbox()); s=max(im.size); c=Image.new('RGBA',(s,s),(0,0,0,0)); c.paste(im,((s-im.width)//2,(s-im.height)//2),im); c.save(r'%ICON_ICO%',format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if errorlevel 1 (
    echo [FEHLER] Icon-Konvertierung fehlgeschlagen.
    goto :fail
)
:icon_ok

rem --- EXE bauen ---
echo [INFO] Baue Einzel-EXE mit PyInstaller ...
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "%APP_NAME%" ^
    --icon "%ICON_ICO%" ^
    --add-data "%ICON_ICO%;." ^
    --add-data "ollama_model_installer_icon_256.png;." ^
    --collect-all customtkinter ^
    --hidden-import ctypes._layout ^
    "%ENTRY%"
if errorlevel 1 (
    echo [FEHLER] PyInstaller-Build fehlgeschlagen.
    goto :fail
)

if not exist "dist\%APP_NAME%.exe" (
    echo [FEHLER] dist\%APP_NAME%.exe wurde nicht erzeugt.
    goto :fail
)

echo.
echo [ERFOLG] Fertig: dist\%APP_NAME%.exe
echo.
if /i not "%~1"=="nopause" pause
endlocal
exit /b 0

:fail
echo.
echo [ABBRUCH] Build nicht erfolgreich.
echo.
if /i not "%~1"=="nopause" pause
endlocal
exit /b 1
