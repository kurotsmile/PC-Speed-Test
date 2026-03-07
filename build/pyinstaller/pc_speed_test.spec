# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None
project_root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
is_darwin = sys.platform == "darwin"
is_windows = sys.platform.startswith("win")
icon_icns = os.path.join(project_root, "build", "assets", "pc_speed_test.icns")
icon_ico = os.path.join(project_root, "build", "assets", "pc_speed_test.ico")

a = Analysis(
    [os.path.join(project_root, "Pc_speed_test.py")],
    pathex=[project_root],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if is_windows:
    # Windows: build onefile so users can copy just one executable.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        exclude_binaries=False,
        name="PC Speed Test",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon=icon_ico if os.path.exists(icon_ico) else None,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="PC Speed Test",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon=icon_ico if os.path.exists(icon_ico) else None,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

if not is_windows:
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="PC Speed Test",
    )

if is_darwin:
    app = BUNDLE(
        coll,
        name="PC Speed Test.app",
        icon=icon_icns if os.path.exists(icon_icns) else None,
        bundle_identifier="com.pcspeedtest.app",
    )
