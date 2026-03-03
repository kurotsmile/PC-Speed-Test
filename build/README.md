# Build Packaging

This folder prepares PC Speed Test for desktop packaging with PyInstaller.

## Optional dependencies

For PDF export support:

```bash
python3 -m pip install -r requirements-optional.txt
```

For packaging:

```bash
python3 -m pip install pyinstaller
```

## macOS

```bash
cd /Users/rot/Desktop/PC\ Speed\ Test\ 
sh build/build_mac.sh
```

Output will be written under `dist/`.

## Windows

Run:

```bat
build\build_windows.bat
```

## Notes

- The current spec bundles `Pc_speed_test.py`.
- Launcher scripts can be distributed beside the packaged app if desired.
- PDF export will work inside the packaged build only if `reportlab` is installed before packaging.
