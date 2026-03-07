@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "WEB_DIR=%SCRIPT_DIR%web"
set "PUBLIC_DIR=%WEB_DIR%\public"
set "HOST=localhost"
set "FIREBASE_PORT=5000"
set "PY_PORT=8080"
set "PS_PORT=9090"
set "PY_CMD="
set "FIREBASE_CMD="

echo.
echo === Run PC Speed Test Web (Local) ===
echo Root: %SCRIPT_DIR%
echo.

if not exist "%WEB_DIR%" (
  echo [ERROR] Missing folder: %WEB_DIR%
  pause
  exit /b 1
)

if not exist "%PUBLIC_DIR%" (
  echo [ERROR] Missing folder: %PUBLIC_DIR%
  pause
  exit /b 1
)

cd /d "%WEB_DIR%"

call :find_firebase
if defined FIREBASE_CMD (
  echo Starting Firebase Hosting emulator...
  echo URL: http://%HOST%:%FIREBASE_PORT%
  start "" cmd /c "timeout /t 2 /nobreak >nul && start http://%HOST%:%FIREBASE_PORT%"
  call "%FIREBASE_CMD%" emulators:start --only hosting --project pcspeedtool --host %HOST% --port %FIREBASE_PORT%
  if not errorlevel 1 exit /b 0
  echo Firebase emulator failed. Falling back to Python static server...
)

echo Firebase CLI not available. Using Python static server...
call :find_python
if not defined PY_CMD (
  echo Python 3 not found. Falling back to built-in PowerShell server...
  goto run_powershell_server
)

cd /d "%PUBLIC_DIR%"
echo Starting static server with %PY_CMD% ...
echo URL: http://%HOST%:%PY_PORT%
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://%HOST%:%PY_PORT%"
call %PY_CMD% -m http.server %PY_PORT% --bind %HOST%
exit /b %errorlevel%

:run_powershell_server
echo Starting PowerShell static server...
echo URL: http://%HOST%:%PS_PORT%
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://%HOST%:%PS_PORT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%WEB_DIR%\serve_public.ps1" -Root "%PUBLIC_DIR%" -HostName "%HOST%" -Port %PS_PORT%
exit /b %errorlevel%

:find_firebase
where firebase.cmd >nul 2>&1
if not errorlevel 1 (
  set "FIREBASE_CMD=firebase.cmd"
  exit /b 0
)
if exist "%APPDATA%\npm\firebase.cmd" (
  set "FIREBASE_CMD=%APPDATA%\npm\firebase.cmd"
  exit /b 0
)
exit /b 1

:find_python
for %%C in ("py -3" "python" "python3") do (
  set "CANDIDATE=%%~C"
  call !CANDIDATE! -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=!CANDIDATE!"
    exit /b 0
  )
)
for %%P in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%LocalAppData%\Programs\Python\Python310\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python311\python.exe"
  "%ProgramFiles%\Python310\python.exe"
) do (
  if exist %%~P (
    call "%%~P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if not errorlevel 1 (
      set "PY_CMD="%%~P""
      exit /b 0
    )
  )
)
exit /b 1
