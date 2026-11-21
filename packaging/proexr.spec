# PyInstaller spec: one-folder Windows build of ProEXR Viewer. Run from the repo root:
#   uv run --group build pyinstaller packaging/proexr.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller

datas, binaries, hiddenimports = [], [], []
for package in ("OpenImageIO", "PyOpenColorIO", "av", "_sounddevice_data"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
hiddenimports += collect_submodules("OpenGL") + ["sounddevice"]
datas += [(str(ROOT / "src" / "proexr" / "resources"), "proexr/resources")]

analysis = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ProEXR Viewer",
    icon=str(ROOT / "packaging" / "proexr.ico"),
    console=False,
    upx=False,
    version=str(ROOT / "build" / "version_info.txt"),
)
COLLECT(exe, analysis.binaries, analysis.datas, name="ProEXR Viewer", upx=False)  # noqa: F821
