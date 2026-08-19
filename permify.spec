# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Permify. Build with build.bat."""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = []
datas += collect_data_files("permify", include_py_files=True)
datas += copy_metadata("readchar")

hiddenimports = []
hiddenimports += collect_submodules("permify")
for _lib in ("spotipy", "librespot", "av", "sounddevice", "numpy",
             "PIL", "rich", "readchar", "requests"):
    hiddenimports += [_lib]
    try:
        hiddenimports += collect_submodules(_lib)
    except Exception:
        pass

a = Analysis(["entry.py"], pathex=[], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=[], win_no_prefer_redirects=False,
             win_private_assemblies=False, cipher=None, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
          name="Permify", debug=False, strip=False, upx=True,
          upx_exclude=[], runtime_tmpdir=None, console=False,
          disable_windowed_traceback=False)
