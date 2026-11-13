"""Fate in the turn path (D-045): off costs nothing, on costs one call, a failure costs the turn nothing.

A stub model answers both calls: the Writer (stream) and the fate stage (complete). The die is forced by patching
fate.derive_roll, so each case names the tier it exercises.

 1) off by default: no model call for fate, nothing in the Writer's messages
 2) on: exactly one fate call; the Writer gets the steering AFTER the player's action and BEFORE the chapter
    directive (so the chapter goal is still the last thing read); the note carries no die; the die and tier are on
    the event line only when asked
 3) preview: the call is made and recorded and the Writer is sent nothing; the idea is on the event line
 4) retry and swipe reuse the cached direction (same sentence, no new call); an undo drops it and a different
    action asks again; the same action after an undo gets the same die
 5) a failing, garbage or hanging-style reply, on both tries, never breaks the turn: the prose is stored, the Writer's
    messages are as if fate were off, and there is one health row; a model that raises is asked once, not twice
 5b) one unusable first answer (not JSON, too long, the wrong shape, a copied label, the player as subject) gets one more
    try that names the refusal, and the recovered line is cached and names the model (D-053, from the first real runs)
 5c) a nearly-JSON reply (speech closing the sentence, the JSON string's closing quote missing) is repaired on the first
    try; the model is never shown the Writer's world-update block
 6) a quiet scene (stakes none) on a setback or a windfall gives no steering; a natural roll ignores the label
 7) a setback that kills the player is vetoed; a direction that repeats an earlier one is asked for again once
 8) RPG saves skip it (one health row for the whole save, not per turn); the opening and a Continue never use it
 9) the quad pipeline: in simple mode (no Logic Agent) fate runs and the Writer is steered; once an authored event rule
    brings the Director back, fate steps aside with one health row for the save
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="cr-fate-engine-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import fate                                   # noqa: E402
from coderain.config import load_config                    # noqa: E402
from coderain.engine import Engine                         # noqa: E402
from coderain.memory import Entry, Library                 # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
_n = [0]
FATE_SIG = "You write ONE hidden steering line"


class Stub:
    """The Writer streams prose; the fate stage asks complete() and gets `replies` in turn."""
    model = "stub-model"

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.fate_calls, self.fate_msgs, self.writer_msgs = 0, [], []
        self.gen = {}

    def complete(self, messages, **k):
        assert messages[0]["content"].startswith(FATE_SIG), messages[0]["content"][:80]
        self.fate_calls += 1
        self.fate_msgs.append(messages)
        r = self.replies.pop(0) if self.replies else reply("A bell rings in the harbour.")
        if isinstance(r, Exception):
            raise r
        return r

    def stream(self, messages, **k):
        self.writer_msgs.append(messages)
        yield "She keeps walking, the box under her arm."


def reply(text, stakes="some"):
    return json.dumps({"stakes": stakes, "direction": text})


def make(mode="off", show_die=False, with_chapter=False, think=False, trinity=False, stub=None):
    _n[0] += 1
    slug = lib.create_story(f"Fate engine {_n[0]}", "A courier crosses a frozen kingdom.")
    store = lib.store(slug)
    store.append_turn("narrator", "The road north is empty.")
    if with_chapter:
        store.upsert_entry("memory/outline.md", Entry(title="Chapter 1", slug="chapter-1",
                                                      attrs={"status": "active"}, body="Reach the northern gate."))
    if mode != "off" or show_die:
        fate.set_settings(store, mode, show_die)
    cfg = load_config()
    cfg.generation["trinity_brain"] = trinity
    if trinity:
        cfg.raw["trinity"] = {}
    cfg.generation["think"] = think
    # The stub below refuses every call that is not a fate call, so the story must not plan a first chapter of its
    # own (D-051). The one case that checks the chapter directive supplies its chapter by hand and keeps the outline on.
    cfg.generation["chapter_outline"] = with_chapter
    eng = Engine(cfg, store)
    stub = stub or Stub()
    eng.llm = stub
    return eng, store, stub


ROLLS = []


def force(face):
    """Pin the die, and remember what the stage asked it for (seed, turn, action, nonce)."""
    def pinned(*a, **k):
        ROLLS.append(a)
        return face
    fate.derive_roll = pinned


REAL_ROLL = fate.derive_roll


def play(eng, action="I keep walking north.", notes=None):
    return "".join(eng.turn(action, on_stage=(notes.append if notes is not None else None)))


def steering(msgs):
    return [m["content"] for m in msgs if m["role"] == "system" and m["content"].startswith("Hidden steering")]


def health(store):
    return [h for h in store.health(50) if h["stage"] == "fate"]


def test_off():
    force(5)
    eng, store, stub = make("off")
    play(eng)
    assert stub.fate_calls == 0 and not steering(stub.writer_msgs[0]), "fate ran while off"
    assert fate.read(store) == [] and not eng._rpg_events
    print("1. off by default costs nothing: no call, no note, no file")


def test_on_order_and_event():
    force(5)                                               # natural
    eng, store, stub = make("on", with_chapter=True)
    stub.replies = [reply("A bell rings in the harbour.")]
    play(eng)
    assert stub.fate_calls == 1
    msgs = stub.writer_msgs[0]
    assert "World updates (required)" in msgs[0]["content"], "the Writer lost its world-update block: this case proves nothing"
    assert "World updates (required)" not in stub.fate_msgs[0][1]["content"], \
        "the model was shown the Writer's sidecar instructions (6 of 106 real replies copied that format)"
    sys_tail = [m["content"] for m in msgs if m["role"] == "system"][1:]
    assert len(steering(msgs)) == 1 and "A bell rings in the harbour." in steering(msgs)[0]
    idx = {k: next(i for i, m in enumerate(msgs) if m["role"] == "system" and m["content"].startswith(k))
           for k in ("Hidden steering", "# THIS CHAPTER")}
    assert idx["Hidden steering"] < idx["# THIS CHAPTER"], "the steering must come BEFORE the chapter directive"
    assert msgs[-1]["content"].startswith("# THIS CHAPTER"), "the chapter goal must stay the last thing read"
    note = steering(msgs)[0].lower()
    for banned in ("d20", "natural", "stakes", "tier", " 5"):
        assert banned not in note.replace("never mention it, dice, luck, odds or fate in the story", ""), banned
    assert not eng._rpg_events, "the die was shown without show_die"
    assert stub.fate_msgs[0][0]["content"].endswith("/no_think"), "the model was not told to skip reasoning"
    assert ROLLS[-1] == (eng._fate_seed(), len(store.turns()) - 1, "I keep walking north."), ROLLS[-1]
    thinker, _ts, thinker_stub = make("on", think=True)
    play(thinker)
    assert not thinker_stub.fate_msgs[0][0]["content"].endswith("/no_think"), "the soft switch was sent to a thinking setup"
    rec = fate.read(store)[0]
    assert rec["tier"] == "natural" and rec["roll"] == 5 and rec["text"] == "A bell rings in the harbour."
    assert stub.fate_msgs[0][1]["content"].count("CHAPTER GOAL:") == 1 and "Reach the northern gate." in stub.fate_msgs[0][1]["content"]
    eng2, _s2, stub2 = make("on", show_die=True)
    stub2.replies = [reply("A bell rings.")]
    play(eng2)
    assert eng2._rpg_events == ["fate d20 5: natural"], eng2._rpg_events
    assert "A bell rings." not in " ".join(eng2._rpg_events), "on must never show the sentence"
    print("2. on: one call; the steering sits after the action and before the chapter goal; no die in the note; "
          "the die shows only when asked")


def test_preview():
    force(14)                                              # surprise
    eng, store, stub = make("preview")
    stub.replies = [reply("A lamplighter hurries past with a ladder.")]
    play(eng)
    assert stub.fate_calls == 1 and not steering(stub.writer_msgs[0]), "preview must send the Writer nothing"
    assert eng._rpg_events == ["fate (preview) d20 14: surprise: A lamplighter hurries past with a ladder."], eng._rpg_events
    assert fate.read(store)[0]["text"] == "A lamplighter hurries past with a ladder."
    print("3. preview: the call is made and recorded, the Writer is sent nothing, the idea is on the event line")


def test_retry_swipe_undo():
    force(12)
    eng, store, stub = make("on")
    stub.replies = [reply("A rival offers a bargain at the quay.")]
    play(eng, "I walk to the quay.")
    first = steering(stub.writer_msgs[0])[0]
    ok, action = eng.rollback_for_retry()
    assert ok and action == "I walk to the quay."
    "".join(eng.regenerate(action))
    assert stub.fate_calls == 1, "a retry asked the model again"
    assert steering(stub.writer_msgs[1]) == [first], "a retry changed the direction"
    "".join(eng.swipe_generate())
    assert stub.fate_calls == 1 and steering(stub.writer_msgs[2]) == [first], "a swipe changed the direction"
    assert len(fate.read(store)) == 1
    assert eng.undo_last() is True
    assert fate.read(store) == [], "an undo kept the exchange's record"
    stub.replies = [reply("Fog rolls over the harbour wall.")]
    play(eng, "I wait by the wall.")
    assert stub.fate_calls == 2 and "Fog rolls over" in steering(stub.writer_msgs[3])[0]
    # undo, then the SAME action: same die, a new sentence (the record was dropped), no state touched
    assert eng.undo_last() is True
    stub.replies = [reply("A gull steals a loaf from the market stall.")]
    play(eng, "I wait by the wall.")
    assert fate.read(store)[0]["roll"] == 12
    print("4. retry and swipe reuse the cached direction with no new call; an undo drops it; a new action asks again")


def test_failures():
    force(5)
    base_eng, _bs, base_stub = make("off")
    play(base_eng)
    base_roles = [m["role"] for m in base_stub.writer_msgs[0]]
    for label, bad in (("garbage", "not json at all"), ("empty", ""), ("raises", RuntimeError("network died")),
                       ("no direction", json.dumps({"stakes": "some"})),
                       ("sidecar shape", json.dumps({"deltas": {}})),
                       ("fenced", json.dumps({"stakes": "some", "direction": "```x```"})),
                       ("too long", json.dumps({"stakes": "some", "direction": "word " * 80})),
                       ("a label", json.dumps({"stakes": "some", "direction": "a small stroke of luck for the player: help arrives"})),
                       ("the player", json.dumps({"stakes": "some", "direction": "You turn to the keeper and buy ale."}))):
        eng, store, stub = make("on")
        stub.replies = [bad, bad]                           # BOTH tries are bad: one is not enough to fail any more
        notes = []
        out = play(eng, notes=notes)
        assert out.startswith("She keeps walking"), (label, out)
        assert store.turns()[-1]["role"] == "narrator", (label, "the turn was not stored")
        msgs = stub.writer_msgs[0]
        assert not steering(msgs) and [m["role"] for m in msgs] == base_roles, (label, "the messages changed")
        assert len(health(store)) == 1, (label, health(store))
        assert any("Fate FAILED" in n for n in notes), (label, notes)
        assert fate.read(store) == [], (label, "a failure was cached")
        # a dead or hanging server is asked once, not twice: the second wait would only double the delay
        assert stub.fate_calls == (1 if label == "raises" else fate.ATTEMPTS), (label, stub.fate_calls)
    print("5. a garbage, empty, raising, fenced, over-long, labelled or player-subject reply, twice, never breaks the "
          "turn: one health row each; a raising model is asked once")


def test_second_try():
    """The first real runs (a 4B and an 8B model) lost a third of the exchanges to one unusable first answer."""
    force(12)
    good = reply("A lamplighter hurries past with a ladder.")
    for label, bad, why in (("garbage", "not json at all", "JSON"),
                            ("too long", json.dumps({"stakes": "some", "direction": "word " * 90}), "300"),
                            ("wrong shape", json.dumps({"deltas": {}}), "direction"),
                            ("a label", json.dumps({"stakes": "some", "direction": "a surprising but harmless development: a crab"}), "words"),
                            ("the player", json.dumps({"stakes": "some", "direction": "You walk to the quay and look around."}), "player")):
        eng, store, stub = make("on")
        stub.replies = [bad, good]
        notes = []
        play(eng, notes=notes)
        assert stub.fate_calls == 2, (label, stub.fate_calls)
        assert "lamplighter" in steering(stub.writer_msgs[0])[0], (label, "the second answer was not used")
        assert not health(store) and not any("FAILED" in n for n in notes), (label, health(store), notes)
        second = stub.fate_msgs[1][1]["content"]
        assert "YOUR LAST ANSWER WAS REFUSED" in second and why in second, (label, second[-300:])
        assert "REFUSED" not in stub.fate_msgs[0][1]["content"], "the first request already named a refusal"
        assert fate.read(store)[0]["text"] == "A lamplighter hurries past with a ladder."
        assert fate.read(store)[0]["model"] == "stub-model", "the record did not name the model"
        # the recovered exchange is cached: a retry asks nobody
        ok, action = eng.rollback_for_retry()
        "".join(eng.regenerate(action))
        assert stub.fate_calls == 2, (label, "a retry asked again after a recovered answer")
    print("5b. an unusable first answer gets one more try that names the refusal; the recovered line is cached")


def test_repaired_reply():
    """The commonest real failure after the length limit: a line that ends in speech, closed by an escaped quote with the
    JSON string's own closing quote missing. It is used on the first try, with no second call and no health row."""
    force(12)
    eng, store, stub = make("on")
    stub.replies = ['```json\n{"stakes": "some", "direction": "Ottoline eyes you, and replies, \\"The ferry is out.\\"}\n```']
    play(eng)
    assert stub.fate_calls == 1 and not health(store), (stub.fate_calls, health(store))
    line = steering(stub.writer_msgs[0])[0]
    assert 'Ottoline eyes you, and replies, "The ferry is out."' in line, line
    assert fate.read(store)[0]["text"] == 'Ottoline eyes you, and replies, "The ferry is out."', "the closing quote was cut"
    print("5c. a nearly-JSON reply is repaired and used on the first try; the line keeps its closing quote")


def test_quiet_scene():
    for face, tier in ((1, "setback"), (20, "windfall")):
        force(face)
        eng, store, stub = make("preview")
        stub.replies = [reply("A beam falls across the path.", stakes="none")]
        play(eng)
        assert eng._rpg_events == [f"fate (preview) d20 {face}: quiet scene, no steering"], eng._rpg_events
        rec = fate.read(store)[0]
        assert rec["text"] == "" and rec["tier"] == tier and rec["stakes"] == "none"
        eng_on, _s, stub_on = make("on")
        stub_on.replies = [reply("A beam falls across the path.", stakes="none")]
        play(eng_on)
        assert not steering(stub_on.writer_msgs[0]), "a quiet scene was steered"
    force(5)                                                # a natural roll ignores the label
    eng, store, stub = make("on")
    stub.replies = [reply("A beam creaks overhead.", stakes="none")]
    play(eng)
    assert len(steering(stub.writer_msgs[0])) == 1
    print("6. stakes none switches a setback or a windfall off; a natural roll ignores the label")


def test_veto_and_repeat():
    force(1)
    eng, store, stub = make("on")
    stub.replies = [reply("The roof gives way and you die in the collapse.")]
    notes = []
    play(eng, notes=notes)
    assert not steering(stub.writer_msgs[0]) and len(health(store)) == 1 and "vetoed" in health(store)[0]["reason"]
    assert fate.read(store) == []
    # a PINNED character is protected by name; an ordinary one is not (the player's "you" would hide this
    # if the same sentence also said "you", so the sentences here never do)
    force(1)
    for victim, protected in (("Odile Marsh", True), ("Bram Halloran", False)):
        eng, store, stub = make("on")
        store.upsert_entry("characters.md", Entry(title="Odile Marsh", slug="odile-marsh", attrs={"pinned": "true"}))
        store.upsert_entry("characters.md", Entry(title="Bram Halloran", slug="bram-halloran"))
        stub.replies = [reply(f"{victim} is killed when the roof gives way.")]
        play(eng)
        assert bool(steering(stub.writer_msgs[0])) is (not protected), (victim, steering(stub.writer_msgs[0]))
        assert bool(fate.read(store)) is (not protected) and len(health(store)) == (1 if protected else 0), victim
    force(5)
    eng, store, stub = make("on")
    stub.replies = [reply("A rival smuggler offers a bargain at the quay.")]
    play(eng, "I walk to the quay.")
    stub.replies = [reply("Another rival smuggler offers a bargain tonight."), reply("The lamplighter runs past with a ladder.")]
    play(eng, "I keep walking.")
    assert stub.fate_calls == 3, stub.fate_calls
    assert "lamplighter" in steering(stub.writer_msgs[1])[0], "the repeat was not asked for again"
    assert "REPEATED" in stub.fate_msgs[2][1]["content"] or "REPEATED" in stub.fate_msgs[1][1]["content"]
    eng, store, stub = make("on")
    stub.replies = [reply("A rival smuggler offers a bargain at the quay."),
                    reply("Another rival smuggler offers a bargain tonight."),
                    reply("A third rival smuggler offers a bargain somewhere.")]
    play(eng, "I walk to the quay.")
    play(eng, "I keep walking.")
    assert not steering(stub.writer_msgs[1]) and "repeated" in health(store)[0]["reason"], health(store)
    print("7. a setback that kills the player is vetoed; a repeat is asked for again once, then dropped with a reason")


def test_skips():
    force(5)
    eng, store, stub = make("on")
    st = store.rpg_state()
    st["enabled"] = True
    store.set_rpg_state(st)
    play(eng, "I act.")
    play(eng, "I act again.")
    assert stub.fate_calls == 0, "fate ran in an RPG save"
    assert len(health(store)) == 1 and "RPG" in health(store)[0]["reason"], health(store)
    eng, store, stub = make("on")
    "".join(eng.opening())
    "".join(eng.continue_story())
    assert stub.fate_calls == 0, "fate ran on an opening or a Continue"
    assert not health(store), "fate tried (and failed) on an opening or a Continue: " + str(health(store))
    play(eng, "Now I act.")
    assert stub.fate_calls == 1
    "".join(eng.continue_story())
    assert stub.fate_calls == 1, "a Continue after an action turn reused the action"
    print("8. RPG saves skip fate with one health row for the save; the opening and a Continue never use it")


class TrinityStub(Stub):
    """Also plays the Director: anything that is not a fate call is a Director plan with nothing to apply."""

    def __init__(self, replies=None):
        super().__init__(replies)
        self.director_calls = 0

    def complete(self, messages, **k):
        if messages[0]["content"].startswith(FATE_SIG):
            return super().complete(messages, **k)
        self.director_calls += 1
        return json.dumps({"beat_plan": "b", "envelope": {"v": 1, "deltas": {}}})


def test_trinity():
    force(5)
    # Simple Story mode on the quad pipeline: the Logic Agent is skipped, so nothing else plans the turn and fate runs,
    # and the Writer gets the steering where it would without the quad pipeline.
    eng, store, stub = make("on", trinity=True, stub=TrinityStub())
    assert eng.trinity is not None, "the quad pipeline did not come up; this case would prove nothing"
    play(eng, "I keep walking north.")
    assert stub.fate_calls == 1 and stub.director_calls == 0, (stub.fate_calls, stub.director_calls)
    assert len(steering(stub.writer_msgs[0])) == 1, "the Writer was not steered in simple mode on the quad pipeline"
    assert not health(store), health(store)
    # An authored event rule forces the Director back on, and the Director already plans the turn as fact:
    # fate steps aside, with one health row for the save however many turns follow.
    eng, store, stub = make("on", trinity=True, stub=TrinityStub())
    store.upsert_entry("events.md", Entry(title="The gate shuts", slug="the-gate-shuts", attrs={},
                                          body="When the courier reaches the gate, it shuts."))
    play(eng, "I reach the gate.")
    play(eng, "I wait.")
    assert stub.fate_calls == 0 and stub.director_calls >= 1, (stub.fate_calls, stub.director_calls)
    assert len(health(store)) == 1 and "Director" in health(store)[0]["reason"], health(store)
    assert not steering(stub.writer_msgs[0]), "fate steered a turn the Director planned"
    print("9. the quad pipeline in simple mode is steered like any other; with the Director planning, fate steps aside once")


for fn in (test_off, test_on_order_and_event, test_preview, test_retry_swipe_undo, test_failures, test_second_try,
           test_repaired_reply, test_quiet_scene, test_veto_and_repeat, test_skips, test_trinity):
    fate.derive_roll = REAL_ROLL
    fn()
fate.derive_roll = REAL_ROLL
shutil.rmtree(HOME, ignore_errors=True)
print("\nFATE ENGINE TESTS PASSED")
