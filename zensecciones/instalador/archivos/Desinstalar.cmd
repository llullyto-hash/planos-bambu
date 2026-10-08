@echo off
title Desinstalar Zen Secciones
echo.
echo   Cierra la ventana de Zen Secciones antes de continuar.
echo   Se borraran el programa, la activacion y el proyecto guardado en este equipo.
echo.
pause
powershell -NoProfile -Command "Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Zen Secciones.lnk'),(Join-Path ([Environment]::GetFolderPath('Programs')) 'Zen Secciones.lnk')"
cd /d "%TEMP%"
rmdir /s /q "%LOCALAPPDATA%\ZenSecciones"
echo.
echo   Zen Secciones fue desinstalado.
echo.
pause
