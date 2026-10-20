@echo off
REM Abre el dashboard en el navegador: http://localhost:8501 (solo esta PC).
REM Para que lo vean otras PCs de la red:  abrir_web.bat --lan
cd /d "%~dp0"
call "%~dp0_entorno.bat"
if errorlevel 1 (pause & exit /b 1)
title Nemesis Monitor - servidor web (cerra esta ventana para detenerlo)
"%NM_PY%" -m nemesis web %*
pause
