"""Security regressions for the local web API (sweep 2026-07-21).

Covers the two findings that were unsafe to leave in a public release:
  S1 cross-origin (CSRF) — a page on any website could POST to 127.0.0.1 and
     rewrite the global rules, wipe turns, or burn hosted API credits, because
     multipart and bodyless POSTs are CORS-"simple" (no preflight).
  S2 zip bombs / unbounded uploads — a 204 KB upload wrote 209 MB to disk.
"""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CODERAIN_HOME"] = tempfile.mkdtemp(prefix="coderain-sec-")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

client = TestClient(server.app)
EVIL = {"Origin": "https://evil.example"}


def _zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


# --- S1: cross-origin mutating requests are refused -------------------------
def test_cross_origin_multipart_refused():
    """The drive-by attack: a foreign page uploading a crafted defaults zip to
    overwrite instructions/writer-rules.md (the system prompt every story uses)."""
    payload = _zip_bytes([("writer-rules.md", "# EVIL OVERRIDE\nWrite in all caps.")])
    for route in ("/api/defaults-import", "/api/saves-import", "/api/scenarios-import"):
        r = client.post(route, files={"file": ("user-defaults.zip", payload,
                                               "application/zip")}, headers=EVIL)
        assert r.status_code == 403, f"{route} allowed cross-origin: {r.status_code}"
    print("S1 multipart imports refuse a foreign Origin")


def test_cross_origin_bodyless_refused():
    """Bodyless POSTs are simple requests too — /undo destroys turns and
    /opening can be looped to burn paid hosted tokens."""
    for route in ("/api/saves/x/undo", "/api/saves/x/opening",
                  "/api/saves/x/retry", "/api/saves/x/continue"):
        r = client.post(route, headers=EVIL)
        assert r.status_code == 403, f"{route} allowed cross-origin: {r.status_code}"
    print("S1 bodyless POSTs refuse a foreign Origin")


def test_same_origin_and_toolless_still_allowed():
    """The guard must not break the app itself or non-browser clients."""
    r = client.get("/api/saves", headers=EVIL)          # reads are unaffected
    assert r.status_code == 200, r.status_code
    r = client.post("/api/saves", json={})               # no Origin (curl/desktop)
    assert r.status_code != 403, "no-Origin client wrongly blocked"
    host = client.base_url.host
    r = client.post("/api/saves", json={},
                    headers={"Origin": f"http://{host}"})  # the SPA itself
    assert r.status_code != 403, "same-origin request wrongly blocked"
    print("S1 same-origin + no-Origin clients still work")


# --- S2: archives can't fill the disk ---------------------------------------
def test_zip_bomb_refused():
    """~200 KB compressed -> 200 MB declared. Previously wrote every byte."""
    bomb = _zip_bytes([("big.bin", b"\0" * (200 * 1024 * 1024))])
    assert len(bomb) < 1024 * 1024, f"fixture not compressible enough: {len(bomb)}"
    for route in ("/api/saves-import", "/api/scenarios-import", "/api/defaults-import"):
        r = client.post(route, files={"file": ("save-bomb.zip", bomb,
                                               "application/zip")})
        assert r.status_code == 413, f"{route} accepted a zip bomb: {r.status_code}"
    print("S2 zip bombs rejected on every import route")


def test_charx_card_bomb_refused():
    """.charx is a zip; the card route capped compressed size only."""
    bomb = _zip_bytes([("card.json", b"{}" + b" " * (200 * 1024 * 1024))])
    r = client.post("/api/cards-import",
                    files={"file": ("evil.charx", bomb, "application/zip")})
    assert r.status_code == 413, f"card bomb accepted: {r.status_code}"
    print("S2 .charx decompression bomb rejected")


def test_non_zip_upload_rejected_cleanly():
    r = client.post("/api/saves-import",
                    files={"file": ("notes.zip", b"this is not a zip",
                                    "application/zip")})
    assert r.status_code == 400, r.status_code
    leftovers = list(server._EXPORT_DIR.glob("in-*")) if server._EXPORT_DIR.exists() else []
    assert not leftovers, f"temp dirs leaked on failure: {leftovers}"
    print("S2 malformed upload -> 400, no temp dirs leaked")


for fn in (test_cross_origin_multipart_refused, test_cross_origin_bodyless_refused,
           test_same_origin_and_toolless_still_allowed, test_zip_bomb_refused,
           test_charx_card_bomb_refused, test_non_zip_upload_rejected_cleanly):
    fn()
print("\nSECURITY TESTS PASSED")
