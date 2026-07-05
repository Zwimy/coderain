"""Build the Coderain desktop app with PyInstaller.

    python build.py            # -> dist/Coderain/  +  dist/Coderain-win-x64.zip

Coderain is fully open source, so there's one build with everything included.
The optional modules (coderain.modules — rpg/trinity/vector) are imported
dynamically, so PyInstaller can't see them by static analysis; --collect-submodules
pulls them in.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "Coderain"
ZIP = "Coderain-win-x64"

args = [
    sys.executable, "-m", "PyInstaller", "--noconfirm",
    "--onedir", "--windowed", "--name", NAME,
    "--add-data", "webapp;webapp",
    "--hidden-import", "multipart", "--hidden-import", "python_multipart",
    "--collect-submodules", "coderain.modules",
    "desktop.py",
]
print(f"building -> dist/{NAME}/  (zip: {ZIP}.zip)")
subprocess.run(args, cwd=ROOT, check=True)

zip_path = ROOT / "dist" / ZIP
if zip_path.with_suffix(".zip").exists():
    zip_path.with_suffix(".zip").unlink()
shutil.make_archive(str(zip_path), "zip", root_dir=ROOT / "dist", base_dir=NAME)
size_mb = zip_path.with_suffix(".zip").stat().st_size / 1e6
print(f"done: {zip_path.with_suffix('.zip')}  ({size_mb:.0f} MB)")
