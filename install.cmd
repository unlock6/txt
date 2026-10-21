@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import tkinter" >nul 2>&1
if errorlevel 1 (
  echo Please install Python 3.12 from https://www.python.org/downloads/windows/
  echo Include the Python launcher and Tcl/Tk during installation.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install .
if errorlevel 1 goto failed
echo Installation complete. Double-click run.cmd to start.
pause
exit /b 0
:failed
echo Installation failed. Check the message above and your internet connection.
pause
exit /b 1
