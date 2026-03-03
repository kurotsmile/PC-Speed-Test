#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

python3 -m pip install --upgrade pyinstaller
python3 -m PyInstaller --clean --noconfirm build/pyinstaller/pc_speed_test.spec

printf '%s\n' "Build complete. Check the dist/ folder."
