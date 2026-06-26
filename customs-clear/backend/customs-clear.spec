# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller customs-clear.spec (из папки backend)

import os
import sys

block_cipher = None
backend_dir = os.path.dirname(os.path.abspath(SPEC))

_pyinstaller_datas = []
_static = os.path.join(backend_dir, 'static')
if os.path.exists(_static):
    _pyinstaller_datas.append((_static, 'static'))
_app_data = os.path.join(backend_dir, 'app', 'data')
if os.path.exists(_app_data):
    _pyinstaller_datas.append((_app_data, os.path.join('app', 'data')))

a = Analysis(
    ['run_server.py'],
    pathex=[backend_dir],
    binaries=[],
    datas=_pyinstaller_datas,
    hiddenimports=[
        'app',
        'app.main',
        'app.api',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'pdfplumber',
        'pymupdf',
        'pytesseract',
        'openpyxl',
        'pandas',
        'docx',
        'bs4',
        'httpx',
        'sqlalchemy',
        'jose',
        'loguru',
    ],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='customs-clear-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
