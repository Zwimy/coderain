"""The version is real, and the SPA is never served stale (2026-07-28).

__version__ sat at "0.1.0" through the 0.2.0, 0.3.0 and 0.3.1 releases: nothing
read it, so nothing caught it. And the SPA was served with default caching,
which on a desktop app means unzipping a new release over an old install can
leave the browser running the previous app.js against the new API.

Asserts:
 1) __version__ is a real, parseable version and not the old placeholder;
 2) it reaches the UI through /api/settings;
 3) every SPA asset is served revalidate-always, entry point and modules alike;
 4) build.py collects srv/ (it builds from CLI args, NOT Coderain.spec, so a
    router missing here is missing from the shipped app).
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-ver-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import __version__  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# ---- 1) a real version --------------------------------------------------
assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), \
    f"__version__ must look like X.Y.Z, got {__version__!r}"
assert __version__ != "0.1.0", \
    "__version__ is still the placeholder that went stale for three releases"
print(f"1) __version__ = {__version__}")

# ---- 2) it reaches the UI ----------------------------------------------
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(server.app)
st = c.get("/api/settings").json()
assert st.get("version") == __version__, \
    f"/api/settings reports {st.get('version')!r}, code says {__version__!r}"
assert "st.version" in (ROOT / "webapp/js/settings.js").read_text(encoding="utf-8"), \
    "the settings view no longer renders the version"
print("2) /api/settings carries it and the settings view renders it")

# ---- 3) nothing is served stale ----------------------------------------
for path in ("/", "/js/app.js", "/js/util.js", "/style.css", "/matrix.js"):
    r = c.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    cc = r.headers.get("cache-control", "")
    assert "no-cache" in cc, (
        f"{path} is served with cache-control={cc!r}. A stale module here means "
        "an upgraded install runs the old app against the new API.")
# The module graph must be covered too: `import './util.js'` resolves without
# the entry point's query string, so a ?v= stamp alone would not be enough.
print("3) entry point, modules, and styles all revalidate")

# ---- 4) the build collects the HTTP layer ------------------------------
build = (ROOT / "build.py").read_text(encoding="utf-8")
assert '"srv"' in build and "collect-submodules" in build, \
    "build.py must --collect-submodules srv; it builds from CLI args, not the spec"
assert "coderain.modules" in build, "build.py stopped collecting coderain.modules"
print("4) build.py collects both srv/ and coderain.modules")

shutil.rmtree(HOME, ignore_errors=True)
print("\nVERSION + ASSET TESTS PASSED")
