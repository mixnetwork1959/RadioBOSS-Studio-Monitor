@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py "%~dp0StudioMonitorNative.py"
) else (
  python "%~dp0StudioMonitorNative.py"
)
if errorlevel 1 pause
