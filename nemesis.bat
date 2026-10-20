@echo off
REM Consola de Nemesis Monitor. Ejemplos:
REM   nemesis.bat check
REM   nemesis.bat validate
REM   nemesis.bat report --format pdf excel powerbi --days 7
REM   nemesis.bat traceroute --ip 192.168.1.1
cd /d "%~dp0"
call "%~dp0_entorno.bat"
if errorlevel 1 exit /b 1
"%NM_PY%" -m nemesis %*
