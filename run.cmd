@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m recording_to_text
if errorlevel 1 pause
