"""Creating things must not destroy or silently drop other things (D-066, the creation-flow pass).

A read-only probe of the creation routes with awkward input found these, each reachable from the app:

 1) a NEW piece whose name makes the slug of one already there REPLACED it with no question and no way back: a second character called
    "Vesper" (or "VESPER", or "Vesper!") wiped the first one's text. Now a 409 that names the existing piece, on both worlds and stories
 2) editing a piece in place (the slug it was opened with) still works, including a new title and a new body
 3) a rename onto another piece's name was the same overwrite (the renamed piece's text replaced the other piece, then the old one was
    removed); now a 409, and neither piece changes. A rename to a free name still works and removes the old one
 4) dropping a library character or a library piece into a world, or into a story's world, a second time replaced what was there; now a
    409 for each of the four routes, and the first drop still works
 5) a new story naming a world, a character or a playable character that no longer exists was made anyway, without them and without a
    word (a picker left open while the thing was deleted in another window). Now a 404 or 400 BEFORE anything is created, so no story
    folder is left behind; a good request is unchanged
 6) a title of a few hundred characters (a pasted paragraph) made a folder name the file system refuses, and creating the world or the
    story was a server error. Folder names are capped at 60 characters, never end in a dash, and two long titles that share their first 60
    characters still get different, openable folders; the title itself is kept whole
 7) a character sheet with a blank name was saved as "Unnamed" without a word; now a 400, like a piece without a title, for a new sheet
    and for an edit
 8) a piece title was unbounded (5000 characters were stored and written into the roster); a chapter title stops at 200, so does this
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-creation-")
os.environ["CODERAIN_HOME"] = HOME

import server                                                   # noqa: E402,F401
from fastapi.testclient import TestClient                       # noqa: E402
from coderain import templates                                  # noqa: E402
from srv import core                                            # noqa: E402

c = TestClient(server.app, raise_server_exceptions=False)
core._cfg.generation["chapter_outline"] = False
core._cfg.generation["trinity_brain"] = False


def world(title):
    return c.post("/api/scenarios", json={"title": title, "premise": "A harbour town."}).json()["slug"]


def put(w, entry, old="", rel="characters.md", story=False):
    url = f"/api/saves/{w}/world/pieces/{rel}" if story else f"/api/scenarios/{w}/pieces/{rel}"
    return c.put(url, json={"entry": entry, "old_slug": old})


def pieces(w, rel="characters.md", story=False):
    if story:
        got = c.get(f"/api/saves/{w}/world/full").json()["pieces"][rel]
    else:
        got = c.get(f"/api/scenarios/{w}/full").json()["pieces"][rel]
    return {e["slug"]: e for e in got}


def story_folders():
    return sorted(p.name for p in Path(core.lib.saves.root).iterdir() if p.is_dir())


def test_new_piece_never_replaces():
    for story in (False, True):
        w = world("Clash")
        if story:
            w = c.post("/api/saves", json={"title": "Clash story", "scenario": w}).json()["slug"]
        assert put(w, {"title": "Vesper", "body": "First."}, story=story).status_code == 200
        for taken in ("Vesper", "VESPER", "vesper", "Vesper!", "  Vesper  "):
            r = put(w, {"title": taken, "body": "A different person."}, story=story)
            assert r.status_code == 409, (story, taken, r.status_code, r.text[:100])
            assert "“Vesper”" in r.json()["detail"] and "another name" in r.json()["detail"], r.json()
        got = pieces(w, story=story)
        assert list(got) == ["vesper"] and got["vesper"]["body"] == "First." and got["vesper"]["title"] == "Vesper", \
            f"a refused piece changed what was there ({'story' if story else 'world'}): {got}"
        assert put(w, {"title": "Bram", "body": "Free name."}, story=story).status_code == 200
        assert sorted(pieces(w, story=story)) == ["bram", "vesper"]
    print("1. a new piece with a taken name (any case, any punctuation) is a 409 naming the existing one, in a world and in a story, and changes nothing")


def test_edit_in_place():
    for story in (False, True):
        w = world("Edit")
        if story:
            w = c.post("/api/saves", json={"title": "Edit story", "scenario": w}).json()["slug"]
        put(w, {"title": "Vesper", "body": "First."}, story=story)
        r = put(w, {"title": "Vesper the Keeper", "slug": "vesper", "body": "Edited.", "importance": 5}, old="vesper", story=story)
        assert r.status_code == 200, r.text
        got = pieces(w, story=story)
        assert list(got) == ["vesper"] and got["vesper"]["body"] == "Edited." and got["vesper"]["title"] == "Vesper the Keeper", got
        # no slug sent and the title unchanged: the slug the title makes is the piece's own (a changed title would be a rename)
        r = put(w, {"title": "Vesper", "body": "Edited again, no slug sent."}, old="vesper", story=story)
        assert r.status_code == 200 and "Edited again" in pieces(w, story=story)["vesper"]["body"], r.text
    print("2. editing a piece in place (its own slug) still works, with a new title and body, with or without the slug in the body")


def test_rename():
    for story in (False, True):
        w = world("Rename")
        if story:
            w = c.post("/api/saves", json={"title": "Rename story", "scenario": w}).json()["slug"]
        put(w, {"title": "Vesper", "body": "Vesper's text."}, story=story)
        put(w, {"title": "Bram", "body": "Bram's text."}, story=story)
        r = put(w, {"title": "Vesper", "slug": "vesper", "body": "Bram renamed."}, old="bram", story=story)
        assert r.status_code == 409, r.text
        got = pieces(w, story=story)
        assert got["vesper"]["body"] == "Vesper's text." and got["bram"]["body"] == "Bram's text.", "a refused rename changed a piece"
        r = put(w, {"title": "Ser Bram", "slug": "ser-bram", "body": "Bram renamed."}, old="bram", story=story)
        assert r.status_code == 200, r.text
        got = pieces(w, story=story)
        assert sorted(got) == ["ser-bram", "vesper"] and got["ser-bram"]["body"] == "Bram renamed.", got
    print("3. a rename onto another piece's name is a 409 and changes neither; a rename to a free name works and removes the old one")


def test_library_drops():
    char = c.post("/api/characters", json={"name": "Vesper", "description": "From the library."}).json()["id"]
    char2 = c.post("/api/characters", json={"name": "Mara", "description": "Also from the library."}).json()["id"]
    lib_piece = c.post("/api/library", json={"type": "location", "entry": {"title": "Old Port", "body": "Docks."}}).json()["id"]
    for story in (False, True):
        w = world("Drops")
        if story:
            w = c.post("/api/saves", json={"title": "Drops story", "scenario": w}).json()["slug"]
        base = f"/api/saves/{w}/world" if story else f"/api/scenarios/{w}"
        put(w, {"title": "Vesper", "body": "Already here."}, story=story)
        r = c.post(f"{base}/from-library", json={"id": char})
        assert r.status_code == 409 and pieces(w, story=story)["vesper"]["body"] == "Already here.", (story, r.status_code, r.text[:100])
        assert c.post(f"{base}/from-library", json={"id": char2}).status_code == 200
        r = c.post(f"{base}/from-library", json={"id": char2})
        assert r.status_code == 409 and "“Mara”" in r.json()["detail"], r.text[:120]
        assert c.post(f"{base}/from-piece-library", json={"id": lib_piece}).status_code == 200
        r = c.post(f"{base}/from-piece-library", json={"id": lib_piece})
        assert r.status_code == 409, (story, r.status_code, r.text[:100])
        assert list(pieces(w, "locations.md", story=story)) == ["old-port"]
    print("4. the same library character or piece dropped in twice is a 409 on all four routes, the first drop works, nothing is replaced")


def test_new_story_checks_before_making():
    w = world("Refs")
    put(w, {"title": "Vesper", "body": "A keeper."})
    c.post("/api/characters", json={"name": "Lib Hero", "kind": "playable"})
    lib_id = next(x["id"] for x in c.get("/api/characters").json()["characters"] if x["name"] == "Lib Hero")
    before = story_folders()
    gone = world("Gone soon")
    c.delete(f"/api/scenarios/{gone}")
    cases = [("a world that never existed", {"scenario": "no-such-world"}, 404, "gone"),
             ("a world deleted behind the dialog", {"scenario": gone}, 404, "gone"),
             ("a character no longer in the library", {"character": "deadbeef0000"}, 404, "library"),
             ("a playable character that is not in the world", {"scenario": w, "playable": "nobody"}, 400, "not in this world"),
             ("a playable character with no world", {"playable": "vesper"}, 400, "needs that world"),
             ("a world id that is not a clean id", {"scenario": "../x"}, 400, "invalid id")]
    for label, extra, status, word in cases:
        r = c.post("/api/saves", json={"title": "Refs story", **extra})
        assert r.status_code == status and word in r.json()["detail"], (label, r.status_code, r.text[:120])
        assert story_folders() == before, f"{label}: a refused new story left a folder behind: {set(story_folders()) - set(before)}"
    ok = c.post("/api/saves", json={"title": "Refs story", "scenario": w, "playable": "vesper"})
    assert ok.status_code == 200, ok.text
    ok2 = c.post("/api/saves", json={"title": "Refs story", "character": lib_id})
    assert ok2.status_code == 200, ok2.text
    assert c.post("/api/saves", json={"title": "Plain"}).status_code == 200
    assert len(story_folders()) == len(before) + 3
    print("5. a new story naming a missing world or character is refused before anything is made (no folder left behind); good requests are unchanged")


def test_long_titles():
    for name, make in (("world", lambda t: c.post("/api/scenarios", json={"title": t, "premise": "p"})),
                       ("story", lambda t: c.post("/api/saves", json={"title": t}))):
        r = make("x" * 1000)
        assert r.status_code == 200, (name, r.status_code, r.text[:100])
        slug = r.json()["slug"]
        assert 0 < len(slug) <= templates.FOLDER_NAME_MAX and not slug.endswith("-"), slug
        opened = c.get(f"/api/scenarios/{slug}/full") if name == "world" else c.get(f"/api/saves/{slug}")
        assert opened.status_code == 200 and opened.json()["title"] == "x" * 1000, "the title was cut, or the folder cannot be opened"
        a, b = make("a" * 80 + "1").json()["slug"], make("a" * 80 + "2").json()["slug"]
        # the cap is on the name made from the title; the uniqueness suffix ("-2") comes on top of it
        assert a != b and len(a) <= templates.FOLDER_NAME_MAX and len(b) <= templates.FOLDER_NAME_MAX + 4, (a, b)
        for s in (a, b):
            assert (c.get(f"/api/scenarios/{s}/full") if name == "world" else c.get(f"/api/saves/{s}")).status_code == 200
        edge = make("x" * 59 + " y " + "z" * 30).json()["slug"]
        assert not edge.endswith("-") and len(edge) <= 60, edge
    assert templates.slugify_name("x" * 200) == "x" * 60
    assert templates.slugify_name("x" * 59 + " y") == "x" * 59, "the cut must not leave a trailing dash"
    assert templates.slugify_name("???") == "story" and templates.slugify_name("") == "story" and templates.slugify_name("Short one") == "short-one"
    print("6. a very long title makes a folder of at most 60 characters with no trailing dash, the title is kept whole, and shared prefixes stay distinct")


def test_character_needs_a_name():
    n0 = len(c.get("/api/characters").json()["characters"])
    for body in ({"name": ""}, {"name": "   "}, {}, {"name": None}, {"description": "no name"}):
        r = c.post("/api/characters", json=body)
        assert r.status_code == 400 and "needs a name" in r.json()["detail"], (body, r.status_code, r.text[:100])
    assert len(c.get("/api/characters").json()["characters"]) == n0, "a refused sheet was saved anyway"
    made = c.post("/api/characters", json={"name": "Mara Vane", "description": "x"}).json()
    r = c.post("/api/characters", json={"id": made["id"], "name": "  ", "description": "changed"})
    assert r.status_code == 400
    kept = next(x for x in c.get("/api/characters").json()["characters"] if x["id"] == made["id"])
    assert kept["name"] == "Mara Vane" and kept["description"] == "x", "a refused edit changed the sheet"
    assert c.post("/api/characters", json={"id": made["id"], "name": "Mara V.", "description": "changed"}).status_code == 200
    print("7. a character sheet with a blank name is a 400 (new or edited) and nothing is saved; a named one still saves")


def test_piece_title_is_a_name():
    w = world("Titles")
    assert put(w, {"title": "T" * 200, "body": "At the limit."}).status_code == 200
    r = put(w, {"title": "U" * 201, "body": "A pasted paragraph."})
    assert r.status_code == 400 and "200 characters" in r.json()["detail"], (r.status_code, r.text[:100])
    assert len(pieces(w)) == 1, "a refused long title was stored"
    s = c.post("/api/saves", json={"title": "Titles story", "scenario": w}).json()["slug"]
    assert put(s, {"title": "V" * 201}, story=True).status_code == 400
    print("8. a piece title of 201 characters is a 400 with a reason (200 is fine), in a world and in a story; nothing is stored")


test_new_piece_never_replaces()
test_edit_in_place()
test_rename()
test_library_drops()
test_new_story_checks_before_making()
test_long_titles()
test_character_needs_a_name()
test_piece_title_is_a_name()
print("\nCREATION GUARDS TESTS PASSED")
