@echo off
REM Mide en segundo plano sin interfaz (para el Programador de tareas).
cd /d "%~dp0"
call "%~dp0_entorno.bat"
if errorlevel 1 exit /b 1
"%NM_PY%" -m nemesis collect
