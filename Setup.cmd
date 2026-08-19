@echo off
setlocal
rem First-run setup.
rem
rem A built release carries its own interpreter in Runtime\, so there is
rem nothing to find and nothing to install -- that branch is the one a
rem player takes, and it needs neither a Python installation nor an
rem internet connection.
rem
rem A source checkout has no Runtime\, and falls back to picking the newest
rem suitable Python on the machine: dolphin-memory-engine has no build for
rem anything past 3.12, so 3.12 is tried by name before falling back to
rem whatever "python" happens to be, and setup_companion.py checks the
rem version it actually got and says so plainly if it is too new.
set "PYTHON="
if exist "%~dp0Runtime\python.exe" set "PYTHON=%~dp0Runtime\python.exe"

if not defined PYTHON (
  for %%V in (3.12 3.11 3.10) do (
    if not defined PYTHON (
      py -%%V -c "import sys" >nul 2>&1 && set "PYTHON=py -%%V"
    )
  )
)
if not defined PYTHON (
  python -c "import sys" >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
  echo.
  echo Python was not found on this computer.
  echo.
  echo This looks like a source checkout rather than a release. A release
  echo brings its own Python and does not need one installed.
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
