@echo off
rem view-specs -- serve the static Pidgin specs site and open it in a browser.
rem Double-click this file, or run it from a terminal. Ctrl+C to stop.
setlocal
set "ROOT=%~dp0"
set "PORT=8791"

rem Prefer the project venv's Python; fall back to whatever is on PATH.
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   Pidgin specs  ->  http://localhost:%PORT%/
echo   Press Ctrl+C to stop the server.
echo.

start "" "http://localhost:%PORT%/index.html"
"%PY%" -m http.server %PORT% --directory "%ROOT%specs"
