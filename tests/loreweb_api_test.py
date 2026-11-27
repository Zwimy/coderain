"""The lore web's routes and its two settings (D-074).

 1) GET gives every entry and every connection, each with its fact; hidden entries are marked
 2) connect writes a tie into the stating entry's own Markdown, keeps its other lines, and a second connect to the same entry replaces the note
    (the author's word wins); a `;` in a note cannot split the line, and the note survives a fold's rewrite that leaves it out
 3) disconnect removes only what was asked: a tie, a link or a holder; the other lines stay; a mention is refused
 4) bad requests: an unknown entry, an entry to itself, a note over the limit, an unknown kind, a connection that is not there, too many ties
 5) a write is refused (409) while a turn is generating
 6) a world (scenario) has the same routes
 7) the settings switches read and write memory.follow_links and memory.tail_ties as real booleans, and only a real true is on
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CODERAIN_HOME"] = tempfile.mkdtemp(prefix="cr-web-api-")

from fastapi.testclient import TestClient            # noqa: E402

import server                                         # noqa: E402
from coderain.memory import Entry                     # noqa: E402
from srv import core                                  # noqa: E402

c = TestClient(server.app)


def new_save(title):
    r = c.post("/api/saves", json={"title": title, "mode": "simple", "premise": "A ferry town."})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    store = server._save_store(slug)
    store.upsert_entry("characters.md", Entry(title="Hollis Wren", slug="hollis-wren", importance=3,
                                              attrs={"relationships": "ottoline-pike: his sister", "status": "alive"},
                                              body="The tavern keeper. He drinks at [[brinewick]]."))
    store.upsert_entry("characters.md", Entry(title="Ottoline Pike", slug="ottoline-pike", importance=3, body="The lighthouse keeper."))
    store.upsert_entry("characters.md", Entry(title="The Patron", slug="the-patron", importance=3, attrs={"hidden": "true"},
                                              body="Secret."))
    store.upsert_entry("items.md", Entry(title="Brass lamp key", slug="brass-lamp-key", importance=3,
                                         attrs={"holder": "hollis-wren", "links": "ottoline-pike, the-patron"}, body="A key."))
    store.upsert_entry("locations.md", Entry(title="Brinewick", slug="brinewick", importance=3, body="A tidal town."))
    return slug, store


def entry(store, rel, slug):
    return {e.slug: e for e in store.entries(rel)}[slug]


def post(slug, verb, **body):
    return c.post(f"/api/saves/{slug}/web/{verb}", json=body)


def edges(payload):
    return {(e["from"], e["to"], e["kind"], e["note"]) for e in payload["edges"]}


def test_get():
    slug, _store = new_save("Web one")
    d = c.get(f"/api/saves/{slug}/web").json()
    titles = {n["slug"]: n for n in d["nodes"]}
    assert titles["the-patron"]["hidden"] is True and titles["hollis-wren"]["hidden"] is False
    assert titles["brass-lamp-key"]["type"] == "items"
    assert edges(d) >= {("hollis-wren", "ottoline-pike", "tie", "his sister"), ("brass-lamp-key", "hollis-wren", "holds", ""),
                        ("brass-lamp-key", "ottoline-pike", "link", ""), ("brass-lamp-key", "the-patron", "link", ""),
                        ("hollis-wren", "brinewick", "mention", "")}, edges(d)
    assert "Brass lamp key is held by Hollis Wren" in [e["fact"] for e in d["edges"]]
    print("1. every entry and connection, each with its fact; the hidden one is marked")


def test_connect():
    slug, store = new_save("Web two")
    r = post(slug, "connect", **{"from": "ottoline-pike", "to": "hollis-wren", "note": "  her   brother; and boss "})
    assert r.status_code == 200, r.text
    got = entry(store, "characters.md", "ottoline-pike").attrs["relationships"]
    assert got == "hollis-wren: her brother, and boss", got
    assert ("ottoline-pike", "hollis-wren", "tie", "her brother, and boss") in edges(r.json())
    assert entry(store, "characters.md", "ottoline-pike").body == "The lighthouse keeper."
    post(slug, "connect", **{"from": "hollis-wren", "to": "ottoline-pike", "note": "his twin"})
    e = entry(store, "characters.md", "hollis-wren")
    assert e.attrs["relationships"] == "ottoline-pike: his twin" and e.attrs["status"] == "alive" and "[[brinewick]]" in e.body, e.attrs
    post(slug, "connect", **{"from": "hollis-wren", "to": "brinewick"})
    assert entry(store, "characters.md", "hollis-wren").attrs["relationships"] == "ottoline-pike: his twin; brinewick"
    # a fold that rewrites the entry and says nothing about ties keeps them, with the author's note
    store.merge_entry("characters.md", Entry(title="Hollis Wren", slug="hollis-wren", attrs={"status": "away"},
                                             body="He left town."), rewrite=True)
    after = entry(store, "characters.md", "hollis-wren").attrs["relationships"]
    assert "ottoline-pike: his twin" in after and "brinewick" in after, after
    print("2. a tie is written into the stating entry; connecting again replaces the note; `;` cannot split it; a fold keeps it")


def test_disconnect():
    slug, store = new_save("Web three")
    r = post(slug, "disconnect", **{"from": "brass-lamp-key", "to": "ottoline-pike", "kind": "link"})
    assert r.status_code == 200, r.text
    key = entry(store, "items.md", "brass-lamp-key")
    assert key.attrs["links"] == "the-patron" and key.attrs["holder"] == "hollis-wren", key.attrs
    r = post(slug, "disconnect", **{"from": "brass-lamp-key", "to": "hollis-wren", "kind": "holds"})
    key = entry(store, "items.md", "brass-lamp-key")
    assert r.status_code == 200 and "holder" not in key.attrs and key.attrs["links"] == "the-patron", key.attrs
    post(slug, "connect", **{"from": "hollis-wren", "to": "brinewick", "note": "born there"})
    r = post(slug, "disconnect", **{"from": "hollis-wren", "to": "ottoline-pike", "kind": "tie"})
    hollis = entry(store, "characters.md", "hollis-wren")
    assert r.status_code == 200 and hollis.attrs["relationships"] == "brinewick: born there", "the other tie went too: " + str(hollis.attrs)
    r = post(slug, "disconnect", **{"from": "hollis-wren", "to": "brinewick", "kind": "tie"})
    hollis = entry(store, "characters.md", "hollis-wren")
    assert r.status_code == 200 and "relationships" not in hollis.attrs and hollis.attrs["status"] == "alive", hollis.attrs
    assert "relationships:" not in store.read("characters.md").split("{#ottoline-pike}")[0].split("{#hollis-wren}")[1]
    r = post(slug, "disconnect", **{"from": "hollis-wren", "to": "brinewick", "kind": "mention"})
    assert r.status_code == 400 and "text" in r.json()["detail"], r.text
    assert "[[brinewick]]" in entry(store, "characters.md", "hollis-wren").body
    print("3. one tie, link or holder is removed and nothing else; a mention is refused")


def test_refusals():
    slug, store = new_save("Web four")
    for body, code in (({"from": "hollis-wren", "to": "nobody"}, 404), ({"from": "nobody", "to": "hollis-wren"}, 404),
                       ({"from": "hollis-wren", "to": "hollis-wren"}, 400),
                       ({"from": "hollis-wren", "to": "brinewick", "note": "x" * 121}, 400)):
        assert post(slug, "connect", **body).status_code == code, (body, code)
    assert post(slug, "connect", **{"from": "hollis-wren", "to": "brinewick", "note": "x" * 120}).status_code == 200
    assert post(slug, "disconnect", **{"from": "hollis-wren", "to": "ottoline-pike", "kind": "spell"}).status_code == 400
    assert post(slug, "disconnect", **{"from": "ottoline-pike", "to": "hollis-wren", "kind": "tie"}).status_code == 404
    assert post(slug, "disconnect", **{"from": "ottoline-pike", "to": "hollis-wren", "kind": "holds"}).status_code == 404
    full = "; ".join(f"filler-{i}: x" for i in range(40))
    e = entry(store, "characters.md", "ottoline-pike")
    e.attrs["relationships"] = full
    store.upsert_entry("characters.md", e)
    assert post(slug, "connect", **{"from": "ottoline-pike", "to": "brinewick"}).status_code == 400
    assert c.get("/api/saves/..%2F..%2Fx/web").status_code in (400, 404)
    assert c.get("/api/saves/no-such-save/web").status_code == 404
    print("4. unknown entries, self-connections, long notes, unknown kinds, missing connections and a full entry are refused")


def test_busy():
    slug, store = new_save("Web five")
    before = store.read("characters.md")
    assert core._gen_lock.acquire(blocking=False)
    try:
        r = post(slug, "connect", **{"from": "ottoline-pike", "to": "hollis-wren"})
        assert r.status_code == 409, r.text
        assert post(slug, "disconnect", **{"from": "hollis-wren", "to": "ottoline-pike", "kind": "tie"}).status_code == 409
        assert c.get(f"/api/saves/{slug}/web").status_code == 200, "reading the web does not wait for a turn"
    finally:
        core._gen_lock.release()
    assert store.read("characters.md") == before
    print("5. no write while a turn is generating; reading still works")


def test_world():
    r = c.post("/api/scenarios", json={"name": "Web world", "premise": "A ferry town."})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    store = server._scen_store(slug)
    for title in ("Ada Fenn", "Bea Lorne"):
        store.upsert_entry("characters.md", Entry(title=title, slug=title.lower().replace(" ", "-"), body=title))
    r = c.post(f"/api/scenarios/{slug}/web/connect", json={"from": "ada-fenn", "to": "bea-lorne", "note": "her friend"})
    assert r.status_code == 200 and ("ada-fenn", "bea-lorne", "tie", "her friend") in edges(r.json()), r.text
    assert "relationships: bea-lorne: her friend" in store.read("characters.md")
    r = c.post(f"/api/scenarios/{slug}/web/disconnect", json={"from": "ada-fenn", "to": "bea-lorne", "kind": "tie"})
    assert r.status_code == 200 and not c.get(f"/api/scenarios/{slug}/web").json()["edges"]
    print("6. a world has the same routes")


def test_settings():
    got = c.get("/api/settings").json()["memory"]
    assert got["follow_links"] is False and got["tail_ties"] is False, got
    r = c.put("/api/settings", json={"mode": "local", "memory": {"follow_links": True, "tail_ties": True}})
    assert r.status_code == 200, r.text
    assert core._cfg.memory["follow_links"] is True and core._cfg.memory["tail_ties"] is True
    got = c.get("/api/settings").json()["memory"]
    assert got["follow_links"] is True and got["tail_ties"] is True
    c.put("/api/settings", json={"mode": "local", "memory": {"follow_links": "false", "tail_ties": 1}})
    assert core._cfg.memory["follow_links"] is False and core._cfg.memory["tail_ties"] is False, core._cfg.memory
    c.put("/api/settings", json={"mode": "local", "memory": {"short_term_turns": 12}})
    assert core._cfg.memory["follow_links"] is False, "a save without the switches changed them"
    print("7. the two switches read and write real booleans, only a real true is on, and a save without them leaves them")


test_get()
test_connect()
test_disconnect()
test_refusals()
test_busy()
test_world()
test_settings()
print("\nLORE WEB API TESTS PASSED")
