"""Character traits: strengths, weaknesses, a personality type and goals, given in the Plan panel (D-032).

What this pins is mostly what must NOT happen, because a trait is the author's words stored on an entry that is
sent with every turn the character is active:

  1. set / clear / replace each of the four fields; everything else about the entry (body, aliases, importance,
     its other header lines) is left exactly as it was, and no other character changes
  2. refusals write nothing: a non-string, a value over its limit, a field that does not exist (wants and
     motivation are live and the fold's, so they are not settable here) and a character that does not exist
  3. every value is one line, however it was typed
  4. the memory fold keeps them: a promotion that rewrites the entry (status, wants, a new alias list, a new
     body) leaves the four fields alone
  5. the chapter planner is told about them when any exist, within a size cap, and not otherwise
  6. the API: GET lists the protagonist first, then characters by importance; PUT sets, 404s an unknown
     character, 400s every bad input, and leaves the file alone when it refuses; a hand edit of characters.md
     is the same thing as the panel
  7. the Writer's rules say how to use them, and an install still on the previous default rules is upgraded
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-cast-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import cast, templates                                        # noqa: E402
from coderain.config import load_config                                     # noqa: E402
from coderain.memory import Entry                                           # noqa: E402
from coderain.planner import ChapterPlanner                                 # noqa: E402
from coderain.summarizer import Summarizer                                  # noqa: E402

import server                                                               # noqa: E402
from fastapi.testclient import TestClient                                   # noqa: E402

c = TestClient(server.app)


def new_save(title="Cast"):
    return c.post("/api/saves", json={"title": title, "mode": "simple", "premise": "A ferry town."}).json()["slug"]


def store_for(slug):
    return server._engine(slug).store


def add(store, slug, title, importance=3, body="", aliases=(), **attrs):
    store.upsert_entry("characters.md", Entry(title, slug, list(aliases), importance, dict(attrs), body))


def disk(store, rel="characters.md"):
    return store.read(rel)


def test_set_clear_and_leave_the_rest_alone():
    """1, 3."""
    store = store_for(new_save("Cast 1"))
    add(store, "odile", "Odile Marsh", 4, "The courier.\n\nShe keeps a lantern.", ["The Courier"], status="wary",
        wants="get the ledger back")
    add(store, "corin", "Corin Hale", 2, "A clerk.")
    before = {e.slug: e for e in store.entries("characters.md")}
    row = cast.set_traits(store, "odile", {"strengths": "reads a room;\nfast with a knife", "goals": "clear her brother's name",
                                           "personality": "  ISTJ  "})
    assert row["strengths"] == "reads a room; fast with a knife" and row["personality"] == "ISTJ", row
    assert row["weaknesses"] == "" and row["wants"] == "get the ledger back", row
    after = {e.slug: e for e in store.entries("characters.md")}
    o, o0 = after["odile"], before["odile"]
    assert (o.body, o.aliases, o.importance, o.attrs["status"], o.attrs["wants"]) == \
        (o0.body, o0.aliases, o0.importance, "wary", "get the ledger back"), "the rest of the entry changed"
    assert after["corin"] == before["corin"], "another character changed"
    assert "strengths: reads a room; fast with a knife" in disk(store), "it is a plain header line in the Markdown"
    # replace one, leave the others; clear one with an empty value; None clears too
    cast.set_traits(store, "odile", {"goals": "get out of the Ring alive"})
    o = [e for e in store.entries("characters.md") if e.slug == "odile"][0]
    assert o.attrs["goals"] == "get out of the Ring alive" and o.attrs["strengths"] == "reads a room; fast with a knife"
    cast.set_traits(store, "odile", {"strengths": "", "personality": None})
    o = [e for e in store.entries("characters.md") if e.slug == "odile"][0]
    assert "strengths" not in o.attrs and "personality" not in o.attrs and o.attrs["goals"], o.attrs
    assert "strengths:" not in disk(store) and "personality:" not in disk(store), "a cleared field leaves no empty line"
    # the limit counts what is stored, not the whitespace typed around it
    assert cast.set_traits(store, "odile", {"goals": "a" + " " * 400 + "b"})["goals"] == "a b"
    print("1,3. set, replace and clear touch only the named fields, one line each, and nothing else changes")


def test_refusals_write_nothing():
    """2."""
    store = store_for(new_save("Cast 2"))
    add(store, "odile", "Odile Marsh", 4, "The courier.")
    before = disk(store)
    bad = [("odile", {"strengths": 5}, "must be text"), ("odile", {"goals": "x" * 301}, "limited to 300"),
           ("odile", {"personality": "x" * 81}, "limited to 80"), ("odile", {"wants": "x"}, "unknown field"),
           ("odile", {"mood": "x"}, "unknown field"), ("odile", ["a"], "must be an object")]
    for key, traits, why in bad:
        try:
            cast.set_traits(store, key, traits)
        except cast.CastError as e:
            assert why in str(e) and not e.missing, (traits, str(e))
        else:
            raise AssertionError(f"accepted {traits!r}")
    try:
        cast.set_traits(store, "nobody", {"goals": "x"})
    except cast.CastError as e:
        assert e.missing
    else:
        raise AssertionError("an unknown character was accepted")
    assert disk(store) == before, "a refusal wrote something"
    # a valid field next to a bad one writes neither
    try:
        cast.set_traits(store, "odile", {"goals": "fine", "strengths": "x" * 400})
    except cast.CastError:
        pass
    assert disk(store) == before, "half a request was written"
    print("2. a non-string, an over-long value, an unknown field and an unknown character are refused with nothing written")


def test_the_fold_keeps_them():
    """4."""
    store = store_for(new_save("Cast 3"))
    add(store, "odile", "Odile Marsh", 4, "The courier.", ["The Courier"], status="wary")
    cast.set_traits(store, "odile", {"strengths": "fast with a knife", "weaknesses": "afraid of deep water",
                                     "personality": "stoic", "goals": "clear her brother's name"})

    class Cfg:
        memory: dict = {}
    s = Summarizer(Cfg(), store, None, None)
    s._apply_promotions({"promotions": [
        {"kind": "character", "slug": "odile", "title": "Odile Marsh", "detail": "Rewritten body.", "status": "calm",
         "wants": "cross the ford", "motivation": "a debt", "aliases": ["Marsh"], "importance": 5},
        {"kind": "character", "slug": "odile-4", "title": "Odile Marsh", "detail": "Rewritten again.", "status": "tired"}]})
    es = store.entries("characters.md")
    assert [e.slug for e in es] == ["odile"], "the second promotion merges (D-029)"
    o = es[0]
    assert o.attrs["status"] == "tired" and o.attrs["wants"] == "cross the ford" and o.body.strip() == "Rewritten again."
    assert (o.attrs["strengths"], o.attrs["weaknesses"], o.attrs["personality"], o.attrs["goals"]) == \
        ("fast with a knife", "afraid of deep water", "stoic", "clear her brother's name"), o.attrs
    print("4. a fold that rewrites status, wants, aliases and the body leaves the author's four fields alone")


def test_the_planner_is_told():
    """5."""
    slug = new_save("Cast 4")
    store = store_for(slug)
    planner = ChapterPlanner(load_config(), store, None)
    assert "CHARACTERS" not in planner._plan_payload(), "nobody has traits: the planner is not told about nobody"
    add(store, "odile", "Odile Marsh", 4)
    add(store, "corin", "Corin Hale", 2)
    cast.set_traits(store, "odile", {"strengths": "fast with a knife", "goals": "clear her brother's name"})
    cast.set_traits(store, "player", {"weaknesses": "trusts the wrong people"})
    payload = planner._plan_payload()
    assert "CHARACTERS" in payload and "Odile Marsh: strengths: fast with a knife; goals: clear her brother's name" in payload
    assert "You (the player): weaknesses: trusts the wrong people" in payload and "Corin Hale" not in payload, payload
    assert payload.index("CHARACTERS") < payload.index("CHAPTERS SO FAR"), "before the chapters it has to fit"
    # a size cap with a visible count of whoever did not fit
    for n in range(40):
        add(store, f"person-{n:02d}", f"Person Number {n:02d}", 3)
        cast.set_traits(store, f"person-{n:02d}", {"goals": "g" * 200})
    block = cast.traits_block(store)
    assert len(block) <= cast.BLOCK_CHARS + 60 and "more not shown" in block, len(block)
    assert cast.traits_block(store, limit=10).count("\n") == 0 and "more not shown" in cast.traits_block(store, limit=10)
    print("5. the planner reads the traits before the chapters when any exist, within a cap, and not otherwise")


def test_the_api():
    """6."""
    slug = new_save("Cast 5")
    store = store_for(slug)
    add(store, "corin", "Corin Hale", 2, "A clerk.")
    add(store, "odile", "Odile Marsh", 5, "The courier.", status="wary")
    add(store, "adda", "Adda Pike", 5, "A ferrywoman.")
    d = c.get(f"/api/saves/{slug}/cast").json()
    assert d["fields"] == ["strengths", "weaknesses", "personality", "goals"] and d["limits"]["personality"] == 80, d
    assert [r["key"] for r in d["characters"]] == ["player", "adda", "odile", "corin"], \
        "the protagonist first, then importance, then name"
    assert d["characters"][0]["player"] is True and d["characters"][2]["strengths"] == ""
    r = c.put(f"/api/saves/{slug}/cast/odile", json={"strengths": "fast with a knife", "goals": "clear her name"})
    assert r.status_code == 200 and r.json()["strengths"] == "fast with a knife" and r.json()["goals"] == "clear her name"
    r = c.put(f"/api/saves/{slug}/cast/player", json={"personality": "a stoic"})
    assert r.status_code == 200 and r.json()["player"] is True and r.json()["personality"] == "a stoic"
    before = disk(store)
    for key, body, code in (("nobody", {"goals": "x"}, 404), ("odile", {"mood": "x"}, 400), ("odile", {"goals": "x" * 301}, 400),
                            ("odile", {"goals": 5}, 400)):
        r = c.put(f"/api/saves/{slug}/cast/{key}", json=body)
        assert r.status_code == code, (key, body, r.status_code, r.text)
    assert disk(store) == before, "a refused request wrote something"
    assert c.get("/api/saves/no-such-save/cast").status_code == 404
    # a hand edit of the Markdown is the same thing as the panel
    store.write("characters.md", disk(store).replace("importance: 2\n", "importance: 2\nweaknesses: cannot lie\n", 1))
    got = {r["key"]: r for r in c.get(f"/api/saves/{slug}/cast").json()["characters"]}
    assert got["corin"]["weaknesses"] == "cannot lie", got["corin"]
    print("6. GET lists the protagonist first; PUT sets, 404s and 400s as specified and writes nothing on a refusal; a hand edit shows")


def test_the_rules():
    """7."""
    assert "## Character traits" in templates.default_rule("writer-rules.md") and templates.RULES_VERSION == 11
    old = "49e91649711565815764fb938fa2241c3c194c9dfb6535f6499ee7b068792831"
    assert old in templates._SHIPPED_RULE_HASHES["writer-rules.md"], "an install on the v10 default would not be upgraded"
    assert "strengths:" in templates.default_rule("writer-rules.md") and "goals:" in templates.default_rule("writer-rules.md")
    print("7. the Writer's rules describe the four fields, and the previous default is registered so installs upgrade")


def test_the_writer_is_given_them():
    """8. End to end: the fields reach the prompt the Writer is sent, for a character who is in play, and for the
    protagonist, and not for one who is not."""
    from coderain.engine import Engine
    slug = new_save("Cast 6")
    store = store_for(slug)
    add(store, "odile", "Odile Marsh", 4, "The courier.", ["The Courier"])
    add(store, "corin", "Corin Hale", 2, "A clerk who never leaves the customs shed.")
    cast.set_traits(store, "odile", {"strengths": "fast with a knife", "goals": "clear her brother's name"})
    cast.set_traits(store, "corin", {"weaknesses": "takes small bribes"})
    cast.set_traits(store, "player", {"personality": "a stoic who keeps promises"})
    store.append_turn("player", "I wait.")
    store.append_turn("narrator", "Odile Marsh looked up from the rope.")
    eng = Engine(load_config(), store)
    msgs = eng._messages(eng.history_window(), "I ask Odile Marsh about the crossing.")
    system = msgs[0]["content"]
    assert "strengths: fast with a knife" in system and "goals: clear her brother's name" in system, "a character in play"
    assert "personality: a stoic who keeps promises" in system, "the protagonist is always in context"
    assert "takes small bribes" not in system, "a character who is not in play costs the prompt nothing"
    print("8. the strengths and goals of a character in play, and the protagonist's personality, are in the Writer's prompt")


for fn in (test_set_clear_and_leave_the_rest_alone, test_refusals_write_nothing, test_the_fold_keeps_them,
           test_the_planner_is_told, test_the_api, test_the_rules, test_the_writer_is_given_them):
    fn()
print("ALL OK")
