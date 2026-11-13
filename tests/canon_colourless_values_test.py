"""A hair or eye value with no colour in it is weak: the story's first real colour replaces it.

What broke. Identity is first write wins, so the first thing a reader files in a slot locked it. A model reading
narration often files a shade ("dark eyes") or a style ("a tight braid") before the sentence that states the
colour, and the colour was then held back as a contradiction every time the story repeated it: 6 to 33 times in
the same slot on a 161-turn read, and on the owner's real story 2 of the 43 held hair and eye slots (D-041). The
ledger already ranks authorities (inferred < narration < scenario < author) and lets a higher one replace a lower
one, so a colourless hair or eye value is now filed as `inferred` and nothing else about first write wins moves.

 1) a colourless eye value commits to an empty slot, as `inferred`
 2) the first narrated colour replaces it: the old interval is closed, no contradiction is recorded
 3) a colour that is held is NOT replaced by another colour, nor by a later colourless value (a contradiction, as before)
 4) a colourless value does not replace another colourless value (same authority), as before
 5) saying a colourless value again is a restatement: one interval, still `inferred`, one more confirmation
 6) hair works the same way, and a style ("tight braid") is the colourless case there
 7) build, age and marks are untouched: still `narration`
 8) an author's correction still outranks a colourless value, and the colour is replaced by nothing weaker
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-colourless-"))

from canon import Store                                           # noqa: E402
from canon.claims import Claim                                    # noqa: E402
from canon.shape import has_colour                                # noqa: E402
from canon.validate import commit, validate                       # noqa: E402

_n = [0]


def _store():
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for eid, name in (("odile", "Odile Marsh"), ("corin", "Corin Hale")):
        s.append(kind="entity_created", entity=eid, slot="character", value=name,
                 authority="scenario", turn=0, aliases=[])
    return s


def say(s, entity, slot, value, quote, turn):
    d = validate(s.canon, [Claim(entity, slot, "set", value, quote, "high")], quote, turn=turn,
                 next_id=len(s.ledger) + 1, create_unknown=False)
    commit(s, d, record_contradictions=True)
    return d[0]


def ivs(s, eid, slot):
    return s.canon.slots[eid][slot]


def test_a_shade_holds_an_empty_slot_as_inferred():
    s = _store()
    d = say(s, "Odile Marsh", "identity.eyes", "dark", "Odile Marsh's dark eyes narrowed", 1)
    assert d.status == "commit", d
    cur = ivs(s, "odile", "identity.eyes")
    assert len(cur) == 1 and cur[0].value == "dark" and cur[0].authority == "inferred", cur
    print("1. a colourless eye value is filed, as inferred")


def test_the_first_colour_replaces_it():
    s = _store()
    say(s, "Odile Marsh", "identity.eyes", "dark", "Odile Marsh's dark eyes narrowed", 1)
    d = say(s, "Odile Marsh", "identity.eyes", "green", "Odile Marsh's green eyes narrowed", 2)
    assert d.status == "commit", d
    cur = ivs(s, "odile", "identity.eyes")
    assert [(i.value, i.authority, i.end_id is None) for i in cur] == [
        ("dark", "inferred", False), ("green", "narration", True)], cur
    assert s.canon.current("odile", "identity.eyes") == "green"
    assert not s.canon.conflicts, s.canon.conflicts
    print("2. the first narrated colour replaces the shade and records no contradiction")


def test_a_held_colour_is_not_replaced():
    s = _store()
    say(s, "Odile Marsh", "identity.eyes", "green", "Odile Marsh's green eyes narrowed", 1)
    d = say(s, "Odile Marsh", "identity.eyes", "grey", "Odile Marsh's grey eyes narrowed", 2)
    assert d.status == "contradiction", d
    d = say(s, "Odile Marsh", "identity.eyes", "dark", "Odile Marsh's dark eyes narrowed", 3)
    assert d.status == "contradiction", d
    assert s.canon.current("odile", "identity.eyes") == "green"
    assert [i.authority for i in ivs(s, "odile", "identity.eyes")] == ["narration"]
    print("3. a held colour is replaced by neither another colour nor a later shade")


def test_a_colourless_value_does_not_replace_another():
    s = _store()
    say(s, "Odile Marsh", "identity.hair", "tight braid", "Odile Marsh wore her hair in a tight braid", 1)
    d = say(s, "Odile Marsh", "identity.hair", "dark", "Odile Marsh's dark hair was wet", 2)
    assert d.status == "contradiction", d
    assert s.canon.current("odile", "identity.hair") == "tight braid"
    print("4. one colourless value does not replace another (same authority)")


def test_saying_it_again_is_a_restatement():
    s = _store()
    say(s, "Odile Marsh", "identity.eyes", "dark", "Odile Marsh's dark eyes narrowed", 1)
    say(s, "Odile Marsh", "identity.eyes", "dark", "Odile Marsh's dark eyes narrowed again", 2)
    cur = ivs(s, "odile", "identity.eyes")
    assert len(cur) == 1 and cur[0].authority == "inferred" and cur[0].confirmations == 2, cur
    print("5. a colourless value said again is a restatement, not a second interval")


def test_hair_and_a_style():
    s = _store()
    say(s, "Odile Marsh", "identity.hair", "tight braid", "Odile Marsh wore her hair in a tight braid", 1)
    assert ivs(s, "odile", "identity.hair")[-1].authority == "inferred"
    d = say(s, "Odile Marsh", "identity.hair", "raven", "Odile Marsh's raven hair was wet", 2)
    assert d.status == "commit" and s.canon.current("odile", "identity.hair") == "raven", d
    assert not s.canon.conflicts
    t = _store()
    say(t, "Odile Marsh", "identity.hair", "raven", "Odile Marsh's raven hair was wet", 1)
    d = say(t, "Odile Marsh", "identity.hair", "platinum", "Odile Marsh's platinum hair was wet", 2)
    assert d.status == "contradiction" and t.canon.current("odile", "identity.hair") == "raven", d
    print("6. a style is replaced by the first colour; a colour still wins against drift (raven stays raven)")


def test_other_slots_are_untouched():
    s = _store()
    say(s, "Corin Hale", "identity.build", "stout", "Corin Hale's stout frame filled the doorway", 1)
    assert ivs(s, "corin", "identity.build")[-1].authority == "narration"
    say(s, "Corin Hale", "identity.marks", "scar", "Corin Hale's scar pulled when he smiled", 2)
    marks = [k for k in s.canon.slots["corin"] if k.startswith("identity.marks")]
    assert marks and all(ivs(s, "corin", k)[-1].authority == "narration" for k in marks), marks
    print("7. build and marks keep narration authority")


def test_author_still_outranks():
    s = _store()
    say(s, "Odile Marsh", "identity.eyes", "dark", "Odile Marsh's dark eyes narrowed", 1)
    s.append(kind="author_edit", entity="odile", slot="identity.eyes", value="amber", authority="author", turn=2)
    assert s.canon.current("odile", "identity.eyes") == "amber"
    d = say(s, "Odile Marsh", "identity.eyes", "green", "Odile Marsh's green eyes narrowed", 3)
    assert d.status == "contradiction" and s.canon.current("odile", "identity.eyes") == "amber", d
    assert has_colour("pale grey-blue") and has_colour("raven") and not has_colour("dark")
    assert not has_colour("elaborate braids") and not has_colour("tight braid")
    print("8. an author's value still outranks the story; has_colour tells a colour from a shade and a style")


try:
    for fn in (test_a_shade_holds_an_empty_slot_as_inferred, test_the_first_colour_replaces_it,
               test_a_held_colour_is_not_replaced, test_a_colourless_value_does_not_replace_another,
               test_saying_it_again_is_a_restatement, test_hair_and_a_style,
               test_other_slots_are_untouched, test_author_still_outranks):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON COLOURLESS VALUES TESTS PASSED")
