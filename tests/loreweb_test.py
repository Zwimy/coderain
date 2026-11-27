"""The lore web (D-074): every way one entry points at another, as one graph, walked both ways, without giving a secret away.

What broke before. The files say "this entry points at that one" in four ways (`relationships:`, `holder:`, `links:`, `[[slug]]`), and each was
followed differently or not at all, and only the way it was written: naming the person who carries the brass lamp key never brought the key.

 1) edges_of reads all four kinds; a reference that names no entry, an entry pointing at itself and a mention that repeats a stronger edge are
    left out; a holder written as a name resolves
 2) neighbours walks both ways: what the entry states first, strongest first; a mention only when asked for
 3) fact says an edge in the direction its file states it
 4) the follow pass walks backwards: naming a holder brings what they hold, and whoever states a tie to them, each with the fact
 5) a secret is never given away: a hidden entry that points at a visible one is not pulled in by it, and a followed entry's line never names a
    hidden entry it is tied to
 6) the author's gates hold backwards too: chance 0, an unmet delay and a matching triggers_not keep an entry out
 7) a mention is never followed back: naming the town does not bring everyone whose entry mentions it
 8) two activated entries joined by the web rank above an unjoined one of the same weight; a mere mention does not count; the boost never
    reaches the score that skips the budget, and nothing is boosted with the pass off
 9) the ties line says a holder or tie whichever end was named
10) the same turn walks the same web (a retry reproduces, invariant 5)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-web-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.loreweb import HOLDS, LINK, MENTION, TIE, Edge, edges_of, fact, neighbours   # noqa: E402
from coderain.memory import Entry, Library, MemoryStore                                    # noqa: E402
from coderain.tailties import tail_ties                                                    # noqa: E402

_n = [0]


def story():
    _n[0] += 1
    lib = Library(WORK / f"lib{_n[0]}")
    return lib.store(lib.create_story("Web", "A ferry town."))


def add(store, rel, title, body="", aliases=(), importance=3, **attrs):
    slug = title.lower().replace(" ", "-")
    store.upsert_entry(rel, Entry(title=title, slug=slug, aliases=list(aliases), importance=importance,
                                  attrs={k: v for k, v in attrs.items() if v}, body=body or f"{title} of the ferry town."))
    return slug


def entries(store):
    return {e.slug: e for rel in store.gated_registries() for e in store.entries(rel)}


def town(store):
    add(store, "characters.md", "Hollis Wren", relationships="ottoline-pike: his sister")
    add(store, "characters.md", "Ottoline Pike")
    add(store, "characters.md", "Maribel Voss", relationships="hollis-wren: owes him money")
    add(store, "items.md", "Brass lamp key", holder="Hollis Wren")                       # a name, not a slug
    add(store, "locations.md", "Brinewick", "A tidal town.")
    add(store, "factions.md", "Tide Guild", "They meet in [[brinewick]] on feast days.", links="hollis-wren")


def prompt(store, action, **kw):
    return "\n".join(str(m["content"]) for m in store.assemble([], action, **kw))


def linked(text):
    if "Linked to what is in play" not in text:
        return []
    rest = text.split("Linked to what is in play", 1)[1].split("\n", 1)[1]
    return [ln for ln in rest.split("\n\n")[0].splitlines() if ln.strip()]


def test_edges():
    store = story()
    town(store)
    add(store, "characters.md", "Loner Jay", "He talks about [[loner-jay]] and [[nobody-here]].", relationships="loner-jay: himself; ghost: x",
        holder="no-such-person", links="missing-thing")
    add(store, "characters.md", "Both Ways", "Of [[ottoline-pike]] and [[brinewick]].", relationships="ottoline-pike: friend")
    got = set(edges_of(entries(store)))
    want = {Edge("hollis-wren", "ottoline-pike", TIE, "his sister"), Edge("maribel-voss", "hollis-wren", TIE, "owes him money"),
            Edge("brass-lamp-key", "hollis-wren", HOLDS), Edge("tide-guild", "hollis-wren", LINK), Edge("tide-guild", "brinewick", MENTION),
            Edge("both-ways", "ottoline-pike", TIE, "friend"), Edge("both-ways", "brinewick", MENTION)}
    assert got == want, (sorted(got - want, key=str), sorted(want - got, key=str))
    print("1. holders, ties, links and mentions become edges; unknown names, self-edges and a mention beside a tie do not")


def test_neighbours_and_facts():
    store = story()
    town(store)
    by = entries(store)
    web = edges_of(by)
    got = [(e.kind, other, out) for e, other, out in neighbours("hollis-wren", web)]
    assert got == [(TIE, "ottoline-pike", True), (HOLDS, "brass-lamp-key", False), (TIE, "maribel-voss", False),
                   (LINK, "tide-guild", False)], got
    assert [other for _e, other, _o in neighbours("brinewick", web)] == [], "a mention was walked"
    assert [other for _e, other, _o in neighbours("brinewick", web, (MENTION,))] == ["tide-guild"]
    said = [fact(e, by) for e, _other, _out in neighbours("hollis-wren", web)]
    assert said == ["Hollis Wren is tied to Ottoline Pike (his sister)", "Brass lamp key is held by Hollis Wren",
                    "Maribel Voss is tied to Hollis Wren (owes him money)", "Tide Guild is linked to Hollis Wren"], said
    print("2. both directions, what the entry states first; a mention only when asked for")
    print("3. every fact is said in the direction its file states it")


def test_backwards():
    store = story()
    town(store)
    lines = linked(prompt(store, "I greet Hollis Wren.", follow_links=True))
    names = [ln.split(" (")[0] for ln in lines]
    assert names == ["Ottoline Pike", "Brass lamp key", "Maribel Voss", "Tide Guild"], names
    assert "Brass lamp key is held by Hollis Wren" in lines[1], lines[1]
    assert "Maribel Voss is tied to Hollis Wren (owes him money)" in lines[2], lines[2]
    assert lines[2].count("owes him money") == 1, "the fact is said twice on one line: " + lines[2]
    assert "Tide Guild is linked to Hollis Wren" in lines[3], lines[3]
    assert linked(prompt(store, "I greet Hollis Wren.", follow_links=False)) == []
    print("4. naming a holder brings what they hold, and whoever states a tie or link to them, each with the fact")


def test_secrets():
    store = story()
    add(store, "characters.md", "Ada Fenn")
    add(store, "characters.md", "The Patron", "Secretly pays the guards.", relationships="ada-fenn: her secret father", hidden="true")
    text = prompt(store, "I greet Ada Fenn.", follow_links=True)
    assert "The Patron" not in text and "secret father" not in text and linked(text) == [], text
    store2 = story()
    add(store2, "characters.md", "Bram Holt", relationships="cy-marsh: his partner")
    add(store2, "characters.md", "Cy Marsh", relationships="the-patron: takes his orders; dov-ash: his cousin")
    add(store2, "characters.md", "The Patron", "Secretly pays the guards.", hidden="true")
    add(store2, "characters.md", "Dov Ash")
    lines = linked(prompt(store2, "I greet Bram Holt.", follow_links=True))
    assert len(lines) == 1 and lines[0].startswith("Cy Marsh"), lines
    assert "Patron" not in lines[0] and "takes his orders" not in lines[0], "a followed line gave a secret away: " + lines[0]
    assert "Dov Ash (dov-ash): his cousin" in lines[0], "the visible tie was lost too: " + lines[0]
    print("5. a hidden entry is never pulled in by what it points at, and no linked line names a hidden entry")


def test_gates_backwards():
    for gate in ({"chance": "0"}, {"delay": "500"}, {"triggers_not": "greet"}):
        store = story()
        add(store, "characters.md", "Ada Fenn")
        add(store, "characters.md", "Bea Lorne", relationships="ada-fenn: her friend", **gate)
        text = prompt(store, "I greet Ada Fenn.", follow_links=True)
        assert linked(text) == [] and "Bea Lorne" not in text, (gate, text)
    print("6. chance 0, an unmet delay and a matching triggers_not keep an entry out when walked backwards")


def test_mentions_not_followed():
    store = story()
    add(store, "locations.md", "Brinewick", "A tidal town.")
    for i in range(6):
        add(store, "characters.md", f"Local {i}", "Born in [[brinewick]].")
    text = prompt(store, "I walk into Brinewick.", follow_links=True)
    assert linked(text) == [] and "Local 3" not in text, text
    print("7. a mention is never followed back: naming the town does not bring the people who mention it")


def test_boost():
    store = story()
    add(store, "characters.md", "Dov Ash", "He heard of [[ada-fenn]].")      # first in the file, joined only by a mention
    add(store, "characters.md", "Ada Fenn")
    add(store, "characters.md", "Bea Lorne", relationships="ada-fenn: her friend")
    ask = "Dov Ash, Ada Fenn and Bea Lorne argue."

    def order(text):
        marks = {n: text.index(f"## {n}  {{#") for n in ("Dov Ash", "Ada Fenn", "Bea Lorne")}
        return sorted(marks, key=marks.get)
    assert order(prompt(store, ask)) == ["Dov Ash", "Ada Fenn", "Bea Lorne"], "the control proves nothing"
    assert order(prompt(store, ask, follow_links=True)) == ["Ada Fenn", "Bea Lorne", "Dov Ash"], "the joined pair did not rise"
    # the arithmetic, called directly: an always-on candidate counts as active, and its score is left alone
    add(store, "characters.md", "Cass Reed")
    add(store, "characters.md", "Pin Vale", pinned="true", links="cass-reed")
    from coderain.memory import _Assembly
    by_slug = {e.slug: ("characters.md", e) for e in store.entries("characters.md")}
    a = _Assembly(history=[], player_input="", scenes_tail=4, budget_tokens=8000)
    cands = [(3.0, "characters.md", by_slug[s][1]) for s in ("cass-reed", "ada-fenn", "bea-lorne", "dov-ash")]
    cands.append((103.0, "characters.md", by_slug["pin-vale"][1]))
    got = {e.slug: score for score, _rel, e in store._boost_connected(a, cands, by_slug)}
    assert got["ada-fenn"] == got["bea-lorne"] == 3.0 * MemoryStore.LINK_BOOST, got
    assert got["dov-ash"] == 3.0, "a mention counted as a connection: " + str(got)
    assert got["pin-vale"] == 103.0, "the boost touched an always-on entry: " + str(got)
    assert got["cass-reed"] == 3.0 * MemoryStore.LINK_BOOST, "an always-on entry linking to a candidate did not count"
    assert 10 * MemoryStore.LINK_BOOST < 100
    print("8. joined candidates rank higher; a mention does not count; always-on scores are untouched and no boost reaches 100")


def test_ties_line_backwards():
    store = story()
    town(store)
    line = tail_ties(store, "I ask Hollis Wren about it.", 3)
    assert "Brass lamp key is held by Hollis Wren" in line and "Maribel Voss is tied to Hollis Wren (owes him money)" in line, line
    assert line.index("Hollis Wren is tied to Ottoline Pike") < line.index("Brass lamp key"), "what the entry states comes first: " + line
    print("9. the ties line says a holder or a tie whichever end was named, what the named entry states first")


def test_same_turn_same_web():
    store = story()
    town(store)
    assert prompt(store, "I greet Hollis Wren.", follow_links=True) == prompt(store, "I greet Hollis Wren.", follow_links=True)
    print("10. the same turn walks the same web")


test_edges()
test_neighbours_and_facts()
test_backwards()
test_secrets()
test_gates_backwards()
test_mentions_not_followed()
test_boost()
test_ties_line_backwards()
test_same_turn_same_web()
print("\nLORE WEB TESTS PASSED")
