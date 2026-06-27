@echo off
setlocal
cd /d "%~dp0"
echo Uninstalling Koe Kichi...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows_uninstall.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
if %EXITCODE% EQU 0 (
  echo Koe Kichi uninstall finished.
) else (
  echo Koe Kichi uninstall failed with exit code %EXITCODE%.
)
echo.
pause
exit /b %EXITCODE%
