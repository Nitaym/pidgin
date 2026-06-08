@echo off
REM Start the Pidgin Office backend (Python stdlib API on :8770)
cd /d "%~dp0backend"
echo Starting backend on http://localhost:8770 ...
python server.py
