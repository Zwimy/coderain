"""See the fold while it still means something (2026-07-28).

A fold rewrites ten turns into a paragraph, and from then on the paragraph is
what the model gets. If it dropped a thread you find out fifty turns later, when
the cause is long out of view. These endpoints are the second chance.

Asserts:
 1) recent folded scenes are listable, newest first, with their turn range;
 2) a summary can be corrected by hand and the fix reaches the next prompt;
 3) a redo rebuilds from the ORIGINAL turns, snapshots first, and REPLACES the
    timeline line rather than appending a second one for the same range;
 4) a redo does not re-run promotions (entity edits made since must survive);
 5) the failure paths refuse cleanly instead of destroying the old summary.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-fold-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Entry, Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
store = lib.store(lib.create_story(
    "Bridge", "A tollkeeper counts what crosses the bridge at night."))

for i in range(1, 13):
    store.append_turn("player" if i % 2 else "narrator", f"turn {i} text")
store.upsert_entry("memory/scenes.md", Entry(
    title="Scene 1", slug="scene-1", attrs={"turns": "1-6", "when": "Day 1, night",
                                            "characters": "tollkeeper"},
    body="The tollkeeper let a cart pass."))
store.write("memory/timeline.md",
            "# Timeline (turn index)\n- [T1-6] Day 1, night: a cart passed\n")

cfg = load_config()
eng = Engine(cfg, store)


class _StubLLM:
    """Answers the fold with fixed JSON; counts how often it is asked."""

    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def complete(self, messages, **kw):
        self.calls += 1
        return self.payload

    def stream(self, messages, **kw):
        return iter([self.complete(messages, **kw)])


# ---- 1) list the folded scenes -----------------------------------------
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(server.app)
slug = c.post("/api/saves", json={
    "title": "Review", "mode": "simple",
    "premise": "A tollkeeper counts what crosses the bridge."}).json()["slug"]
srv_store = server._engine(slug).store
for n, rng in ((1, "1-6"), (2, "7-12")):
    srv_store.upsert_entry("memory/scenes.md", Entry(
        title=f"Scene {n}", slug=f"scene-{n}", attrs={"turns": rng},
        body=f"Summary of scene {n}."))
got = c.get(f"/api/saves/{slug}/scenes?limit=2").json()["scenes"]
assert [s["slug"] for s in got] == ["scene-2", "scene-1"], got
assert got[0]["turns"] == "7-12", got[0]
print("1) folded scenes list newest-first with their turn range")

# ---- 2) hand-correct a summary -----------------------------------------
r = c.put(f"/api/saves/{slug}/scenes/scene-1",
          json={"summary": "The tollkeeper REFUSED the cart and kept the seal."})
assert r.status_code == 200, r.text
assert "REFUSED" in srv_store.entries("memory/scenes.md")[0].body
sys_txt = server._engine(slug)._messages(
    srv_store.recent_turns(4), "next")[0]["content"]
assert "REFUSED" in sys_txt, "the corrected summary must reach the next prompt"
assert c.put(f"/api/saves/{slug}/scenes/scene-1",
             json={"summary": "  "}).status_code == 400, "empty must be refused"
assert c.put(f"/api/saves/{slug}/scenes/nope", json={"summary": "x"}) \
    .status_code == 404
print("2) a corrected summary sticks and reaches the next prompt")

# ---- 3) redo rebuilds from the original turns --------------------------
eng.llm = _StubLLM('{"scene_summary": "The cart carried a sealed box '
                   'the tollkeeper did not open.", "timeline": "sealed box passed"}')
eng.summarizer.llm = eng.llm
snaps_before = len(list((Path(store.dir) / ".snapshots").glob("*"))) \
    if (Path(store.dir) / ".snapshots").exists() else 0
res = eng.summarizer.refold_scene("scene-1")
assert res["ok"] and "sealed box" in res["summary"], res
assert eng.summarizer.llm.calls >= 1, "a redo must actually re-ask the model"
body = next(e for e in store.entries("memory/scenes.md") if e.slug == "scene-1").body
assert "sealed box" in body, body
snaps_after = len(list((Path(store.dir) / ".snapshots").glob("*")))
assert snaps_after > snaps_before, "a redo must snapshot first (it is destructive)"
tl = store.read("memory/timeline.md")
assert tl.count("[T1-6]") == 1, f"the timeline grew a duplicate range:\n{tl}"
assert "sealed box" in tl, tl
print("3) redo rebuilds from the turns, snapshots, and replaces the timeline line")

# ---- 4) a redo leaves entities alone -----------------------------------
store.upsert_entry("characters.md", Entry(
    title="Tollkeeper", slug="tollkeeper", attrs={"wants": "to be left alone"},
    body="Hand-edited after the fold: she keeps a ledger of every seal."))
eng.llm = _StubLLM('{"scene_summary": "A second rewrite.", "timeline": "again",'
                   ' "promotions": [{"kind": "character", "slug": "tollkeeper",'
                   ' "title": "Tollkeeper", "detail": "OVERWRITTEN BY THE REDO"}]}')
eng.summarizer.llm = eng.llm
assert eng.summarizer.refold_scene("scene-1")["ok"]
keeper = next(e for e in store.entries("characters.md") if e.slug == "tollkeeper")
assert "OVERWRITTEN" not in keeper.body, \
    "a redo re-ran promotions and clobbered a hand-edited entity"
assert "ledger of every seal" in keeper.body, keeper.body
print("4) a redo rewrites the summary only, never the entities")

# ---- 5) failure paths refuse without destroying anything ---------------
before = next(e for e in store.entries("memory/scenes.md")
              if e.slug == "scene-1").body
eng.llm = _StubLLM("not json at all")
eng.summarizer.llm = eng.llm
bad = eng.summarizer.refold_scene("scene-1")
assert not bad["ok"] and "no summary" in bad["error"], bad
assert next(e for e in store.entries("memory/scenes.md")
            if e.slug == "scene-1").body == before, \
    "a failed redo must leave the old summary untouched"
assert not eng.summarizer.refold_scene("scene-404")["ok"]
store.upsert_entry("memory/scenes.md", Entry(
    title="Orphan", slug="orphan", attrs={}, body="no turn range"))
orphan = eng.summarizer.refold_scene("orphan")
assert not orphan["ok"] and "range" in orphan["error"], orphan
assert any(h["stage"] == "refold" for h in store.health()), \
    "a failed redo should leave a trace in the health log"
print("5) bad JSON, a missing scene and a rangeless scene all refuse cleanly")

shutil.rmtree(HOME, ignore_errors=True)
print("\nFOLD REVIEW TESTS PASSED")
