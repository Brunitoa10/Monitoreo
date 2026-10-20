@echo off
REM ==================================================================
REM  Entorno 100% portable: usa el Python incluido en .\runtime
REM  No instala nada, no toca el registro ni el perfil del usuario.
REM  Lo usan los demas .bat (no hace falta ejecutarlo a mano).
REM ==================================================================
set "NM_HOME=%~dp0"
set "NM_PY=%NM_HOME%runtime\python.exe"
set "NM_PYW=%NM_HOME%runtime\pythonw.exe"
call :desempaquetar
if not exist "%NM_PY%" exit /b 1
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "MPLCONFIGDIR=%NM_HOME%data\matplotlib"
chcp 65001 >nul
exit /b 0

:desempaquetar
REM Descomprime cada parte una sola vez (marca runtime\.<parte>.ok). Si llega una parte nueva, se agrega sola.
if not exist "%NM_HOME%runtime_pkg\" (
  if not exist "%NM_PY%" echo [ERROR] Falta la carpeta runtime_pkg con los archivos runtime-XX.zip
  exit /b 0
)
pushd "%NM_HOME%runtime_pkg"
for %%F in (runtime-*.zip) do if not exist "%NM_HOME%runtime\.%%~nF.ok" call :extraer "%%~fF" "%%~nF"
popd
exit /b 0

:extraer
echo Preparando Python portable: %~nx1 ...
tar -xf "%~1" -C "%NM_HOME%." 2>nul
if errorlevel 1 powershell -NoProfile -Command "Expand-Archive -LiteralPath '%~1' -DestinationPath '%NM_HOME%.' -Force"
if errorlevel 1 (echo [ERROR] No se pudo descomprimir %~nx1. Descomprimilo a mano en esta carpeta. & exit /b 1)
type nul > "%NM_HOME%runtime\.%~2.ok"
exit /b 0
