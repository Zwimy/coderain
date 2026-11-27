"""Follow one hop from what activated: an item to its holder, a person to their ties (D-059, from D-058).

What broke. Name-keyed activation finds an entry only when the story names it. "Who is the sister of the person
who carries the brass lamp key" names the key, so the key's entry reached the prompt, and the answer sat one link
away in the holder's `relationships:` line, which never did: in a measured 120-turn story two-hop evidence was in the
Writer's prompt 0 of 10 times, so the question could only be answered by luck. The pass is off by default
(`memory: {follow_links: true}`) until a measured run says it helps.

  1. off: no Linked section and no holder in the prompt (the baseline that the pass has to beat)
  2. an item's `holder:` is followed: the holder's line is in the prompt, with its ties and the other person's name
     beside the slug
  3. a person's ties are followed: naming one person brings the people they are tied to
  4. depth 1: what was followed is not followed again
  5. an entry already in the prompt in full is not repeated as a linked line
  6. a hidden entry is never followed, a secret stays in its own block
  7. the author's gates hold: `chance: 0`, `delay` and `triggers_not` keep an entry out
  8. at most FOLLOW_PER_ENTRY per source and FOLLOW_TOTAL per turn
  9. a holder written as a name or an alias resolves; one that names nobody is ignored; so is a tie to oneself
 10. the player is never followed
 11. the lore budget holds: followed lines are dropped before they push anything else out, and pinned stays in
 12. a [[reference]] or `links:` to a followed entry does not make a second, one-line copy of it
 13. the same story and the same turn follow the same links (a retry reproduces, invariant 5)
 14. the engine reads `memory.follow_links` as on only for the real value true, and passes it to assemble
 15. a followed line is one line, bounded, ties first
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-follow-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.memory import Entry, Library, MemoryStore                         # noqa: E402

_n = [0]


def story():
    _n[0] += 1
    lib = Library(WORK / f"lib{_n[0]}")
    return lib.store(lib.create_story("Follow", "A ferry town."))


def person(store, name, slug, ties="", body="", **attrs):
    a = {"status": "alive", **attrs}
    if ties:
        a["relationships"] = ties
    store.upsert_entry("characters.md", Entry(title=name, slug=slug, aliases=[name.split()[0]], importance=3,
                                              attrs=a, body=body or f"{name} lives in the ferry town."))


def item(store, name, slug, holder, **attrs):
    store.upsert_entry("items.md", Entry(title=name, slug=slug, aliases=[f"the {name.lower()}"], importance=3,
                                         attrs={"holder": holder, **attrs}, body=f"{name}, kept safe."))


def cast(store):
    person(store, "Hollis Wren", "hollis-wren", "ottoline-pike: his sister", "The tavern keeper.")
    person(store, "Ottoline Pike", "ottoline-pike", "hollis-wren: her brother", "The lighthouse keeper.")
    person(store, "Corwin Tide", "corwin-tide", "maribel-voss: owes her money", "The mudlark boy.")
    person(store, "Maribel Voss", "maribel-voss", "corwin-tide: is owed money by him", "The customs officer.")
    item(store, "Brass lamp key", "brass-lamp-key", "hollis-wren")
    item(store, "Salt ledger", "salt-ledger", "corwin-tide")


def prompt(store, action, **kw):
    msgs = store.assemble([], action, **kw)
    return "\n".join(str(m["content"]) for m in msgs)


def linked(text):
    """The Linked section's lines, or [] when there is none."""
    if "Linked to what is in play" not in text:
        return []
    rest = text.split("Linked to what is in play", 1)[1].split("\n", 1)[1]
    return [ln for ln in rest.split("\n\n")[0].splitlines() if ln.strip()]


ASK = "I ask Dessa who is the sister of the person who carries the brass lamp key."


def test_off_is_the_baseline():
    """1."""
    store = story()
    cast(store)
    text = prompt(store, ASK)
    assert "Linked to what is in play" not in text
    assert "Hollis Wren" not in text and "ottoline-pike" not in text, "the holder is not in a prompt that only names the key"
    assert "Brass lamp key" in text, "the item itself is activated by its name, as always"
    assert prompt(store, ASK, follow_links=False) == text
    print("1. off: the key is in the prompt, its holder and the holder's ties are not")


def test_an_item_is_followed_to_its_holder():
    """2."""
    store = story()
    cast(store)
    text = prompt(store, ASK, follow_links=True)
    lines = linked(text)
    assert len(lines) == 1 and lines[0].startswith("Hollis Wren (hollis-wren)"), lines
    assert "Ottoline Pike (ottoline-pike): his sister" in lines[0], lines[0]
    print("2. the key leads to its holder, and to the holder's sister by name and slug")


def test_a_person_is_followed_to_their_ties():
    """3."""
    store = story()
    cast(store)
    lines = linked(prompt(store, "I ask Corwin Tide what he is up to.", follow_links=True))
    assert len(lines) == 1 and lines[0].startswith("Maribel Voss (maribel-voss)"), lines
    assert "Corwin Tide (corwin-tide): is owed money by him" in lines[0], lines[0]
    print("3. naming one person brings the people they are tied to")


def test_one_line_for_two_sources():
    """3b. Two people named, both tied to the same third: that third is one linked line, not two."""
    store = story()
    person(store, "Ada Fenn", "ada-fenn", "cy-marsh: her rival")
    person(store, "Bea Lorne", "bea-lorne", "cy-marsh: her cousin")
    person(store, "Cy Marsh", "cy-marsh")
    lines = linked(prompt(store, "Ada Fenn and Bea Lorne argue.", follow_links=True))
    assert len(lines) == 1 and lines[0].startswith("Cy Marsh"), lines
    print("3b. a person tied to two of the people in play is linked once")


def test_depth_one():
    """4. A names B, B names C: B is linked, C is not."""
    store = story()
    person(store, "Ada Fenn", "ada-fenn", "bea-lorne: her friend")
    person(store, "Bea Lorne", "bea-lorne", "cy-marsh: her rival")
    person(store, "Cy Marsh", "cy-marsh", "ada-fenn: owes him")
    lines = linked(prompt(store, "I greet Ada Fenn.", follow_links=True))
    assert [ln.split(" (")[0] for ln in lines] == ["Bea Lorne"], lines
    assert "Cy Marsh" in lines[0], "Bea's own tie is shown as text on her line"
    assert not any(ln.startswith("Cy Marsh") for ln in lines), lines
    print("4. what was followed is not followed again")


def test_in_the_prompt_already():
    """5. Both named: both are in full, nothing is linked."""
    store = story()
    cast(store)
    text = prompt(store, "Hollis Wren and Ottoline Pike meet.", follow_links=True)
    assert linked(text) == [], linked(text)
    assert text.count("## Hollis Wren") == 1 and text.count("## Ottoline Pike") == 1
    print("5. someone already in the prompt in full is not repeated as a linked line")


def test_hidden_is_never_followed():
    """6."""
    store = story()
    person(store, "Ada Fenn", "ada-fenn", "the-patron: her secret father")
    person(store, "The Patron", "the-patron", "", "Secretly her father.", hidden="true")
    text = prompt(store, "I greet Ada Fenn.", follow_links=True)
    assert "Secretly her father" not in text and "the-patron (" not in text.lower() and linked(text) == [], text
    print("6. a secret is not pulled out of its block by a tie")


def test_the_authors_gates_hold():
    """7."""
    store = story()
    person(store, "Ada Fenn", "ada-fenn", "bea-lorne: a; cy-marsh: b; dov-ash: c")
    person(store, "Bea Lorne", "bea-lorne", "", chance="0")
    person(store, "Cy Marsh", "cy-marsh", "", delay="500")
    person(store, "Dov Ash", "dov-ash", "", triggers_not="greet")
    assert linked(prompt(store, "I greet Ada Fenn.", follow_links=True)) == []
    store2 = story()
    person(store2, "Ada Fenn", "ada-fenn", "dov-ash: c")
    person(store2, "Dov Ash", "dov-ash", "", triggers_not="goodbye")
    assert len(linked(prompt(store2, "I greet Ada Fenn.", follow_links=True))) == 1, "the gate only holds when it matches"
    print("7. chance 0, an unmet delay and a matching triggers_not keep an entry out; a gate that does not match does not")


def test_the_caps():
    """8."""
    store = story()
    names = [f"Pal {c}" for c in "ABCDEFGH"]
    for n in names:
        person(store, n, n.lower().replace(" ", "-"))
    person(store, "Ada Fenn", "ada-fenn", "; ".join(f"{n.lower().replace(' ', '-')}: pal" for n in names))
    lines = linked(prompt(store, "I greet Ada Fenn.", follow_links=True))
    assert len(lines) == MemoryStore.FOLLOW_PER_ENTRY, lines
    store2 = story()
    for i in range(4):                                           # four sources, five targets each
        person(store2, f"Src {i}", f"src-{i}", "; ".join(f"t{i}-{j}: tie" for j in range(5)))
        for j in range(5):
            person(store2, f"Tgt {i}x{j}", f"t{i}-{j}")
    lines = linked(prompt(store2, "Src 0, Src 1, Src 2 and Src 3 all talk.", follow_links=True))
    assert len(lines) == MemoryStore.FOLLOW_TOTAL, (len(lines), lines)
    print(f"8. at most {MemoryStore.FOLLOW_PER_ENTRY} per source and {MemoryStore.FOLLOW_TOTAL} a turn")


def test_resolution():
    """9."""
    store = story()
    person(store, "Hollis Wren", "hollis-wren", "ottoline-pike: his sister")
    person(store, "Ottoline Pike", "ottoline-pike")
    item(store, "Brass lamp key", "brass-lamp-key", "Hollis Wren")                    # a name, not a slug
    item(store, "Salt ledger", "salt-ledger", "Hollis")                               # an alias
    item(store, "Customs stamp", "customs-stamp", "nobody-at-all")
    item(store, "Mooring rope", "mooring-rope", "mooring-rope")                       # held by itself
    assert len(linked(prompt(store, "the brass lamp key", follow_links=True))) == 1
    assert len(linked(prompt(store, "the salt ledger", follow_links=True))) == 1
    assert linked(prompt(store, "the customs stamp", follow_links=True)) == []
    assert linked(prompt(store, "the mooring rope", follow_links=True)) == []
    print("9. a holder written as a name or an alias resolves; an unknown holder and a self-tie do nothing")


def test_the_player_is_not_followed():
    """10."""
    store = story()
    me = store.entries("player.md")
    slug = me[0].slug if me else "player"
    person(store, "Ada Fenn", "ada-fenn", f"{slug}: an old friend of yours")
    assert linked(prompt(store, "I greet Ada Fenn.", follow_links=True)) == []
    print("10. the player is already in the prompt and is not followed")


def test_the_budget_holds():
    """11."""
    store = story()
    cast(store)
    store.upsert_entry("characters.md", Entry(title="Dame Pin", slug="dame-pin", aliases=[], importance=5,
                                              attrs={"pinned": "true"}, body="Always here."))
    big = prompt(store, ASK, follow_links=True, budget_tokens=8000)
    assert linked(big)
    small = prompt(store, ASK, follow_links=True, budget_tokens=220)
    assert "Always here." in small, "pinned stays in, whatever the budget"
    # the pass's own arithmetic, called directly: a line is kept when it fits the lore budget exactly, dropped by one character less
    from coderain.memory import _Assembly
    by_slug = {e.slug: (rel, e) for rel in ("characters.md", "items.md") for e in store.entries(rel)}
    key = by_slug["brass-lamp-key"][1]

    def follow(used, budget):
        a = _Assembly(history=[], player_input="", scenes_tail=4, budget_tokens=8000)
        a.matched_slugs = {"brass-lamp-key"}
        got = store._follow_links(a, {"items.md": [key]}, by_slug, 0, used, budget)
        return got, [s for s in a.sections if s[1].startswith("Linked")], a.followed
    size, secs, followed = follow(0, 1e9)
    assert size > 0 and len(secs) == 1 and followed == {"hollis-wren"}, (size, secs, followed)
    assert size == len(secs[0][2]), "the budget is charged for exactly the line that is shown"
    assert secs[0][0] == 2, "linked lines compete with activated lore (priority 2), ahead of the recalled extras (3)"
    assert follow(0, size)[1], "a line that fits exactly is kept"
    assert follow(0, size - 1) == (0, [], set()), "one character over the lore budget and it is dropped, uncharged"
    assert follow(100, 100 + size - 1) == (100, [], set()) and follow(100, 100 + size)[0] == 100 + size, "the budget already used counts"
    print("11. a tight budget drops linked lines before anything else, the arithmetic is exact, and pinned stays in")


def test_no_second_copy():
    """12. `links:` on the item names the holder too: the Referenced block must not print it again."""
    store = story()
    cast(store)
    item(store, "Brass lamp key", "brass-lamp-key", "hollis-wren", links="hollis-wren")
    text = prompt(store, ASK, follow_links=True)
    assert text.count("Hollis Wren (hollis-wren)") == 1, text
    assert "Referenced (by name)" not in text, "the one-line copy of the holder is the old `links:` block, now redundant"
    off = prompt(store, ASK, follow_links=False)
    assert "Referenced (by name)" in off and "Hollis Wren" in off, "without the pass the old `links:` one-liner is unchanged"
    # and the semantic recall is told not to print it again either
    asked_to_skip = []

    def retriever(haystack, exclude):
        asked_to_skip.append(set(exclude))
        return []
    prompt(store, ASK, follow_links=True, retriever=retriever)
    assert asked_to_skip and all("hollis-wren" in ex for ex in asked_to_skip), asked_to_skip
    print("12. a followed entry is not also listed as a referenced one-liner or recalled again")


def test_same_turn_same_links():
    """13."""
    store = story()
    cast(store)
    a = prompt(store, ASK, follow_links=True)
    b = prompt(store, ASK, follow_links=True)
    assert a == b
    print("13. the same turn follows the same links")


def test_the_engine_switch():
    """14."""
    from coderain.config import load_config
    from coderain.engine import Engine
    seen = []
    for value, want in (("true", True), ('"true"', False), ('"false"', False), ("false", False), (None, False)):
        home = Path(tempfile.mkdtemp(prefix="cr-follow-eng-"))
        cfg = home / "config.yaml"
        cfg.write_text(
            "active_profile: local\nprofiles:\n  local:\n    base_url: http://localhost:9/v1\n    model: stub\n"
            "    api_key_env: OLLAMA_API_KEY\n    context_tokens: 16384\n"
            + ("memory:\n  follow_links: " + value + "\n" if value is not None else ""), encoding="utf-8")
        store = Library(home).store(Library(home).create_story("Eng", "x"))
        eng = Engine(load_config(cfg), store)
        got = []
        # The engine calls assemble_parts (assemble is its first return value, kept for callers that want only the messages),
        # so that is the seam where the flag has to arrive (D-072).
        real = store.assemble_parts
        store.assemble_parts = lambda *a, **k: (got.append(k.get("follow_links")), real(*a, **k))[1]
        eng._messages([], "hello")
        assert eng.follow_links is want and got == [want], (value, eng.follow_links, got)
        seen.append(value)
    print("14. only a real true turns the pass on, and the engine hands it to assemble:", seen)


def test_the_line():
    """15."""
    store = story()
    person(store, "Ada Fenn", "ada-fenn", "bea-lorne: her friend")
    person(store, "Bea Lorne", "bea-lorne", "ada-fenn: " + "very long " * 60, "First line.\nSecond line.",
           status="")
    text = prompt(store, "I greet Ada Fenn.", follow_links=True)
    lines = linked(text)
    assert len(lines) == 1 and "\n" not in lines[0] and len(lines[0]) <= MemoryStore.FOLLOW_LINE, lines
    assert lines[0].startswith("Bea Lorne (bea-lorne). Ties: Ada Fenn (ada-fenn): very long"), lines[0]
    store2 = story()
    person(store2, "Ada Fenn", "ada-fenn", "bea-lorne: her friend")
    person(store2, "Bea Lorne", "bea-lorne", "", "First line.\nSecond line.", status="")
    assert linked(prompt(store2, "I greet Ada Fenn.", follow_links=True))[0] == "Bea Lorne (bea-lorne). First line."
    # a followed person with many ties shows the first few, whole
    store3 = story()
    person(store3, "Ada Fenn", "ada-fenn", "bea-lorne: her friend")
    person(store3, "Bea Lorne", "bea-lorne", "; ".join(f"pal-{i}: tie {i}" for i in range(7)))
    line = linked(prompt(store3, "I greet Ada Fenn.", follow_links=True))[0]
    assert "pal-3: tie 3" in line and "pal-4" not in line, line
    print("15. a followed line is one bounded line, the ties before the description")


for fn in (test_off_is_the_baseline, test_an_item_is_followed_to_its_holder, test_a_person_is_followed_to_their_ties,
           test_one_line_for_two_sources, test_depth_one, test_in_the_prompt_already, test_hidden_is_never_followed, test_the_authors_gates_hold,
           test_the_caps, test_resolution, test_the_player_is_not_followed, test_the_budget_holds,
           test_no_second_copy, test_same_turn_same_links, test_the_engine_switch, test_the_line):
    fn()
print("ALL OK")
