@echo off
rem Command-line version of the daily routine (no window). Same steps as the One-Click Update button.
cd /d "%~dp0"
set "PROG="
for /d %%D in ("%~dp0*") do if exist "%%~fD\layout.py" if exist "%%~fD\gen_tips.py" set "PROG=%%~fD"
if not defined PROG if exist "%~dp0gen_tips.py" set "PROG=%~dp0"
if not defined PROG (
  echo Cannot find gen_tips.py. Please unzip ALL files into this folder first, then run this file again.
  pause
  exit /b 1
)
rem --fetch: download today's data first (export_500_all.py --keep-older-draws).
rem --backfill: if a day was skipped, fetch that day's results automatically so yesterday's tips still get reviewed.
rem --team-data: fetch real two-team data before every pick. Default source = Sina lottery articles (free, no key needed);
rem   if api_key.txt exists it also uses the API-Football key to fill the gaps (see --source in gen_tips.py).
python "%PROG%\gen_tips.py" --fetch --limit 280 --backfill --team-data
pause
