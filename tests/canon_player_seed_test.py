"""The protagonist's own file is the first write for their looks (D-025).

player.md is the person's description of the player character ("Name: Finn / Info: 200cm
tall, male, black hair, green eyes, ..."). The Scribe's first sentences about a "you" were
about someone else's hair, so the protagonist's identity was a string of misfiles. The file
is better evidence than any of it, so what it states about the player's looks is written into
the ledger at SCENARIO authority, in plain code: narration can agree with it, and a different
value is held back as a conflict instead of becoming canon.

 1) the real file's shape yields height, hair and eyes, and none of the rest ("versed in
    chess", "well read"); each candidate passes the same shape rules a Scribe claim does
 2) free text yields age, hair and marks ("thin scar over his left eye"), one value per slot
 3) things that look like looks and are not yield nothing
 4) seeding writes scenario-authority records at the turn given, and is safe to repeat
 5) a value the narration wrote first is replaced once by the file; an author's edit is not
 6) after seeding, a narrated hair colour that differs is a contradiction, and one that agrees
    corroborates
 7) no player, an unknown player or an empty file seed nothing
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-seed-"))

from canon import Store                                                    # noqa: E402
from canon.claims import Claim                                             # noqa: E402
from canon.replay import player_facts, seed_player                         # noqa: E402
from canon.validate import validate                                        # noqa: E402

REAL = ("# Player character\n\nName: Finn\nInfo: 200cm tall, male, black hair, green eyes, versed in "
        "chess and archery, well read, easily distracted. A good listener, liked by everyone.\n")
_n = [0]


def _store():
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    s.append(kind="entity_created", entity="finn", slot="character", value="Finn",
             authority="scenario", turn=0, aliases=["Blank"])
    return s


def test_the_real_files_shape():
    assert player_facts(REAL) == [("identity.build", "200cm tall", "200cm tall"),
                                  ("identity.hair", "black", "black hair"),
                                  ("identity.eyes", "green", "green eyes")]
    assert [f[:2] for f in player_facts("Name: Odile\nInfo: she is a woman, tall, blue eyes")] == [
        ("identity.build", "tall"), ("identity.eyes", "blue")], "a clause that is just 'tall' is a build"
    print("1. the real file's shape gives height, hair and eyes and nothing else")


def test_free_text():
    f = dict((s, v) for s, v, _q in player_facts(
        "Finn is a 25-year-old tourist with long black hair and a thin scar over his left eye, "
        "a dragon tattoo on her arm. He is muscular."))
    assert f["identity.age"] == "25 years old" and f["identity.hair"] == "long black", f
    assert "identity.eyes" not in f, "'left eye' is a place, not a colour"
    marks = [v for s, v, _q in player_facts("a thin scar over his left eye, a dragon tattoo on her arm")
             if s == "identity.marks"]
    assert marks == ["thin scar over his left eye", "dragon tattoo on her arm"], marks
    assert dict((s, v) for s, v, _q in player_facts("Info: aged 31, dyed pink hair, dark brown eyes, muscular")) == {
        "identity.age": "31 years old", "identity.hair": "dyed pink", "identity.eyes": "dark brown",
        "identity.build": "muscular"}
    assert dict((s, v) for s, v, _q in player_facts("black hair, brown hair, green eyes, blue eyes"))["identity.hair"] == "black", \
        "the first the file states wins"
    many = ", ".join(f"a {c} tattoo on his {p}" for c, p in
                     (("red", "arm"), ("blue", "leg"), ("green", "back"), ("gold", "neck"), ("grey", "hand"),
                      ("pink", "foot")))
    assert len([f for f in player_facts(many) if f[0] == "identity.marks"]) == 4, "a bound on marks"
    print("2. free text gives age, hair, eyes, build and one mark per phrase; the first value of a slot wins")


def test_things_that_only_look_like_looks():
    for text in ("Info: his hair is a mess, eyes tired", "Info: tall glass of water, leather jacket",
                 "Info: versed in chess, well read", "Info: green eyes closed in prayer", ""):
        got = [f for f in player_facts(text) if f[0] in ("identity.hair", "identity.build", "identity.age")]
        assert got == [], (text, got)
    assert player_facts("Info: a hair stylist who sleeps late") == [], "'hair' is not a trait here"
    print("3. a messy head, a tall glass, a skill and a hair stylist are not looks")


def test_seeding_is_scenario_authority_at_the_turn_given_and_safe_to_repeat():
    s = _store()
    wrote = seed_player(s, "finn", REAL, turn=0)
    assert wrote == [("identity.build", "200cm tall"), ("identity.hair", "black"), ("identity.eyes", "green")]
    recs = [r for r in s.ledger.records if r.slot.startswith("identity.")]
    assert [(r.authority, r.turn, r.kind) for r in recs] == [("scenario", 0, "fact_established")] * 3
    assert recs[1].span == "black hair"
    n = len(s.ledger)
    assert seed_player(s, "finn", REAL, turn=5) == [] and len(s.ledger) == n, "a second pass writes nothing"
    s2 = _store()
    s2.append(kind="entity_created", entity="odile", slot="character", value="Odile", authority="scenario",
              turn=7, aliases=[])
    assert seed_player(s2, "finn", "Info: black hair", turn=3) == [], \
        "a turn before the ledger's last is refused quietly, and the next pass tries again"
    assert s2.canon.current("finn", "identity.hair") is None
    assert seed_player(s2, "finn", "Info: black hair", turn=9) == [("identity.hair", "black")]
    assert s2.ledger.records[-1].turn == 9
    print("4. seeding writes scenario records at the turn given, and a repeat writes nothing")


def test_narration_first_is_replaced_once_and_an_authors_edit_is_not():
    s = _store()
    s.append(kind="fact_established", entity="finn", slot="identity.hair", value="blank",
             authority="narration", turn=4, span="a Blank")
    s.append(kind="fact_established", entity="finn", slot="identity.eyes", value="red",
             authority="author", turn=4, span="edited by hand")
    wrote = seed_player(s, "finn", REAL, turn=5)
    assert ("identity.hair", "black") in wrote and ("identity.eyes", "green") not in wrote, wrote
    assert s.canon.current("finn", "identity.hair") == "black" and s.canon.current("finn", "identity.eyes") == "red"
    assert seed_player(s, "finn", REAL, turn=6) == [], "the replacement happens once"
    print("5. a narrated first value is replaced by the file once; an author's edit outranks it")


def test_after_seeding_a_different_narrated_value_is_a_contradiction():
    s = _store()
    seed_player(s, "finn", REAL, turn=0)
    prose = "Finn stood there, his green eyes bright and his brown hair damp."
    ds = validate(s.canon, [Claim("Finn", "identity.hair", "set", "brown", "his brown hair damp", "high"),
                            Claim("Finn", "identity.eyes", "set", "green", "his green eyes bright", "high")],
                  prose, turn=1, next_id=len(s.ledger) + 1, create_unknown=False)
    assert [(d.status, d.reason) for d in ds] == [("contradiction", "identity_locked"), ("commit", "restated")], ds
    print("6. the file's hair is defended against a different narrated one, and its eyes are corroborated")


def test_nothing_to_seed():
    s = _store()
    assert seed_player(s, None, REAL) == [] and seed_player(s, "nobody", REAL) == []
    assert seed_player(s, "finn", "") == [] and seed_player(s, "finn", "# Player character\n\nName: Finn\n") == []
    assert [r for r in s.ledger.records if r.slot.startswith("identity.")] == []
    print("7. no player, an unknown player or an empty file seed nothing")


try:
    for fn in (test_the_real_files_shape, test_free_text, test_things_that_only_look_like_looks,
               test_seeding_is_scenario_authority_at_the_turn_given_and_safe_to_repeat,
               test_narration_first_is_replaced_once_and_an_authors_edit_is_not,
               test_after_seeding_a_different_narrated_value_is_a_contradiction,
               test_nothing_to_seed):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON PLAYER SEED TESTS PASSED")
