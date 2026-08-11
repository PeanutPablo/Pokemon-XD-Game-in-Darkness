@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Tools\Build Accessibility Release.ps1" %*
if errorlevel 1 (
  echo.
  echo Release creation failed. No archive should be distributed.
  pause
  exit /b 1
)
echo.
echo Accessibility-only release created successfully.
pause
endlocal
