# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

block_cipher = None

# Collect data files from packages that need them
datas = []
datas += collect_data_files('onnxruntime')
datas += collect_data_files('jieba')
datas += collect_data_files('janome')
datas += collect_data_files('pythainlp')
datas += collect_data_files('pdfminer')
datas += collect_data_files('pikepdf')
datas += collect_data_files('mahotas')

# App resources
datas += [
    ('resources', 'resources'),
    ('NOTICE', 'docs'),
    ('docs/THIRD_PARTY_NOTICES.md', 'docs'),
    # The optional SAM runner executes inside its isolated sidecar Python.
    # Application packages remain inside PyInstaller's bytecode archive and
    # are not copied as plain source into customer installations.
    ('app/sam_refiner_runner.py', 'app'),
]

# Hidden imports that PyInstaller may miss
hiddenimports = [
    # PySide6
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
    'PySide6.QtSvg',
    'PySide6.QtMultimedia',
    # onnxruntime providers
    'onnxruntime.capi.onnxruntime_pybind11_state',
    # app modules
    'controller',
    'comic',
    'app.production_self_test',
    'app.ui.splash_screen',
    # misc
    'keyring.backends.Windows',
    'keyring.backends.fail',
    'pkg_resources',
    'PIL._tkinter_finder',
    # High-quality text envelope interpolation (headless: PySide owns the UI).
    'cv2',
]
hiddenimports += collect_submodules('winrt')

a = Analysis(
    ['mukai.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'tkinter', '_tkinter',
        'scipy', 'IPython', 'jupyter',
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
    [],
    exclude_binaries=True,
    name='MukaiTranslate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # No terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icons/icon.ico',
    version='build/windows-version-info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MukaiTranslate',
)
