@echo off
setlocal
rem Starts the access layer and Dolphin together, using the paths Setup
rem recorded. This is the file to run every time you play.
rem
rem launch_accessible.py closes any access layer still running from an
rem earlier session before it starts a new one, so double-clicking this
rem twice, or after a crash, leaves one companion running rather than two
rem talking over each other.
rem
rem Runtime\ is the interpreter a built release carries; .venv is what a
rem source checkout builds. If neither is here, Setup has not been run --
rem launch_accessible.py says so itself, so this only has to find an
rem interpreter capable of delivering that message.
set "PYTHON="
if exist "%~dp0Runtime\python.exe" set "PYTHON=%~dp0Runtime\python.exe"
if not defined PYTHON if exist "%~dp0Companion\.venv\Scripts\python.exe" set "PYTHON=%~dp0Companion\.venv\Scripts\python.exe"
if not defined PYTHON (
  echo.
  echo This copy has not been set up yet. Run Setup.cmd first.
  echo.
  pause
  exit /b 1
)

"%PYTHON%" "%~dp0Companion\launch_accessible.py"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
endlocal
