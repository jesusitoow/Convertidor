@echo off
setlocal
cd /d "%~dp0"
echo.
echo  YT2MP3 / MediaVault v2.0 - instalando...
echo.

where uv >nul 2>nul
if %errorlevel%==0 (
    echo Usando uv con Python 3.12
    uv venv --python 3.12 --clear .venv || goto :fail
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt || goto :fail
) else (
    where python >nul 2>nul || (
        echo No encontre Python 3.12 o superior. Instalalo desde https://www.python.org/downloads/
        echo y marca la casilla "Add python.exe to PATH".
        goto :fail
    )
    python -m venv .venv || goto :fail
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail
)

echo.
echo  Listo. Abre la app con run.bat
echo.
pause
exit /b 0

:fail
echo.
echo  Algo salio mal. Revisa el mensaje de arriba.
pause
exit /b 1
