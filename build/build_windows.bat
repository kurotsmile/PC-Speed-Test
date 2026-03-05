@echo off
setlocal

cd /d "%~dp0\.."

python build\generate_icon.py

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  python -m pip install --user pyinstaller
)

set "PYINSTALLER_CONFIG_DIR=%CD%\.pyinstaller-cache"
python -m PyInstaller --clean --noconfirm build\pyinstaller\pc_speed_test.spec

echo Build complete. Check the dist\ folder.
endlocal
