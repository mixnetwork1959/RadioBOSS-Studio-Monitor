@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo RadioBOSS Studio Monitor v1.0.1 - Public Windows Build
echo ============================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py"
) else (
  set "PY_CMD=python"
)

%PY_CMD% --version
if errorlevel 1 (
  echo.
  echo ERROR: Python 3.11 or newer was not found.
  echo Install Python and enable Add Python to PATH.
  pause
  exit /b 1
)

echo.
echo Installing build requirements...
%PY_CMD% -m pip install --upgrade pip
%PY_CMD% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :failed

echo.
echo Running source tests...
%PY_CMD% "%~dp0selftest.py"
if errorlevel 1 goto :failed

echo.
echo Cleaning previous build output...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"
if exist "%~dp0release-package" rmdir /s /q "%~dp0release-package"

echo.
echo Building portable Windows EXE...
%PY_CMD% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "RadioBOSS-Studio-Monitor" ^
  --collect-all PySide6 ^
  --collect-all pycaw ^
  --collect-all comtypes ^
  --hidden-import=PySide6.QtSvg ^
  --hidden-import=PySide6.QtNetwork ^
  "%~dp0StudioMonitorNative.py"
if errorlevel 1 goto :failed

mkdir "%~dp0release-package"
copy /y "%~dp0dist\RadioBOSS-Studio-Monitor.exe" "%~dp0release-package\RadioBOSS-Studio-Monitor.exe" >nul
copy /y "%~dp0README.md" "%~dp0release-package\README.md" >nul
copy /y "%~dp0NOTICE.txt" "%~dp0release-package\NOTICE.txt" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path '%~dp0release-package\*' -DestinationPath '%~dp0RadioBOSS-Studio-Monitor-v1.0.1-Windows.zip' -Force"
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo BUILD COMPLETE
echo ============================================================
echo EXE: %~dp0dist\RadioBOSS-Studio-Monitor.exe
echo ZIP: %~dp0RadioBOSS-Studio-Monitor-v1.0.1-Windows.zip
echo.
echo The ZIP contains no configuration, password, or log files.
pause
exit /b 0

:failed
echo.
echo ============================================================
echo BUILD FAILED
echo ============================================================
pause
exit /b 1
