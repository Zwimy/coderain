"""Duplicates in the app (D-065): the merge tool of D-030 and D-038 over HTTP, with an undo.

`python -m coderain.dedupe` merged entries that are one character, place or item, and the app had no way to. These are the promises of the
routes, each one a way a merge could quietly lose something:

 1) GET lists what has the same whole name (with the entry that would stay) and what MAY be one character (the author's call), the backups,
    and whether the canon ledger exists (it keeps the old entities until rebuilt)
 2) an explicit merge folds exactly the entries named into the first, keeps their aliases, writes a backup of every registry it changes, and
    the app's own store sees the result at once
 3) every refusal writes nothing: an unknown slug, one slug alone, the same slug twice, the player's sheet, a file that is not a registry, a
    body of the wrong shape; the registry and the list of backups are as they were
 4) {"auto": true} merges the same-name groups and nothing else; with none it is a 400
 5) a restore puts the backup's registries back byte for byte, and first backs up what is there now, so the restore can be restored too
 6) a restore is only for a stamp the tool made: a path, a missing stamp and a folder with no registry in it are refused
 7) a merge or a restore while a turn is generating is a 409 (the lock every save-changing call takes) and the view still answers
 8) an unknown save is a 404 and a slug that is not a clean id is refused
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-dedupeapi-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.memory import Entry                                           # noqa: E402
import server                                                               # noqa: E402
from fastapi.testclient import TestClient                                   # noqa: E402

c = TestClient(server.app)


def new_story(title):
    slug = c.post("/api/saves", json={"title": title, "mode": "simple", "premise": "A harbour town."}).json()["slug"]
    store = server._engine(slug).store
    long = "Dame Vesper keeps the harbour light and a ledger of every debt owed to the ferry. " * 3
    for title_, slug_, body, aliases in (("Bram Halloran", "bram-halloran", "The customs officer.", []),
                                        ("Bram Halloran", "bram-halloran-2", "The customs officer, second entry.", ["Bram"]),
                                        ("Vesper", "vesper", "Short.", []),
                                        ("Dame Vesper", "dame-vesper", long, ["The Keeper"]),
                                        ("Vesper Ann-Marie", "vesper-ann-marie", "Her given name.", [])):
        store.upsert_entry("characters.md", Entry(title=title_, slug=slug_, aliases=aliases, importance=3, body=body))
    return slug, store


def slugs(store):
    return sorted(e.slug for e in store.entries("characters.md"))


def test_view():
    slug, store = new_story("Dup view")
    v = c.get(f"/api/saves/{slug}/duplicates").json()
    assert [(g["rel"], g["keep"]["slug"], [d["slug"] for d in g["drop"]]) for g in v["same_name"]] == \
        [("characters.md", "bram-halloran", ["bram-halloran-2"])], v["same_name"]
    assert v["same_name"][0]["keep"]["title"] == "Bram Halloran" and v["same_name"][0]["why"] == "same name"
    cl = v["possible"][0]
    assert cl["rel"] == "characters.md" and sorted(e["slug"] for e in cl["entries"]) == ["dame-vesper", "vesper", "vesper-ann-marie"], cl
    assert cl["keep"] == "dame-vesper", "the entry with the longest body should be the one suggested to stay"
    assert v["backups"] == [] and v["canon"] is False
    (Path(store.dir) / "canon").mkdir()
    assert c.get(f"/api/saves/{slug}/duplicates").json()["canon"] is True
    print("1. the view lists same-name groups and possible clusters (with the suggested keeper), no backups yet, and the canon flag")


def test_explicit_merge():
    slug, store = new_story("Dup merge")
    before = (Path(store.dir) / "characters.md").read_text(encoding="utf-8")
    r = c.post(f"/api/saves/{slug}/duplicates/merge", json={"rel": "characters.md", "keep": "dame-vesper", "drop": ["vesper", "vesper-ann-marie"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["result"]["merged"] == 1 and out["result"]["dropped"] == 2, out["result"]
    assert slugs(store) == ["bram-halloran", "bram-halloran-2", "dame-vesper"], "exactly the named entries were folded"
    kept = next(e for e in store.entries("characters.md") if e.slug == "dame-vesper")
    assert "Vesper" in kept.aliases and "The Keeper" in kept.aliases and "Vesper Ann-Marie" in kept.aliases, kept.aliases
    assert out["possible"] == [], "the merged cluster is still listed"
    stamp = out["backups"][0]
    assert (Path(store.dir) / ".dedupe-backup" / stamp / "characters.md").read_text(encoding="utf-8") == before, "the backup is not the file as it was"
    print("2. an explicit merge folds exactly the named entries, keeps their names as aliases and backs up the registry first")
    return slug, store, stamp, before


def test_refusals():
    slug, store = new_story("Dup refuse")
    store.write("player.md", "## Rook Vane\nname: Rook Vane\n")
    store.upsert_entry("characters.md", Entry(title="Rook Vane", slug="rook-vane", importance=3, body="x"))
    store.upsert_entry("characters.md", Entry(title="Rook", slug="rook", importance=3, body="y"))
    text = (Path(store.dir) / "characters.md").read_text(encoding="utf-8")
    for bad in ({"keep": "nobody", "drop": ["vesper"]}, {"keep": "vesper", "drop": []}, {"keep": "vesper", "drop": ["vesper"]},
                {"keep": "vesper", "drop": ["dame-vesper", "dame-vesper"]}, {"keep": "rook-vane", "drop": ["rook"]},
                {"keep": "vesper", "drop": ["dame-vesper"], "rel": "scenes.md"}, {"keep": "vesper", "drop": "dame-vesper"},
                {"keep": 5, "drop": ["vesper"]}, {"drop": ["vesper"]}, {}, {"auto": "yes"}, {"keep": "vesper", "drop": [3]}):
        r = c.post(f"/api/saves/{slug}/duplicates/merge", json=bad)
        assert r.status_code == 400, (bad, r.status_code, r.text[:100])
    assert (Path(store.dir) / "characters.md").read_text(encoding="utf-8") == text, "a refused merge changed the registry"
    assert c.get(f"/api/saves/{slug}/duplicates").json()["backups"] == [], "a refused merge left a backup"
    print("3. every refusal is a 400 that writes nothing (no change, no backup)")


def test_auto():
    slug, store = new_story("Dup auto")
    r = c.post(f"/api/saves/{slug}/duplicates/merge", json={"auto": True})
    assert r.status_code == 200 and r.json()["result"] == {"backup": r.json()["result"]["backup"], "merged": 1, "dropped": 1}, r.text
    assert slugs(store) == ["bram-halloran", "dame-vesper", "vesper", "vesper-ann-marie"], "auto must merge the same-name group and nothing else"
    again = c.post(f"/api/saves/{slug}/duplicates/merge", json={"auto": True})
    assert again.status_code == 400, "a second auto merge with nothing left should say so"
    print("4. auto merges the same-name groups only; with none it is a 400")


def test_restore(slug, store, stamp, before):
    # the same story, merged in test 2: put the first backup back
    current = (Path(store.dir) / "characters.md").read_text(encoding="utf-8")
    r = c.post(f"/api/saves/{slug}/duplicates/restore", json={"backup": stamp})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["restored"] == ["characters.md"] and (Path(store.dir) / "characters.md").read_text(encoding="utf-8") == before, "not byte for byte"
    assert len(slugs(store)) == 5 and out["backed_up_as"] in out["backups"] and out["backed_up_as"] != stamp
    undone = c.post(f"/api/saves/{slug}/duplicates/restore", json={"backup": out["backed_up_as"]})
    assert undone.status_code == 200 and (Path(store.dir) / "characters.md").read_text(encoding="utf-8") == current, "the restore could not be undone"
    print("5. a restore puts the registry back byte for byte, and can itself be restored")
    return stamp


def test_restore_refusals(slug, store, stamp):
    root = Path(store.dir) / ".dedupe-backup"
    (root / "20200101-000000").mkdir()
    (root / "notes").mkdir()                                # a folder the tool did not make is not a backup
    assert "notes" not in c.get(f"/api/saves/{slug}/duplicates").json()["backups"], "a folder that is not a stamp was listed as a backup"
    # a backup folder that also holds something that is not a registry: only registries are put back
    mixed = root / "20210101-000000"
    mixed.mkdir()
    (mixed / "characters.md").write_text((Path(store.dir) / "characters.md").read_text(encoding="utf-8"), encoding="utf-8")
    (mixed / "meta.json").write_text("{\"hacked\": true}", encoding="utf-8")
    meta_before = (Path(store.dir) / "meta.json").read_text(encoding="utf-8")
    r = c.post(f"/api/saves/{slug}/duplicates/restore", json={"backup": "20210101-000000"})
    assert r.status_code == 200 and r.json()["restored"] == ["characters.md"], r.text[:200]
    assert (Path(store.dir) / "meta.json").read_text(encoding="utf-8") == meta_before, "a restore overwrote a file that is not a registry"
    n_before = len(c.get(f"/api/saves/{slug}/duplicates").json()["backups"])
    for body, want in (({"backup": "../x"}, 400), ({"backup": "20200101-000000/../.."}, 400), ({"backup": 5}, 400), ({}, 400),
                       ({"backup": "20990101-000000"}, 404), ({"backup": "20200101-000000"}, 400)):
        r = c.post(f"/api/saves/{slug}/duplicates/restore", json=body)
        assert r.status_code == want, (body, r.status_code, r.text[:100])
    assert len(c.get(f"/api/saves/{slug}/duplicates").json()["backups"]) == n_before, "a refused restore left a backup"
    print("6. a restore is only for a stamp the tool made: a path, a missing stamp and an empty folder are refused")


def test_busy(slug):
    assert server._gen_lock.acquire(blocking=False)
    try:
        assert c.get(f"/api/saves/{slug}/duplicates").status_code == 200
        assert c.post(f"/api/saves/{slug}/duplicates/merge", json={"auto": True}).status_code == 409
        r = c.post(f"/api/saves/{slug}/duplicates/merge", json={"rel": "characters.md", "keep": "bram-halloran", "drop": ["bram-halloran-2"]})
        assert r.status_code == 409, (r.status_code, r.text[:100])
        r = c.post(f"/api/saves/{slug}/duplicates/restore", json={"backup": c.get(f"/api/saves/{slug}/duplicates").json()["backups"][0]})
        assert r.status_code == 409, (r.status_code, r.text[:100])
    finally:
        server._gen_lock.release()
    print("7. a merge or a restore while a turn is generating is a 409 and the view still answers")


def test_slugs():
    assert c.get("/api/saves/no-such-story/duplicates").status_code == 404
    assert c.get("/api/saves/Not A Slug/duplicates").status_code in (400, 404)
    assert c.post("/api/saves/no-such-story/duplicates/merge", json={"auto": True}).status_code == 404
    print("8. an unknown save is a 404 and a slug that is not a clean id is refused")


test_view()
s, st, stamp, before = test_explicit_merge()
test_refusals()
test_auto()
test_restore(s, st, stamp, before)
test_restore_refusals(s, st, stamp)
test_busy(s)
test_slugs()
print("\nDEDUPE API TESTS PASSED")
