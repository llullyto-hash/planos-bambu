@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Primero hay que instalar. Ejecutando INSTALAR.bat...
  call INSTALAR.bat
)
start "" ".venv\Scripts\pythonw.exe" -m ortofoto.gui
