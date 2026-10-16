# -*- mode: python ; coding: utf-8 -*-
"""ICE-Babysitting 主程序打包配置(PyInstaller)。

WebView2 原生 DLL 的路径在这里是**动态探测**的,不写死虚拟环境路径 ——
这样任何人克隆仓库后,用自己的 Python 环境都能正常打包。
"""
import os

import qtwebview2
from PyInstaller.utils.hooks import collect_all

# WebView2 原生 DLL 必须落在 _internal\lib\ 下,
# 因为 qtwebview2 运行时是从 sys._MEIPASS\lib 加载它的。
WV2_LIB = os.path.join(os.path.dirname(qtwebview2.__file__), "lib")

datas = [
    (WV2_LIB, "lib"),
    ("assets/ice-babysitting.ico", "assets"),
]
binaries = []
hiddenimports = ['qtwebview2', 'clr']
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='ICE-Babysitting',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/ice-babysitting.ico',
    uac_admin=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ICE-Babysitting',
)
