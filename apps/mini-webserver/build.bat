@echo off
REM Baut dist\MiniWebserver.exe (Python 3.9 oder neuer muss installiert sein)
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :fehler
python -m mini_webserver.utils.icon assets\icon.ico || goto :fehler
python -m PyInstaller --noconfirm --clean --noconsole --onefile --name MiniWebserver --icon assets\icon.ico --collect-all customtkinter --hidden-import pystray._win32 main.py || goto :fehler
echo.
echo Fertig: dist\MiniWebserver.exe
echo Kopiere die .exe in den Ordner deines HTML-Projekts und starte sie dort.
pause
exit /b 0
:fehler
echo Der Build ist fehlgeschlagen.
pause
exit /b 1
