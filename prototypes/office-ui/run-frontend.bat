@echo off
REM Serve the Pidgin Office frontend (static files on :5500)
cd /d "%~dp0"
echo Serving frontend on http://localhost:5500 ...
npx serve -p 5500 --no-clipboard
