"""The tic guard (D-064): phrases the Writer keeps reusing, found in code and said back to it.

What broke. A small local Writer feeds on its own recent replies, so what it wrote last turn is what it writes this turn: D-055 counted 103
recurring eight-word runs in one 80-turn story, D-034 saw the turn length grow the same way. `coderain/tics.py` finds the phrases that open in
several of the last replies by plain counting, and the engine says them back ("say it another way") when `generation: {tic_guard: true}`.

 1) fewer than MIN_REPLIES replies, or none, say nothing
 2) a phrase must recur across DIFFERENT replies: the same phrase five times in one reply is not a tic
 3) grammar is not a tic (needs two content words), and a character's or place's name is never content
 4) only the longest version is listed, never a shorter piece of one already listed
 5) the most widespread phrases come first, at most MAX_TICS, and a phrase that is a whole sentence is left out
 6) only the last WINDOW replies count; case, punctuation and the curly apostrophe do not matter; the same replies give the same list
 7) the line: one sentence with every phrase quoted, nothing when there are no tics
 8) the engine: off by default and for anything but a real true; on, one system message after the action and before the chapter directive,
    never stored; the story's own names are not tics; a failure is reported and costs no turn; the line asks for nothing when no phrase recurs
 9) the model copying the line at the start of its reply has it dropped by the echo filter, like the card
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-tics-"))
os.environ["CODERAIN_HOME"] = str(WORK / "home")

from coderain.config import load_config                                    # noqa: E402
from coderain.engine import Engine                                         # noqa: E402
from coderain.memory import SCENE_STATE_HEAD, Entry, Library                # noqa: E402
from coderain.planner import ChapterPlanner                                # noqa: E402
from coderain.tics import HEAD, MAX_PHRASE, MAX_TICS, MIN_REPLIES, WINDOW, find_tics, tic_line   # noqa: E402

TIC = "her breath hitched in her throat"
REPLIES = [f"Rain on the pier. {TIC}. The ferry waits.",
           f"Nothing moves for a while. {TIC}, and the lamp gutters.",
           f"A door bangs somewhere below. {TIC}. She counts the steps.",
           "Gulls wheel over the mudflats and the tide turns."]


def test_too_few():
    assert find_tics([]) == [] and find_tics(REPLIES[:2]) == []
    assert MIN_REPLIES == 3 and TIC in find_tics(REPLIES[:3])
    print("1. fewer than MIN_REPLIES replies say nothing")


def test_different_replies():
    one = ["Her breath hitched in her throat. " * 5, "Rain on the pier.", "The ferry waits."]
    assert find_tics(one) == [], "a phrase repeated inside one reply was a tic"
    assert TIC in find_tics(REPLIES)
    print("2. a phrase must recur across different replies")


def test_grammar_and_names():
    grammar = [f"{x}, but it was not that it was." for x in ("Rain falls", "Light fades", "Voices drop", "Smoke curls")]
    assert find_tics(grammar) == [], find_tics(grammar)
    one_word = [f"{x} in the middle of the {y}." for x, y in (("Rain falls", "night"), ("Light fades", "road"), ("Voices drop", "hall"), ("Smoke curls", "sky"))]
    assert find_tics(one_word) == [], "'in the middle of the' has one content word: grammar with a noun in it, not a tic"
    stock = [f"{x} in the middle of the room." for x in ("Rain falls", "Light fades", "Voices drop", "Smoke curls")]
    assert find_tics(stock) == ["in the middle of the room"], "a stock phrase with two content words is a tic"
    named = [f"Ottoline Pike and Hollis Wren {w}." for w in ("wait", "argue", "leave")]
    assert any("ottoline pike" in t for t in find_tics(named)), "the control: without names a repeated pair of names is a phrase"
    assert find_tics(named, names=["Ottoline Pike", "Hollis Wren"]) == [], "a name was listed as a tic"
    print("3. grammar is not a tic and a name is never content")


def test_longest_only():
    base = "The corner lamp is colder than the first."
    replies = [f"{x} {base}" for x in ("Rain.", "Wind.", "Dusk.", "Fog.")]
    tics = find_tics(replies)
    assert tics, "the long phrase was not found"
    for a in tics:
        for b in tics:
            assert a == b or f" {a} " not in f" {b} ", f"{a!r} is a piece of {b!r}"
    assert any(len(t.split()) >= 7 for t in tics), "the overlapping pieces were not joined into the sentence they came from: " + str(tics)
    assert len(tics) == 1, tics
    print("4. only the longest version is listed:", tics)


def test_ranking_cap_and_length():
    phrases = [f"alpha{i} beta{i} gamma{i}" for i in range(9)]
    replies = []
    for r in range(6):       # each phrase is followed by a word that is different every time, so no two phrases run into one another
        replies.append(". ".join(f"{phrases[i]} zz{r}q{i}" for i in range(9) if i == 0 or r < 3 + (i % 4)) + ".")
    tics = find_tics(replies)
    assert len(tics) == MAX_TICS and tics[0] == "alpha0 beta0 gamma0", tics      # in every reply: first
    sentence = ["one two three four five six seven eight nine ten eleven twelve " * 1 for _ in range(4)]
    assert all(len(t) <= MAX_PHRASE for t in find_tics(sentence))
    long_words = ["supercalifragilistic expialidocious antidisestablishmentarian floccinaucinihilipilification pneumonoultramicroscopic " * 1] * 4
    assert find_tics(long_words) == [], "a phrase longer than MAX_PHRASE was listed"
    print("5. most widespread first, at most MAX_TICS, and nothing longer than MAX_PHRASE")


def test_window_and_normal_form():
    old = [f"The {TIC}." for _ in range(3)]
    words = "copper lantern harbour marrow sparrow thistle velvet quarry ember saddle orchard cinder".split()
    fresh = [f"{words[i]} {words[i + 1]} {words[i + 2]} drifted {words[i + 3]} slowly past." for i in range(WINDOW)]
    assert find_tics(old + fresh) == [], "a phrase that only the old replies share was listed"
    loud = ["Her BREATH hitched, in her throat!", "her breath hitched in her throat...", "Her breath hitched in her ‘throat’."]
    assert "her breath hitched in her" in " ".join(find_tics(loud)) or "breath hitched in her throat" in " ".join(find_tics(loud)), find_tics(loud)
    assert find_tics(REPLIES) == find_tics(list(REPLIES)), "not deterministic"
    print("6. only the last WINDOW replies count; case, punctuation and quotes do not matter; the same replies give the same list")


def test_the_line():
    assert tic_line([]) == ""
    line = tic_line(["her breath hitched", "the corner lamp"])
    assert line == HEAD + '"her breath hitched"; "the corner lamp".', line
    assert "\n" not in line
    print("7. one line, every phrase quoted, nothing for none")


class Cap:
    gen = {"max_tokens": 2000}

    def __init__(self, reply="The door swings open."):
        self.msgs, self.reply = None, reply

    def stream(self, messages, **k):
        self.msgs = messages
        yield self.reply


def engine(replies=REPLIES, place=False, **generation):
    cfg = load_config()
    cfg.generation.update({"trinity_brain": False, "use_memory_tool": False, "think": False, "chapter_outline": True})
    cfg.generation.pop("tic_guard", None)
    cfg.generation.update(generation)
    cfg.raw.pop("canon", None)
    cfg.memory.clear()
    store = Library(WORK / "lib").store(Library(WORK / "lib").create_story(f"Tics {id(replies)} {len(generation)}", "A ferry town."))
    store.upsert_entry("characters.md", Entry(title="Ottoline Pike", slug="ottoline-pike", aliases=["Ottoline"]))
    if place:
        store.upsert_entry("locations.md", Entry(title="Marrow Quay", slug="marrow-quay"))
    for text in replies:
        store.append_turn("player", "I wait.")
        store.append_turn("narrator", text)
    ChapterPlanner(cfg, store, None).replace_all([{"title": "The River Road", "goal": "reach the ford", "status": "active"}])
    eng = Engine(cfg, store)
    eng.llm = Cap()
    return store, eng


def tic_messages(msgs):
    return [m for m in msgs if m["role"] == "system" and m["content"].startswith(HEAD)]


def test_the_engine():
    for value in (None, False, "true", "yes", 1, [], 0):
        store, eng = engine(**({} if value is None else {"tic_guard": value}))
        list(eng.turn("I look around."))
        assert eng.tic_guard is False and not tic_messages(eng.llm.msgs), f"tic_guard={value!r} turned it on"
    store, eng = engine(tic_guard=True)
    list(eng.turn("I look around."))
    msgs = eng.llm.msgs
    got = tic_messages(msgs)
    assert len(got) == 1 and TIC in got[0]["content"], [m["content"][:50] for m in msgs if m["role"] == "system"]
    assert msgs[-1]["role"] == "system" and "THIS CHAPTER" in msgs[-1]["content"], "the chapter goal must stay the last thing read"
    assert msgs[-2]["content"] == got[0]["content"], "the line sits right before the chapter directive"
    # the scene-state message (D-072) sits before the action; its place is pinned in prompt_layout_test
    rest = [m for m in msgs if not m["content"].startswith(SCENE_STATE_HEAD)]
    assert rest[-3]["role"] == "user" and "look around" in rest[-3]["content"], "and after the player's action"
    assert all(HEAD not in t["text"] for t in store.turns()), "the line was stored in the transcript"
    # only the narrator's replies are read: the player's own repeated action is the player's business
    store, eng = engine(replies=["Wind rises.", "Rain falls.", "Gulls cry.", "Fog lifts."], tic_guard=True)
    for _ in range(4):
        store.append_turn("player", "I wait by the old stone gate.")
        store.append_turn("narrator", "The tide goes out.")
    store.append_turn("player", "I wait by the old stone gate.")
    list(eng.turn("I wait by the old stone gate."))
    assert not any("old stone gate" in m["content"] for m in tic_messages(eng.llm.msgs)), "the player's repeated action was said back as a tic"
    # a story's own name recurring is not a tic
    named = [f"{w} at the Marrow Quay." for w in ("Wind rises", "Rain falls", "Gulls cry")]
    store, eng = engine(replies=named, tic_guard=True)
    list(eng.turn("I look around."))
    assert tic_messages(eng.llm.msgs), "the control: without the place in the story, 'the marrow quay' is a phrase that recurs"
    store, eng = engine(replies=named, place=True, tic_guard=True)
    list(eng.turn("I look around."))
    assert not tic_messages(eng.llm.msgs), "the story's own place name was said back as a tic: " + str(tic_messages(eng.llm.msgs))
    # nothing recurs: no message at all (not an empty header)
    store, eng = engine(replies=REPLIES[3:] * 1 + ["Different words entirely."] * 2, tic_guard=True)
    list(eng.turn("I look around."))
    assert not tic_messages(eng.llm.msgs)
    # a failure reports once and costs no turn
    import coderain.engine as eng_mod
    real = eng_mod.find_tics
    eng_mod.find_tics = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        store, eng = engine(tic_guard=True)
        out = "".join(eng.turn("I look around."))
        assert out.strip() and not tic_messages(eng.llm.msgs)
        assert [h for h in store.health(20) if h["stage"] == "tic-guard"], "the failure was not reported"
    finally:
        eng_mod.find_tics = real
    print("8. off by default and for anything but a real true; on, one system message after the action and before the chapter directive, "
          "never stored; names are not tics; a failure costs no turn")


def test_echo_filter():
    store, eng = engine(tic_guard=True)
    line = tic_line(find_tics([t["text"] for t in store.turns() if t["role"] == "narrator"], ["Ottoline Pike", "Ottoline"]))
    assert line.startswith(HEAD), line
    eng.llm = Cap(reply=line + "\nThe lamp gutters and goes out.")
    out = "".join(eng.turn("I look around."))
    assert HEAD not in out and "The lamp gutters and goes out." in out, out
    print("9. a copy of the line at the start of the reply is dropped by the echo filter, and the prose after it is kept")


test_too_few()
test_different_replies()
test_grammar_and_names()
test_longest_only()
test_ranking_cap_and_length()
test_window_and_normal_form()
test_the_line()
test_the_engine()
test_echo_filter()
print("\nTICS TESTS PASSED")
