"""The status block's label, copied into the reply (D-080).

What broke. The world-sidecar instruction puts "Nothing changed:" and "Something changed ...:" over its two example blocks,
and small models copy the label into their reply, above the block or instead of it. Only the ```rpg block was removed, so the
label reached the reader, was saved in the transcript, and each saved one taught the model to write it again: in long test
runs it ended 74% of gemma3:4b's replies and half of Gemma 4 E4B's. A few replies also wrote the block's JSON without the fence,
and the reader saw raw JSON.

 1) every label the instruction itself puts over a block is caught, so a reworded instruction cannot slip past
 2) removed: the label alone at the end, in bold, twice, and with the block's JSON under it without the fence
 3) kept, byte for byte: "Nothing changed." with a full stop, sentences that start with the words, the words mid-line, a label
    with more story after it, and braces that are not the block
 4) streamed: split at every point, one character at a time or all at once, the same text comes out, a label never appears on
    the way, and ordinary text is not held back
 5) the engine, single-brain: neither the reader nor the transcript gets the label, the block under it still applies, and a
    block written without its fence is said in the health log
 6) the engine, quad: the Writer's copy of the label (learned from the history) is removed too
 7) a story saved with the label keeps its transcript as it was, and the prompt's history is sent without it
 8) the paths that read a whole reply at once (memory tool, greeting, impersonate) get the same cut
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-label-"))
os.environ["CODERAIN_HOME"] = str(WORK / "home")

from coderain import templates                                                          # noqa: E402
from coderain.config import load_config                                                 # noqa: E402
from coderain.engine import Engine                                                      # noqa: E402
from coderain.memory import Library                                                     # noqa: E402
from coderain.sidecar import drop_status_label, filter_status_label, strip_sidecar      # noqa: E402

lib = Library(WORK / "lib")
_n = [0]

DASH = chr(0x2014)
BLOCK = '```rpg\n{"deltas": {"time_advance": {"days": 0, "phase": "evening"}}}\n```'
CUT = {   # reply as written -> what the reader keeps
    "You step in.\n\nNothing changed:": "You step in.",
    "You step in.\n\nNothing changed:\n\n": "You step in.",
    "You step in.\n**Nothing changed:**\n": "You step in.",
    "You step in.\n\n**Nothing changed**:": "You step in.",
    f"You step in.\n\nSomething changed {DASH} include ONLY the keys that changed:\n": "You step in.",
    "You step in.\n\nSomething changed:": "You step in.",
    "You step in.\n\nNothing changed:\n\nNothing changed:\n": "You step in.",
    'You step in.\n\nNothing changed:\n{"deltas": {}}\n': "You step in.",
    'You step in.\n\nNothing changed:\n```json\n{\n  "deltas": {"location": "tavern"}\n}\n```': "You step in.",
    'You step in.\n\nNothing changed: {"deltas": {"location": "tavern"}}': "You step in.",
    "Nothing changed:": "",
}
KEEP = [
    "You wait an hour. Nothing changed.",
    "You wait.\n\nNothing changed.",
    "Nothing changed, and yet the room felt colder.\n",
    "He waited by the door. Nothing changed:",
    "Nothing changed:\nThen the door opened and the rain came in.",
    "You look again.\nNothing changed: he was still staring at you.\nYou look away.",
    "You read the note.\n\nNothing changed:\n{sigh} he muttered.",
    "You read the note.\n\nNothing changes:",
    "Some things changed:\nthe sign, the door.",
    "No.\n\nSomething is off.\n\n*Nothing* about this feels right:",
    "**She nods.**\n\n> quoted line",
    "",
]


def test_the_instructions_own_labels():
    lines = templates.WORLD_SIDECAR.split("\n")
    labels = []
    for i, line in enumerate(lines):
        if line.startswith("```rpg"):
            above = next((ln for ln in reversed(lines[:i]) if ln.strip()), "")
            labels.append(above)
    assert len(labels) == 2, labels
    for label in labels:
        assert drop_status_label("The rain stops.\n\n" + label)[0] == "The rain stops.", f"not caught: {label!r}"
    print("1. both labels the instruction puts over its example blocks are caught:", [x.encode("ascii", "replace") for x in labels])


def test_cut_and_keep():
    for said, want in CUT.items():
        got, gone = drop_status_label(said)
        assert got == want and gone, (said, got, gone)
    print("2. removed at the end: alone, bold, twice, and with the block's JSON under it without the fence")
    for said in KEEP:
        got, gone = drop_status_label(said)
        assert got == said and not gone, (said, got, gone)
    print("3. prose that only looks like it is left as it was")


def stream(pieces):
    removed: list = []
    out = list(filter_status_label(iter(pieces), removed))
    return out, removed


def test_streamed():
    for said, want in list(CUT.items()) + [(k, k) for k in KEEP]:
        splits = [[said], list(said)] + [[said[:i], said[i:]] for i in range(len(said) + 1)]
        for pieces in splits:
            out, removed = stream(pieces)
            text = "".join(out)
            if said in CUT:
                assert text.rstrip() == want and removed, (said, pieces, text)
                assert "changed" not in "".join(out), ("the label reached the stream on the way", said, pieces, out)
            else:
                assert text == said and not removed, (said, pieces, text)
    # Ordinary text is passed on as it arrives, not gathered up to the end.
    taken = []

    def source():
        for piece in ["You walk in. ", "The fire is low. ", "\nSomeone coughs.", " Done."]:
            taken.append(piece)
            yield piece
    flow = filter_status_label(source(), [])
    assert next(flow) == "You walk in. " and len(taken) == 1, "the first words waited for more of the reply"
    assert next(flow) == "The fire is low. " and len(taken) == 2
    assert next(flow).startswith("\nSomeone") and len(taken) == 3, "a line that is no label was held"
    list(flow)
    print("4. streamed at every split: the same cut, no label on the way, and ordinary text is not held back")


class Writer:
    model = "stub"

    def __init__(self, reply):
        self.reply, self.gen, self.msgs = reply, {}, None

    def stream(self, messages, **k):
        self.msgs = messages
        for i in range(0, len(self.reply), 7):
            yield self.reply[i:i + 7]

    def complete(self, messages, **k):                      # the quad's Director
        return json.dumps({"beat_plan": "You look around.", "must_stay_consistent": [], "recall_queries": [],
                           "envelope": {"v": 1, "deltas": {}}})


def story():
    _n[0] += 1
    return lib.store(lib.create_story(f"Label {_n[0]}", "A ferry town."))


def engine(store, reply, quad=False):
    cfg = load_config()
    cfg.generation.update({"trinity_brain": quad, "use_memory_tool": False, "think": False, "chapter_outline": False})
    cfg.raw.pop("trinity", None)
    eng = Engine(cfg, store)
    eng.llm = Writer(reply)
    return eng


def phase(store):
    return store.world_state()["time"].get("phase")


def told(store):
    return [t["text"] for t in store.turns() if t["role"] == "narrator"]


def unfenced_notes(store):
    return [h for h in store.health(50) if "without the ```rpg fence" in str(h.get("reason", ""))]


def test_single_brain():
    store = story()
    before = phase(store)
    eng = engine(store, "You step in.\n\nNothing changed:\n\n" + BLOCK)
    out = "".join(eng.turn("I go in."))
    assert out.strip() == "You step in." and told(store)[-1] == "You step in.", (out, told(store))
    assert before != "evening" and phase(store) == "evening", "the block under the label stopped applying"
    assert not unfenced_notes(store), "the bare label was reported as a lost block"
    store = story()
    eng = engine(store, 'You step in.\n\nNothing changed:\n{"deltas": {"time_advance": {"days": 0, "phase": "night"}}}')
    out = "".join(eng.turn("I go in."))
    assert out.strip() == "You step in." and told(store)[-1] == "You step in.", (out, told(store))
    assert len(unfenced_notes(store)) == 1 and phase(store) != "night", (store.health(10), phase(store))
    print("5. single-brain: no label for the reader or the transcript, the block still applies, an unfenced one is reported")


def test_quad():
    store = story()
    eng = engine(store, "You look around.\n\nNothing changed:\n", quad=True)
    assert eng.trinity is not None
    out = "".join(eng.turn("I look around."))
    assert out.strip() == "You look around." and told(store)[-1] == "You look around.", (out, told(store))
    print("6. quad: the Writer's copy of the label is removed too")


def test_history():
    store = story()
    store.append_turn("player", "I wait.\n\nNothing changed:")
    store.append_turn("narrator", "Rain taps the glass.\n\nNothing changed:")
    store.append_turn("player", "I sit.")
    store.append_turn("narrator", "Nothing changed:")
    eng = engine(store, "You sit.")
    list(eng.turn("I stand."))
    sent = [m for m in eng.llm.msgs if m["role"] in ("user", "assistant")]
    assert [m["content"] for m in sent[:4]] == ["I wait.\n\nNothing changed:", "Rain taps the glass.", "I sit.",
                                                "Nothing changed:"], [m["content"] for m in sent]
    assert told(store)[0] == "Rain taps the glass.\n\nNothing changed:", "the saved transcript was changed"
    print("7. a saved label stays in the transcript and is left out of the history the model is sent; your own words are never "
          "touched, and a turn that was only the label is sent as it was")


def test_whole_reply_paths():
    visible, side = strip_sidecar("You step in.\n\nNothing changed:\n\n" + BLOCK)
    assert visible == "You step in." and side and side["deltas"]["time_advance"]["phase"] == "evening", (visible, side)
    visible, side = strip_sidecar("You step in.\n\nNothing changed:")
    assert visible == "You step in." and side is None, (visible, side)
    assert strip_sidecar("You wait. Nothing changed.")[0] == "You wait. Nothing changed."
    print("8. a reply read whole gets the same cut, and its block is still read")


for fn in (test_the_instructions_own_labels, test_cut_and_keep, test_streamed, test_single_brain, test_quad, test_history,
           test_whole_reply_paths):
    fn()
print("\nSTATUS LABEL TESTS PASSED")
