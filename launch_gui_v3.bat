@echo off
setlocal

rem Launch the Thermo Acoustic Streaming Qt GUI v3 transitional layout.
rem v2 remains available through launch_gui_v2.bat as the rollback path.
rem Machine-specific settings: edit these if the Conda environment or CETONI SDK moves.
set "PYTHON_EXE=C:\Users\Lab user\.conda\envs\exp_ctrl\python.exe"
set "QMIXSDK=C:\Users\Lab user\AppData\Local\CETONI_SDK"

cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python executable not found:
    echo   %PYTHON_EXE%
    echo.
    echo Check that the exp_ctrl Conda environment exists, or edit PYTHON_EXE at the top of this script.
    echo Also confirm QMIXSDK if Qmix hardware will be used:
    echo   %QMIXSDK%
    pause
    exit /b 1
)

"%PYTHON_EXE%" -m thermo_acoustic.qt_ui_v3
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo GUI v3 exited with error code %EXIT_CODE%.
)

pause
exit /b %EXIT_CODE%
