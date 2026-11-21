"""Writes build/version_info.txt (Windows file properties for the .exe) from proexr.__version__."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = re.search(r'__version__ = "([^"]+)"', (ROOT / "src" / "proexr" / "__init__.py").read_text()).group(1)
numbers = tuple(int(n) for n in re.findall(r"\d+", version)[:4]) + (0,) * 4
numbers = numbers[:4]
template = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'PROEXR MORU'),
      StringStruct('FileDescription', 'ProEXR Viewer'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('ProductName', 'ProEXR Viewer'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('OriginalFilename', 'ProEXR Viewer.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
(ROOT / "build").mkdir(exist_ok=True)
(ROOT / "build" / "version_info.txt").write_text(template)
print(version)
sys.exit(0)
