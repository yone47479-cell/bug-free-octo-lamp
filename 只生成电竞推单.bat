@echo off
cd /d "%~dp0"
set "ES_PROG="
for /d %%D in ("%~dp0*") do if exist "%%~fD\esports_data.py" set "ES_PROG=%%~fD\esports_data.py"
if not defined ES_PROG if exist "%~dp0esports_data.py" set "ES_PROG=%~dp0esports_data.py"
if not defined ES_PROG (
  echo Cannot find esports_data.py. Extract the complete package first.
  pause
  exit /b 1
)
python "%ES_PROG%"
pause
