@echo off
setlocal
cd /d "%~dp0"

echo Installing Koe Kichi for Windows...
echo.

if exist "%~dp0scripts\windows_source_install.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows_source_install.ps1"
) else if exist "%~dp0windows_install.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_install.ps1" -SkipBuild
) else (
  echo Installer files were not found.
  echo Expected scripts\windows_source_install.ps1 or windows_install.ps1 next to this file.
  exit /b 1
)
set EXITCODE=%ERRORLEVEL%

echo.
if not "%EXITCODE%"=="0" (
  echo Installation failed with exit code %EXITCODE%.
  echo Please copy this window text when reporting the issue.
) else (
  echo Installation finished.
  echo Start Koe Kichi from the Start Menu.
)
echo.
pause
exit /b %EXITCODE%
