@echo off
setlocal enabledelayedexpansion

REM Get script directory
set SCRIPT_DIR=%~dp0
set WEB_DIR=%SCRIPT_DIR%web
set PROJECT_ID=pcspeedtool
set FIREBASE_ACCOUNT=nguyennhung2672@gmail.com

echo.
echo === Firebase Web Deploy ===
echo Project: %PROJECT_ID%
echo Account: %FIREBASE_ACCOUNT%
echo.

REM Check and install Firebase CLI if needed
call :check_firebase_cli
if !errorlevel! neq 0 (
    goto error_exit
)

REM Check if web directory exists
call :check_web_dir
if !errorlevel! neq 0 (
    goto error_exit
)

REM Ensure account is logged in
call :ensure_account_login
if !errorlevel! neq 0 (
    goto error_exit
)

REM Deploy to Firebase Hosting
call :deploy_hosting
if !errorlevel! neq 0 (
    goto error_exit
)

echo.
echo Deploy thanh cong.
pause
exit /b 0

:error_exit
echo.
echo Deploy that bai. Kiem tra loi o phan tren.
pause
exit /b 1

REM ===== Functions =====

:check_firebase_cli
where firebase >nul 2>&1
if !errorlevel! equ 0 (
    exit /b 0
)

echo Khong tim thay Firebase CLI.
echo Dang kiem tra Node.js va npm...

call :check_nodejs
if !errorlevel! neq 0 (
    exit /b 1
)

echo Dang cai dat Firebase CLI...
call npm install -g firebase-tools
if !errorlevel! neq 0 (
    echo Khong the cai dat Firebase CLI. Kiem tra kết noi internet va quyen truy cap.
    exit /b 1
)

echo Firebase CLI da duoc cai dat thanh cong.
exit /b 0

:check_nodejs
where npm >nul 2>&1
if !errorlevel! equ 0 (
    exit /b 0
)

echo Khong tim thay Node.js.
echo Dang cai dat tu dong Node.js...

REM Try winget
where winget >nul 2>&1
if !errorlevel! equ 0 (
    echo Dang cai dat Node.js bang winget...
    call winget install OpenJS.NodeJS -e -h
    if !errorlevel! equ 0 (
        echo Node.js da duoc cai dat thanh cong.
        REM Refresh environment
        call refreshenv.cmd 2>nul
        exit /b 0
    )
)

REM Try chocolatey
where choco >nul 2>&1
if !errorlevel! equ 0 (
    echo Dang cai dat Node.js bang chocolatey...
    call choco install nodejs -y
    if !errorlevel! equ 0 (
        echo Node.js da duoc cai dat thanh cong.
        exit /b 0
    )
)

echo Khong the cai dat Node.js tu dong.
echo Vui long tai Node.js tu: https://nodejs.org/
echo Sau do chay lai script nay.
exit /b 1

:check_web_dir
if exist "%WEB_DIR%" (
    exit /b 0
)
echo Khong tim thay thu muc web: %WEB_DIR%
exit /b 1

:ensure_account_login
REM Check if account is already logged in
firebase login:list 2>nul | findstr "%FIREBASE_ACCOUNT%" >nul
if !errorlevel! equ 0 (
    echo Da tim thay tai khoan Firebase: %FIREBASE_ACCOUNT%
    exit /b 0
)

echo Tai khoan %FIREBASE_ACCOUNT% chua duoc them vao Firebase CLI.
echo Dang mo dang nhap de them tai khoan...
call firebase login --reauth --no-localhost
if !errorlevel! neq 0 (
    echo Dang nhap that bai.
    exit /b 1
)

REM Verify account was added
firebase login:list 2>nul | findstr "%FIREBASE_ACCOUNT%" >nul
if !errorlevel! equ 0 (
    echo Da them tai khoan thanh cong: %FIREBASE_ACCOUNT%
    exit /b 0
)

echo Van chua thay tai khoan %FIREBASE_ACCOUNT% sau khi dang nhap.
echo Hay dang nhap dung email roi chay lai.
exit /b 1

:deploy_hosting
cd /d "%WEB_DIR%"
if !errorlevel! neq 0 (
    echo Khong the chuyen den thu muc web: %WEB_DIR%
    exit /b 1
)

echo Dang deploy Firebase Hosting...
call firebase deploy --only hosting --project %PROJECT_ID% --account %FIREBASE_ACCOUNT%
exit /b !errorlevel!
