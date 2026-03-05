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

Outputs will be written under `dist/`:

- `PC Speed Test.app`
- `PC-Speed-Test-macOS.zip`

## Windows

Run:

```bat
build\build_windows.bat
```

## Notes

- The current spec bundles `Pc_speed_test.py`.
- The current build uses `onedir`, which is more reliable for desktop distribution than onefile app bundles on macOS.
- Launcher scripts can be distributed beside the packaged app if desired.
- PDF export will work inside the packaged build only if `reportlab` is installed before packaging.
