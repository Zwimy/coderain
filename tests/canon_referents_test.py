"""Who "she", "he" and "you" mean (D-024).

The validator refused every claim about someone the passage does not name, and refused a
pronoun as the subject of a claim. In the real save "you" is in 973 of 976 narrator turns
and the player is named in 117, so the protagonist had almost no facts; and in a long scene
"she" runs for dozens of turns after the name appeared once.

The code now decides who a pronoun means, never the Scribe, and only where it is safe.
Hand-read samples of the real save (112 decided cases) gave about 9 in 10 right, so pronouns
are resolved for STATE facts (replaced and aged out, D-023) and never for identity facts
(first write wins, permanent). "You" is exact and works for both.

Each rule below is a way the nearest name was wrong in that save:

 1) a name counts only where it is capitalised at THAT occurrence ("Rowan" is a character,
    "the rowan tree" is not), and a single word after "the" is a faction or a place
 2) the nearest earlier sentence that names someone decides, if it names exactly one
 3) a name AFTER the pronoun in its own sentence is the object, not the antecedent
 4) a pronoun inside quoted speech, and a name inside it, are about a third party
 5) an engine scene header ("### [...]") and the player are never a third-person antecedent
 6) a contraction ("She'd") is a pronoun
 7) two possible referents, or none, is "unclear"
 8) gender is read from sentences that name exactly one character; too few votes is unknown
 9) the validator: a pronoun entity resolves for state and not for identity; "you" is the
    player; a quote written about a woman is not a fact about a man; an empty Who changes
    nothing
10) the player is found from player.md, or from config; ambiguity is None
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-refs-"))

from canon import Store                                                    # noqa: E402
from canon.claims import Claim                                             # noqa: E402
from canon.referents import (Passage, decide_gender, explain, gender_votes, genders_from,  # noqa: E402
                             in_speech, locate, make_who, referent, sentence_bounds)
from canon.replay import (GenderVotes, passage_who, player_entity,        # noqa: E402
                          player_gender, reads_anyone)
from canon.scene import mention_spans, mentions                           # noqa: E402
from canon.validate import (Who, commit, is_second_person, pronoun_kind,  # noqa: E402
                            quote_gender, validate)

_n = [0]
PEOPLE = [("odile", "Odile Marsh", ["The Courier"]), ("corin", "Corin Hale", []),
          ("tamsin", "Tamsin Reeve", []), ("finn", "Finn", ["Blank"]),
          ("marlow", "Marlow", ["Guild"]), ("rowan", "Rowan", []), ("hush", "Hush", [])]


def _store(people=PEOPLE):
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for eid, name, aliases in people:
        s.append(kind="entity_created", entity=eid, slot="character", value=name,
                 authority="scenario", turn=0, aliases=aliases)
    return s


def who_is(prose, quote, g="F", *, before="", genders=None, player=None, reach=30):
    canon = _store().canon
    return referent(canon, Passage(canon, prose, before, player), quote, g,
                    genders=genders, reach=reach)


# ---------------------------------------------------------------------------
def test_a_name_must_be_capitalised_where_it_occurs_and_not_follow_the_():
    c = _store().canon
    assert mentions(c, "Rowan is on the bench, a hand on the rowan branch.") == {"rowan"}
    assert [(p[2]) for p in mention_spans(c, "Rowan sat. The rowan branch ached.")] == ["rowan"], \
        "only the capitalised occurrence is a mention"
    assert mentions(c, "A hush fell over the hall.") == set(), "a common word is not Hush"
    assert mentions(c, "Hush fell over the hall.") == {"hush"}, "sentence-initial is a name"
    s = "Odile laughed."
    assert [(a, b) for a, b, _e in mention_spans(c, s)] == [(0, 5)], "spans point at the words"
    p = Passage(c, "That counts in the Guild. She turned away.")
    assert referent(c, p, "She turned away.", "F") is None, "'the Guild' is a faction, not Marlow"
    p = Passage(c, "Guild said so. She turned away.")
    assert referent(c, p, "She turned away.", "F") == "marlow"
    print("1. a name needs a capital at that occurrence, and a word after 'the' is not a name")


def test_the_nearest_sentence_that_names_one_character_decides():
    assert who_is("Odile stood by the door. She wore a grey coat.", "She wore a grey coat.") == "odile"
    assert who_is("Odile tied her hair.", "Odile tied her hair.") == "odile"
    assert who_is("Odile stood. The rain fell. The wind rose. She wore a coat.", "She wore a coat.",
                  reach=3) == "odile"
    assert who_is("Odile stood. The rain fell. The wind rose. She wore a coat.", "She wore a coat.",
                  reach=2) is None, "too far for the reach it was given"
    assert who_is("Odile watched Tamsin. She frowned.", "She frowned.") is None, \
        "two women in the nearest sentence: unclear, and no widening"
    assert who_is("Odile stood. Corin watched Tamsin. She frowned.", "She frowned.",
                  genders={"corin": "M"}) == "tamsin", "gender removes one candidate"
    print("2. the nearest naming sentence decides when it names exactly one; two is unclear")


def test_a_name_after_the_pronoun_is_the_object():
    assert who_is("Odile stood. She brought the cup to Tamsin's lips.",
                  "She brought the cup to Tamsin's lips.") == "odile"
    assert who_is("Odile turned. She'd seen Tamsin there.", "She'd seen Tamsin there.") == "odile", \
        "a contraction is a pronoun, so Tamsin after it is the object"
    assert who_is("Odile waits it out and her own patience wears thin.",
                  "Odile waits it out and her own patience wears thin.") == "odile", "a name BEFORE it counts"
    print("3. a name after the pronoun in its sentence is not its antecedent, 'She'd' included")


def test_speech_and_headers_and_the_player_are_not_antecedents():
    c = _store().canon
    assert in_speech('He said, "she left', 14) and not in_speech('He said, "she left" and went', 27)
    assert in_speech("He said, “she left", 14)
    assert who_is('Odile said, "She is tired."', "She is tired.") is None, \
        "a pronoun in speech is about someone the speaker is talking of, not the speaker"
    assert who_is('Corin said, "That is what Odile did." She turned away.', "She turned away.",
                  genders={"corin": "M"}) is None, "a name in speech names a third party"
    assert who_is("### [2073-03-04] [Hush's Cellar]\nShe holds your gaze.", "She holds your gaze.") is None, \
        "a scene header names a place"
    assert who_is("Finn watched. She smiled.", "She smiled.", player="finn") is None, \
        "a third-person pronoun never means you"
    assert who_is("Finn watched. She smiled.", "She smiled.") == "finn", "unless nobody said who the player is"
    assert referent(c, Passage(c, "She turned."), "She turned.", "F") is None, "nobody named at all"
    print("4. speech, headers and the player are never what a pronoun looks back to")


def test_the_turns_before_count_when_they_are_given():
    before = "Odile stood by the door."
    assert who_is("She tilts her head.", "She tilts her head.", before=before) == "odile"
    assert who_is("She tilts her head.", "She tilts her head.", before=before, reach=0) is None
    assert who_is("She tilts her head.", "She tilts her head.") is None, "no earlier turns, nobody named"
    who, said = explain(_store().canon, Passage(_store().canon, "She nods.", before), "She nods.", "F")
    assert (who, said) == ("odile", "Odile stood by the door."), "it can say which sentence named her"
    print("5. earlier turns are searched when given, and the answer can name its evidence")


def test_locating_a_quote_and_splitting_sentences():
    text = "Odile laughed. “No,” she said. Corin left!\nA new line."
    assert [text[a:b].strip() for a, b in sentence_bounds(text)] == [
        "Odile laughed.", "“No,” she said.", "Corin left!", "A new line."]
    assert locate("Odile Marsh wore a coat.", "wore a coat") == (12, 23)
    assert locate("Odile Marsh wore a coat.", "WORE A COAT.") == (12, 23), "case and a final stop"
    assert locate("Odile Marsh wore a long grey coat today.", "wore a long grey wool coat") is not None
    assert locate("Odile Marsh wore a coat.", "nothing like it at all") is None
    print("6. sentences split on stops and newlines; a quote is found even when it is paraphrased a little")


def test_quote_helpers():
    assert quote_gender("her hair") == "F" and quote_gender("his coat") == "M"
    assert quote_gender("her coat on his arm") is None and quote_gender("the coat") is None
    assert is_second_person("your hoodie") and is_second_person("you're cold")
    assert not is_second_person("your hand on her hip") and not is_second_person("the hoodie")
    assert pronoun_kind("She") == "F" and pronoun_kind("his") == "M" and pronoun_kind("You") == "you"
    assert pronoun_kind("the woman") == "F" and pronoun_kind("they") is None and pronoun_kind("Odile") is None
    print("7. gender of a quote, second person, and what a Scribe's pronoun stands for")


def test_gender_is_read_from_sentences_that_name_one_character():
    c = _store().canon
    text = ("Odile tied her hair. Corin watched Tamsin and her coat. Corin lifted his cup, his jaw tight. "
            "Finn said, but her eyes.\n### Odile's header her\nRowan hid her face.")
    v = gender_votes(c, text, player="finn")
    assert v == {"odile": [0, 1], "corin": [2, 0], "rowan": [0, 1]}, v
    assert decide_gender(0, 2) is None and decide_gender(0, 3) == "F" and decide_gender(5, 0) == "M"
    assert decide_gender(4, 1) == "M" and decide_gender(3, 2) is None, "an 80% majority, no less"
    assert genders_from({"a": [0, 5], "b": [3, 3], "c": [1, 0]}) == {"a": "F"}
    gv = GenderVotes([{"votes": {"odile": [0, 2]}}, {"votes": {"odile": [0, 1]}}, {"turn": 3}])
    assert gv.genders() == {"odile": "F"}
    w = passage_who(c, "Finn stood.", votes=GenderVotes([{"votes": {"finn": [0, 9]}}]), player="finn",
                    before=[], player_is="M")
    assert w.genders["finn"] == "M", "what player.md says about the player beats what the story's votes say"
    assert passage_who(c, "Finn stood.", votes=GenderVotes(), player="finn", before=[]).genders == {}
    print("8. gender comes from single-name sentences, needs three votes and an 80% share, skips the player")


def _claim(entity, slot, op, value, quote):
    return Claim(entity, slot, op, value, quote, "high")


def _run(s, claim, prose, who=None, turn=1):
    ds = validate(s.canon, [claim], prose, turn=turn, next_id=len(s.ledger) + 1,
                  create_unknown=False, who=who)
    commit(s, ds)
    return ds[0]


def test_the_validator_resolves_pronouns_for_state_and_never_for_identity():
    s = _store()
    prose = "Odile stood by the door. She wore a grey coat, her hair raven."
    who = make_who(s.canon, prose, genders={}, player="finn")
    d = _run(s, _claim("she", "state.outfit", "add", "grey coat", "She wore a grey coat"), prose, who)
    assert (d.status, d.entity, d.via) == ("commit", "odile", "pronoun"), d
    assert list(s.canon.current("odile", "state.outfit")) == ["grey coat"]
    d = _run(s, _claim("she", "identity.hair", "set", "raven", "her hair raven"), prose, who, turn=2)
    assert (d.status, d.reason) == ("reject", "unresolved_entity"), "an identity fact is permanent"
    d = _run(s, _claim("Odile", "state.held", "add", "cup", "She sipped the cup"),
             "Odile stood. She sipped the cup.", make_who(s.canon, "Odile stood. She sipped the cup."), turn=3)
    assert (d.status, d.via) == ("commit", ""), "named in the passage: nothing was inferred"
    # the Scribe names her though the passage does not: fine for state, refused for identity
    prose2 = "She tilts her head, her coat wet."
    who2 = make_who(s.canon, prose2, genders={}, before="Odile stood by the door.")
    d = _run(s, _claim("Odile", "state.outfit", "add", "wet coat", "her coat wet"), prose2, who2, turn=4)
    assert (d.status, d.via) == ("commit", "context"), d
    d = _run(s, _claim("Odile", "identity.eyes", "set", "green", "her green eyes"), "She tilts her green eyes.",
             make_who(s.canon, "She tilts her green eyes.", before="Odile stood by the door."), turn=5)
    assert (d.status, d.reason) == ("reject", "entity_not_in_passage"), d
    print("9a. 'she' resolves for an outfit and not for hair; a name not in the passage is accepted for state only")


def test_you_is_the_player_for_every_slot():
    s = _store()
    prose = "You pull on your hoodie. Your hair is raven."
    who = make_who(s.canon, prose, player="finn")
    d = _run(s, _claim("you", "state.outfit", "add", "hoodie", "pull on your hoodie"), prose, who)
    assert (d.status, d.entity, d.via) == ("commit", "finn", "you"), d
    d = _run(s, _claim("you", "identity.hair", "set", "raven", "Your hair is raven"), prose, who, turn=2)
    assert (d.status, d.entity) == ("commit", "finn"), "identity too: 'you' is exact"
    d = _run(s, _claim("Finn", "state.held", "add", "cup", "your cup"), "You lift your cup.",
             make_who(s.canon, "You lift your cup.", player="finn"), turn=3)
    assert d.status == "commit", "the Scribe named the player and the passage did not"
    d = _run(s, _claim("Finn", "state.held", "add", "key", "your key on her palm"),
             "You hold your key on her palm.", make_who(s.canon, "You hold your key on her palm.", player="finn"), turn=4)
    assert (d.status, d.reason) == ("reject", "entity_not_in_passage"), "two people in the quote settle nothing"
    d = _run(s, _claim("you", "state.outfit", "add", "coat", "your coat"), "You wear your coat.", Who(), turn=5)
    assert (d.status, d.reason) == ("reject", "unresolved_entity"), "nobody said who you is"
    print("9b. 'you' is the player, for state and identity alike; a quote about two people settles nothing")


def test_a_quote_about_a_woman_is_not_a_fact_about_a_man():
    s = _store()
    prose = "Corin sat. Her raven hair was loose."
    d = _run(s, _claim("Corin", "identity.hair", "set", "raven", "Her raven hair"), prose,
             make_who(s.canon, prose, genders={"corin": "M"}), turn=2)
    assert (d.status, d.reason) == ("reject", "gender_mismatch"), d
    prose = "Corin sat. His raven hair was loose."
    d = _run(s, _claim("Corin", "identity.hair", "set", "raven", "His raven hair"), prose,
             make_who(s.canon, prose, genders={"corin": "M"}), turn=3)
    assert d.status == "commit", d
    prose = "Corin sat. Her raven hair was loose."
    d = _run(s, _claim("Corin", "identity.hair", "set", "raven", "Her raven hair"), prose, Who(), turn=4)
    assert (d.status, d.reason) == ("commit", "restated"), \
        "with no genders known nothing is refused for gender (it is the same value, said again)"
    assert s.canon.slots["corin"]["identity.hair"][-1].confirmations == 2
    print("9c. a woman's quote is refused for a man whose gender is known, and nothing is refused when it is not")


def test_an_empty_who_changes_nothing():
    s = _store()
    prose = "Odile stood. She wore a grey coat."
    d = _run(s, _claim("she", "state.outfit", "add", "grey coat", "She wore a grey coat"), prose)
    assert (d.status, d.reason) == ("reject", "unresolved_entity"), "D-019, as before"
    d = _run(s, _claim("Corin", "state.outfit", "add", "grey coat", "She wore a grey coat"), prose, turn=2)
    assert (d.status, d.reason) == ("reject", "entity_not_in_passage")
    print("9d. with no Who, a pronoun is refused and a name has to be in the passage, as D-019 says")


def test_the_player_is_found_from_player_md_or_config():
    class E:
        def __init__(self, title, slug, aliases=()):
            self.title, self.slug, self.aliases = title, slug, list(aliases)
    entries = [E("Finn", "finn", ["Blank"]), E("Odile Marsh", "odile"), E("Corin Hale", "corin")]
    assert player_entity(entries, "# Player\nThe player is Finn, a tourist.") == "finn"
    assert player_entity(entries, "You are Blank, and Odile knows it.") is None, "two matches: no guess"
    assert player_entity(entries, "Nobody in particular.") is None
    twins = [E("Finn", "finn"), E("The Courier", "courier", ["Finn"])]
    assert player_entity(twins, "Name: Finn\nInfo: tall.") is None, \
        "two characters answer to the Name: line, so there is no one to pick"
    # The real file's shape: "Name:" is authoritative, and loose words must not match a
    # second character ("well" is an alias of someone in the real save).
    entries.append(E("Dr. Nell", "nell", ["Well"]))
    real = "# Player character\n\nName: Finn\nInfo: 200cm tall, male, well read, green eyes.\n"
    assert player_entity(entries, real) == "finn", "the Name: line decides, not every word of the file"
    assert player_entity(entries, "Name: Odile Marsh\nInfo: tall.") == "odile", "a whole name matches"
    assert player_entity(entries, "Name: Nobody Atall\nInfo: Finn is here.") is None, \
        "a Name: that matches no one is not rescued by other words"
    assert player_entity(entries, "Info: finn and well, lowercase words are not names.") is None
    assert player_entity(entries, "info: finn is tall") is None, "one lowercase word is still not a name"
    assert player_entity(entries, "Info: Finn is tall") == "finn", "a capitalised one is"
    assert player_gender(real) == "M" and player_gender("a woman of forty") == "F"
    assert player_gender("male and female voices") is None and player_gender("tall") is None
    assert player_entity(entries, "Nobody in particular.", configured="odile") == "odile", "config wins"
    assert player_entity(entries, "Finn", configured="nobody") == "finn", "a config slug that is not a character is ignored"
    c = _store().canon
    assert reads_anyone(c, "You walk on in the rain.", "finn") and not reads_anyone(c, "You walk on.", None)
    assert reads_anyone(c, "Corin walks on.", None) and not reads_anyone(c, "The rain falls.", "finn")
    assert reads_anyone(c, "She tilts her head.", None, "Odile stood by the door."), \
        "a pronoun-only passage is about whoever the turns before named"
    assert not reads_anyone(c, "She tilts her head.", None, "The rain fell."), "...if they named anyone"
    assert not reads_anyone(c, "The rain falls.", None, "Odile stood by the door."), "...and it has a pronoun"
    print("10. the player comes from player.md or config; a passage is read if it names someone or says 'you'")


def test_identity_through_a_pronoun_only_when_switched_on():
    """D-035. Off by default (D-024: identity is first write wins, so a wrong attribution is permanent). With a reach
    it takes a look through "she" or "he" for the one compatible character the nearest sentences name, and no further:
    measured on 36 look sentences from soak replies where the intended character is known, the rule was right 34 times
    when it answered and answered about half the time."""
    def run(claim_of, prose, before, turn, reach, genders=None, entity="she"):
        s = _store()
        who = make_who(s.canon, prose, genders=genders or {}, player="finn", before=before, identity_reach=reach)
        return s, _run(s, claim_of(entity), prose, who, turn=turn)
    hair = lambda ent: _claim(ent, "identity.hair", "set", "raven", "her raven hair")           # noqa: E731
    prose = "She turns, her raven hair loose."
    s, d = run(hair, prose, "Odile Marsh waited by the door.", 1, None)
    assert (d.status, d.reason) == ("reject", "unresolved_entity"), "off (the default): a pronoun never names an identity subject"
    s, d = run(hair, prose, "Odile Marsh waited by the door.", 1, 2)
    assert (d.status, d.entity, d.via) == ("commit", "odile", "pronoun"), d
    assert s.canon.current("odile", "identity.hair") == "raven"
    # two possible people in the nearest sentence, or the name too far back, is still unclear
    s, d = run(hair, prose, "Odile Marsh and Tamsin Reeve waited.", 1, 2)
    assert (d.status, d.reason) == ("reject", "unresolved_entity"), d
    far = "Odile Marsh waited. The rain fell. The tide came in. The lamps burned low."
    s, d = run(hair, prose, far, 1, 2)
    assert (d.status, d.reason) == ("reject", "unresolved_entity"), "more than two sentences back"
    s, d = run(hair, prose, far, 1, 30)
    assert (d.status, d.entity) == ("commit", "odile"), "the reach is the switch's number"
    # a quote about a man is still not about her; and the Scribe naming someone the passage does not name works too
    s, d = run(lambda e: _claim(e, "identity.hair", "set", "raven", "His raven hair"), "He turns, his raven hair loose.",
               "Odile Marsh waited by the door.", 1, 2, genders={"odile": "F"})
    assert d.status == "reject", d
    named = lambda e: _claim("Odile", "identity.eyes", "set", "green", "her green eyes")      # noqa: E731
    s, d = run(named, "She tilts her green eyes.", "Odile Marsh waited by the door.", 1, 2, entity="Odile")
    assert (d.status, d.via) == ("commit", "context"), d
    s, d = run(named, "She tilts her green eyes.", "Odile Marsh waited by the door.", 1, None, entity="Odile")
    assert (d.status, d.reason) == ("reject", "entity_not_in_passage"), "off: as D-024 says"
    # first write still wins: a later, different value through a pronoun is not committed over the first
    s, d = run(hair, prose, "Odile Marsh waited by the door.", 1, 2)
    d2 = _run(s, _claim("she", "identity.hair", "set", "platinum", "her platinum hair"), "She smiles, her platinum hair bright.",
              make_who(s.canon, "She smiles, her platinum hair bright.", before="Odile Marsh waited.", identity_reach=2), turn=2)
    assert s.canon.current("odile", "identity.hair") == "raven" and d2.status != "commit", (d2, s.canon.current("odile", "identity.hair"))
    print("9c. identity through a pronoun is off by default and, with a reach, answers only for one compatible character "
          "within that many sentences")


try:
    for fn in (test_a_name_must_be_capitalised_where_it_occurs_and_not_follow_the_,
               test_the_nearest_sentence_that_names_one_character_decides,
               test_a_name_after_the_pronoun_is_the_object,
               test_speech_and_headers_and_the_player_are_not_antecedents,
               test_the_turns_before_count_when_they_are_given,
               test_locating_a_quote_and_splitting_sentences,
               test_quote_helpers,
               test_gender_is_read_from_sentences_that_name_one_character,
               test_the_validator_resolves_pronouns_for_state_and_never_for_identity,
               test_identity_through_a_pronoun_only_when_switched_on,
               test_you_is_the_player_for_every_slot,
               test_a_quote_about_a_woman_is_not_a_fact_about_a_man,
               test_an_empty_who_changes_nothing,
               test_the_player_is_found_from_player_md_or_config):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON REFERENTS TESTS PASSED")
