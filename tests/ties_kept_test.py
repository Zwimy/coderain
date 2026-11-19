"""A fold must not forget who a character is tied to (D-059, from the graph probe, D-058).

What broke. A fold hands the lore-keeper model the current entry and keeps whatever it writes back, and
`merge_entry(rewrite=True)` read a missing `relationships:` line as "the story ended these ties" (the
status, when and relationships attrs were "managed"). A small model leaves the line out. In a measured
120-turn story the ties an author had written on six characters reached the Writer's prompt in 2 of 12
questions about them, and the final save held a tie on none of the six, while every item entry (which no
fold rewrites) was intact. The same mechanism drifted a hair colour in the long real story.

  1. a rewrite that leaves the ties out keeps them (the defect, through the real fold door)
  2. a rewrite that restates a tie with a DIFFERENT note does not change the note on file (first write wins). The
     first version let it, and the next real run showed what a small model does with that: "her brother" came
     back as "his sister" (the tie from the other side), two cousins as "counselor", plus a tie nobody planted
  3. a rewrite may add a tie to someone new; the old ties keep their place and wording
  4. a restatement with no note does not wipe the note that was there; a note arrives where there was none
  5. "Hollis Wren" and "hollis-wren" are one tie (keyed by slug); the model's `with` goes through the slug rule
  6. a tie to oneself is refused; a hand-written one already on the line is left alone
  7. MAX_TIES: past it a NEW tie is left out and no old tie is dropped to make room
  8. MAX_TIES_CHARS: a new tie that would not fit is left out; a note given to a tie that had none cannot push a
     line past the bound; a hand-written line already past it is neither cut nor grown
  9. the append door (rewrite=False) keeps ties the same way
 10. no ties anywhere: no empty `relationships:` attr is written
 11. only the ties changed: status and when are still cleared by a rewrite that omits them
 12. an item's `holder:` is kept by a rewrite or a merge that omits it
 13. Entry.relationships() reads ":", "=" and a bare name as it always did
 14. a removed tie stays removed once the file is edited by hand (the file is the truth)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-ties-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.memory import (MAX_TIES, MAX_TIES_CHARS, Entry, Library,        # noqa: E402
                             merge_ties, parse_ties)
from coderain.summarizer import Summarizer                                       # noqa: E402


class _Cfg:
    memory: dict = {}


_n = [0]


def fresh():
    _n[0] += 1
    lib = Library(WORK / f"lib{_n[0]}")
    store = lib.store(lib.create_story("Ties", "A ferry town."))
    return store, Summarizer(_Cfg(), store, None, None)


def hollis(store, ties="ottoline-pike: his sister; corwin-tide: owes him a favour", **attrs):
    store.upsert_entry("characters.md", Entry(
        title="Hollis Wren", slug="hollis-wren", aliases=["Hollis"], importance=3,
        attrs={"status": "alive", "relationships": ties, **attrs}, body="The tavern keeper."))


def ties_of(store, slug="hollis-wren"):
    return [e for e in store.entries("characters.md") if e.slug == slug][0].attrs.get("relationships", "")


def promo(**kw):
    return {"kind": "character", "slug": "hollis-wren", "title": "Hollis Wren", "detail": "A newer sheet.", **kw}


def test_a_rewrite_that_leaves_the_ties_out_keeps_them():
    """1."""
    store, s = fresh()
    hollis(store)
    s._apply_promotions({"promotions": [promo(status="alive")]})
    assert ties_of(store) == "ottoline-pike: his sister; corwin-tide: owes him a favour", ties_of(store)
    s._apply_promotions({"promotions": [promo(status="alive", relationships=[])]})        # an empty list too
    assert ties_of(store) == "ottoline-pike: his sister; corwin-tide: owes him a favour", ties_of(store)
    print("1. a rewrite that leaves the ties out (or sends none) keeps them")


def test_a_restated_note_does_not_replace_the_note():
    """2."""
    store, s = fresh()
    hollis(store)
    s._apply_promotions({"promotions": [promo(relationships=[{"with": "corwin-tide", "note": "forgave the debt"},
                                                             {"with": "ottoline-pike", "note": "counselor"}])]})
    assert ties_of(store) == "ottoline-pike: his sister; corwin-tide: owes him a favour", ties_of(store)
    print("2. a restated tie does not change the note on file; the story's change is an edit of the file")


def test_a_new_tie_is_added_after_the_old_ones():
    """3."""
    store, s = fresh()
    hollis(store)
    s._apply_promotions({"promotions": [promo(relationships=[{"with": "Dessa Quill", "note": "drinks there"}])]})
    assert ties_of(store) == ("ottoline-pike: his sister; corwin-tide: owes him a favour; "
                              "dessa-quill: drinks there"), ties_of(store)
    print("3. a new tie is appended; the old ties keep their order and wording")


def test_an_empty_note_does_not_wipe_a_note():
    """4."""
    assert merge_ties("ottoline-pike: his sister", "ottoline-pike") == "ottoline-pike: his sister"
    assert merge_ties("ottoline-pike: his sister", "ottoline-pike:") == "ottoline-pike: his sister"
    assert merge_ties("ottoline-pike", "ottoline-pike: his sister") == "ottoline-pike: his sister"
    print("4. a restatement with no note keeps the note; a note arrives where there was none")


def test_ties_are_keyed_by_slug():
    """5."""
    assert merge_ties("hollis-wren: his brother", "Hollis Wren: a brother, and a drunk") == "hollis-wren: his brother"
    assert merge_ties("Hollis Wren", "hollis-wren: older") == "Hollis Wren: older", "as written kept, the note given"
    assert merge_ties("", "???: nobody; !!!") == "", "a name that makes no slug is no tie"
    store, s = fresh()
    hollis(store, ties="")
    s._apply_promotions({"promotions": [promo(relationships=[{"with": "Ottoline Pike!", "note": "his sister"}])]})
    assert ties_of(store) == "ottoline-pike: his sister", ties_of(store)
    print("5. one tie per other person, however the name is spelt; the fold's own slug rule still applies")


def test_a_tie_to_oneself():
    """6."""
    assert merge_ties("ottoline-pike: his sister", "hollis-wren: himself; corwin-tide: a debt", own="hollis-wren") == \
        "ottoline-pike: his sister; corwin-tide: a debt"
    assert merge_ties("hollis-wren: written by hand", "", own="hollis-wren") == "hollis-wren: written by hand"
    # through the real door, with nothing else on the line: the refused tie must not be written in its place
    store, s = fresh()
    hollis(store, ties="")
    s._apply_promotions({"promotions": [promo(relationships=[{"with": "Hollis Wren", "note": "himself"}])]})
    assert ties_of(store) == "", ties_of(store)
    print("6. a new tie to the character itself is refused; one already written is left")


def test_the_tie_count_is_bounded():
    """7."""
    old = "; ".join(f"person-{i}: tie {i}" for i in range(MAX_TIES))
    out = merge_ties(old, "newcomer: a new tie")
    assert out == old, "the line is full: the new tie is left out and no old tie is dropped"
    one_short = "; ".join(f"person-{i}: tie {i}" for i in range(MAX_TIES - 1))
    out = merge_ties(one_short, "newcomer: a; second-newcomer: b")
    assert len(parse_ties(out)) == MAX_TIES and "newcomer: a" in out and "second-newcomer" not in out, out
    print(f"7. at most {MAX_TIES} ties; the newest are the ones left out")


def test_the_line_length_is_bounded():
    """8."""
    pad = "x" * 66
    old = "; ".join(f"p{i}: {pad}" for i in range(11))                       # about 790 characters
    assert 0 < MAX_TIES_CHARS - len(old) < 60, len(old)
    out = merge_ties(old, f"newcomer: {pad}")
    assert out == old, "a new tie that would pass the character bound is left out"
    bare = old + "; p11"                                                      # one tie with no note, line still within bound
    assert len(bare) <= MAX_TIES_CHARS, len(bare)
    assert merge_ties(bare, "p11: " + "y" * 200) == bare, "a note given to a bare tie may not grow the line past the bound"
    assert merge_ties(bare, "p11: ok") == bare.replace("p11", "p11: ok"), "a short one fits"
    long_by_hand = "; ".join(f"p{i}: {pad}" for i in range(14)) + "; bare"       # already past the bound, by hand
    assert len(long_by_hand) > MAX_TIES_CHARS
    assert merge_ties(long_by_hand, "") == long_by_hand, "a hand-written line is not cut"
    assert merge_ties(long_by_hand, "bare: a short note") == long_by_hand, "nor grown, even by a short note"
    assert merge_ties(long_by_hand, "bare: " + "z" * 100) == long_by_hand
    print(f"8. a line stays within {MAX_TIES_CHARS} characters unless it was already past it")


def test_the_append_door_keeps_ties_too():
    """9."""
    store, s = fresh()
    hollis(store)
    store.merge_entry("characters.md", Entry(
        title="Hollis Wren", slug="hollis-wren", aliases=[], importance=3,
        attrs={"relationships": "dessa-quill: drinks there"}, body="More detail."))
    assert ties_of(store) == ("ottoline-pike: his sister; corwin-tide: owes him a favour; "
                              "dessa-quill: drinks there"), ties_of(store)
    print("9. the append merge unions ties instead of replacing the line")


def test_no_ties_no_attr():
    """10."""
    store, s = fresh()
    hollis(store, ties="")
    s._apply_promotions({"promotions": [promo()]})
    e = [e for e in store.entries("characters.md") if e.slug == "hollis-wren"][0]
    assert "relationships" not in e.attrs, e.attrs
    assert "relationships:" not in e.render(), e.render()
    print("10. nobody tied to anybody: no empty relationships line")


def test_status_and_when_are_still_cleared():
    """11. only the ties were taken out of the managed keys."""
    store, s = fresh()
    hollis(store, when="Day 2", status="alive")
    s._apply_promotions({"promotions": [promo()]})
    e = [e for e in store.entries("characters.md") if e.slug == "hollis-wren"][0]
    assert "status" not in e.attrs and "when" not in e.attrs, e.attrs
    assert e.attrs.get("relationships"), "and the ties are still there"
    print("11. a rewrite still clears a status and a when it leaves out")


def test_holder_survives():
    """12."""
    store, s = fresh()
    store.upsert_entry("items.md", Entry(title="Brass lamp key", slug="brass-lamp-key", aliases=[], importance=3,
                                         attrs={"holder": "hollis-wren"}, body="A key."))
    s._apply_promotions({"promotions": [{"kind": "item", "slug": "brass-lamp-key", "title": "Brass lamp key",
                                         "detail": "A heavy key, polished."}]})
    store.merge_entry("items.md", Entry(title="Brass lamp key", slug="brass-lamp-key", aliases=[], importance=3,
                                        attrs={}, body="More."))
    e = store.entries("items.md")[0]
    assert e.attrs.get("holder") == "hollis-wren" and e.holder() == "hollis-wren", e.attrs
    assert Entry("K", "k", attrs={"holder": "Hollis Wren"}).holder() == "hollis-wren"
    assert Entry("K", "k").holder() == ""
    print("12. an item's holder is not lost to a rewrite or a merge; a name reads as its slug")


def test_parse_is_unchanged():
    """13."""
    e = Entry("A", "a", attrs={"relationships": "b: ally; c = rival; d; ; e:  spaced out "})
    assert e.relationships() == [("b", "ally"), ("c", "rival"), ("d", ""), ("e", "spaced out")], e.relationships()
    assert Entry("A", "a").relationships() == []
    print("13. Entry.relationships() reads the line as before")


def test_a_doubled_slug_is_the_same_person():
    """15. A real 120-turn story: 8 of the 14 ties the model ADDED were a person's slug written twice
    ("hollis-wren-hollis-wren: her brother"), a copy of the tie already there under a key no entry answers to."""
    assert merge_ties("hollis-wren: her brother", "hollis-wren-hollis-wren: her brother") == "hollis-wren: her brother"
    assert merge_ties("", "dessa-quill-dessa-quill: his cousin") == "dessa-quill: his cousin", "a new one is written as the slug"
    assert merge_ties("", "Hollis Wren Hollis Wren: kin") == "hollis-wren: kin"
    assert merge_ties("", "ada-ada: x") == "ada: x"
    # only an exact doubling collapses
    assert merge_ties("", "hollis-wren-ottoline-pike: x") == "hollis-wren-ottoline-pike: x"
    assert merge_ties("", "mara-mara-fenn: x") == "mara-mara-fenn: x", "an odd number of words is a name"
    assert merge_ties("", "hollis-wren-hollis-pike: x") == "hollis-wren-hollis-pike: x"
    # what is already on the file is never rewritten, doubled or not
    assert merge_ties("hollis-wren-hollis-wren: old copy", "") == "hollis-wren-hollis-wren: old copy"
    both = "hollis-wren: her brother; hollis-wren-hollis-wren: old copy"      # both spellings already on file: both stay
    assert merge_ties(both, "") == both
    # and through the real door
    store, s = fresh()
    hollis(store, ties="ottoline-pike: his sister")
    s._apply_promotions({"promotions": [promo(relationships=[{"with": "ottoline-pike-ottoline-pike", "note": "his sister"},
                                                             {"with": "dessa-quill-dessa-quill", "note": "drinks there"}])]})
    assert ties_of(store) == "ottoline-pike: his sister; dessa-quill: drinks there", ties_of(store)
    print("15. a person's slug written twice is the same person, and what is on file is never rewritten")


def test_a_hand_edit_sticks():
    """14. removing a tie is an edit of the file; the next fold must not bring it back."""
    store, s = fresh()
    hollis(store)
    hollis(store, ties="ottoline-pike: his sister")                       # the author deleted the debt by hand
    s._apply_promotions({"promotions": [promo()]})
    assert ties_of(store) == "ottoline-pike: his sister", ties_of(store)
    print("14. a tie the author removed by hand does not come back")


for fn in (test_a_rewrite_that_leaves_the_ties_out_keeps_them, test_a_restated_note_does_not_replace_the_note,
           test_a_new_tie_is_added_after_the_old_ones, test_an_empty_note_does_not_wipe_a_note,
           test_ties_are_keyed_by_slug, test_a_tie_to_oneself, test_the_tie_count_is_bounded,
           test_the_line_length_is_bounded, test_the_append_door_keeps_ties_too, test_no_ties_no_attr,
           test_status_and_when_are_still_cleared, test_holder_survives, test_parse_is_unchanged,
           test_a_hand_edit_sticks, test_a_doubled_slug_is_the_same_person):
    fn()
print("ALL OK")
