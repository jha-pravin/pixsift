# PyInstaller spec: builds PixSift.app on macOS and PixSift\PixSift.exe on Windows.
# Run via build_mac.sh / build_windows.ps1 (they build the UI and icons first).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
mac = sys.platform == "darwin"

a = Analysis(
    [str(Path(SPECPATH) / "launcher.py")],
    pathex=[str(ROOT / "backend")],
    datas=[(str(ROOT / "frontend" / "dist"), "ui"), (str(ROOT / "backend" / "pixsift" / "data"), "pixsift/data")],
    binaries=collect_dynamic_libs("pillow_heif"),
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("pixsift"),
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "PyInstaller", "cv2", "sklearn", "scipy", "tokenizers",
              "onnx", "PIL.ImageQt", "PIL.ImageTk", "numpy.f2py", "pydoc_data", "unittest", "lib2to3"],
    noarchive=False,
)
# onnxruntime's Python module is self-contained; its separate C-API library (~32 MB) is never loaded.
a.binaries = [b for b in a.binaries if not Path(b[0]).name.startswith("libonnxruntime.")]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PixSift",
    console=False,
    icon=str(Path(SPECPATH) / ("pixsift.icns" if mac else "pixsift.ico")),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PixSift")

if mac:
    app = BUNDLE(
        coll,
        name="PixSift.app",
        icon=str(Path(SPECPATH) / "pixsift.icns"),
        bundle_identifier="app.pixsift.desktop",
        info_plist={
            "CFBundleShortVersionString": "0.4.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # Shown by macOS the first time PixSift scans these protected locations.
            "NSDesktopFolderUsageDescription": "PixSift scans your Desktop for pictures.",
            "NSDocumentsFolderUsageDescription": "PixSift scans your Documents for pictures.",
            "NSDownloadsFolderUsageDescription": "PixSift scans your Downloads for pictures.",
            "NSRemovableVolumesUsageDescription": "PixSift scans external drives for pictures.",
            "NSNetworkVolumesUsageDescription": "PixSift scans network drives for pictures.",
        },
    )
