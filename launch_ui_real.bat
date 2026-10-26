@echo off
rem Double-click to start the UI in REAL mode, on an authorized workstation only.
rem Connect actions access real devices; there is no additional per-connection confirmation.
rem If no suitable Python is found this stops; it never falls back to simulation.
rem Python selection, failure messages and options: tools\launch_common.cmd
call "%~dp0tools\launch_common.cmd" real
exit /b %ERRORLEVEL%
