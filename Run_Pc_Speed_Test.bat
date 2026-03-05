@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PY_SCRIPT=%SCRIPT_DIR%Pc_speed_test.py"
set "REQ_FILE=%SCRIPT_DIR%requirements.txt"
set "LOG_FILE=%TEMP%\pc_speed_test_gui.log"
set "PY_CMD="

echo === PC Speed Test Launcher (Windows) ===
echo Folder: %SCRIPT_DIR%

if not exist "%PY_SCRIPT%" (
  echo Could not find "%PY_SCRIPT%"
  goto :pause_exit
)

call :find_python
if not defined PY_CMD (
  echo Python 3 was not found.
  echo Please install Python 3.8+ from https://www.python.org/downloads/windows/
  goto :pause_exit
)

echo Found Python: %PY_CMD%

call :ensure_pip
if errorlevel 1 (
  echo Could not initialize pip.
  goto :pause_exit
)

call :install_requirements

call :run_tool
if errorlevel 1 (
  goto :pause_exit
)

exit /b 0

REM Auto-close on error without pause
exit /b %errorlevel%

:find_python
for %%C in ("py -3" "python" "python3") do (
  set "CANDIDATE=%%~C"
  call !CANDIDATE! -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=!CANDIDATE!"
    exit /b 0
  )
)
exit /b 1

:ensure_pip
call %PY_CMD% -m pip --version >nul 2>&1
if not errorlevel 1 exit /b 0

echo pip is not ready. Trying ensurepip...
call %PY_CMD% -m ensurepip --upgrade >nul 2>&1
if errorlevel 1 exit /b 1

call %PY_CMD% -m pip --version >nul 2>&1
exit /b %errorlevel%

:install_requirements
if not exist "%REQ_FILE%" (
  echo requirements.txt not found. Skipping dependency install.
  exit /b 0
)

call %PY_CMD% -c "import psutil" >nul 2>&1
if not errorlevel 1 (
  echo psutil is already installed.
  exit /b 0
)

echo Installing required dependencies...
call %PY_CMD% -m pip install --user -r "%REQ_FILE%"
if not errorlevel 1 exit /b 0

echo Dependency install failed. The tool will still run in basic mode.
exit /b 0

:run_tool
echo.
echo Launching PC Speed Test GUI...

call %PY_CMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
  echo tkinter is not available. Falling back to terminal mode.
  call %PY_CMD% "%PY_SCRIPT%" --benchmark
  exit /b %errorlevel%
)

REM Run Python GUI without cmd window using VBScript
set "TEMP_VBS=%TEMP%\launch_pc_speed_test.vbs"
(
  echo Set objShell = CreateObject("WScript.Shell"^)
  echo strCommand = "%PY_CMD% ""%PY_SCRIPT%"" --gui --benchmark"
  echo objShell.Run strCommand, 0, False
) > "%TEMP_VBS%"

cscript //nologo "%TEMP_VBS%"
del /q "%TEMP_VBS%" >nul 2>&1
exit /b 0

:pause_exit
echo.
exit /b 1
