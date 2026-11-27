"""The ties line at the tail of the prompt (D-063, from the graph probe D-058 to D-061).

What broke. With the evidence already in the Writer's prompt, a 4B model answered "who is her brother" and "who carries the key"
wrongly about a third of the time: the facts sit in the middle of a long system message, far from the question. The canon card
is the one thing the engine already puts after the player's action, but it is built from the canon ledger, which has looks and
clothes and no ties or possessions. This is one short system message built from the story's own files (`relationships:` and
`holder:`), right after the card. Off unless `memory: {tail_ties: true}`; it has not been measured on a model, which is why.

 1) nothing named, nothing said: an empty string, not a header over no facts
 2) an item named by the action brings its holder, and the holder's ties (the two-hop question), each fact once
 3) a person named by title, by alias and by an unshared first name brings their ties; a first name two entries share names nobody
 4) a hidden entry is never said, as holder, as tie target or as the thing named
 5) the author's gates hold: `chance: 0`, `delay` (the committed message count) and `triggers_not` (in the text)
 6) a holder or a tie that names nobody, and a tie to oneself, are left out, never guessed
 7) bounded: at most MAX_FACTS facts and MAX_LINE characters, the later facts dropped whole
 8) deterministic: the same files and text give the same line (a retry reproduces, invariant 5), and a word boundary is kept
 9) the engine: off by default and for anything but a real true; on, the line is one system message after the player's action,
    before the chapter directive, never stored in the transcript, and a failure in it is reported and costs no turn
10) the model copying the line into its reply has it dropped by the echo filter, like the card
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-tailties-"))
os.environ["CODERAIN_HOME"] = str(WORK / "home")

from coderain.config import load_config                                    # noqa: E402
from coderain.engine import Engine                                         # noqa: E402
from coderain.memory import SCENE_STATE_HEAD, Entry, Library                # noqa: E402
from coderain.planner import ChapterPlanner                                # noqa: E402
from coderain.tailties import HEAD, MAX_FACTS, MAX_LINE, tail_ties         # noqa: E402

lib = Library(WORK / "lib")
_n = [0]
ROWS = [{"title": "The River Road", "goal": "reach the ford", "status": "active"}]


def story():
    _n[0] += 1
    return lib.store(lib.create_story(f"Ties {_n[0]}", "A ferry town."))


def person(store, name, slug, ties="", aliases=None, **attrs):
    a = {"status": "alive", **attrs}
    if ties:
        a["relationships"] = ties
    store.upsert_entry("characters.md", Entry(title=name, slug=slug, aliases=[name.split()[0]] if aliases is None else aliases,
                                              importance=3, attrs=a, body=f"{name} lives in the ferry town."))


def item(store, name, slug, holder, **attrs):
    store.upsert_entry("items.md", Entry(title=name, slug=slug, aliases=[f"the {name.lower()}"], importance=3,
                                         attrs={"holder": holder, **attrs}, body=f"{name}, kept safe."))


def cast(store):
    person(store, "Hollis Wren", "hollis-wren", "ottoline-pike: his sister")
    person(store, "Ottoline Pike", "ottoline-pike", "hollis-wren: her brother")
    person(store, "Corwin Tide", "corwin-tide", "maribel-voss: owes her money")
    person(store, "Maribel Voss", "maribel-voss", "corwin-tide: is owed money by him")
    item(store, "Brass lamp key", "brass-lamp-key", "hollis-wren")
    item(store, "Salt ledger", "salt-ledger", "corwin-tide")


def test_nothing_named():
    store = story()
    cast(store)
    assert tail_ties(store, "I look at the grey water.", 4) == ""
    assert tail_ties(store, "", 0) == ""
    assert tail_ties(story(), "I talk to Hollis Wren.", 4) == "", "an empty story"
    print("1. nothing named, nothing said")


def test_item_holder_and_two_hop():
    store = story()
    cast(store)
    line = tail_ties(store, "I ask who carries the brass lamp key.", 4)
    assert line.startswith(HEAD) and line.endswith("."), line
    facts = line[len(HEAD):-1].split(". ")
    assert facts == ["Brass lamp key is held by Hollis Wren", "Hollis Wren is tied to Ottoline Pike (his sister)"], facts
    line = tail_ties(store, "I look at the salt ledger and the brass lamp key.", 4)
    assert "Salt ledger is held by Corwin Tide" in line and "Corwin Tide is tied to Maribel Voss (owes her money)" in line, line
    assert line.count("Hollis Wren is tied to Ottoline Pike") == 1, "a fact said twice"
    store2 = story()
    person(store2, "Hollis Wren", "hollis-wren", "ottoline-pike: his sister; ottoline-pike: his sister")
    person(store2, "Ottoline Pike", "ottoline-pike")
    assert tail_ties(store2, "I greet Hollis.", 4).count("Hollis Wren is tied to Ottoline Pike") == 1, "a repeated tie was said twice"
    print("2. an item named brings its holder and the holder's ties, each fact once")


def test_naming():
    store = story()
    cast(store)
    for text in ("I greet Hollis Wren.", "I greet Hollis.", "I greet hollis wren"):
        assert "Hollis Wren is tied to Ottoline Pike (his sister)" in tail_ties(store, text, 4), text
    store2 = story()
    person(store2, "Ottoline Pike", "ottoline-pike", "ottoline-wren: her cousin", aliases=[])
    person(store2, "Ottoline Wren", "ottoline-wren", "ottoline-pike: her cousin", aliases=[])
    assert tail_ties(store2, "I greet Ottoline.", 4) == "", "a first name two people share named somebody"
    assert "Ottoline Pike is tied to Ottoline Wren" in tail_ties(store2, "I greet Ottoline Pike.", 4)
    print("3. a person is named by title, alias or an unshared first name; a shared first name names nobody")


def test_hidden():
    store = story()
    cast(store)
    person(store, "Secret Keeper", "secret-keeper", "hollis-wren: knows his secret", hidden="true")
    assert tail_ties(store, "I greet Secret Keeper.", 4) == "", "a hidden entry was named"
    person(store, "Hollis Wren", "hollis-wren", "ottoline-pike: his sister; secret-keeper: his accomplice")
    assert "Secret Keeper" not in tail_ties(store, "I greet Hollis.", 4), "a hidden tie target was said"
    item(store, "Hidden stash", "hidden-stash", "secret-keeper")
    assert "stash" not in tail_ties(store, "I look at the hidden stash.", 4).lower()
    item(store, "Brass lamp key", "brass-lamp-key", "secret-keeper")
    assert tail_ties(store, "I look at the brass lamp key.", 4) == "", "a hidden holder was said"
    print("4. a hidden entry is never said, as the thing named, as a holder or as a tie target")


def test_gates():
    store = story()
    cast(store)
    person(store, "Delayed Dora", "delayed-dora", "hollis-wren: his niece", delay="10")
    assert tail_ties(store, "I greet Delayed Dora.", 4) == "" and "Delayed Dora" in tail_ties(store, "I greet Delayed Dora.", 10)
    person(store, "Never Nell", "never-nell", "hollis-wren: his aunt", chance="0")
    assert tail_ties(store, "I greet Never Nell.", 99) == ""
    person(store, "Quiet Quentin", "quiet-quentin", "hollis-wren: his uncle", triggers_not="storm")
    assert "Quiet Quentin" in tail_ties(store, "I greet Quiet Quentin.", 4)
    assert tail_ties(store, "I greet Quiet Quentin in the storm.", 4) == ""
    person(store, "Hollis Wren", "hollis-wren", "ottoline-pike: his sister; never-nell: his niece-in-law")
    assert "Never Nell" not in tail_ties(store, "I greet Hollis.", 4), "a tie to an entry the author gated off was said"
    print("5. chance 0, delay and triggers_not hold, for the thing named and for a tie target")


def test_names_nobody():
    store = story()
    person(store, "Hollis Wren", "hollis-wren", "nobody-here: his twin; hollis-wren: himself; ottoline-pike: his sister")
    person(store, "Ottoline Pike", "ottoline-pike", "hollis-wren: her brother")
    item(store, "Brass lamp key", "brass-lamp-key", "a stranger on the quay")
    line = tail_ties(store, "I greet Hollis.", 4)
    assert "nobody" not in line.lower() and "himself" not in line.lower() and "Hollis Wren is tied to Hollis Wren" not in line, line
    assert "Hollis Wren is tied to Ottoline Pike (his sister)" in line
    assert tail_ties(store, "I look at the brass lamp key.", 4) == "", "a holder that names nobody was guessed"
    item(store, "Odd stone", "odd-stone", "odd-stone")
    assert tail_ties(store, "I look at the odd stone.", 4) == "", "an item held by itself was said"
    print("6. a holder or tie that names nobody, and a tie to oneself, are left out")


def test_bounds():
    store = story()
    ties = "; ".join(f"person-{i}: relative number {i}" for i in range(12))
    person(store, "Hollis Wren", "hollis-wren", ties)
    for i in range(12):
        person(store, f"Person {i}", f"person-{i}")
    line = tail_ties(store, "I greet Hollis.", 4)
    facts = line[len(HEAD):-1].split(". ")
    assert len(facts) == MAX_FACTS and len(line) <= MAX_LINE, (len(facts), len(line))
    assert facts == [f"Hollis Wren is tied to Person {i} (relative number {i})" for i in range(MAX_FACTS)], "the earliest were not kept"
    long_note = "x" * 200
    store2 = story()
    person(store2, "Hollis Wren", "hollis-wren", "; ".join(f"person-{i}: {long_note}" for i in range(6)))
    for i in range(6):
        person(store2, f"Person {i}", f"person-{i}")
    line = tail_ties(store2, "I greet Hollis.", 4)
    assert len(line) <= MAX_LINE and all(f.endswith(")") for f in line[len(HEAD):-1].split(". ")), "a fact was cut in half"
    print("7. at most MAX_FACTS facts and MAX_LINE characters; the later facts are dropped whole")


def test_deterministic_and_boundaries():
    store = story()
    cast(store)
    a = tail_ties(store, "I ask who carries the brass lamp key.", 4)
    assert a == tail_ties(store, "I ask who carries the brass lamp key.", 4)
    person(store, "Ash Vane", "ash-vane", "hollis-wren: his friend", aliases=[])
    assert tail_ties(store, "She washed the cups.", 4) == "", "'Ash' matched inside 'washed'"
    assert "Ash Vane" in tail_ties(store, "I greet Ash Vane.", 4)
    print("8. the same files and text give the same line, and a word boundary is kept")


class Cap:
    gen = {"max_tokens": 2000}

    def __init__(self, reply="The door swings open."):
        self.msgs, self.reply = None, reply

    def stream(self, messages, **k):
        self.msgs = messages
        yield self.reply


def engine(**memory):
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["use_memory_tool"] = False
    cfg.generation["think"] = False
    cfg.generation["chapter_outline"] = True
    cfg.raw.pop("canon", None)
    cfg.memory.clear()
    cfg.memory.update(memory)
    store = story()
    cast(store)
    store.append_turn("player", "I wait.")
    store.append_turn("narrator", "Hollis Wren lights the brass lamp.")
    ChapterPlanner(cfg, store, None).replace_all(ROWS)
    eng = Engine(cfg, store)
    eng.llm = Cap()
    return store, eng


def ties_messages(msgs):
    return [m for m in msgs if m["role"] == "system" and m["content"].startswith(HEAD)]


def test_the_engine():
    for value in (None, False, "true", "yes", 1, [], 0):
        store, eng = engine(**({} if value is None else {"tail_ties": value}))
        list(eng.turn("I ask who carries the brass lamp key."))
        assert eng.tail_ties is False and not ties_messages(eng.llm.msgs), f"tail_ties={value!r} turned it on"
    store, eng = engine(tail_ties=True)
    list(eng.turn("I ask who carries the brass lamp key."))
    msgs = eng.llm.msgs
    got = ties_messages(msgs)
    assert len(got) == 1, [m["content"][:40] for m in msgs if m["role"] == "system"]
    assert "Brass lamp key is held by Hollis Wren" in got[0]["content"] and "Hollis Wren is tied to Ottoline Pike" in got[0]["content"]
    assert msgs[-1]["role"] == "system" and "THIS CHAPTER" in msgs[-1]["content"], "the chapter goal must stay the last thing read"
    assert msgs[-2] is got[0] or msgs[-2]["content"] == got[0]["content"], "the line sits right before the chapter directive"
    # the scene-state message (D-072) sits before the action; its place is pinned in prompt_layout_test
    rest = [m for m in msgs if not m["content"].startswith(SCENE_STATE_HEAD)]
    assert rest[-3]["role"] == "user" and "brass lamp key" in rest[-3]["content"], "and after the player's action"
    assert all(HEAD not in t["text"] for t in store.turns()), "the line was stored in the transcript"
    # the engine hands the committed message count: a `delay` the story has reached lets the entry through
    store, eng = engine(tail_ties=True)
    person(store, "Delayed Dora", "delayed-dora", "hollis-wren: his niece", delay="1")
    list(eng.turn("I greet Delayed Dora."))
    assert "Delayed Dora is tied to Hollis Wren" in ties_messages(eng.llm.msgs)[0]["content"], "the delay was judged at turn 0"
    # the last reply counts too: a name that only the narrator used still brings its ties
    store, eng = engine(tail_ties=True)
    list(eng.turn("I nod."))
    assert "Hollis Wren is tied to Ottoline Pike" in ties_messages(eng.llm.msgs)[0]["content"]
    # a failure reports once and costs no turn
    import coderain.engine as eng_mod
    real = eng_mod.tail_ties
    eng_mod.tail_ties = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        store, eng = engine(tail_ties=True)
        out = "".join(eng.turn("I ask who carries the brass lamp key."))
        assert out.strip() and not ties_messages(eng.llm.msgs), "a failing ties line broke the turn or still appeared"
        assert [h for h in store.health(20) if h["stage"] == "tail-ties"], "the failure was not reported"
    finally:
        eng_mod.tail_ties = real
    print("9. off by default and for anything but a real true; on, one system message after the action and before the chapter "
          "directive, never stored; a failure costs no turn")


def test_echo_filter():
    # The filter drops a LEADING run of lines the prompt already carried (streaming.filter_context_echo): a model that
    # starts its reply by copying the line back has it dropped, like the card, and the prose after it is kept.
    store, eng = engine(tail_ties=True)
    line = tail_ties(store, "I ask who carries the brass lamp key.\nHollis Wren lights the brass lamp.", len(store.turns()))
    assert line.startswith(HEAD), line
    eng.llm = Cap(reply=line + "\nHollis smiles and turns away.")
    out = "".join(eng.turn("I ask who carries the brass lamp key."))
    assert HEAD not in out and "is held by Hollis Wren" not in out, "the model's copy of the ties line reached the reader: " + out
    assert "Hollis smiles and turns away." in out, "the prose after the copied line was lost: " + out
    print("10. a copy of the ties line at the start of the reply is dropped by the echo filter, and the prose after it is kept")


test_nothing_named()
test_item_holder_and_two_hop()
test_naming()
test_hidden()
test_gates()
test_names_nobody()
test_bounds()
test_deterministic_and_boundaries()
test_the_engine()
test_echo_filter()
print("\nTAIL TIES TESTS PASSED")
