# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Discord Media Downscaler.
# Run via build.bat / build.sh (or: pyinstaller DiscordMediaDownscaler.spec --clean --noconfirm)
#
# Key: collect_data_files('imageio_ffmpeg') pulls in the bundled ffmpeg binary
# so the binary is fully self-contained and works on any machine.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# imageio-ffmpeg ships its own ffmpeg binary; include it as data
ffmpeg_datas = collect_data_files('imageio_ffmpeg')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=ffmpeg_datas,
    hiddenimports=[
        'imageio_ffmpeg',
        'PIL._tkinter_finder',
        'PIL.Image',
        'PIL.ImageSequence',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim heavy packages that aren't needed
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'wx', 'gi',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DiscordMediaDownscaler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # Compress with UPX if available (reduces size ~20%)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # No terminal window
    windowed=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,          # Drop a .ico file here if you want a custom icon
)
