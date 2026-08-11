@echo off
setlocal
rem Starts the companion and Dolphin together using the paths Setup
rem recorded. Run Setup.cmd first if this reports missing settings.
"%~dp0Companion\.venv\Scripts\python.exe" "%~dp0Companion\launch_accessible.py"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
endlocal
