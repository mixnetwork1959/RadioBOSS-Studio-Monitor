@echo off
setlocal
cd /d "%~dp0"
echo Installing Windows Core Audio meter dependencies...
where py >nul 2>nul
if %errorlevel%==0 (
  py -m pip install -r "%~dp0requirements-audio.txt"
) else (
  python -m pip install -r "%~dp0requirements-audio.txt"
)
if errorlevel 1 (
  echo.
  echo Installation failed.
  pause
  exit /b 1
)
echo.
echo Audio meter installed. Restart Studio Monitor.
pause
