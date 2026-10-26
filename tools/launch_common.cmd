@echo off
rem Shared launcher. Usage: launch_common.cmd simulation|real
rem Called by launch_ui.bat (simulation) and launch_ui_real.bat (real). The mode is fixed by the
rem caller and is never changed here, whatever happens while looking for Python.
rem
rem Python is chosen from this list, first usable one wins (each is validated by
rem tools\check_launch_python.py for the mode):
rem   1. %THERMO_ACOUSTIC_PYTHON%  explicit choice; if set but unusable the launch fails, no fallback
rem   2. <workspace>\.venv\Scripts\python.exe
rem   3. %USERPROFILE%\.conda\envs\exp_ctrl\python.exe   (the lab's named conda environment)
rem PATH is not searched. Nothing is installed or changed.
rem Parenthesised if-blocks are avoided on purpose: a folder name with ")" breaks them.
rem Test hooks: THERMO_ACOUSTIC_DRY_RUN=1 prints the command and stops; THERMO_ACOUSTIC_NO_PAUSE=1
rem skips the "press a key" pauses.
setlocal EnableExtensions

set "MODE="
if /i "%~1"=="simulation" set "MODE=simulation"
if /i "%~1"=="real" set "MODE=real"
if not defined MODE goto badmode

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "CHECK_OUT=%TEMP%\thermo_acoustic_launch_check_%RANDOM%.txt"
set "PY="
set "N=0"

if defined THERMO_ACOUSTIC_PYTHON goto explicit
call :try "%ROOT%\.venv\Scripts\python.exe" "workspace .venv"
call :try "%USERPROFILE%\.conda\envs\exp_ctrl\python.exe" "conda environment exp_ctrl"
goto selected

:explicit
call :try "%THERMO_ACOUSTIC_PYTHON%" "THERMO_ACOUSTIC_PYTHON"

:selected
if exist "%CHECK_OUT%" del "%CHECK_OUT%" >nul 2>&1
if not defined PY goto nopython

echo Using Python: %PY%
echo Mode: %MODE%
if "%MODE%"=="real" echo REAL hardware mode: Connect actions access devices directly; no extra connection confirmation is shown.
if defined THERMO_ACOUSTIC_DRY_RUN goto dryrun

cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%\src"
"%PY%" -m thermo_acoustic.main --mode %MODE%
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" exit /b 0
echo.
echo The thermo-acoustic UI exited with error code %EXIT_CODE% (mode: %MODE%).
if not defined THERMO_ACOUSTIC_NO_PAUSE pause
exit /b %EXIT_CODE%

:dryrun
echo DRY RUN, not started: PYTHONPATH=%ROOT%\src  "%PY%" -m thermo_acoustic.main --mode %MODE%
exit /b 0

:badmode
echo Internal error: the launch mode must be "simulation" or "real", not "%~1".
goto fail

:nopython
echo.
echo Could not start the thermo-acoustic UI in %MODE% mode: no usable Python was found.
echo.
echo Tried, in order:
if %N% GEQ 1 echo   1. %LABEL_1%: %WHY_1%
if %N% GEQ 2 echo   2. %LABEL_2%: %WHY_2%
if %N% GEQ 3 echo   3. %LABEL_3%: %WHY_3%
echo.
if defined THERMO_ACOUSTIC_PYTHON echo THERMO_ACOUSTIC_PYTHON is set, so no other Python was tried. Fix it or clear it.
echo What to do (nothing is installed automatically):
echo   - Point the launcher at an existing Python 3.11+ that has the packages, then run it again:
echo         set THERMO_ACOUSTIC_PYTHON=C:\full\path\to\python.exe
echo     (or set it permanently in Windows "Environment Variables"). You can test an interpreter with:
echo         "C:\full\path\to\python.exe" "%ROOT%\tools\check_launch_python.py" %MODE%
echo   - Or create the workspace environment yourself with setup_windows_environment.bat
echo     (it creates .venv and installs the packages from requirements-exp_ctrl.txt).
echo   - Real mode also needs pyserial, pythonnet and mecom in the same interpreter.
goto fail

:fail
if not defined THERMO_ACOUSTIC_NO_PAUSE pause
exit /b 1

:try
rem %1 = python.exe to try, %2 = label. Sets PY when usable; otherwise records why not.
if defined PY goto :eof
set /a N+=1
set "LABEL_%N%=%~2"
if exist "%~1" goto try_check
set "WHY_%N%=not found (%~1)"
goto :eof
:try_check
"%~1" "%ROOT%\tools\check_launch_python.py" %MODE% > "%CHECK_OUT%" 2>&1
if errorlevel 1 goto try_rejected
set "PY=%~1"
goto :eof
:try_rejected
set "DETAIL=no details"
for /f "usebackq delims=" %%L in ("%CHECK_OUT%") do set "DETAIL=%%L"
set "WHY_%N%=%~1 cannot be used - %DETAIL%"
goto :eof
