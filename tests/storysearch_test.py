"""Search of the story's own words (D-075): the exact line said long ago comes back, and nothing else does.

 1) a turn is cut into passages of at most 500 characters that keep every word in order; paragraphs stay together, long ones break at sentences
 2) the search words: lower case, no stop words, each once, at most 24
 3) a passage is found by its words (also another form of them), only before the history window, one per turn, in story order; one shared
    word out of several is not enough
 4) the index follows the transcript: an undo, an edit and a retry leave no old line behind; a fresh file is rebuilt; odd input cannot break it
 5) with an embedder, a passage with no shared word is found by meaning, and the two rankings are merged; at most 64 new passages are
    embedded per search; a dead embedder is logged once and keyword search carries on
 6) the block is bounded, marks the player's lines, and keeps `{{macros}}` in story text as text
 7) the engine: with memory.story_search the passages ride the scene-state message with their turn numbers, only from before the window;
    off by default and for anything but a real true; never for Continue; the first to go under a tight budget; a broken index costs no turn
 8) the memory tool: a reference the timeline does not know is looked up in the story itself
 9) a branch and an export carry no search index, nor SQLite's side files
"""
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-search-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain import storysearch                                                    # noqa: E402
from coderain.config import load_config                                             # noqa: E402
from coderain.engine import Engine                                                  # noqa: E402
from coderain.memory import SCENE_STATE_HEAD, Entry, Library                          # noqa: E402
from coderain.storysearch import PASSAGE_CHARS, StorySearch, passages, query_terms  # noqa: E402

lib = Library(WORK / "lib")
_n = [0]


def story():
    _n[0] += 1
    return lib.store(lib.create_story(f"Search {_n[0]}", "A ferry town."))


def say(store, *pairs):
    for role, text in pairs:
        store.append_turn(role, text)


TALE = [
    ("player", "I ask the ferrywoman about the lamp."),
    ("narrator", "\"The lamp on the breakwater went dark the night the salt barge never came in,\" she says."),
    ("player", "I walk to the customs shed."),
    ("narrator", "The shed smells of tar. Something has been pushed under the loose floorboards by the stove."),
    ("player", "I wait by the door."),
    ("narrator", "Hours pass. A grey heron stands on its post by the door."),
    ("player", "I buy rope from Dessa."),
    ("narrator", "Dessa counts your coins twice and writes the sum in her second ledger."),
]


def found(store, query, before=None, **kw):
    s = StorySearch(store, **kw)
    return s.search(query, len(store.turns()) if before is None else before)


def test_passages():
    long = " ".join(f"Sentence number {i} of a very long paragraph about the tide." for i in range(40))
    text = "A short first paragraph.\n\nA second one.\n\n" + long + "\n\n" + "x" * 1200
    got = passages(text)
    assert all(0 < len(p) <= PASSAGE_CHARS for p in got), [len(p) for p in got]
    assert got[0].startswith("A short first paragraph. A second one."), "short paragraphs are not joined"
    assert " ".join(got).replace(" ", "") == " ".join(text.split()).replace(" ", ""), "words were lost or reordered"
    assert all(p.endswith(".") for p in got[1:3]), "a long paragraph was not cut at sentence ends"
    assert passages("") == [] and passages("   \n\n  ") == []
    print("1. passages of at most 500 characters keep every word in order; long paragraphs break at sentences")


def test_terms():
    got = query_terms("I ask the ferrywoman about the LAMP, the lamp and the ferrywoman's barge.")
    assert got == ["ferrywoman", "lamp", "barge"], got
    assert query_terms("I go and I look at it") == []
    assert len(query_terms(" ".join(f"word{i}" for i in range(50)))) == storysearch.MAX_TERMS
    print("2. the search words are lower case, without stop words, each once, at most 24")


def test_keyword():
    store = story()
    say(store, *TALE)
    got = found(store, "What about the lamp and the salt barge?")
    assert [t for t, _r, _p in got][:1] == [2], got
    assert got[0][2].startswith("\"The lamp on the breakwater"), got[0]
    assert 2 in [t for t, _r, _p in found(store, "who carried the loose floorboard pushing")] or \
           4 in [t for t, _r, _p in found(store, "pushing under a loose floorboard")], "another form of a word did not match"
    assert 4 in [t for t, _r, _p in found(store, "pushing under a loose floorboard")]
    assert found(store, "the door of the lighthouse tower stair") == [] or all("door" not in p or "tower" in p for _t, _r, p in found(
        store, "the door of the lighthouse tower stair")), "one shared word out of several was enough"
    assert found(store, "heron") and found(store, "heron")[0][0] == 6, "a single search word needs only itself"
    assert found(store, "salt barge lamp", before=1) == [], "a turn inside the window was searched"
    assert [t for t, _r, _p in found(store, "salt barge lamp", before=2)] == [2]
    two = "The lamp lamp lamp, the salt barge. " * 12 + "\n\n" + "The salt barge lamp. " * 20           # two passages in one turn
    assert len(passages(two)) == 2, "the control proves nothing"
    say(store, ("player", "I ask about the lamp."), ("narrator", two))
    turns = [t for t, _r, _p in found(store, "salt barge lamp")]
    assert len(turns) == len(set(turns)) and turns == sorted(turns), ("one per turn, in story order", turns)
    print("3. found by words in any form, only before the window, one per turn in story order; one shared word of many is not enough")


def test_follows_the_transcript():
    store = story()
    say(store, *TALE)
    assert found(store, "grey heron post")
    store.drop_last_turns(4)                                                     # an undo takes the heron's turn away
    assert found(store, "grey heron post", before=99) == [], "an undone line is still in the index"
    say(store, ("player", "I buy rope."), ("narrator", "A white gull screams over the stalls."))
    assert [t for t, _r, _p in found(store, "white gull stalls")] == [6]
    lines = store.read("transcript.md").replace("salt barge never came in", "eel boat never came in")
    store.write("transcript.md", lines)                                          # an edit
    assert found(store, "salt barge") == [] and found(store, "eel boat") != []
    (Path(store.dir) / "search.db").unlink()
    assert found(store, "eel boat")[0][0] == 2, "a deleted index was not rebuilt"
    for odd in ('"lamp" OR (barge*', "NEAR(lamp, 2)", "lamp -barge", "; DROP TABLE passage; --", "🙂 lamp", ""):
        StorySearch(store).search(odd, 99)                                       # must not raise
    assert found(store, "eel boat"), "the table survived"
    print("4. the index follows undo, edits and new turns, is rebuilt when deleted, and odd input cannot break it")


class Meaning:
    """A fake embedder: texts about money point one way, everything else another."""
    model = "fake-embed"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("no embeddings here")
        self.calls.append(len(texts))
        money = ("coin", "ledger", "debt", "owe", "paid")
        return [[1.0, 0.1] if any(w in t.lower() for w in money) else [0.05, 1.0] for t in texts]


def test_meaning():
    store = story()
    say(store, *TALE)
    asked = "Who owes money around here?"
    assert 8 not in [t for t, _r, _p in found(store, asked)], "the control proves nothing"
    got = [t for t, _r, _p in found(store, asked, embedder=Meaning())]
    assert 8 in got, ("the passage about coins and a ledger was not found by meaning", got)
    # merged: a passage both rankings like comes first
    s = StorySearch(store, embedder=Meaning())
    top = s.search("coins ledger", len(store.turns()), top_k=1)
    assert [t for t, _r, _p in top] == [8], top
    many = story()
    for i in range(100):
        say(many, ("narrator", f"Page {i}: the tide table lists the ferry times."))
    m = Meaning()
    StorySearch(many, embedder=m).search("ferry times", 100)
    assert m.calls[0] == storysearch.EMBED_PER_CALL, m.calls
    StorySearch(many, embedder=m).search("ferry times", 100)
    assert m.calls[2] == 100 - storysearch.EMBED_PER_CALL, ("the rest are embedded on the next search", m.calls)
    dead = story()
    say(dead, *TALE)
    broken = StorySearch(dead, embedder=Meaning(fail=True))
    assert broken.search("salt barge lamp", 8) and broken.search("salt barge lamp", 8), "keyword search stopped with the embedder"
    rows = [h for h in dead.health(20) if h["stage"] == "story-search"]
    assert len(rows) == 1 and "meaning" in rows[0]["reason"], rows
    print("5. meaning finds what shares no words and merges with keywords; 64 embeddings a search; a dead embedder is logged once")


def test_block():
    store = story()
    say(store, ("player", "I swear the {{roll::2d6}} dice are loaded, {{user}}."), ("narrator", "The loaded dice clatter. " * 30))
    block = StorySearch(store).block("loaded dice", 2, max_chars=400)
    assert len(block) <= 400, len(block)
    full = StorySearch(store).block("loaded dice", 2)
    assert full.startswith("[T1, the player] I swear"), full[:60]
    assert "{{" not in full and "roll::2d6" in full, "a macro in story text can be expanded again: " + full[:90]
    assert StorySearch(store).block("nothing matches this zebra", 2) == ""
    print("6. the block is bounded, marks the player's lines, and keeps a macro in story text as text")


class Cap:
    model = "stub"

    def __init__(self):
        self.sent = []

    def stream(self, messages, **k):
        self.sent.append([dict(m) for m in messages])
        yield "You look around the quay."

    def complete(self, messages, **k):
        return ""


def engine(value="unset", window=2):
    store = story()
    say(store, *TALE)
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["chapter_outline"] = False
    cfg.memory["short_term_turns"] = window
    if value != "unset":
        cfg.memory["story_search"] = value
    eng = Engine(cfg, store)
    eng.llm = Cap()
    return store, eng


def scene(msgs):
    got = [m["content"] for m in msgs if str(m.get("content", "")).startswith(SCENE_STATE_HEAD)]
    return got[0] if got else ""


def test_engine():
    store, eng = engine(True)
    "".join(eng.turn("I ask about the salt barge and the lamp."))
    msgs = eng.llm.sent[-1]
    assert "## From earlier in the story" in scene(msgs) and "[T2] \"The lamp on the breakwater" in scene(msgs), scene(msgs)
    assert "From earlier in the story" not in msgs[0]["content"], "the passages are in the cached top"
    # only before the window: with a 2-message window, turns 7-9 are in the history and must not be quoted
    "".join(eng.turn("I look at Dessa's second ledger of coins."))
    sent = eng.llm.sent[-1]
    history = [m for m in sent[1:-1] if m["role"] != "system"]
    assert history, "the control proves nothing: no history was sent"
    quoted = scene(sent)
    assert all(m["content"][:40] not in quoted for m in history), ("a line already in the history was quoted again", quoted)
    for value in ("unset", False, "true", "false", 1):
        _s, off = engine(value)
        "".join(off.turn("I ask about the salt barge and the lamp."))
        assert "From earlier in the story" not in "".join(m["content"] for m in off.llm.sent[-1]), value
    cont_store, cont = engine(True)
    # a line before the window that Continue's own instruction would match, so that searching it would show
    cont_store.write("transcript.md", cont_store.read("transcript.md").replace(
        "Hours pass.", "A fresh scene: the current pushes the barge forward with detail."))
    assert StorySearch(cont_store).search("current scene forward fresh detail", 6), "the control proves nothing"
    "".join(cont.continue_story())
    assert "From earlier in the story" not in "".join(m["content"] for m in cont.llm.sent[-1]), "Continue searched its own instruction"
    tight_store, _eng = engine(True)
    tight_store.upsert_entry("characters.md", Entry(title="Dame Pin", slug="dame-pin", importance=3, attrs={"pinned": "true"},
                                                    body="Always here, whatever the budget."))
    lines = "[T2] " + "the salt barge never came in " * 40
    _m, roomy = tight_store.assemble_parts([], "salt barge", budget_tokens=8000, layout="cache", earlier=lines)
    msgs, small = tight_store.assemble_parts([], "salt barge", budget_tokens=220, layout="cache", earlier=lines)
    assert "From earlier in the story" in roomy, "the control proves nothing"
    assert "the salt barge never came in the salt barge never came in the salt barge" not in small, "it survived a budget with no room"
    assert "Always here, whatever the budget." in msgs[0]["content"] + small, "pinned went before the search passages"
    broke_store, broke = engine(True)
    (Path(broke_store.dir) / "search.db").write_bytes(b"this is not a database at all" * 100)
    out = "".join(broke.turn("I ask about the salt barge and the lamp."))
    assert out.startswith("You look"), out
    assert [h for h in broke_store.health(20) if h["stage"] == "story-search"], "the failure was not reported"
    assert broke._before_window(broke_store.turns()[-2:]) == len(broke_store.turns()) - 2
    print("7. the engine quotes earlier passages in the scene state only when asked, never for Continue, drops them first, survives a broken index")


def test_memory_tool():
    store = story()
    say(store, *TALE)
    got = store.recall_turns("the grey heron on its post")
    assert "No timeline entry matches" in got and "[T6]" in got and "heron" in got, got
    assert store.recall_turns("zebra herd") == "No timeline entry matches 'zebra herd'."
    print("8. the memory tool looks up in the story itself what the timeline does not know")


def test_copies():
    store = story()
    say(store, *TALE)
    assert found(store, "heron")
    d = Path(store.dir)
    (d / "search.db-wal").write_bytes(b"w")
    (d / "search.db-shm").write_bytes(b"s")
    slug = d.name
    branch = lib.saves.branch(slug, 4)
    names = [p.name for p in (lib.saves.root / (branch[0] if isinstance(branch, tuple) else branch)).rglob("*")]
    assert not [n for n in names if ".db" in n], names
    dup = lib.saves.duplicate(slug)
    assert not [p.name for p in (lib.saves.root / dup).rglob("*") if ".db" in p.name]
    path = lib.saves.export(slug, WORK / "out.zip")
    assert not [n for n in zipfile.ZipFile(path).namelist() if ".db" in n]
    print("9. a branch, a duplicate and an export carry no index and none of SQLite's side files")


test_passages()
test_terms()
test_keyword()
test_follows_the_transcript()
test_meaning()
test_block()
test_engine()
test_memory_tool()
test_copies()
print("\nSTORY SEARCH TESTS PASSED")
