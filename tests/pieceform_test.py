"""The piece editor's field table and the AI merge (webapp/js/pieceform.js).

What broke. "Improve with AI" and "Seed from idea" wrote only some of the form's fields back: never a character's
wants, motivation, traits or links, the activation controls (group, chance, delay, sticky, cooldown, requires, blocked
by, semantic, recurse) or the four trait fields of D-032, and collect() then re-merged the OLD attributes over the
AI's answer. The author's form looked updated and the answer was silently dropped for those fields, and there was
no undo. The fix is one table that drives both directions plus a merge that is lossless.

Node runs the pure module (it has no DOM). Without node the test says so and skips: it is a development check, not a
runtime dependency.

 1) the table has unique ids and attributes, and each kind of piece gets exactly its own fields
 2) every attribute the AI states reaches the merged entry, managed or not; one it leaves out keeps the author's value
 3) null and undefined never clobber, lists and numbers arrive as text, and a bad title, importance or alias list keeps
    the form's own
 4) unmanaged attributes (a character's extra header lines) are carried and an AI result may replace them
 5) the editor's HTML has an element for every field in the table, the Undo AI button exists, and collect, fill and the
    Characters screen use the shared table and labels
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "webapp" / "js"

NODE = shutil.which("node")
if not NODE:
    print("SKIP: node is not installed; the piece editor's merge is not checked here")
    print("\nPIECEFORM TESTS PASSED (skipped)")
    sys.exit(0)

SCRIPT = r"""
import * as pf from %s;
const out = {};
out.ids = pf.FIELDS.map(f => f.id);
out.attrs = pf.FIELDS.map(f => f.attr);
out.chars = pf.fieldsFor("characters.md").map(f => f.attr);
out.events = pf.fieldsFor("events.md").map(f => f.attr);
out.items = pf.fieldsFor("items.md").map(f => f.attr);
out.threads = pf.fieldsFor("threads.md").map(f => f.attr);
out.places = pf.fieldsFor("locations.md").map(f => f.attr);
out.unmanaged = pf.unmanaged({weight: "x", custom: "y", strengths: "s", traits: "a", status: "wary"});
const cur = {title: "Odile", slug: "odile", importance: 4, aliases: ["The Courier"], body: "Old body.",
             attrs: {wants: "old want", custom: "keep", traits: "a, b", pinned: "true", group: "g1", status: "wary"}};
out.full = pf.mergeFill(cur, {title: "Odile Marsh", importance: 5, aliases: ["Odile", "The Courier"], body: "New body.",
  attrs: {wants: "new want", motivation: "her debt", strengths: "reads a room", weaknesses: "trusts too late",
          personality: "ISTJ", goals: "clear her name", traits: "brave, wary", links: "corin-hale", group: "g2",
          chance: 50, delay: "2", semantic: "true", custom2: "z", status: "calm"}});
out.empty = pf.mergeFill(cur, {attrs: {}});
out.noentry = pf.mergeFill(cur, null);
out.nulls = pf.mergeFill(cur, {title: null, importance: "lots", aliases: "no", body: undefined,
                               attrs: {wants: null, group: undefined, traits: ["x", "y"], chance: 7}});
out.csv = [pf.csv("a, b,, c "), pf.csv(""), pf.csv(undefined)];
console.log(JSON.stringify(out));
""" % json.dumps((JS / "pieceform.js").as_uri())

r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT], capture_output=True, text=True, timeout=60)
assert r.returncode == 0, r.stderr[-600:]
o = json.loads(r.stdout.strip().splitlines()[-1])


def test_table():
    assert len(set(o["ids"])) == len(o["ids"]) and len(set(o["attrs"])) == len(o["attrs"]), "duplicate ids or attributes"
    common = {"weight", "triggers", "pinned", "hidden", "group", "chance", "delay", "sticky", "cooldown",
              "triggers_all", "triggers_not", "semantic", "recurse"}
    assert set(o["places"]) == common, o["places"]
    assert set(o["chars"]) == common | {"playable", "stats", "skills", "wants", "motivation", "strengths",
                                        "weaknesses", "personality", "goals"}, o["chars"]
    assert set(o["events"]) == common | {"once"} and set(o["items"]) == common | {"rarity"}, (o["events"], o["items"])
    assert set(o["threads"]) == common | {"objectives"}, o["threads"]
    print("1. unique ids and attributes; each kind of piece gets exactly its own fields (a character 22, a place 13)")


def test_merge_is_lossless():
    m = o["full"]
    assert (m["title"], m["importance"], m["aliases"], m["body"], m["slug"]) == \
        ("Odile Marsh", 5, ["Odile", "The Courier"], "New body.", "odile"), m
    a = m["attrs"]
    for k, v in {"wants": "new want", "motivation": "her debt", "strengths": "reads a room",
                 "weaknesses": "trusts too late", "personality": "ISTJ", "goals": "clear her name",
                 "traits": "brave, wary", "links": "corin-hale", "group": "g2", "chance": "50", "delay": "2",
                 "semantic": "true", "custom2": "z", "status": "calm"}.items():
        assert a.get(k) == v, (k, a.get(k), v)
    assert a["custom"] == "keep" and a["pinned"] == "true", "an attribute the AI left out was lost"
    e = o["empty"]
    assert e["title"] == "Odile" and e["importance"] == 4 and e["aliases"] == ["The Courier"] and e["body"] == "Old body."
    assert e["attrs"] == {"wants": "old want", "custom": "keep", "traits": "a, b", "pinned": "true", "group": "g1",
                          "status": "wary"}, e["attrs"]
    assert o["noentry"]["title"] == "Odile" and o["noentry"]["attrs"]["wants"] == "old want"
    print("2. every attribute the AI states reaches the merged entry; one it leaves out keeps the author's value")


def test_edges():
    n = o["nulls"]
    assert n["title"] == "Odile" and n["importance"] == 4 and n["aliases"] == ["The Courier"] and n["body"] == "Old body.", n
    assert n["attrs"]["wants"] == "old want" and n["attrs"]["group"] == "g1", "null or undefined clobbered a value"
    assert n["attrs"]["traits"] == "x, y" and n["attrs"]["chance"] == "7", "a list or a number did not arrive as text"
    assert o["csv"] == [["a", "b", "c"], [], []], o["csv"]
    print("3. null and undefined never clobber; lists and numbers arrive as text; bad title, importance or aliases keep the form's")


def test_unmanaged_are_carried():
    assert o["unmanaged"] == {"custom": "y", "status": "wary"}, o["unmanaged"]
    assert o["full"]["attrs"]["status"] == "calm", "an AI result must be able to replace an unmanaged attribute"
    print("4. unmanaged attributes are carried, and an AI result may replace them")


def test_the_form_uses_the_table():
    builder = (JS / "builder.js").read_text(encoding="utf-8")
    cast = (JS / "cast.js").read_text(encoding="utf-8")
    traits = {"strengths", "weaknesses", "personality", "goals"}
    for fid, attr in zip(o["ids"], o["attrs"]):
        if attr in traits:
            assert 'id="p-${f}"' in builder, "the trait fields are not rendered in the form"
        else:
            assert f'id="{fid}"' in builder or f'check("{fid}"' in builder, f"the form has no element {fid} for {attr}"
    assert 'id="p-undo-ai"' in builder and "applyAI" in builder and "mergeFill" in builder
    assert "fieldsFor(rel)" in builder and builder.count("applyAI(out.entry)") == 2, "seed and improve both go through applyAI"
    assert re.search(r"fill\(out\.entry\)", builder) is None, "a raw fill() of an AI result is back"
    assert "chips[c].set(" in builder
    assert "const attrs = {...carried};" in builder and "for (const c of CHIPS) attrs[c] = chips[c].get().join" in builder,         "collect() no longer carries the unmanaged attributes and both chip lists"
    assert "carried = unmanaged(ea);" in builder, "an applied entry does not reset the carried attributes"
    assert "const fill = entry => apply(mergeFill(collect(), entry));" in builder, "fill() no longer goes through the merge"
    assert "from \"./pieceform.js\"" in cast and "const LABEL = {" not in cast, "the Characters screen has its own copy of the labels"
    assert "values.splice(0, values.length, ...(list || [])); render();" in (JS / "util.js").read_text(encoding="utf-8"),         "chipInput().set does not replace the list and redraw"
    print("5. the form has an element for every field in the table, Undo AI exists, and seed and improve both use the merge")


for fn in (test_table, test_merge_is_lossless, test_edges, test_unmanaged_are_carried, test_the_form_uses_the_table):
    fn()
print("\nPIECEFORM TESTS PASSED")
