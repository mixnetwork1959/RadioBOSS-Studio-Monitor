@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo RadioBOSS Studio Monitor Diagnostics
echo ============================================================
echo.
echo Folder: %CD%
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py --version
  py "%~dp0selftest.py"
) else (
  python --version
  python "%~dp0selftest.py"
)
echo.
if errorlevel 1 (
  echo RESULT: ERROR
) else (
  echo RESULT: All offline tests passed
)
echo.
pause
