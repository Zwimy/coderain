"""Fate's routes and the hand-edit path (D-045).

 1) GET /api/saves/{slug}/fate: off by default, with no reason; an RPG story says why fate cannot run
 2) PUT sets the mode and the die separately, keeps the other, and refuses a bad mode or a non-boolean with a 400 and
    leaves the setting alone; an unknown save is a 404
 3) the setting is read fresh each turn (no engine rebuild): the engine's store sees the change at once
 4) editing the transcript so it is SHORTER drops the cached directions for the removed exchanges and keeps the
    others; writing the same text again, or a longer one, drops nothing
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-fate-api-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import fate                                                   # noqa: E402

import server                                                               # noqa: E402
from fastapi.testclient import TestClient                                   # noqa: E402

c = TestClient(server.app)


def new_save(title):
    return c.post("/api/saves", json={"title": title, "mode": "simple", "premise": "A ferry town."}).json()["slug"]


def store_for(slug):
    return server._engine(slug).store


def rec(n):
    return {"n": n, "key": f"{n}:aaaaaaaaaaaa:bbbbbbbb", "nonce": 0, "roll": 5, "tier": "natural", "stakes": "some",
            "text": f"line {n}", "model": "stub"}


def test_get_and_put():
    slug = new_save("Fate api 1")
    got = c.get(f"/api/saves/{slug}/fate").json()
    assert got == {"mode": "off", "show_die": False, "blocked": ""}, got
    r = c.put(f"/api/saves/{slug}/fate", json={"mode": "preview"})
    assert r.status_code == 200 and r.json() == {"mode": "preview", "show_die": False}, r.text
    r = c.put(f"/api/saves/{slug}/fate", json={"show_die": True})
    assert r.json() == {"mode": "preview", "show_die": True}, "setting the die changed the mode"
    r = c.put(f"/api/saves/{slug}/fate", json={"mode": "ON", "show_die": False})
    assert r.json() == {"mode": "on", "show_die": False}
    for bad in ({"mode": "sometimes"}, {"mode": 5}, {"show_die": "yes"}, {"show_die": 1}):
        r = c.put(f"/api/saves/{slug}/fate", json=bad)
        assert r.status_code == 400, (bad, r.status_code)
    assert c.get(f"/api/saves/{slug}/fate").json()["mode"] == "on", "a refused change altered the setting"
    assert c.put("/api/saves/no-such-save-here/fate", json={"mode": "on"}).status_code == 404
    assert c.get("/api/saves/no-such-save-here/fate").status_code == 404
    print("1-2. defaults, a partial update, and 400 / 404 refusals that change nothing")


def test_rpg_is_blocked_and_the_engine_sees_changes():
    slug = new_save("Fate api 2")
    store = store_for(slug)
    st = store.rpg_state()
    st["enabled"] = True
    store.set_rpg_state(st)
    got = c.get(f"/api/saves/{slug}/fate").json()
    assert got["blocked"] and "RPG" in got["blocked"], got
    slug2 = new_save("Fate api 3")
    eng_store = store_for(slug2)
    assert fate.settings(eng_store)["mode"] == "off"
    c.put(f"/api/saves/{slug2}/fate", json={"mode": "on", "show_die": True})
    assert fate.settings(store_for(slug2)) == {"mode": "on", "show_die": True}, "the engine's store did not see the change"
    print("3. an RPG story says why fate cannot run; the engine's store sees a change at once")


def test_transcript_edit_prunes():
    long_slug, short_slug = new_save("Fate api long"), new_save("Fate api short")
    long_s, short_s = store_for(long_slug), store_for(short_slug)
    for s, turns in ((long_s, 3), (short_s, 2)):
        for k in range(turns):
            s.append_turn("player", f"I act {k}.")
            s.append_turn("narrator", f"Something happens {k}.")
    base = len(long_s.turns()) - 6                       # whatever the opening left in front
    for n in (base + 2, base + 4, base + 6):
        fate.put(long_s, rec(n))
    shorter = short_s.read("transcript.md")
    r = c.put(f"/api/saves/{long_slug}/files/transcript.md", json={"text": shorter})
    assert r.status_code == 200, r.text
    assert len(store_for(long_slug).turns()) == len(short_s.turns())
    assert [x["n"] for x in fate.read(store_for(long_slug))] == [base + 2, base + 4], fate.read(store_for(long_slug))
    r = c.put(f"/api/saves/{long_slug}/files/transcript.md", json={"text": shorter})
    assert [x["n"] for x in fate.read(store_for(long_slug))] == [base + 2, base + 4], "an identical write pruned"
    print("4. a shortened transcript drops the removed exchanges' directions and keeps the rest; an identical write drops none")


for fn in (test_get_and_put, test_rpg_is_blocked_and_the_engine_sees_changes, test_transcript_edit_prunes):
    fn()
print("\nFATE API TESTS PASSED")
