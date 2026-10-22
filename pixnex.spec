# -*- mode: python ; coding: utf-8 -*-
#
# pixnex 打包配置（PyInstaller）
# ==============================
# 使用 onedir（目录）模式，而不是 onefile：
#   onefile 的引导程序启动时必须先把整个包解压到 %TEMP%\_MEIxxxxxx，
#   一旦系统临时目录不可写/被安全软件拦截，就会在任何 Python 代码运行之前
#   弹出原生错误框 “Could not create temporary directory!”。
#   onedir 直接从 dist\pixnex\ 目录运行，不需要临时目录，启动也更快。
#
# 产物：dist\pixnex\pixnex.exe（分发时整个 dist\pixnex 文件夹一起给）
#
# 如果确实需要单文件 exe，把文件末尾 EXE 的 exclude_binaries 去掉、把
# a.binaries / a.datas 移回 EXE，并给 EXE 加 runtime_tmpdir（换成一个确定可写
# 的目录，例如 exe 所在目录相对路径 '.'），同时去掉 COLLECT。
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

# UI 主题样式表按 __file__ 相对路径加载 assets 里的单色图标，
# 打包时必须把这些非 Python 文件一起带进产物目录。
ui_assets_dir = Path('colorPickerPro', 'ui', 'assets')
if ui_assets_dir.is_dir():
    plugin_datas.append(
        (str(ui_assets_dir), str(Path('colorPickerPro', 'ui', 'assets'))))

# theme.apply_theme() 会加载 Qt 自带的简体中文翻译，让系统文件对话框等
# 标准控件的按钮也显示中文。只收集需要的 .qm。
qt_translations = pyside6_dir / 'translations'
for qm_name in ('qtbase_zh_CN.qm', 'qt_zh_CN.qm'):
    qm_file = qt_translations / qm_name
    if qm_file.is_file():
        plugin_datas.append(
            (str(qm_file), str(Path('PySide6', 'translations'))))

# 主题图标是 SVG：需要 QtSvg 运行库 + imageformats/qsvg 插件。
# 插件目录由 datas 整体带入，这里显式收集它依赖的 DLL。
svg_binaries = []
for dll_name in ('Qt6Svg.dll',):
    dll_path = pyside6_dir / dll_name
    if dll_path.is_file():
        svg_binaries.append((str(dll_path), '.'))

a = Analysis(
    ['colorPickerPro.py'],
    pathex=[],
    binaries=svg_binaries,
    datas=plugin_datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtSvg',
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
    [],
    exclude_binaries=True,
    name='pixnex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='pixnex.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='pixnex',
)
