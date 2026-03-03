@echo off
setlocal

cd /d "%~dp0\.."

python -m pip install --upgrade pyinstaller
python -m PyInstaller --clean --noconfirm build\pyinstaller\pc_speed_test.spec

echo Build complete. Check the dist\ folder.
endlocal
