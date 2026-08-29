@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py "%~dp0test_radioboss_api.py"
) else (
  python "%~dp0test_radioboss_api.py"
)
pause
