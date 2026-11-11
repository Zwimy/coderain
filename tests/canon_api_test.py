"""The canon routes (D-028): see what canon holds about a character, and correct it.

The corrections are Markdown in the save (corrections.md), so the app and a hand edit are the same thing. The
routes are the part an interface (or a button next to a wrong value) calls. Each numbered assertion pins one
promise:

 1) with the shadow off nothing reads the story, but the file can still be viewed, written and checked, and
    it takes effect when the shadow is turned on
 2) PUT replaces the file exactly, and reports what could not be read, by line; a non-string or an oversize
    body is refused and the file is left alone
 3) POST adds one correction, never the same one twice, and refuses every input the file format cannot hold
    (a bad slot or op, a name with a colon or an equals sign, a value that would start a note, an empty or a
    too-long value) without touching the file
 4) an unknown save is a 404, and a slug that is not a clean id is refused
 5) corrections.md travels with an export, because it is the author's and cannot be rebuilt
 6) with the shadow on, GET shows what canon holds with the corrections applied and whose word each value is,
    and a correction added through POST shows at once and reaches the ledger on the reader's next pass; the
    file put back without that line (what the panel's Remove does) releases the value in the view at once and
    in the ledger at the next pass
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-canonapi-")
os.environ["CODERAIN_HOME"] = HOME

from canon.scribe import Scribe                                           # noqa: E402
from coderain.memory import Entry                                         # noqa: E402

import server                                                             # noqa: E402
from fastapi.testclient import TestClient                                 # noqa: E402

c = TestClient(server.app)
T1 = "Odile Marsh stepped in, her raven hair damp. Odile wore a grey coat."


class Stub:
    stays_local = True

    def complete(self, system, user, schema_=None):
        if "her raven hair" in user:
            claim = dict(entity="Odile Marsh", slot="identity.hair", op="set", value="raven",
                         evidence="her raven hair", confidence="high")
            return json.dumps({"claims": [claim]})
        return json.dumps({"claims": []})


def new_save(title):
    return c.post("/api/saves", json={"title": title, "mode": "simple",
                                      "premise": "A harbour town."}).json()["slug"]


def disk(slug):
    return server._engine(slug).store.read("corrections.md")


def test_without_the_shadow():
    slug = new_save("Canon API off")
    r = c.get(f"/api/saves/{slug}/canon")
    assert r.status_code == 200
    v = r.json()
    assert v["shadow"] is False and v["values"] == [] and v["text"] == "" and v["corrections"] == [], v
    r = c.put(f"/api/saves/{slug}/canon/corrections", json={"text": "- Odile: hair = raven\n"}).json()
    assert r["shadow"] is False and [x["who"] for x in r["corrections"]] == ["Odile"]
    print("1. with the shadow off the file can still be viewed, written and checked")
    return slug


def test_put(slug):
    text = "# my notes\n- Odile: hair = raven\n- broken line\n- Corin: hair is not raven\n"
    v = c.put(f"/api/saves/{slug}/canon/corrections", json={"text": text}).json()
    assert disk(slug) == text, "the file is not exactly what was sent"
    assert [(x["who"], x["op"]) for x in v["corrections"]] == [("Odile", "set"), ("Corin", "wrong")]
    assert [p["line"] for p in v["problems"]] == [3], v["problems"]
    for bad in ({"text": 5}, {"text": None}, {}, {"text": "x" * 20_001}):
        r = c.put(f"/api/saves/{slug}/canon/corrections", json=bad)
        assert r.status_code == 400, (bad if len(str(bad)) < 40 else "big", r.status_code)
    assert disk(slug) == text, "a refused body changed the file"
    print("2. PUT stores the text exactly and reports unreadable lines by number; bad bodies are refused "
          "and leave the file alone")
    return text


def test_post(slug, text):
    url = f"/api/saves/{slug}/canon/corrections"
    ok = c.post(url, json={"who": "Tamsin", "slot": "eye", "op": "set", "value": "pale gray"})
    assert ok.status_code == 200 and disk(slug) == text + "- Tamsin: eyes = pale gray\n", disk(slug)
    again = c.post(url, json={"who": "tamsin", "slot": "eyes", "op": "set", "value": "Pale Gray"})
    assert again.status_code == 200 and disk(slug) == text + "- Tamsin: eyes = pale gray\n", "added twice"
    before = disk(slug)
    for bad in ({"who": "", "slot": "hair", "op": "set", "value": "red"},
                {"who": "A" * 200, "slot": "hair", "op": "set", "value": "red"},
                {"who": "Odile", "slot": "hairstyle", "op": "set", "value": "red"},
                {"who": "Odile", "slot": "hair", "op": "maybe", "value": "red"},
                {"who": "Od:ile", "slot": "hair", "op": "set", "value": "red"},
                {"who": "Od=ile", "slot": "hair", "op": "set", "value": "red"},
                {"who": "Odile", "slot": "hair", "op": "set", "value": "red -- a note"},
                {"who": "Odile", "slot": "hair", "op": "set", "value": ""},
                {"who": "Odile", "slot": "hair", "op": "set", "value": "x" * 81}):
        r = c.post(url, json=bad)
        assert r.status_code == 400, (bad, r.status_code)
    assert disk(slug) == before, "a refused correction changed the file"
    fresh = new_save("Canon API fresh")
    c.post(f"/api/saves/{fresh}/canon/corrections", json={"who": "Odile", "slot": "hair", "op": "wrong", "value": "raven"})
    assert disk(fresh).startswith("# Canon corrections") and disk(fresh).rstrip().endswith("- Odile: hair is not raven")
    print("3. POST adds one correction once, adds the header to a new file, and refuses every input the "
          "format cannot hold without touching the file")


def test_slugs():
    assert c.get("/api/saves/no-such-save/canon").status_code == 404
    assert c.get("/api/saves/..%2Fetc/canon").status_code in (400, 404)
    assert c.put("/api/saves/Bad Slug!/canon/corrections", json={"text": ""}).status_code in (400, 404)
    print("4. an unknown save is a 404 and an unclean slug is refused")


def test_export(slug):
    dest = Path(HOME) / "x.zip"
    server.lib.saves.export(slug, dest)
    names = zipfile.ZipFile(dest).namelist()
    assert "corrections.md" in names, names[:12]
    exported = zipfile.ZipFile(dest).read("corrections.md").decode("utf-8")
    assert exported.replace("\r\n", "\n") == disk(slug), "the exported text is not what was written"
    print("5. corrections.md travels with an export")


def test_with_the_shadow():
    server.core._cfg.raw["canon"] = {"shadow": True, "backfill": "all"}
    server.core._engines.clear()
    try:
        slug = new_save("Canon API on")
        eng = server._engine(slug)
        sh = eng.canon_shadow
        assert sh is not None
        sh.scribe = Scribe(Stub())
        eng.store.upsert_entry("characters.md", Entry(title="Odile Marsh", slug="odile"))
        eng.store.append_turn("player", "I wait.")
        eng.store.append_turn("narrator", T1)
        sh.reconcile()
        v = c.get(f"/api/saves/{slug}/canon").json()
        assert v["shadow"] is True and v["unread"] == 0, v
        by = {(r["who"], r["slot"]): r for r in v["values"]}
        assert by[("Odile Marsh", "hair")]["value"] == "raven" and by[("Odile Marsh", "hair")]["by"] == "narration"
        r = c.post(f"/api/saves/{slug}/canon/corrections",
                   json={"who": "Odile Marsh", "slot": "hair", "op": "set", "value": "auburn"})
        assert r.status_code == 200
        by = {(x["who"], x["slot"]): x for x in r.json()["values"]}
        assert by[("Odile Marsh", "hair")]["value"] == "auburn" and by[("Odile Marsh", "hair")]["by"] == "author", \
            "the view must show the correction at once"
        sh.wait()                                           # the reader's pass that the POST kicked
        assert sh._store().canon.current("odile", "identity.hair") == "auburn", "it never reached the ledger"
        # the panel's Remove: take the line out of the file and PUT the file back. The value it set is released
        # (the slot is empty, it is not shown as held, and it is not "yours" next to no correction), and the
        # story's earlier value is not brought back, because the ledger no longer holds it as open
        text = c.get(f"/api/saves/{slug}/canon").json()["text"]
        kept = "\n".join(ln for ln in text.split("\n") if "auburn" not in ln)
        assert kept != text, text
        r = c.put(f"/api/saves/{slug}/canon/corrections", json={"text": kept})
        assert r.status_code == 200, r.text
        r = r.json()
        assert r["corrections"] == [], r["corrections"]
        assert not any(x["who"] == "Odile Marsh" and x["slot"] == "hair" for x in r["values"]), \
            "the removed correction's value is still shown as held: " + str(r["values"])
        sh.wait()
        assert sh._store().canon.current("odile", "identity.hair") is None, "the release never reached the ledger"
        r = c.post(f"/api/saves/{slug}/canon/corrections",
                   json={"who": "Nobody Here", "slot": "eyes", "op": "set", "value": "grey"}).json()
        assert any("Nobody Here" in p["why"] for p in r["problems"]), r["problems"]
    finally:
        server.core._cfg.raw.pop("canon", None)
        server.core._engines.clear()
    print("6. with the shadow on, GET shows canon with the corrections applied and whose word each value is; "
          "a POST shows at once and reaches the ledger; removing the line (the panel's Remove) releases the "
          "value at once and in the ledger; an unknown character is reported")


try:
    s = test_without_the_shadow()
    t = test_put(s)
    test_post(s, t)
    test_slugs()
    test_export(s)
    test_with_the_shadow()
finally:
    shutil.rmtree(HOME, ignore_errors=True)
print("\nCANON API TESTS PASSED")
