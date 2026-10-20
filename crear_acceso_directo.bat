@echo off
REM Crea un acceso directo "Nemesis Monitor" en el Escritorio que abre la app.
cd /d "%~dp0"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Nemesis Monitor.lnk'); $s.TargetPath='%~dp0abrir_app.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.IconLocation='%SystemRoot%\System32\imageres.dll,144'; $s.Description='Nemesis Monitor'; $s.Save()"
if errorlevel 1 (
  echo No se pudo crear automaticamente. Crea a mano un acceso directo a:
  echo   %~dp0abrir_app.bat
) else (
  echo Acceso directo creado en el Escritorio.
)
pause
