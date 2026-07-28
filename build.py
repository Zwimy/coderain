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
sys.path.insert(0, str(ROOT))
from coderain import __version__ as VERSION   # noqa: E402

NAME = "Coderain"
ZIP = "Coderain-win-x64"

args = [
    sys.executable, "-m", "PyInstaller", "--noconfirm",
    "--onedir", "--windowed", "--name", NAME,
    "--add-data", "webapp;webapp",
    "--hidden-import", "multipart", "--hidden-import", "python_multipart",
    "--collect-submodules", "coderain.modules",
    # The HTTP layer. desktop.py -> server.py imports these statically, but list
    # them so a router can never quietly go missing from a build.
    "--collect-submodules", "srv",
    "desktop.py",
]


def _last_tag() -> str:
    try:
        out = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                             cwd=ROOT, capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else ""
    except OSError:
        return ""


print(f"building Coderain v{VERSION} -> dist/{NAME}/  (zip: {ZIP}.zip)")
tag = _last_tag()
if tag and tag.lstrip("v") != VERSION:
    # Not fatal: you bump the code first and tag afterwards, so being AHEAD of
    # the last tag is the normal state. Being behind it is the bug.
    print(f"  note: last git tag is {tag}, code says {VERSION}"
          + ("  <-- code is BEHIND the tag, bump coderain/__init__.py"
             if tag.lstrip("v") > VERSION else "  (tag it after this build)"))
subprocess.run(args, cwd=ROOT, check=True)

zip_path = ROOT / "dist" / ZIP
if zip_path.with_suffix(".zip").exists():
    zip_path.with_suffix(".zip").unlink()
shutil.make_archive(str(zip_path), "zip", root_dir=ROOT / "dist", base_dir=NAME)
size_mb = zip_path.with_suffix(".zip").stat().st_size / 1e6
print(f"done: {zip_path.with_suffix('.zip')}  ({size_mb:.0f} MB)")
