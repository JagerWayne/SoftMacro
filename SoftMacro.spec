# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller one-folder build for SoftMacro.
# Build with:  pyinstaller --noconfirm --clean SoftMacro.spec
# (or run build_installer.bat, which also compiles the Inno Setup installer)

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static'), ('events.txt', '.'), ('LICENSE', '.'), ('README.md', '.')],
    hiddenimports=['pystray._win32', 'keyboard._winkeyboard', 'keyboard._winmouse', 'pynput.keyboard._win32', 'pynput.mouse._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SoftMacro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['softmacro.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SoftMacro',
)
