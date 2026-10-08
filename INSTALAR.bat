@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Instalacion del programa Topografia - Polilineas - Metrados
echo ============================================================
echo.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo No se encontro Python.
  echo Instale Python 3.12 desde https://www.python.org/downloads/
  echo y en el instalador marque la casilla "Add python.exe to PATH".
  echo Luego vuelva a ejecutar este archivo.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% --version
echo Creando entorno del programa (carpeta .venv)...
%PY% -m venv .venv || (echo No se pudo crear el entorno & pause & exit /b 1)
echo Instalando librerias (puede tardar unos minutos, necesita internet)...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || (echo Error instalando librerias & pause & exit /b 1)
echo.
echo Listo. Para abrir el programa use ABRIR_PROGRAMA.bat
pause
