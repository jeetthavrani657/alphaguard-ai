@echo off
rem Start the NSE research terminal (read-only; never runs a strategy).
rem Double-click to run. Opens http://127.0.0.1:8000 in your browser; close this
rem window (or press Ctrl+C) to stop it.
rem
rem Runs from this folder. The Python path below is the one that has the
rem project's packages installed (pandas, fastapi, uvicorn, ...); if Python is
rem ever reinstalled elsewhere, update it here -- same convention as
rem run_forward_log.bat.
rem
rem Results are produced separately, in a terminal:
rem     python -m webapp.backend.snapshot
rem This script only serves what that already wrote.

cd /d "%~dp0"
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" run_webapp.py --open %*
if errorlevel 1 pause
exit /b %ERRORLEVEL%
