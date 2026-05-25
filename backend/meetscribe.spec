# meetscribe.spec
# ─────────────────────────────────────────────────────────────
# PyInstaller build spec for MeetScribe.
#
# Build with:
#   pyinstaller meetscribe.spec
#
# Output: dist/MeetScribe/MeetScribe.exe  (folder mode)
#         or dist/MeetScribe.exe          (onefile mode — slower startup)
#
# Tips:
# - The NeMo/Parakeet model weights are NOT bundled. They are downloaded
#   on first run to %APPDATA%/MeetScribe/models/ (or wherever NeMo caches).
# - Ollama runs as a separate process; no bundling needed.
# - pyaudiowpatch DLLs are auto-collected below.
# ─────────────────────────────────────────────────────────────

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── Collect NeMo + dependencies ───────────────────────────────────────
nemo_datas, nemo_binaries, nemo_hiddenimports = collect_all("nemo")
torch_datas, torch_binaries, torch_hiddenimports = collect_all("torch")
pyannote_datas, pyannote_binaries, pyannote_hiddenimports = collect_all("pyannote")

all_datas = nemo_datas + torch_datas + pyannote_datas
all_binaries = nemo_binaries + torch_binaries + pyannote_binaries
all_hiddenimports = (
    nemo_hiddenimports
    + torch_hiddenimports
    + pyannote_hiddenimports
    + collect_submodules("scipy")
    + collect_submodules("sklearn")
    + collect_submodules("numba")
    + [
        "pyaudiowpatch",
        "numpy",
        "reportlab",
        "docx",
        "wave",
        "json",
        "pathlib",
        "threading",
    ]
)

a = Analysis(
    ["main.py"],
    pathex=[str(Path(".").resolve())],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "IPython",
        "notebook",
        "pytest",
        "tkinter",    # remove if your GUI uses tkinter
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
    name="MeetScribe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # set True for debug; False hides the terminal
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",  # replace with your icon path (or remove this line)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MeetScribe",
)
