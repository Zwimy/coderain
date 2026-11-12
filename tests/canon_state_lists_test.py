"""State lists stopped growing and stopped refusing (D-023).

The real-save gate found three things wrong with outfit, held items and injuries:
 * they were mostly not what the slot says: a plume of smoke, a teacup, tattoos and
   bare feet as an outfit; thumbs, fingers and a glow as held; "bike" and "soaked"
   as injuries;
 * they only grew: the Scribe says a thing was taken off almost never (6 times in
   1,646 turns), and a list at the cap REFUSED the newest item (386 refusals), so a full
   card showed the oldest things in the story and nothing new;
 * nothing said when a value was last true, so a coat worn once at turn 75 sat on the
   card at turn 1,048.

 1) outfit needs a garment, held an object, injury a wound; the plural of "tight" is not
    "tights", and "balls" is not a ball
 2) a new garment replaces the one of its kind, a dress takes the top and bottom with
    it, and things that are worn together stay
 3) saying an item again moves it to the newest place, with its old wording, and is
    RECORDED so the ledger knows the story said it again
 4) a full list drops its OLDEST item instead of refusing the new one
 5) canon knows when a value was last stated, and a snapshot from before that existed
    still loads
 6) the card leaves out a value the story has not stated for too long, says nothing
    new when no turn is given, and the cast does not put someone in a room because of
    a place stated a thousand turns ago
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-lists-"))

from canon import Store, shape, wardrobe                                  # noqa: E402
from canon.claims import Claim                                            # noqa: E402
from canon.ledger import MAX_LIST                                         # noqa: E402
from canon.replay import state_ages                                       # noqa: E402
from canon.scene import FRESH_TURNS, Scene, card_line, find_scene, render_card  # noqa: E402
from canon.state import Canon                                             # noqa: E402
from canon.validate import LIST_CAP, commit, validate                     # noqa: E402

OUT, HELD, HURT = "state.outfit", "state.held", "state.injury"


def _check(slot, rows):
    for value, quote, want in rows:
        got = shape.problem(slot, value, quote)
        assert got == want, (slot, value, quote, "expected", want, "got", got)


def test_each_list_takes_only_what_it_is_for():
    _check(OUT, [
        ("cropped tank top", "a cropped tank top", None),
        ("heavy boots", "her heavy boots", None),
        ("tuxedo vest sweated through", "tuxedo vest sweated through", None),   # a trailing remark
        ("folded pair of black shorts", "a folded pair of black shorts", None),
        ("towel, a small one, wrapped around her hips", "found a towel, a small one", None),
        ("plume of smoke", "a plume of smoke", "not_a_garment"),
        ("teacup", "the teacup", "not_a_garment"),
        ("bare feet", "her bare feet", "not_a_garment"),
        ("anchor tattoos", "her anchor tattoos", "not_a_garment"),
        ("tattered velvet", "tattered velvet", "not_a_garment"),
        ("pistol tucked in her belt", "a pistol tucked in her belt", "not_a_garment"),  # the pistol, not the belt
        ("bare feet—boots", "her bare feet—boots", "not_a_garment"),         # a dash ends the phrase
        ("knuckles are drawn tight", "her knuckles are drawn tight", "not_a_garment"),  # tight is not tights
    ])
    _check(HELD, [
        ("cup", "reaches for his cup", None),
        ("slim datapad", "pulls a slim datapad from her jacket", None),
        ("pint jar", "picks up the pint jar", None),
        ("thumb", "her thumb on his wrist", "not_an_object"),
        ("elbow", "his elbow in her ribs", "not_an_object"),
        ("balls", "the weight of the balls", "not_an_object"),                # the plural is refused outright
        ("warm current", "the warm current", "not_an_object"),
        ("percentages", "percentages say you will not walk", "not_an_object"),
    ])
    _check(HURT, [
        ("knife wound below her left shoulder blade", "a knife wound below her left shoulder blade", None),
        ("swollen left ankle", "her left ankle, swollen and purple", None),
        ("burn mark on her hip", "a burn mark on her hip", None),
        ("headache, temples", "the headache is back", None),
        ("injured leg", "her injured leg", None),
        ("broken nose", "a broken nose", None),                                  # weak words need a body part
        ("burn on her left wrist", "a burn on her left wrist", None),
        ("broken white line along the wall", "a broken white line", "not_a_wound"),
        ("screen cracked and repaired with tape", "the screen cracked", "not_a_wound"),
        ("goes limp", "the rope goes limp", "not_a_wound"),
        ("swollen head", "the swollen head", "not_a_wound"),                   # swollen needs a limb or the face
        ("ribs", "catches her in the ribs", "not_a_wound"),
        ("fingertips graze it but can't stop it", "her fingertips graze it", "not_a_wound"),  # a verb
        ("legs tremble", "her legs tremble", "not_a_wound"),
        ("scar on ribs", "a scar on her ribs", "not_a_wound"),                 # a mark, not an injury
    ])
    print("1. outfit needs a garment, held an object, injury a wound; 'tight' is not 'tights' and "
          "'balls' is not a ball")


def test_a_new_garment_replaces_its_kind():
    r = wardrobe.replaced_by
    assert r("red dress", ["grey tee", "jeans", "boots", "silver ring", "coat"]) == \
        ["boots", "silver ring", "coat"], "a dress takes the top and the bottom with it"
    assert r("black jeans", ["grey tee", "blue jeans", "towel", "boots"]) == ["grey tee", "boots"]
    assert r("green hoodie", ["grey tee", "jeans"]) == ["jeans"], "a hoodie is a top here"
    assert r("tuxedo vest", ["leather jacket", "boots"]) == ["boots"], "tuxedo vest is a vest, an outer layer"
    assert r("silver ring", ["gold ring", "watch", "boots"]) == ["gold ring", "watch", "boots"], \
        "jewellery is worn together"
    assert r("black mask", ["grey scarf", "red mask"]) == ["grey scarf", "red mask"]
    assert r("something odd", ["grey tee"]) == ["grey tee"], "a non-garment replaces nothing"
    assert wardrobe.last_of("knuckles are drawn tight", wardrobe.CATEGORY) is None,         "a plural is read as its singular and never the other way: tight is not tights"
    assert wardrobe.last_of("pair of boots", wardrobe.CATEGORY) == "boots"
    assert wardrobe.category("tuxedo vest sweated through") == "outer"
    assert wardrobe.category("shirt dress") == "full"
    # Hair accessories count as worn jewellery. They were refused as "not a garment" until
    # these words were added. This pins the lexicon only: whether the Scribe ever files such
    # an item under outfit is a separate question this assertion does not answer.
    assert wardrobe.category("silver hairpins") == "jewellery" and wardrobe.category("a barrette") == "jewellery"
    assert wardrobe.replaced_by("pearl hairpins", ["gold ring", "grey tee"]) == ["gold ring", "grey tee"]
    assert shape.problem(OUT, "hairpins", "the pearl in her hairpins") is None
    print("2. a garment replaces its kind (a dress takes top and bottom, jeans take a dress), "
          "and what is worn together stays")


_n = [0]


def _store():
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    s.append(kind="entity_created", entity="odile", slot="character", value="Odile Marsh",
             authority="scenario", turn=0, aliases=[])
    return s


def _say(s, slot, op, value, quote, turn):
    c = Claim("Odile", slot, op, value, quote, "high")
    ds = validate(s.canon, [c], f"Odile stood there, {quote}.", turn=turn,
                  next_id=len(s.ledger) + 1, create_unknown=False)
    commit(s, ds)
    return ds[0]


def test_saying_it_again_moves_it_to_the_newest_place_and_is_recorded():
    s = _store()
    _say(s, OUT, "add", "grey coat", "a grey coat", 2)
    _say(s, OUT, "add", "leather boots", "leather boots", 3)
    n = len(s.ledger)
    d = _say(s, OUT, "add", "grey coat", "her grey coat", 9)
    assert (d.status, d.reason) == ("commit", "restated"), d
    assert len(s.ledger) == n + 1, "a repeat is a record, not a no-op"
    assert list(s.canon.current("odile", OUT)) == ["leather boots", "grey coat"]
    assert s.canon.last_seen("odile", OUT) == 9
    d = _say(s, OUT, "add", "grey coat", "the grey coat", 12)               # already the newest
    assert (d.status, d.reason) == ("commit", "restated") and s.canon.last_seen("odile", OUT) == 12
    assert s.canon.slots["odile"][OUT][-1].confirmations == 2
    # a scalar said again is recorded too
    _say(s, "state.mood", "set", "tired", "looking tired", 13)        # a ledger's turns never go back
    d = _say(s, "state.mood", "set", "tired", "still tired", 20)
    assert (d.status, d.reason) == ("commit", "restated") and s.canon.last_seen("odile", "state.mood") == 20
    # The same on a list with no replace-by-kind rule. The outfit case above cannot show a
    # duplicate, because a restated coat replaces itself by kind whether or not the repeat
    # branch runs; held items have no such rule, so only here does a second copy appear.
    _say(s, HELD, "add", "brass key", "a brass key", 21)
    _say(s, HELD, "add", "lantern", "a lantern", 22)
    d = _say(s, HELD, "add", "brass key", "the brass key", 23)
    assert (d.status, d.reason) == ("commit", "restated"), d
    assert list(s.canon.current("odile", HELD)) == ["lantern", "brass key"], s.canon.current("odile", HELD)
    print("3. an item or value said again is recorded (newest, old wording) and its last-seen turn moves, "
          "and a held item said again is moved, not listed twice")


def test_an_item_that_says_several_old_ones_replaces_them():
    """A 240-turn soak (a local 4B Writer) ended with held: rope, rag, rope and rag, worn rope and rag, and an outfit of
    spectacles, glasses, spectacles and glasses, in the card sent every turn. The repeat rule only merged when exactly
    ONE item matched, so once the list held two parts of a phrase the whole phrase matched two and was appended."""
    s = _store()
    _say(s, HELD, "add", "rope", "a coil of rope", 2)
    _say(s, HELD, "add", "rag", "a rag", 3)
    d = _say(s, HELD, "add", "rope and rag", "rope and rag", 4)
    assert d.status == "commit", d
    assert list(s.canon.current("odile", HELD)) == ["rope and rag"], s.canon.current("odile", HELD)
    _say(s, HELD, "add", "worn rope and rag", "a worn rope and rag", 5)          # says all of it and more: the richer wording wins
    assert list(s.canon.current("odile", HELD)) == ["worn rope and rag"], s.canon.current("odile", HELD)
    # only whole words inside it: what is unrelated stays
    _say(s, HELD, "add", "lantern", "a lantern", 6)
    _say(s, HELD, "add", "rope and chain", "rope and chain", 7)                 # shares "rope" but is not made of it
    assert list(s.canon.current("odile", HELD)) == ["worn rope and rag", "lantern", "rope and chain"], s.canon.current("odile", HELD)
    s2 = _store()
    _say(s2, HELD, "add", "sword", "a sword", 2)
    _say(s2, HELD, "add", "shield", "a shield", 3)
    _say(s2, HELD, "add", "lantern", "a lantern", 4)
    _say(s2, HELD, "add", "sword and shield", "sword and shield", 5)
    assert list(s2.canon.current("odile", HELD)) == ["lantern", "sword and shield"], s2.canon.current("odile", HELD)
    _say(s2, HELD, "add", "rope and chain", "rope and chain", 6)             # shares no whole word with them: nothing absorbed
    assert list(s2.canon.current("odile", HELD)) == ["lantern", "sword and shield", "rope and chain"]
    s3 = _store()                                                              # the outfit list too
    _say(s3, OUT, "add", "hat", "a hat", 2)
    _say(s3, OUT, "add", "gloves", "gloves", 3)
    _say(s3, OUT, "add", "hat and gloves", "hat and gloves", 4)
    assert list(s3.canon.current("odile", OUT)) == ["hat and gloves"], s3.canon.current("odile", OUT)
    print("3b. an item that says everything several old ones say replaces them; unrelated items stay")


def test_a_full_list_drops_the_oldest_instead_of_refusing_the_new():
    s = _store()
    worn = ["ring", "bracelet", "watch", "scarf", "belt", "mask", "glasses", "choker",
            "necklace", "earrings", "anklet", "beads"]                       # kinds worn together
    for i, w in enumerate(worn):
        d = _say(s, OUT, "add", w, f"a {w}", 2 + i)
        assert d.status == "commit", (w, d)
    cur = list(s.canon.current("odile", OUT))
    assert len(cur) == LIST_CAP[OUT] == 10 and cur[-1] == "beads" and "ring" not in cur, cur
    objects = ["cup", "pen", "key", "coin", "book", "lamp", "rope"]
    for i, w in enumerate(objects):
        assert _say(s, HELD, "add", w, f"a {w}", 30 + i).status == "commit"
    cur = list(s.canon.current("odile", HELD))
    assert cur == objects[1:] and len(cur) == LIST_CAP[HELD] == 6, cur
    assert max(LIST_CAP.values()) <= MAX_LIST, "the ledger's own bound still holds"
    s = _store()
    _say(s, HELD, "add", "red helmet", "a red helmet", 2)
    _say(s, HELD, "add", "black helmet", "a black helmet", 3)
    assert list(s.canon.current("odile", HELD)) == ["red helmet", "black helmet"],         "only the outfit list replaces by kind; two helmets can be carried"
    print("4. a full list drops its oldest item (outfit cap 10, held cap 6) and never refuses a new one")


def test_a_misfit_is_refused_in_the_validator_and_changes_nothing():
    s = _store()
    _say(s, OUT, "add", "grey coat", "a grey coat", 2)
    n = len(s.ledger)
    for slot, value, quote, why in ((OUT, "plume of smoke", "a plume of smoke", "not_a_garment"),
                                    (HELD, "thumb", "her thumb", "not_an_object"),
                                    (HURT, "bike", "the bike crash", "not_a_wound")):
        d = _say(s, slot, "add", value, quote, 3)
        assert (d.status, d.reason) == ("reject", why), (slot, d)
    assert len(s.ledger) == n and list(s.canon.current("odile", OUT)) == ["grey coat"]
    print("5c. a misfit claim on a state list is rejected and the ledger does not move")


def test_a_garment_replaces_its_kind_in_the_validator_and_history_keeps_the_old_one():
    s = _store()
    _say(s, OUT, "add", "grey tee", "a grey tee", 2)
    _say(s, OUT, "add", "blue jeans", "blue jeans", 3)
    _say(s, OUT, "add", "heavy boots", "heavy boots", 4)
    _say(s, OUT, "add", "black dress", "a black dress", 10)
    assert list(s.canon.current("odile", OUT)) == ["heavy boots", "black dress"]
    then = s.canon.value_at_turn("odile", OUT, 5)
    assert list(then) == ["grey tee", "blue jeans", "heavy boots"], "the old outfit is still in the ledger"
    print("5a. a dress replaces the tee and jeans in the validator; turn 5 still reads the old outfit")


def test_last_seen_and_old_snapshots():
    c = Canon()
    s = _store()
    _say(s, "state.mood", "set", "angry", "angry", 4)
    assert s.canon.last_seen("odile", "state.mood") == 4
    assert s.canon.last_seen("odile", "state.location") is None
    d = s.canon.as_dict()
    for slots in d["slots"].values():                  # a snapshot from before last_turn existed
        for ivs in slots.values():
            for iv in ivs:
                iv.pop("last_turn")
    old = Canon.from_dict(d)
    assert old.last_seen("odile", "state.mood") == 4, "falls back to when it was opened"
    again = Canon.from_dict(s.canon.as_dict())
    assert again.digest() == s.canon.digest() and c.last_seen("x", "state.mood") is None
    print("5b. canon knows when a value was last stated; a snapshot without it still loads")


def test_the_card_leaves_out_what_has_not_been_stated_for_too_long():
    s = _store()
    _say(s, OUT, "add", "grey coat", "a grey coat", 10)
    _say(s, "state.mood", "set", "angry", "angry", 10)
    scene = Scene(cast=("odile",))
    assert "grey coat" in card_line(s.canon, "odile") and "angry" in card_line(s.canon, "odile")
    both = card_line(s.canon, "odile", now=10 + FRESH_TURNS["mood"])
    assert "grey coat" in both and "angry" in both, "inside both windows"
    line = card_line(s.canon, "odile", now=10 + FRESH_TURNS["mood"] + 1)
    assert "grey coat" in line and "angry" not in line, "the mood expired first"
    assert card_line(s.canon, "odile", now=10 + FRESH_TURNS["outfit"] + 1) == "", "nothing left to say"
    assert render_card(s.canon, scene, now=10 + FRESH_TURNS["outfit"] + 1) == ""
    _say(s, OUT, "add", "grey coat", "her grey coat", 300)                 # said again
    assert "grey coat" in card_line(s.canon, "odile", now=300 + FRESH_TURNS["outfit"])
    assert "grey coat" in card_line(s.canon, "odile", now=None), "no turn given, nothing expires"
    later = Scene(cast=(), omitted=("odile",))                             # past the cap, but stated
    assert "Odile Marsh" in render_card(s.canon, later, now=300 + FRESH_TURNS["outfit"])
    assert render_card(s.canon, later, now=300 + FRESH_TURNS["outfit"] + 1) == ""
    print("6a. the card drops a value past its window, keeps one the story said again, and "
          "expires nothing when no turn is given")


def test_the_report_can_say_how_old_each_state_value_is():
    s = _store()
    _say(s, "state.mood", "set", "angry", "angry", 10)
    _say(s, OUT, "add", "grey coat", "a grey coat", 50)
    s.append(kind="entity_created", entity="corin", slot="character", value="Corin Hale",
             authority="scenario", turn=50, aliases=[])
    s.append(kind="state_set", entity="corin", slot=OUT, value=["boots"], authority="narration", turn=80)
    a = state_ages(s.canon, 100, {"mood": 15, "outfit": 120, "held": 30})
    assert a["mood"] == {"values": 1, "window": 15, "past_window": 1, "median_age": 90}, a
    assert a["outfit"] == {"values": 2, "window": 120, "past_window": 0, "median_age": 50}, a   # ages 20 and 50
    assert a["held"] == {"values": 0, "window": 30, "past_window": 0, "median_age": None}, a
    print("6c. the shadow report's state ages are counts and ages against the card's windows")


def test_an_old_place_does_not_put_someone_in_the_room():
    s = _store()
    for eid, name in (("corin", "Corin Hale"), ("tamsin", "Tamsin Reeve")):
        s.append(kind="entity_created", entity=eid, slot="character", value=name,
                 authority="scenario", turn=0, aliases=[])
    for eid, turn in (("tamsin", 5), ("odile", 100), ("corin", 100)):      # in ledger order
        s.append(kind="location_changed", entity=eid, slot="state.location",
                 value="the harbour", authority="narration", turn=turn)
    recent = ["Odile Marsh watched the water."]
    here = find_scene(s.canon, recent).cast
    assert set(here) == {"odile", "corin", "tamsin"}, "without a turn, a place is a place"
    here = find_scene(s.canon, recent, now=110).cast
    assert set(here) == {"odile", "corin"}, ("tamsin's harbour was stated 105 turns ago", here)
    assert find_scene(s.canon, recent, now=400).cast == ("odile",),         "when even the named character's place is old, there is no place to match"
    s2 = _store()                                   # the named one's place is old, another's is not
    s2.append(kind="entity_created", entity="corin", slot="character", value="Corin Hale",
              authority="scenario", turn=0, aliases=[])
    for eid, turn in (("odile", 100), ("corin", 290)):
        s2.append(kind="location_changed", entity=eid, slot="state.location",
                  value="the harbour", authority="narration", turn=turn)
    assert find_scene(s2.canon, recent, now=300).cast == ("odile",),         "an old place is not a place: matching on it would seat Corin by Odile's stale harbour"
    print("6b. a place stated long ago puts nobody in the cast")


try:
    for fn in (test_each_list_takes_only_what_it_is_for, test_a_new_garment_replaces_its_kind,
               test_saying_it_again_moves_it_to_the_newest_place_and_is_recorded,
               test_an_item_that_says_several_old_ones_replaces_them,
               test_a_full_list_drops_the_oldest_instead_of_refusing_the_new,
               test_a_misfit_is_refused_in_the_validator_and_changes_nothing,
               test_a_garment_replaces_its_kind_in_the_validator_and_history_keeps_the_old_one,
               test_last_seen_and_old_snapshots,
               test_the_card_leaves_out_what_has_not_been_stated_for_too_long,
               test_the_report_can_say_how_old_each_state_value_is,
               test_an_old_place_does_not_put_someone_in_the_room):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON STATE LISTS TESTS PASSED")
