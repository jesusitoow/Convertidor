@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Primero ejecuta install.bat
    pause
    exit /b 1
)
echo Creando YT2MP3.exe (tarda un par de minutos)...
.venv\Scripts\python.exe -m pip install pyinstaller || goto :fail
.venv\Scripts\python.exe -m PyInstaller --noconsole --onefile --clean --name YT2MP3 ^
    --collect-all customtkinter --collect-all imageio_ffmpeg --collect-all yt_dlp ^
    --collect-all send2trash launcher.py || goto :fail
echo.
echo  Listo: dist\YT2MP3.exe
pause
exit /b 0

:fail
echo Fallo la compilacion.
pause
exit /b 1
