"""Player character (2026-07-22 play-test): the AI ignored player.md, and world
creation had no way to choose/create a player character."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="cr-player-")
os.environ["CODERAIN_HOME"] = HOME
from coderain.memory import Library      # noqa: E402

lib = Library(HOME)


def test_freeform_player_md_still_reaches_context():
    store = lib.store(lib.create_story("Free", "A town."))
    # freeform prose, NO "## You {#player}" entry heading
    store.write("player.md",
                "# Player character\n\nI am Kestrel, a one-eyed smuggler who owes "
                "the Ashen Cartel a debt and never backs down from a dare.\n")
    assert store.entries("player.md") == [], "fixture must have no entry heading"
    sys_prompt = store.assemble([], "look around")[0]["content"]
    assert "Kestrel" in sys_prompt and "smuggler" in sys_prompt, \
        "freeform player.md was dropped from context"
    print("freeform player.md (no entry heading) still reaches the model")


def test_create_your_own_player_via_api():
    import server
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    r = c.post("/api/saves", json={
        "title": "Mine", "mode": "simple",
        "player_name": "Mara Vane",
        "player_desc": "A wandering hedge-witch with a debt to a dangerous patron.",
    })
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    store = server.lib.saves.store(slug)
    entry = {e.slug: e for e in store.entries("player.md")}.get("player")
    assert entry is not None and entry.title == "Mara Vane", store.read("player.md")
    assert "hedge-witch" in entry.body
    # and it's in context
    assert "Mara Vane" in store.assemble([], "go")[0]["content"]
    print("create-your-own player writes player.md and reaches context")


for fn in (test_freeform_player_md_still_reaches_context,
           test_create_your_own_player_via_api):
    fn()
shutil.rmtree(HOME, ignore_errors=True)
print("\nPLAYER CHARACTER TESTS PASSED")
