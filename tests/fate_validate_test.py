"""Fate's pure-code checks: what a direction may say, and what the model and the Writer are told (D-045).

The model proposes one sentence and a `stakes` label; code decides whether to use it. Invariant 1: the validator is
pure code, never an LLM.

 1) clean_line: one line, bounded, no fences or headings or lists; too long is refused, not cut. Refused too, each
    seen in a real run on a 4B and an 8B model (D-053): the kind's description copied back as a label, a line under
    three words, one that stops mid-sentence, one whose subject is the player. A label at the very start is dropped
    instead. A possessive ("Your pack is lost") and a world event that mentions the player are fine
 2) parse_reply: the stakes label is 'some' only when the model said so (missing, invalid or any other word is none),
    and a reply that is not an object, or has no direction, is refused with a reason
 3) armour: a setback that kills or removes the player or a protected character is vetoed; the same words about
    anyone else, or in another tier, are not
 4) repeats: a direction that restates a recent one (three content words in a row) is found; a different one is not
 5) leaks: the mechanism said aloud, or the steering line copied back (six words in a row), is found
 6) the Writer's directive never carries the die, the tier or a number, and says what it must not override
 7) the request to the model names the kind, carries the chapter goal and the recent directions, and names a repeat
 8) the event line: preview shows everything, on shows the die only when asked and never the sentence
 9) the record names the model (the real client keeps it on its profile; it was blank until a real run showed it)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coderain import fate                                   # noqa: E402


def test_clean_line():
    assert fate.clean_line("  A courier  arrives\nat the gate. ") == ("A courier arrives at the gate.", "")
    assert fate.clean_line("- A bell rings in the harbour.") == ("A bell rings in the harbour.", "")
    assert fate.clean_line('"The lamp gutters."')[0] == "The lamp gutters."
    for bad in ("", "   ", None, 7, ["x"], "```json\nx```", "a `code` span"):
        text, why = fate.clean_line(bad)
        assert text == "" and why, (bad, text, why)
    def line(n):                                            # n characters, many words, no end punctuation
        return ("ab " * n)[:n - 1] + "z"
    ok, _ = fate.clean_line(line(fate.MAX_TEXT))
    assert len(ok) == fate.MAX_TEXT
    text, why = fate.clean_line(line(fate.MAX_TEXT + 1))
    assert text == "" and "limit" in why, (text, why)
    assert fate.MAX_TEXT >= 300, "the first real runs wrote 201 to 284 characters when asked for 20 words"
    # an exact label at the start is dropped, the sentence behind it kept
    for labelled, kept in (
            ("a surprising but harmless development: a crab scuttles out from under the bar",
             "a crab scuttles out from under the bar"),
            ("A setback: Bram demands to see the letter before you may speak",
             "Bram demands to see the letter before you may speak"),
            ("a small stroke of luck for the player: the ferryman offers a free crossing",
             "the ferryman offers a free crossing"),
            ("The ordinary next beat: Ottoline names a price for the room", "Ottoline names a price for the room"),
            ("an unexpected but harmless development: a gull lands on the rail and stares",
             "a gull lands on the rail and stares")):
        assert fate.clean_line(labelled) == (kept, ""), (labelled, fate.clean_line(labelled))
    assert fate.clean_line("A surprise guest arrives: the tax collector, early") == \
        ("A surprise guest arrives: the tax collector, early", ""), "only the exact label forms are stripped"
    # what stays refused: a label in the middle, a stub of a line, a cut-off line, the player as the subject
    for bad, word in (("As you step onto the path, a surprising but harmless development: a flock rises", "description"),
                      ("a small stroke of luck for the player: help arrives", "words"),
                      ("a small stroke of luck for the player: help", "words"),
                      ("A sudden gust of wind whips the rain into a frenzy, scattering the sample:", "mid-sentence"),
                      ("The gate opens, and the guard shrugs,", "mid-sentence"),
                      ("The sample scatters across the deck " + chr(0x2014), "mid-sentence"),
                      ("You turn to the keeper and buy a tankard of ale", "player"),
                      ("You're handed a folded note by a passing child", "player")):
        text, why = fate.clean_line(bad)
        assert text == "" and word in why, (bad, text, why)
    for fine in ("Your pack is torn open by a snagged branch.", "A guard stops you at the gate and asks for a pass.",
                 "As you reach the door, a bell rings twice behind you."):
        assert fate.clean_line(fine) == (fine, ""), fine
    print("1. one clean line, bounded; fences, empties, over-long, labelled, stub, cut-off and player-subject lines are refused")


def test_parse_reply():
    assert fate.parse_reply({"stakes": "some", "direction": "The tide turns."}) == ("some", "The tide turns.", "")
    assert fate.parse_reply({"stakes": "SOME ", "direction": "The tide turns."})[0] == "some"
    for stakes in ("none", "", "high", "low", "yes", True, None, 1):
        assert fate.parse_reply({"stakes": stakes, "direction": "The tide turns."})[0] == "none", stakes
    assert fate.parse_reply({"direction": "The tide turns."})[0] == "none", "a missing label must mean none"
    for obj in (None, [], "text", 5, {"stakes": "some"}, {"stakes": "some", "direction": ""},
                {"stakes": "some", "direction": ["a"]}):
        s, text, why = fate.parse_reply(obj)
        assert text == "" and why, (obj, text, why)
    print("2. stakes is 'some' only when said; a bad or empty reply is refused with a reason")


def test_armour():
    prot = ["odile marsh", "odile", "the courier"]
    assert fate.armour("Odile is killed when the roof gives way.", "setback", prot) == "killed"
    assert fate.armour("The roof gives way and you die.", "setback", prot) == "die"
    assert fate.armour("Your pack is destroyed in the fall.", "setback", prot) == "destroyed"
    assert fate.armour("A guard dies in the collapse.", "setback", prot) == "", "an unprotected NPC may die"
    assert fate.armour("The roof gives way and slows you down.", "setback", prot) == ""
    assert fate.armour("Odile is killed when the roof gives way.", "natural", prot) == "", "only a setback is vetoed"
    assert fate.armour("Odile is killed when the roof gives way.", "windfall", prot) == ""
    assert fate.armour("The Courier is crippled by the fall.", "setback", prot) == "crippled", "an alias is protected"
    assert fate.armour("Odilea dies.", "setback", prot) == "", "a name is matched as a whole word"
    print("3. a setback that kills or removes a protected character is vetoed; others and other tiers are not")


def test_repeats_and_leaks():
    recent = ["A rival smuggler offers a bargain at the quay.", "Fog rolls over the harbour wall."]
    assert fate.repeats("Another rival smuggler offers a bargain tonight.", recent)
    assert not fate.repeats("The lamplighter runs past with a ladder.", recent)
    assert not fate.repeats("The lamplighter runs past.", [])
    assert fate.leaks("You rolled the dice and hoped.", "x y")
    assert fate.leaks("It was a clear d20 moment.", "")
    assert fate.leaks("A stranger offers a bargain at the old quay tonight.", "stranger offers a bargain at the old quay")
    assert not fate.leaks("A stranger waits at the quay.", "A rival smuggler offers a bargain at the quay.")
    assert not fate.leaks("She rolled a barrel along the dock.", "x")
    long = "The old lamplighter hurries past the harbour with a long ladder"
    assert fate.leaks("Beside the old lamplighter hurries past the harbour wall.", long), "six words copied must count"
    assert not fate.leaks("A lamplighter hurries past the harbour at dusk.", long), "five words copied must not"
    print("4-5. a repeat and a leak are found; a different line and an ordinary 'rolled' are not")


def test_directive_and_request():
    d = fate.directive("A bell rings in the harbour.")
    assert "A bell rings in the harbour." in d and "never mention it" in d
    assert "does not override the chapter goal" in d and "Do not kill" in d
    for banned in ("d20", "roll", "setback", "windfall", "natural", "surprise", "tier", "stakes"):
        assert banned not in d.lower().replace("never mention it, dice, luck, odds or fate", ""), banned
    msgs = fate.build_messages("WORLD TEXT", [{"role": "user", "content": "I wait."},
                                              {"role": "assistant", "content": "Rain falls."}],
                               "Odile: raven hair", "Reach the gate.", "I open the door.", "setback",
                               ["Fog rolls in."], offender="rival smuggler offers")
    sysm, user = msgs[0]["content"], msgs[1]["content"]
    assert "a setback" in sysm and "/no_think" in sysm and '"stakes"' in sysm
    assert fate._EXAMPLE["setback"] in sysm, "the example of the shape is not in the request"
    assert "REFUSED" not in user and "REFUSED: the direction is under 3 words" in fate.build_messages(
        "w", [], "", "", "a", "setback", [], note="the direction is under 3 words")[1]["content"]
    for kind in fate._KIND:                                  # every tier has an example, and the validator accepts it
        assert fate.clean_line(fate._EXAMPLE[kind]) == (fate._EXAMPLE[kind], ""), (kind, "an example the checks refuse")
    assert set(fate._EXAMPLE) == set(fate._KIND) == {name for name, _lo, _hi in fate.BANDS}
    assert "WORLD TEXT" in user and "Odile: raven hair" in user and "CHAPTER GOAL:\nReach the gate." in user
    assert "Player: I wait." in user and "Narrator: Rain falls." in user and "PLAYER ACTION:\nI open the door." in user
    assert "- Fog rolls in." in user and "rival smuggler offers" in user
    assert "/no_think" not in fate.build_messages("w", [], "", "", "a", "natural", [], no_think=False)[0]["content"]
    assert "a setback" not in fate.build_messages("w", [], "", "", "a", "natural", [])[0]["content"]
    print("6-7. the Writer's note carries no die or tier; the model's request names the kind, the goal and the repeats")


def test_event_line():
    rec = {"roll": 14, "tier": "surprise", "text": "A bell rings."}
    quiet = {"roll": 2, "tier": "setback", "text": ""}
    assert fate.event_line(rec, "preview", False) == "fate (preview) d20 14: surprise: A bell rings."
    assert fate.event_line(quiet, "preview", False) == "fate (preview) d20 2: quiet scene, no steering"
    assert fate.event_line(rec, "on", False) is None
    assert fate.event_line(rec, "on", True) == "fate d20 14: surprise", "on shows the die, never the sentence"
    assert fate.event_line(quiet, "on", True) == "fate d20 2: quiet scene"
    assert fate.event_line(rec, "off", True) is None
    print("8. preview shows the idea; on shows the die only when asked and never the sentence")


def test_model_name():
    class Profile:
        model = "real-model"

    class Real:                                              # the real client: the name lives on its profile
        profile = Profile()

    class Stub:                                              # a test stub: the name is `model`
        model = "stub-model"

    class Both(Stub):
        profile = Profile()

    assert fate._model_name(Real()) == "real-model", "the real client's model was blank in every run's record"
    assert fate._model_name(Stub()) == "stub-model"
    assert fate._model_name(Both()) == "real-model" and fate._model_name(object()) == ""
    assert len(fate._model_name(type("L", (), {"model": "m" * 200})())) == 80
    print("9. the record names the model: from the client's profile, else the stub's attribute, bounded")


for fn in (test_clean_line, test_parse_reply, test_armour, test_repeats_and_leaks, test_directive_and_request,
           test_event_line, test_model_name):
    fn()
print("\nFATE VALIDATE TESTS PASSED")
