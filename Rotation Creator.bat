@echo off
rem Double-click to start the interactive Wardogs Rotation Creator.
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_python
echo Python was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup.
pause
exit /b 1

:run_py
py rotate.py
exit /b

:run_python
python rotate.py
