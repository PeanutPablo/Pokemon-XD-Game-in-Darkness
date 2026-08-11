@echo off
setlocal
rem First-run setup. Picks the newest suitable Python it can find: the
rem launcher package (dolphin-memory-engine) has no build for anything
rem past 3.12, so 3.12 is tried by name before falling back to whatever
rem "python" happens to be, and setup_companion.py checks the version it
rem actually got and says so plainly if it is too new.
set "PYTHON="
for %%V in (3.12 3.11 3.10) do (
  if not defined PYTHON (
    py -%%V -c "import sys" >nul 2>&1 && set "PYTHON=py -%%V"
  )
)
if not defined PYTHON (
  python -c "import sys" >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
  echo.
  echo Python was not found on this computer.
  echo.
  echo Install Python 3.12 from https://www.python.org/downloads/ and tick
  echo "Add python.exe to PATH" during installation, then run Setup.cmd again.
  echo.
  pause
  exit /b 1
)

%PYTHON% "%~dp0Companion\setup_companion.py"
if errorlevel 1 (
  echo.
  echo Setup did not finish. Nothing has been changed outside this folder.
  pause
  exit /b 1
)
echo.
pause
endlocal
