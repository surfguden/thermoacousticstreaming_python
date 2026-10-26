@echo off
rem Double-click to start the UI in SIMULATION mode. No hardware is touched.
rem Python selection, failure messages and options: tools\launch_common.cmd
call "%~dp0tools\launch_common.cmd" simulation
exit /b %ERRORLEVEL%
