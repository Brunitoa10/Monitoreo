@echo off
REM Abre Nemesis Monitor como aplicacion de escritorio (ventana propia de Windows).
REM Solo localhost. Al cerrar la ventana se apaga todo. Log: Logs\Python\app.log
cd /d "%~dp0"
call "%~dp0_entorno.bat"
if errorlevel 1 (pause & exit /b 1)
start "" "%NM_PYW%" -m nemesis app %*
