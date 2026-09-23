@echo off
setlocal

cd /d "%~dp0"

echo Setting up the thermo-acoustic control environment...
echo.

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_COMMAND=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Could not find Python.
        echo Install 64-bit Python 3.11 or newer from https://www.python.org/downloads/windows/
        echo Make sure the Python launcher or python.exe is available on PATH.
        goto :failed
    )
    set "PYTHON_COMMAND=python"
)

%PYTHON_COMMAND% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo Python 3.11 or newer is required.
    goto :failed
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv...
    %PYTHON_COMMAND% -m venv ".venv"
    if errorlevel 1 (
        echo Failed to create .venv.
        goto :failed
    )
) else (
    echo Using the existing .venv.
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo The existing .venv uses Python older than 3.11.
    echo Rename or remove .venv, then run this setup again.
    goto :failed
)

echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to update pip.
    goto :failed
)

echo Installing Python dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade -r "requirements-exp_ctrl.txt"
if errorlevel 1 (
    echo Dependency installation failed.
    echo Git must be installed and available on PATH to install pyMeCom.
    goto :failed
)

echo.
echo Checking installed Python dependencies...
".venv\Scripts\python.exe" "tools\check_environment.py"
if errorlevel 1 (
    echo The environment check reported missing core dependencies.
    goto :failed
)

echo.
echo Python environment setup completed successfully.
echo.
echo IMPORTANT: Real hardware also requires vendor software installed separately:
echo   - Hamamatsu DCAM-API and dcamapi.dll
echo   - Digilent WaveForms and dwf.dll
echo   - CETONI Qmix SDK with QMIXSDK configured
echo   - Thorlabs Kinesis
echo.
echo After installing the required vendor software, run launch_ui_real.bat.
pause
exit /b 0

:failed
echo.
echo Environment setup did not complete.
pause
exit /b 1
