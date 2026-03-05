#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

python3 build/generate_icon.py

if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
  python3 -m pip install --user pyinstaller
fi
PYINSTALLER_CONFIG_DIR="$PWD/.pyinstaller-cache" \
  python3 -m PyInstaller --clean --noconfirm build/pyinstaller/pc_speed_test.spec

if [ -d "dist/PC Speed Test.app" ]; then
  xattr -cr "dist/PC Speed Test.app" || true
  codesign --force --deep --sign - "dist/PC Speed Test.app"
  rm -f "dist/PC-Speed-Test-macOS.zip"
  ditto -c -k --sequesterRsrc --keepParent "dist/PC Speed Test.app" "dist/PC-Speed-Test-macOS.zip"
fi

printf '%s\n' "Build complete. Check the dist/ folder."
