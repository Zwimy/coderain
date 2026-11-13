"""One name is one entry: the fold must not write a second entry for someone who already has one.

What broke. The fold trusted the `slug` the lore-keeper model wrote and deduped by slug alone. A small
local model does not reuse the slug it was shown. In a plain invented 240-turn story played through
gemma3:4b it wrote `bram-halloran-4` and `bram-halloran-bram-halloran` for the existing `bram-halloran`,
and each became a second entry: characters.md grew from 6 sections to 16 (plus two invented people), the
canon ledger from 6 characters to 15, and a name two entries answer to cannot be attributed to either, so
most facts about those people were refused. The same fold also let aliases pile up by case variants and
run-on repeats until one line held 400+ characters. Both happened with canon switched off.

  1. a new slug for an existing TITLE merges into that entry (no second entry, body replaced)
  2. the two shapes seen live (a doubled slug and a numbered one) both merge
  3. case, punctuation and a leading "the" do not make a different name
  4. a different whole name never merges: "Tamsin Pike" is not "Tamsin Reeve"
  5. a title that is merely listed as another entry's alias is NOT a match: small models write wrong aliases
  6. a slug that already exists is used as written, as before
  7. with duplicates already present, the entry made under the name's own slug wins
  8. threads and canon events are untouched (two events can share a title)
  9. new aliases are cleaned: repeats, run-ons and a word said twice are refused
 10. merge_entry unions aliases without case variants and stops at the cap without shrinking old entries
 11. the merge is reported in the fold's events, not silent
 12. a duplicate inside the same fold merges into the entry the fold wrote a moment before
 13. another entry's name (or slug) is never written as this entry's alias, in a new entry or a
     merge; the same words in a different registry, and a real nickname, are still accepted.
     (A soak save had one character's slug as another's alias: the exact name then matched two
     entities and every claim about the real owner was refused, D-039.)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-resolve-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.memory import (MAX_ALIASES, Entry, Library, name_key,        # noqa: E402
                             usable_alias)
from coderain.summarizer import Summarizer                                   # noqa: E402


class _Cfg:
    memory: dict = {}


_n = [0]


def fresh():
    _n[0] += 1
    lib = Library(WORK / f"lib{_n[0]}")
    store = lib.store(lib.create_story("Resolve", "A ferry town."))
    return store, Summarizer(_Cfg(), store, None, None)


def tamsin(store, **kw):
    store.upsert_entry("characters.md", Entry(
        title="Tamsin Reeve", slug="tamsin-reeve", aliases=kw.get("aliases", ["Tamsin"]),
        importance=3, attrs={}, body="The ferrywoman."))


def promo(slug, title, detail="A newer sheet.", kind="character", **kw):
    return {"kind": kind, "slug": slug, "title": title, "detail": detail, **kw}


def slugs(store, rel="characters.md"):
    return [e.slug for e in store.entries(rel)]


def test_same_title_new_slug_merges():
    """1."""
    store, s = fresh()
    tamsin(store)
    s._apply_promotions({"promotions": [promo("tamsin-reeve-7", "Tamsin Reeve", "Newer detail.")]})
    es = store.entries("characters.md")
    assert [e.slug for e in es] == ["tamsin-reeve"], [e.slug for e in es]
    assert es[0].body.strip() == "Newer detail.", es[0].body
    print("1. a new slug for an existing title merges into the existing entry")


def test_the_two_live_shapes():
    """2."""
    store, s = fresh()
    tamsin(store)
    s._apply_promotions({"promotions": [promo("tamsin-reeve-tamsin-reeve", "Tamsin Reeve"),
                                        promo("tamsin-reeve-4", "Tamsin Reeve")]})
    assert slugs(store) == ["tamsin-reeve"], slugs(store)
    print("2. a doubled slug and a numbered slug both merge")


def test_name_key_ignores_case_punctuation_and_the():
    """3."""
    store, s = fresh()
    store.upsert_entry("locations.md", Entry(title="The Salt Market", slug="the-salt-market", aliases=[],
                                             importance=3, attrs={}, body="A market."))
    s._apply_promotions({"promotions": [promo("salt-market-2", "salt  MARKET", kind="location"),
                                        promo("salt-market-3", "Salt-Market", kind="location")]})
    assert slugs(store, "locations.md") == ["the-salt-market"], slugs(store, "locations.md")
    assert name_key("The Salt Market") == name_key("salt-market") == "salt market"
    assert name_key("The") == "the", "a lone 'the' is a name, not an article"
    print("3. case, punctuation and a leading 'the' do not make a different name")


def test_a_different_name_is_a_different_entry():
    """4. the over-merge guard: the first name alone is not the name."""
    store, s = fresh()
    tamsin(store, aliases=[])                       # no alias "Tamsin": a bare first name is not the name
    s._apply_promotions({"promotions": [promo("tamsin-pike", "Tamsin Pike", "Someone else."),
                                        promo("tamsin", "Tamsin", "A bare first name.")]})
    assert slugs(store) == ["tamsin-reeve", "tamsin-pike", "tamsin"], slugs(store)
    print("4. a different whole name, or a bare first name, stays its own entry")


def test_an_alias_is_not_a_match():
    """5. A dry run on a soak save had one character's name written into another's alias list. If an
    alias counted, the second character's first promotion would be folded into the first."""
    store, s = fresh()
    tamsin(store, aliases=["Tamsin", "the ferrywoman", "Hob Marrow"])          # the last one is the model's mistake
    s._apply_promotions({"promotions": [promo("ferrywoman", "The Ferrywoman", "By her job."),
                                        promo("hob-marrow", "Hob Marrow", "A different man."),
                                        promo("tamsin", "Tamsin", "A bare first name.")]})
    assert slugs(store) == ["tamsin-reeve", "ferrywoman", "hob-marrow", "tamsin"], slugs(store)
    print("5. a title that is only listed as another entry's alias makes its own entry")


def test_an_existing_slug_is_used_as_written():
    """6. unchanged behaviour: the slug wins even when the title differs."""
    store, s = fresh()
    tamsin(store)
    s._apply_promotions({"promotions": [promo("tamsin-reeve", "Some Other Title", "Rewritten.")]})
    es = store.entries("characters.md")
    assert [e.slug for e in es] == ["tamsin-reeve"] and es[0].body.strip() == "Rewritten."
    assert es[0].title == "Tamsin Reeve", "the existing title is kept"
    # the slug names one entry and the title another: the slug wins, as it always did
    store2, s2 = fresh()
    tamsin(store2)
    store2.upsert_entry("characters.md", Entry(title="Hob Marrow", slug="hob-marrow", aliases=[],
                                               importance=3, attrs={}, body="The tavern keeper."))
    s2._apply_promotions({"promotions": [promo("hob-marrow", "Tamsin Reeve", "Written to the slug.")]})
    by = {e.slug: e.body.strip() for e in store2.entries("characters.md")}
    assert by == {"tamsin-reeve": "The ferrywoman.", "hob-marrow": "Written to the slug."}, by
    print("6. an existing slug is used as written")


def test_duplicates_already_present_prefer_the_entry_under_its_own_slug():
    """7."""
    store, s = fresh()
    store.upsert_entry("characters.md", Entry(title="Tamsin Reeve", slug="tamsin-reeve-4", aliases=[],
                                              importance=3, attrs={}, body="The numbered copy."))
    tamsin(store)
    store.upsert_entry("characters.md", Entry(title="Tamsin Reeve", slug="tamsin-reeve-tamsin-reeve",
                                              aliases=[], importance=3, attrs={}, body="The doubled copy."))
    s._apply_promotions({"promotions": [promo("tamsin-9", "Tamsin Reeve", "Newest.")]})
    bodies = {e.slug: e.body.strip() for e in store.entries("characters.md")}
    assert bodies["tamsin-reeve"] == "Newest." and len(bodies) == 3, bodies
    print("7. with duplicates present, the entry under its own slug takes the update")


def test_threads_and_events_are_untouched():
    """8."""
    store, s = fresh()
    s._apply_promotions({"promotions": [promo("the-duel", "The Duel", "First.", kind="canon-event"),
                                        promo("the-duel-2", "The Duel", "Second.", kind="canon-event")]})
    assert slugs(store, "canon-events.md") == ["the-duel", "the-duel-2"], slugs(store, "canon-events.md")
    print("8. canon events that share a title stay separate")


def test_new_aliases_are_cleaned():
    """9."""
    store, s = fresh()
    s._apply_promotions({"promotions": [promo(
        "tamsin-reeve", "Tamsin Reeve",
        aliases=["Tamsin", "tamsin", "Tamsin Reeve", "reeve reeve the ferrywoman reeve",
                 "the ferrywoman", "b c d e f g", "", "Ferrywoman"])]})
    got = store.entries("characters.md")[0].aliases
    assert got == ["Tamsin", "the ferrywoman"], got
    assert usable_alias("Old Hob", set()) and not usable_alias("Hob Hob", set())
    assert usable_alias("The Old Man of the Sea", set()), "'the' and 'of' may repeat, they are filler"
    print("9. repeats, run-ons and a word said twice are refused as aliases")


def test_union_dedupes_and_caps_without_shrinking():
    """10."""
    store, _s = fresh()
    old = [f"nick{n}" for n in range(MAX_ALIASES - 1)]
    store.upsert_entry("characters.md", Entry(title="Tamsin Reeve", slug="tamsin-reeve", aliases=old,
                                              importance=3, attrs={}, body="x"))
    store.merge_entry("characters.md", Entry(title="Tamsin Reeve", slug="tamsin-reeve",
                                             aliases=["NICK0", "fresh one", "fresh two", "fresh three"],
                                             importance=3, attrs={}, body="y"), rewrite=True)
    got = store.entries("characters.md")[0].aliases
    assert len(got) == MAX_ALIASES and "NICK0" not in got and "fresh one" in got and "fresh two" not in got, got
    big = [f"w{n}x" for n in range(MAX_ALIASES + 5)]
    store.upsert_entry("characters.md", Entry(title="Hob Marrow", slug="hob-marrow", aliases=big,
                                              importance=3, attrs={}, body="x"))
    store.merge_entry("characters.md", Entry(title="Hob Marrow", slug="hob-marrow", aliases=["extra"],
                                             importance=3, attrs={}, body="y"), rewrite=True)
    got2 = [e for e in store.entries("characters.md") if e.slug == "hob-marrow"][0].aliases
    assert got2 == big, "an entry already over the cap keeps what it has and stops growing"
    print("10. aliases are deduped by name, capped, and an old long list is not cut")


def test_the_merge_is_reported():
    """11."""
    store, s = fresh()
    tamsin(store)
    events = s._apply_promotions({"promotions": [promo("tamsin-reeve-7", "Tamsin Reeve")]})
    assert any("already exists" in e and "tamsin-reeve" in e for e in events), events
    print("11. the merge appears in the fold's events")


def test_two_promotions_in_one_fold():
    """12. the second promotion must see the entry the first one just wrote."""
    store, s = fresh()
    s._apply_promotions({"promotions": [promo("tamsin-reeve", "Tamsin Reeve", "First."),
                                        promo("tamsin-reeve-2", "Tamsin Reeve", "Second.")]})
    es = store.entries("characters.md")
    assert [e.slug for e in es] == ["tamsin-reeve"] and es[0].body.strip() == "Second.", [e.slug for e in es]
    print("12. a duplicate inside the same fold merges into the entry made a moment before")


def test_another_entrys_name_is_not_an_alias():
    """13."""
    store, s = fresh()
    tamsin(store)
    store.upsert_entry("characters.md", Entry(title="Ines Bray", slug="ines-bray", aliases=["Ines"],
                                              importance=3, attrs={}, body="The ropewalker."))
    store.upsert_entry("locations.md", Entry(title="Salt Market", slug="salt-market", aliases=[],
                                             importance=3, attrs={}, body="A market."))
    s._apply_promotions({"promotions": [
        promo("ines-bray", "Ines Bray", "Newer.",
              aliases=["tamsin-reeve", "Tamsin Reeve", "the ropewalker", "Salt Market"])]})
    got = [e for e in store.entries("characters.md") if e.slug == "ines-bray"][0].aliases
    assert got == ["Ines", "the ropewalker", "Salt Market"], got   # a merge: the slug and the name are refused
    s._apply_promotions({"promotions": [
        promo("odile-marsh", "Odile Marsh", "New.", aliases=["tamsin-reeve", "Ines-Bray", "the courier"])]})
    new = [e for e in store.entries("characters.md") if e.slug == "odile-marsh"][0].aliases
    assert new == ["the courier"], new                              # a brand-new entry: same rule
    assert slugs(store) == ["tamsin-reeve", "ines-bray", "odile-marsh"], slugs(store)
    print("13. another entry's name or slug is never an alias (merge or new entry); "
          "other registries and real nicknames are unaffected")


for fn in (test_same_title_new_slug_merges, test_the_two_live_shapes,
           test_name_key_ignores_case_punctuation_and_the, test_a_different_name_is_a_different_entry,
           test_an_alias_is_not_a_match, test_an_existing_slug_is_used_as_written,
           test_duplicates_already_present_prefer_the_entry_under_its_own_slug,
           test_threads_and_events_are_untouched, test_new_aliases_are_cleaned,
           test_union_dedupes_and_caps_without_shrinking, test_the_merge_is_reported,
           test_two_promotions_in_one_fold, test_another_entrys_name_is_not_an_alias):
    fn()
print("ALL OK")
