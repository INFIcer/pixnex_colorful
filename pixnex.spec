# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

site_packages = Path('.venv', 'Lib', 'site-packages')
pyside6_dir = site_packages / 'PySide6'
plugins_dir = pyside6_dir / 'plugins'

essential_plugins = [
    'platforms',
    'styles',
    'imageformats',
    'iconengines',
    'platforminputcontexts',
    'generic',
]

plugin_datas = []
for name in essential_plugins:
    src = plugins_dir / name
    if src.is_dir():
        plugin_datas.append((str(src), str(Path('PySide6', 'plugins', name))))

a = Analysis(
    ['colorPickerPro.py'],
    pathex=[],
    binaries=[],
    datas=plugin_datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'shiboken6',
        'pymem',
        'pymem.process',
        'psutil',
        'win32com',
        'win32com.client',
        'pythoncom',
        'pywintypes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtNetwork',
        'PySide6.QtSql',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtTextToSpeech',
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtDataVisualization',
        'PySide6.QtCharts',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtHelp',
        'PySide6.QtPrintSupport',
        'PySide6.QtTest',
        'PySide6.QtConcurrent',
        'PySide6.QtDBus',
        'PySide6.QtUiTools',
        'test',
        'unittest',
        'pytest',
        'tkinter',
        'matplotlib',
        'scipy',
        'PIL',
        'OpenGL',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pixnex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='pixnex.ico',
)
