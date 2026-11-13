"""A wrong first identity value locks the slot for good (D-022).

Identity is first write wins: the first value a slot gets is defended against every
later one. The real-save gate found the Scribe's first value was often about
something else: a tattoo colour filed as hair, "her violet eyes" filed as hair, a
string of green beads filed as hair, an expression ("dark, sharp, utterly
unimpressed") filed as an eye colour. The right value was narrated many times
afterwards and was held back every time. Worse, the restatement logic then counted
"the thin black fabric of her glove" as a second sighting of black hair.

canon/shape.py refuses a claim whose quote does not describe the slot, before the
restatement rewrite. These sentences are invented, built on the same shapes.

 1) hair and eyes: the slot's noun must be in the quote and the value attached to it
 2) neighbouring features: each colour goes to its own noun, in both orders
 3) an ornament, a tattoo, an expression or a passing condition is not the trait
 4) post-nominal values ("hair was iron grey", "eyes, green like yours") are kept,
    and a run does not leak across a noun ("hair, pale skin")
 5) a hair style may take one word the vocabulary does not know ("tactical crop")
 6) build must touch the body or the person ("lean frame", "she's tall"), not a
    window, a stride or a verb ("she leans in")
 7) age must be an age: years old, a decade, a bare number only when the quote says
    age, never a measurement or a duration
 8) slots it has no rule for (location, mood) are not its business
 9) in the validator: a misfiled claim is rejected and writes nothing; the right
    value is then the first write; a misfit is never counted as a confirmation
10) one quote filed under two people waits for both; under one person it commits;
    state slots are not subject to it, and an unnamed third claimant is rejected
    for that reason, not parked

Added with D-026. The second real-save gate held 87 marks and 54 of them were not marks
(a way of gripping, a figure of speech, an object), and two eye colours were "cold" and
"wild". A mark never ages off the card, so each would have been shown for good.

11) a mark names a mark (a scar, tattoo, ink, piercing, birthmark); a word that is only
    sometimes one ("mark", "line", "scale", "brand") or an adjective ("scarred") needs
    a body part in the value or the quote
12) eyes need a colour or a shade of one; the rule does not reach hair
9c) in the validator: a non-mark and a modifier for eyes write nothing, and the real
    values that follow are the first write with no conflict
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-shape-"))

from canon import Store, shape                                         # noqa: E402
from canon.claims import Claim                                         # noqa: E402
from canon.validate import commit, validate                            # noqa: E402

HAIR, EYES, BUILD, AGE = "identity.hair", "identity.eyes", "identity.build", "identity.age"
NOUN, ATTACH = "slot_not_in_evidence", "value_not_on_slot"


def check(rows):
    for slot, value, quote, want in rows:
        got = shape.problem(slot, value, quote)
        assert got == want, (slot, value, quote, "expected", want, "got", got)


def test_hair_and_eyes_need_their_noun_and_the_value_on_it():
    check([
        (HAIR, "raven", "Her waist-length raven hair swayed.", None),
        (EYES, "green", "his green eyes sharp and assessing", None),
        (HAIR, "silver-haired", "the silver-haired courier", None),
        (HAIR, "anchor ink", "His anchor ink faded under the shirt sleeve.", NOUN),
        (HAIR, "violet", "Her violet eyes locked onto his.", NOUN),
        (EYES, "indigo", "an indigo tattoo ran along her ribs", NOUN),
        (EYES, "amber", "the amber eye above the cage door rotated", NOUN),   # one eye is a lens
        (HAIR, "her", "her hair", ATTACH),                                  # names no trait
    ])
    print("1. hair and eyes need their own noun in the quote and the value attached to it")


def test_each_colour_goes_to_its_own_noun():
    q = "She had platinum hair, violet eyes, and a bored look."
    check([(HAIR, "platinum", q, None), (EYES, "violet", q, None),
           (HAIR, "violet", q, ATTACH), (EYES, "platinum", q, ATTACH)])
    q = "green eyes and raven hair"
    check([(EYES, "green", q, None), (HAIR, "raven", q, None),
           (HAIR, "green", q, ATTACH), (EYES, "raven", q, ATTACH)])
    print("2. in 'platinum hair, violet eyes' and 'green eyes and raven hair' each colour "
          "goes to its own noun, in both orders")


def test_ornaments_tattoos_expressions_and_conditions_are_not_the_trait():
    check([
        (HAIR, "green beads", "green beads clicked softly in her hair", ATTACH),
        (HAIR, "dark", "the dark coat hid her hair", ATTACH),
        (HAIR, "damp", "Her hair is still damp.", ATTACH),                 # a condition of the moment
        (EYES, "wide", "Her eyes widened.", ATTACH),
        (EYES, "dark, sharp, utterly unimpressed",
         "Her eyes, dark, sharp, utterly unimpressed by the show, raked the room.", ATTACH),
        (EYES, "locked on it", "Her eyes are locked on it.", ATTACH),
    ])
    print("3. an ornament, a coat, a damp head, a stare and an expression are refused")


def test_value_after_the_noun_is_kept_and_does_not_leak():
    check([
        (HAIR, "iron grey", "Corin's hair was iron grey; Ansel's was straw.", None),
        (HAIR, "red and gold", "her red and gold hair", None),              # "and" does not end a run
        (EYES, "pale gray, almost silver", "Her eyes - pale gray, almost silver - flicked away.", None),
        (EYES, "green", "His eyes, green like yours, but older, harder.", None),
        (EYES, "pale blue", "Tamsin's eyes were a pale blue.", None),
        # the run after "hair" goes on to the next noun, so it is that noun's
        (HAIR, "pale", "She had dark hair, pale skin and a scar.", ATTACH),
        (HAIR, "dark", "She had dark hair, pale skin and a scar.", None),
        (HAIR, "dark", "the dark coat, her hair", ATTACH),
    ])
    print("4. 'hair was iron grey', 'eyes, pale gray, flicked' and 'eyes, green like yours' "
          "are kept; 'hair, pale skin' gives the pale to the skin")


def test_a_free_adjective_before_a_shade_noun_is_part_of_the_phrase():
    """13. D-042: "Her eyes are an unnerving shade of grey" was refused (value_not_on_slot) because the
    free adjective between "an" and "shade" is not on any list. Both readers on a 161-turn transcript
    proposed the clean value for it and 13 and 8 distinct claims were refused; it is how narration says it."""
    check([
        (EYES, "grey", "Her eyes are an unnerving shade of grey", None),
        (EYES, "grey", "his eyes, a startling shade of grey, held hers", None),
        (EYES, "grey-blue", "Her eyes are a startling shade of grey-blue", None),
        (HAIR, "auburn", "Her hair is a surprising shade of auburn", None),
        (EYES, "green", "Odile's eyes were an unusual colour, a deep green", None),          # unchanged
        (EYES, "pale grey", "Her eyes are a pale shade of grey", None),                       # a modifier stays part of the value
        (EYES, "pale", "Her eyes are a pale shade of grey", None),
        # what must still be refused
        (EYES, "grey", "Her eyes are startling shade of grey", ATTACH),                       # an article is required
        (EYES, "grey", "Her eyes are a startling mess of grey", ATTACH),                      # only a shade noun counts
        (EYES, "pale grey", "Her eyes are a strange, very pale grey", ATTACH),                # the free word needs a shade noun after it
        (EYES, "grey", "Her eyes widened at an unusual shade of grey on the wall", ATTACH),   # a verb ends the phrase
        (EYES, "unnerving", "Her eyes are an unnerving shade of grey", ATTACH),              # the free word is not the value
        (EYES, "grey", "The harbour was an unusual shade of grey", NOUN),                     # no eyes in the quote
    ])
    print("13. 'an unnerving shade of grey' is the eyes' grey; no article, no shade noun, a verb in between, "
          "or the adjective as the value is still refused")


def test_a_hair_style_takes_one_unlisted_word():
    check([
        (HAIR, "tactical crop", "judging by the tactical crop of her hair", None),
        (HAIR, "severe bob", "black hair cut in a severe bob", None),
        (HAIR, "bob", "She wore a bob.", None),
        (HAIR, "bun", "Her hair was in a bun.", None),
        (HAIR, "bun", "Her hair was loose.", ATTACH),                    # the style word must be in the quote
        (HAIR, "crop", "a crop top and jeans", NOUN),                    # a garment, not a haircut
    ])
    print("5. a style noun takes one word the vocabulary does not know (tactical crop)")


def test_build_must_touch_the_body_or_the_person():
    check([
        (BUILD, "tall", "She's tall, but you have six inches on her.", None),
        (BUILD, "lean frame", "the fabric clinging to her lean frame", None),
        (BUILD, "big woman", "a big woman with a sour look", None),
        (BUILD, "lean and scarred", "her body lean and scarred", None),
        (BUILD, "broad shoulders", "her broad swimmer's shoulders squared", None),
        (BUILD, "small and high", "the windows are small and high", ATTACH),
        (BUILD, "rangy", "that same rangy, effortless stride", ATTACH),
        (BUILD, "lean", "she lean in close to listen", ATTACH),             # a verb
        (BUILD, "knees", "Her knees pressed together.", ATTACH),
        (BUILD, "lean", "They're lean and hard-eyed.", None),             # "they're" keeps its subject
        (BUILD, "tall", "You're tall for this.", None),
    ])
    print("6. a build word must touch the body or the person; a window, a stride, a knee and a "
          "verb do not count")


def test_age_must_be_an_age():
    check([
        (AGE, "twenty-two years old", "She's twenty-two years old.", None),
        (AGE, "early twenties", "She's young, early twenties.", None),
        (AGE, "mid-twenties", "a face younger than the voice, mid-twenties, maybe", None),
        (AGE, "nineteen", "She's young. Nineteen, I think?", None),
        (AGE, "thirty-something", "a thirty-something dockworker", None),
        (AGE, "nineteen", "Nineteen steps led down.", ATTACH),             # a number with no age cue
        (AGE, "twenty-three", "The home side won twenty-three to nothing.", ATTACH),  # a score
        (AGE, "twelve years", "I have spent twelve years in the pits.", ATTACH),
        (AGE, "170 centimeters", "170 centimeters, like the file said.", ATTACH),
        (AGE, "about twelve", "about twelve feet away", ATTACH),           # a cue, but a unit follows
        (AGE, "cold air", "stiff in the cold air", ATTACH),
        (AGE, "veteran", "a veteran of a hundred fights", ATTACH),
    ])
    print("7. an age is a number of years, a decade or an age word, and a bare number needs an age cue")


def test_other_slots_are_not_this_modules_business():
    for slot in ("state.location", "state.mood", "identity.unheard_of"):
        assert shape.problem(slot, "anything", "nothing about it") is None, slot
    print("8. location, mood and unknown slots pass through untouched")


MARKS, NOT_MARK = "identity.marks", "not_a_mark"


def test_a_mark_has_to_name_a_mark():
    check([
        (MARKS, "jagged scar that splits her eyebrow", "behind the jagged scar that splits her eyebrow", None),
        (MARKS, "anchor tattoo", "the anchor tattoo on his forearm", None),
        (MARKS, "sailor ink", "the old sailor ink down his arm", None),
        (MARKS, "small gold piercing", "a small gold piercing gleamed in his ear", None),
        (MARKS, "birthmark", "a birthmark under his left ear", None),
        (MARKS, "scars", "his scarred back turned to the door", None),
        (MARKS, "scar tissue", "fingers tracing the scar tissue there", None),
        # the shapes the second gate's ledger held as marks (invented sentences, same shape)
        (MARKS, "calloused grip", "her calloused grip closed on the rail", NOT_MARK),
        (MARKS, "sharp tongue", "the sharp tongue that never rested", NOT_MARK),
        (MARKS, "lazy smirk", "the shadow of his lazy smirk", NOT_MARK),
        (MARKS, "red ticket", "the red ticket pinned to your sleeve", NOT_MARK),
        (MARKS, "indigo", "He had never been inked with anything but indigo.", NOT_MARK),
        (MARKS, "amber eyes", "Corin's amber eyes narrowed", NOT_MARK),
        (MARKS, "salt crusted on your skin", "the salt crusted on your skin", NOT_MARK),
        (MARKS, "cuts, bruises", "cuts and bruises on her arm", NOT_MARK),
    ])
    print("11a. a mark is a scar, tattoo, ink, piercing, birthmark...; a grip, a tongue, a ticket, "
          "a bare colour and a pair of eyes are not")


def test_words_that_are_only_sometimes_a_mark_need_a_body():
    check([
        (MARKS, "old burn mark on his calf", "the old burn mark on his calf", None),
        (MARKS, "mark on his wrist", "the mark on his wrist itched", None),
        (MARKS, "small mole", "a small mole beside her nose", None),   # body in the quote
        (MARKS, "scarred knuckles", "rain beaded on his scarred knuckles", None),
        (MARKS, "scarred", "his scarred face in the lamplight", None),
        (MARKS, "scarred", "the scarred table and the cracked floor", NOT_MARK),
        (MARKS, "bathroom scales", "he stepped on the bathroom scales", NOT_MARK),
        (MARKS, "brand", "the brand of whisky on the shelf", NOT_MARK),
        (MARKS, "line", "she crossed the line", NOT_MARK),
        (MARKS, "mark", "he missed his mark by an inch", NOT_MARK),
    ])
    print("11b. 'mark', 'line', 'scale', 'brand' and 'scarred' count only with a body in the value "
          "or the quote")


def test_eyes_need_a_colour_or_a_shade_and_hair_is_not_held_to_it():
    check([
        (EYES, "green", "Her green eyes held his.", None),
        (EYES, "dark", "Her dark eyes held his.", None),
        (EYES, "pale", "Her pale eyes track his face.", None),
        (EYES, "cold green", "Her cold green eyes held his.", None),
        (EYES, "cold", "Her cold eyes held his.", ATTACH),
        (EYES, "wild", "Her wild eyes locked on his.", ATTACH),
        (HAIR, "wild", "Her wild hair blew across her face.", None),
    ])
    print("12. eyes need a colour or a shade (dark, pale); 'cold' and 'wild' are not one; the "
          "rule does not reach hair")


# --- in the validator -----------------------------------------------------------------
_n = [0]


def _store(*people):
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for eid, name in people:
        s.append(kind="entity_created", entity=eid, slot="character", value=name,
                 authority="scenario", turn=0, aliases=[])
    return s


def _c(entity, slot, op, value, evidence, conf="high"):
    return Claim(entity, slot, op, value, evidence, conf)


def _run(store, claims, prose, turn=1):
    ds = validate(store.canon, claims, prose, turn=turn, next_id=len(store.ledger) + 1,
                  create_unknown=False)
    commit(store, ds)
    return ds


def test_a_misfiled_claim_writes_nothing_and_the_right_value_is_then_first():
    s = _store(("odile", "Odile Marsh"))
    ds = _run(s, [_c("Odile", HAIR, "set", "violet", "Her violet eyes")],
              "Odile turned. Her violet eyes were bright.")
    assert (ds[0].status, ds[0].reason) == ("reject", NOUN), ds[0]
    assert s.canon.current("odile", HAIR) is None and not s.canon.conflicts
    ds = _run(s, [_c("Odile", EYES, "set", "dark, sharp, unimpressed",
                     "Her eyes, dark, sharp, unimpressed by you, raked the room")],
              "Odile looked up. Her eyes, dark, sharp, unimpressed by you, raked the room.", turn=2)
    assert (ds[0].status, ds[0].reason) == ("reject", ATTACH), ds[0]
    ds = _run(s, [_c("Odile", EYES, "set", "green", "her green eyes")],
              "Odile smiled at last, her green eyes warm.", turn=3)
    assert ds[0].status == "commit"
    assert s.canon.current("odile", EYES) == "green"
    assert not s.canon.conflicts, "the wrong first write would have defended itself here"
    print("9a. a misfiled claim writes nothing, an expression is not an eye colour, and the "
          "real value is then the first write with no conflict")


def test_a_misfit_is_not_counted_as_a_second_sighting():
    s = _store(("odile", "Odile Marsh"))
    _run(s, [_c("Odile", HAIR, "set", "raven", "raven hair")], "Odile's raven hair swayed.")
    ds = _run(s, [_c("Odile", HAIR, "set", "black", "the thin black fabric of her glove")],
              "Odile's hands shook, the thin black fabric of her glove soaked through.", turn=2)
    assert (ds[0].status, ds[0].reason) == ("reject", NOUN), ds[0]
    iv = s.canon.slots["odile"][HAIR][-1]
    assert iv.value == "raven" and iv.confirmations == 1, iv
    ds = _run(s, [_c("Odile", HAIR, "set", "black", "her black hair")],
              "Odile tied back her black hair.", turn=3)
    assert ds[0].status == "commit" and s.canon.slots["odile"][HAIR][-1].confirmations == 2
    print("9b. 'black fabric' is not a second sighting of black hair; 'her black hair' is one")


def test_a_junk_mark_and_a_modifier_for_eyes_write_nothing_and_the_real_ones_follow():
    s = _store(("odile", "Odile Marsh"))
    ds = _run(s, [_c("Odile", MARKS, "add", "calloused grip", "Odile's calloused grip")],
              "Odile's calloused grip closed on the rail.")
    assert (ds[0].status, ds[0].reason) == ("reject", NOT_MARK), ds[0]
    assert not [k for k in s.canon.slots.get("odile", {}) if k.startswith("identity.marks.")]
    ds = _run(s, [_c("Odile", MARKS, "add", "thin scar over her left eye", "a thin scar over her left eye")],
              "Odile squinted, a thin scar over her left eye pulling tight.", turn=2)
    assert ds[0].status == "commit"
    assert [k for k in s.canon.slots["odile"] if k.startswith("identity.marks.")]
    ds = _run(s, [_c("Odile", EYES, "set", "cold", "Her cold eyes")],
              "Odile turned. Her cold eyes found him.", turn=3)
    assert (ds[0].status, ds[0].reason) == ("reject", ATTACH), ds[0]
    assert s.canon.current("odile", EYES) is None, "a modifier must not take the slot"
    ds = _run(s, [_c("Odile", EYES, "set", "grey", "her grey eyes")],
              "Odile smiled, her grey eyes warm.", turn=4)
    assert ds[0].status == "commit" and s.canon.current("odile", EYES) == "grey"
    assert not s.canon.conflicts
    print("9c. a mark that is not one writes nothing, 'cold' does not take the eyes, and the real "
          "values are then the first write with no conflict")


def test_one_quote_for_two_people_waits_for_both():
    prose = "Odile and Corin waited. A woman with gray hair watched from the door."
    both = [_c("Odile", HAIR, "set", "gray", "a woman with gray hair"),
            _c("Corin", HAIR, "set", "gray", "a woman with gray hair")]
    s = _store(("odile", "Odile Marsh"), ("corin", "Corin Hale"))
    ds = _run(s, both, prose)
    assert [(d.status, d.reason) for d in ds] == [("pending", "ambiguous_owner")] * 2, ds
    assert s.canon.current("odile", HAIR) is None and s.canon.current("corin", HAIR) is None
    s = _store(("odile", "Odile Marsh"), ("corin", "Corin Hale"))
    assert _run(s, both[:1], prose)[0].status == "commit"
    s = _store(("odile", "Odile Marsh"), ("corin", "Corin Hale"))
    ds = _run(s, [_c("Odile", HAIR, "set", "gray", "Odile's gray hair"),
                  _c("Corin", HAIR, "set", "gray", "Corin's gray hair")],
              "Odile's gray hair was cut short. Corin's gray hair was long.")
    assert [d.status for d in ds] == ["commit", "commit"], ds
    print("10a. one quote filed under two people waits for both; under one person, or with "
          "a quote each, it commits")


def test_the_ownership_rule_is_about_identity_and_about_people_the_passage_names():
    s = _store(("odile", "Odile Marsh"), ("corin", "Corin Hale"))
    ds = _run(s, [_c("Odile", "state.outfit", "add", "grey coat", "both wore grey coats"),
                  _c("Corin", "state.outfit", "add", "grey coat", "both wore grey coats")],
              "Odile and Corin were cold, and both wore grey coats.")
    assert [d.status for d in ds] == ["commit", "commit"], ds
    s = _store(("odile", "Odile Marsh"), ("corin", "Corin Hale"))
    ds = _run(s, [_c("Odile", "state.mood", "set", "calm", "both felt calm"),
                  _c("Corin", "state.mood", "set", "calm", "both felt calm")],
              "Odile and Corin sat down, and both felt calm.")
    assert [d.status for d in ds] == ["commit", "commit"], ds      # a "set" state slot too
    s = _store(("odile", "Odile Marsh"), ("corin", "Corin Hale"), ("tamsin", "Tamsin Reeve"))
    ds = _run(s, [_c("Odile", HAIR, "set", "gray", "a woman with gray hair"),
                  _c("Corin", HAIR, "set", "gray", "a woman with gray hair"),
                  _c("Tamsin", HAIR, "set", "gray", "a woman with gray hair")],
              "Odile and Corin waited. A woman with gray hair watched from the door.")
    assert [(d.status, d.reason) for d in ds] == [
        ("pending", "ambiguous_owner"), ("pending", "ambiguous_owner"),
        ("reject", "entity_not_in_passage")], ds
    s = _store(("odile", "Odile Marsh"), ("tamsin", "Tamsin Reeve"))
    ds = _run(s, [_c("Odile", HAIR, "set", "gray", "a woman with gray hair"),
                  _c("Tamsin", HAIR, "set", "gray", "a woman with gray hair")],
              "Odile waited. A woman with gray hair watched from the door.")
    assert [(d.status, d.reason) for d in ds] == [
        ("commit", ""), ("reject", "entity_not_in_passage")], ds   # an unnamed claimant makes nothing ambiguous
    s = _store(("odile", "Odile Marsh"), ("corin", "Corin Hale"))
    ds = _run(s, [_c("Odile", HAIR, "set", "gray", "a woman with gray hair"),
                  _c("Corin", HAIR, "set", "gray", "a woman with gray hair", conf="low")],
              "Odile and Corin waited. A woman with gray hair watched from the door.")
    assert [(d.status, d.reason) for d in ds] == [("commit", ""), ("pending", "low_confidence")], ds
    print("10b. state slots are exempt; a claimant the passage does not name, or one too unsure to "
          "count, makes nothing ambiguous")


if __name__ == "__main__":
    fns = [v for k, v in globals().items() if k.startswith("test_")]   # definition order
    try:
        for fn in fns:
            fn()
    finally:
        import shutil
        shutil.rmtree(WORK, ignore_errors=True)
    print("\nCANON SHAPE TESTS PASSED")
