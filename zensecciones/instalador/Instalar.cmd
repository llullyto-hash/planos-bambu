@echo off
title Instalador de Zen Secciones
echo.
echo   Instalando Zen Secciones...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0archivos\instalar.ps1" -Src "%~dp0archivos"
if errorlevel 1 (
  echo.
  echo   La instalacion no se completo. Revisa el mensaje de arriba.
  echo.
  pause
  exit /b 1
)
echo   Listo. Se creo el acceso directo "Zen Secciones" en el escritorio y en el menu Inicio.
echo   Envia el codigo de equipo de arriba a tu proveedor para recibir tu clave de activacion.
echo   (El codigo tambien queda guardado en %LOCALAPPDATA%\ZenSecciones\codigo_equipo.txt)
echo.
pause
