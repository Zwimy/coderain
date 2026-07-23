"""World creation should also stock the reusable Pieces library (2026-07-22:
'when creating a world, add everything to pieces as well'). Idempotent."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="cr-w2lib-")
os.environ["CODERAIN_HOME"] = HOME
import server                            # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(server.app)


def _seed_world():
    slug = server.lib.scenarios.create("Cast World", "A premise about a heist crew.")
    store = server._scen_store(slug)
    store.write("characters.md",
                "# Characters\n\n## Kaelen {#kaelen}\nimportance: 4\n\nA grim knight.\n"
                "\n## Mara {#mara}\nimportance: 3\n\nA sly fence.\n")
    store.write("locations.md",
                "# Locations\n\n## Ashford {#ashford}\nimportance: 3\n\nA rainy town.\n")
    store.write("items.md",
                "# Items\n\n## The Ledger {#ledger}\nimportance: 4\n\nA stolen book.\n")
    return slug


def test_mirror_adds_and_is_idempotent():
    slug = _seed_world()
    before_chars = len(server.characters.list())
    before_pieces = len(server.pieces_lib.list())

    r = c.post(f"/api/scenarios/{slug}/to-library")
    assert r.status_code == 200, r.text
    added = r.json()["added"]
    assert added["characters"] == 2, added        # Kaelen + Mara
    assert added["pieces"] == 2, added             # Ashford + Ledger

    names = {ch["name"] for ch in server.characters.list()}
    assert {"Kaelen", "Mara"} <= names
    piece_titles = {p["entry"]["title"] for p in server.pieces_lib.list()}
    assert {"Ashford", "The Ledger"} <= piece_titles

    # running again adds NOTHING (idempotent)
    again = c.post(f"/api/scenarios/{slug}/to-library").json()["added"]
    assert again == {"characters": 0, "pieces": 0}, again
    assert len(server.characters.list()) == before_chars + 2
    assert len(server.pieces_lib.list()) == before_pieces + 2
    print("world -> library mirror works and is idempotent")


test_mirror_adds_and_is_idempotent()
shutil.rmtree(HOME, ignore_errors=True)
print("\nWORLD-TO-LIBRARY TESTS PASSED")
