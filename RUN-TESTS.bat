@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py"
) else (
  set "PY_CMD=python"
)
%PY_CMD% "%~dp0selftest.py"
if errorlevel 1 goto :failed
%PY_CMD% "%~dp0test_connection_recovery.py"
if errorlevel 1 goto :failed
%PY_CMD% "%~dp0test_display_modes.py"
if errorlevel 1 goto :failed
echo.
echo ALL TESTS PASSED
pause
exit /b 0
:failed
echo.
echo TEST FAILED
pause
exit /b 1
