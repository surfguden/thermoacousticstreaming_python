@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Could not find .venv\Scripts\python.exe
    echo Create the project virtual environment and install the UI dependencies first.
    pause
    exit /b 1
)

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m thermo_acoustic.main --mode real

if errorlevel 1 (
    echo.
    echo The thermo-acoustic UI exited with an error.
    pause
)

endlocal
