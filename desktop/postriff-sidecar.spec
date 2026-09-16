# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/ouxianxing/Documents/James-Au-Studio/desktop/sidecar_entry.py'],
    pathex=['/Users/ouxianxing/Documents/James-Au-Studio/src'],
    binaries=[],
    datas=[('/Users/ouxianxing/Documents/James-Au-Studio/src/postriff_alpha/profile_builder_prompt.md', 'postriff_alpha')],
    hiddenimports=['PIL.Image', 'PIL.JpegImagePlugin', 'PIL.PngImagePlugin'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='postriff-sidecar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='postriff-sidecar',
)
