@echo off
cd /d "%~dp0"
set "PROG="
for /d %%D in ("%~dp0*") do if exist "%%~fD\layout.py" if exist "%%~fD\tips_console.pyw" set "PROG=%%~fD"
if not defined PROG if exist "%~dp0tips_console.pyw" set "PROG=%~dp0"
if not defined PROG (
  echo Cannot find tips_console.pyw. Please unzip ALL files into this folder, then double-click this file again.
  pause
  exit /b 1
)
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw "%PROG%\tips_console.pyw"
  exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%PROG%\tips_console.pyw"
  exit /b 0
)
echo Python was not found on this computer.
echo Please install Python 3 from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer, then double-click this file again.
pause
