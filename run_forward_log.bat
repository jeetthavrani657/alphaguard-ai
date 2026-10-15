@echo off
rem Daily forward-test run (FORWARD_TEST.md). Started by the Windows task
rem "NSE-ForwardTest-Daily"; safe to double-click to run by hand.
rem
rem Research only: logs what the frozen rule WOULD have done. Places no orders.
rem
rem Runs from this folder, so the project can be moved without editing this
rem file -- but the Python path below is the one that has the project's
rem packages installed (pandas, yfinance, statsmodels, scipy); if Python is
rem ever reinstalled elsewhere, update it here.
rem
rem Output: the full console report overwrites reports\output\forward_last_run.log
rem (the validator prints a long per-stock report, so history is NOT kept in
rem this log). The history of the NUMBERS is reports\output\forward_snapshots.csv,
rem which gains one row per data date.

cd /d "%~dp0"
if not exist "reports\output" mkdir "reports\output"
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\forward_log.py > "reports\output\forward_last_run.log" 2>&1
exit /b %ERRORLEVEL%
