@echo off
setlocal

cd /d "%~dp0"

echo.
echo === Package PC Speed Test for Windows ===
echo Working dir: %CD%
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python khong co trong PATH.
  echo Cai Python roi mo terminal moi, sau do chay lai script nay.
  exit /b 1
)

python --version
if errorlevel 1 (
  echo [ERROR] Khong the chay python.
  exit /b 1
)

python -m pip --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] pip chua san sang.
  echo Thu chay: python -m ensurepip --upgrade
  exit /b 1
)

echo Dang cai/cap nhat dependencies...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] Khong the cap nhat pip.
  exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Khong the cai dat requirements.txt
  exit /b 1
)

if exist requirements-optional.txt (
  echo Dang cai optional dependencies...
  python -m pip install -r requirements-optional.txt
)

echo.
echo Dang build bang PyInstaller...
call build\build_windows.bat
if errorlevel 1 (
  echo.
  echo [ERROR] Build that bai.
  exit /b 1
)

echo.
echo [OK] Dong goi hoan tat.
echo Kiem tra thu muc dist\
exit /b 0
