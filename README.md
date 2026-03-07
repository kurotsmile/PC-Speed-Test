# PC Speed Test

PC Speed Test is a lightweight system health and performance tool with:
- Desktop app (GUI + CLI) in Python
- Custom benchmark plugins
- TXT/JSON/PDF reporting
- Static website (Firebase Hosting) for product landing

## 1) Main Features

- Collect system info: CPU, RAM, disk, network, OS
- Run lightweight benchmarks:
  - CPU loop
  - RAM copy
  - Disk read/write
  - File operations
  - Network latency/DNS/jitter
- One-click Health Check: overall score + optimization suggestions
- Save benchmark/snapshot history for trend tracking
- Custom alert thresholds for RAM/Disk/CPU
- Plugin benchmark support in `plugins/`
- GUI dashboard for end users
- CLI mode for scripts/automation

## 2) Project Structure

```text
PC-Speed-Test/
|- Pc_speed_test.py              # Main app (GUI + CLI)
|- requirements.txt              # Required dependencies
|- requirements-optional.txt     # reportlab, pyinstaller
|- Run_Pc_Speed_Test.bat         # Windows launcher (source mode)
|- Run_Pc_Speed_Test.command     # macOS launcher (source mode)
|- package_windows.cmd           # Quick Windows packaging script
|- build/
|  |- build_windows.bat          # Windows build script (PyInstaller)
|  |- build_mac.sh               # macOS build script
|  |- pyinstaller/pc_speed_test.spec
|  `- assets/                    # Icons/images for packaging
|- plugins/
|  |- README.md
|  `- example_python_benchmark.py
`- web/
   |- firebase.json
   |- .firebaserc
   |- public/                    # Static web files
   `- README.md
```

## 3) Requirements

- Python 3.8+ (3.10+ recommended)
- pip
- Tkinter (for GUI)
- `psutil` (in `requirements.txt`)
- `reportlab` for PDF export (in `requirements-optional.txt`)

## 4) Run the Project (Source Mode)

### Windows

```powershell
cd D:\Projects\PC-Speed-Test
.\Run_Pc_Speed_Test.bat
```

Or run directly:

```powershell
python Pc_speed_test.py --gui --benchmark
```

### macOS

```bash
cd /path/to/PC-Speed-Test
sh Run_Pc_Speed_Test.command
```

Or:

```bash
python3 Pc_speed_test.py --gui --benchmark
```

## 5) CLI Usage

Show all options:

```bash
python Pc_speed_test.py --help
```

Common commands:

```bash
# Quick text report
python Pc_speed_test.py --benchmark

# JSON output
python Pc_speed_test.py --benchmark --json

# Open GUI
python Pc_speed_test.py --gui

# Health check (includes benchmark + score)
python Pc_speed_test.py --health-check

# Export report as PDF/TXT/JSON
python Pc_speed_test.py --benchmark --export-report --report-format pdf
python Pc_speed_test.py --benchmark --export-report --report-format txt
python Pc_speed_test.py --benchmark --export-report --report-format json

# Background monitor
python Pc_speed_test.py --background-monitor --monitor-interval 60
python Pc_speed_test.py --background-monitor --monitor-once

# Open Task Manager (Windows) / Activity Monitor (macOS)
python Pc_speed_test.py --open-system-monitor

# Check local update metadata
python Pc_speed_test.py --check-update
python Pc_speed_test.py --check-update --auto-update

# Set alert thresholds
python Pc_speed_test.py --set-ram-threshold 85
python Pc_speed_test.py --set-disk-threshold 90
python Pc_speed_test.py --set-cpu-threshold 90
```

## 6) Output Data

The app writes data under `output/`:
- `output/reports/`: TXT/JSON reports
- `output/pdf/`: PDF reports
- `output/history/benchmark_history.json`: benchmark history
- `output/history/system_snapshots.json`: monitor snapshots
- `output/alert_thresholds.json`: alert thresholds

Note:
- In packaged mode, `output/` is created next to the `.exe`.

## 7) Plugin Benchmarks

Add `.py` files in `plugins/`.

Rules:
- Must define `run_test()`
- `run_test()` must return a `dict`
- Optional `score` (0..100) is used in Health Check

Example:

```python
def run_test():
    return {
        "name": "db-test",
        "score": 78.5,
        "latency_ms": 42.1,
    }
```

## 8) Build and Packaging

### Windows (Recommended)

Quick script:

```powershell
cd D:\Projects\PC-Speed-Test
.\package_windows.cmd
```

Expected output:
- Single executable: `dist\PC Speed Test.exe`

### Windows (Manual)

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-optional.txt
build\build_windows.bat
```

### macOS

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-optional.txt
sh build/build_mac.sh
```

Expected outputs:
- `dist/PC Speed Test.app`
- `dist/PC-Speed-Test-macOS.zip`

## 9) Deploy Website to Firebase Hosting

Web folder: `web/`

### Quick (Windows)

```powershell
cd D:\Projects\PC-Speed-Test
.\deploy_web.bat
```

### Quick (macOS)

```bash
cd /path/to/PC-Speed-Test
sh deploy_web.command
```

### Manual

```bash
npm install -g firebase-tools
firebase login
cd web
firebase use pcspeedtool
firebase deploy --only hosting
```

## 10) Suggested Operation Flow

1. Validate source mode (`python Pc_speed_test.py --gui --benchmark`)
2. Build package (Windows: `package_windows.cmd`)
3. Test package on a clean machine (without source code)
4. Update version metadata in `build/latest_version.json` if using update flow
5. Deploy web if landing page changes are needed

## 11) Troubleshooting

- `firebase is not recognized`:
  - Install Node.js
  - Add to PATH:
    - `C:\Program Files\nodejs`
    - `%APPDATA%\npm`
  - Restart terminal

- Double-click `.exe` does not open GUI:
  - Latest build defaults to GUI when run without arguments
  - Rebuild with `package_windows.cmd`

- PDF export fails:
  - Install `reportlab`:
    - `python -m pip install reportlab`

- Blocked by antivirus/SmartScreen:
  - Use code signing for release builds
  - Whitelist app in internal environments

## 12) License

No dedicated license file is currently included. If you plan a public release, add a `LICENSE` file.
