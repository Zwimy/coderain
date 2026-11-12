"""Injection (D-027): the engine puts the canon card in front of the Writer, behind a flag.

Until now nothing canon produced reached a prompt. This is the step that changes what
the model is told, so the suite pins what it must not break. Each assertion is one
promise, and each was made to fail by breaking its guard (see the commit message).

 1) config: "on" only for a literal true, "preview" for that string, everything else off;
    the card size is bounded; identity-only needs a literal false
 2) off by default: with the shadow running and no `inject`, the model is told nothing
    new and nothing is logged
 3) preview builds and logs the card but SENDS nothing: the step to take first
 4) on sends it as a system message after the player's action and before the chapter
    directive, so the chapter goal is still the last thing read; the transcript never
    holds it; the log row holds counts, never prose
 5) a turn is never delayed or broken: a reader that holds its lock, a first turn after
    a restart, a card builder that explodes. Each gives a turn with prose, no card, and
    a visible reason; a restart loads the snapshot from disk and a reader that is behind
    gives identity only
 6) a retry shows nothing the discarded reply stated (state still shows); an edit of an
    old turn shows only what came before it, with no state
 7) `inject` without the shadow does nothing and says so in the health log
 8) a model that copies a card line into its reply has it dropped by the echo filter
"""
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-inject-"))
os.environ["CODERAIN_HOME"] = str(WORK / "home")      # before coderain is imported

from canon.card import IDENTITY_HEADER                                   # noqa: E402
from canon.scribe import Scribe                                           # noqa: E402
from coderain.canon_shadow import _lock_for, settings                     # noqa: E402
from coderain.config import load_config                                   # noqa: E402
from coderain.engine import Engine                                        # noqa: E402
from coderain.memory import Entry, Library                                # noqa: E402
from coderain.planner import ChapterPlanner                               # noqa: E402

lib = Library(WORK / "lib")
_n = [0]
PEOPLE = [("odile", "Odile Marsh", ["The Courier"]), ("corin", "Corin Hale", []),
          ("tamsin", "Tamsin Reeve", [])]
T1 = "Odile Marsh stepped in, her raven hair damp. Odile wore a grey coat."
T2 = "Corin Hale's grey eyes narrowed. Tamsin Reeve picked up a lantern."
T3 = "Tamsin Reeve wore a red cloak."
ROWS = [{"title": "The River Road", "goal": "reach the ford", "status": "active"},
        {"title": "The Bridge", "goal": "cross unseen", "status": "planned"}]


def claim(entity, slot, op, value, evidence):
    return dict(entity=entity, slot=slot, op=op, value=value, evidence=evidence, confidence="high")


SCRIPT = [
    ("her raven hair", [claim("Odile Marsh", "identity.hair", "set", "raven", "her raven hair"),
                        claim("Odile Marsh", "state.outfit", "add", "grey coat", "Odile wore a grey coat")]),
    ("grey eyes narrowed", [claim("Corin Hale", "identity.eyes", "set", "grey", "Corin Hale's grey eyes"),
                            claim("Tamsin Reeve", "state.held", "add", "lantern",
                                  "Tamsin Reeve picked up a lantern")]),
    ("red cloak", [claim("Tamsin Reeve", "state.outfit", "add", "red cloak",
                         "Tamsin Reeve wore a red cloak")]),
]


class Stub:
    stays_local = True

    def complete(self, system, user, schema_=None):
        for needle, claims in SCRIPT:
            if needle in user:
                return json.dumps({"claims": claims})
        return json.dumps({"claims": []})


class Cap:
    """Captures exactly what the model is handed."""
    gen = {"max_tokens": 2000}

    def __init__(self, reply="The door swings open."):
        self.msgs, self.reply = None, reply

    def stream(self, messages, **k):
        self.msgs = messages
        yield self.reply


def new_save():
    _n[0] += 1
    store = lib.store(lib.create_story(f"Inject {_n[0]}", "A harbour town."))
    for slug, title, aliases in PEOPLE:
        store.upsert_entry("characters.md", Entry(title=title, slug=slug, aliases=list(aliases)))
    return store


def story(store, *texts):
    for t in texts:
        store.append_turn("player", "I wait.")
        store.append_turn("narrator", t)


@contextmanager
def configured(canon=True, **sec):
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["use_memory_tool"] = False
    cfg.generation["think"] = False
    cfg.generation["chapter_outline"] = True
    # identity "always" by default HERE: these tests pin what the card says, and their stories' recent turns
    # name everyone and contradict nobody, so the default ("needed") would rightly leave the looks out.
    # test 10 turns it on.
    cfg.raw["canon"] = {"shadow": True, "backfill": "all", "identity": "always", **sec} if canon else sec
    try:
        yield cfg
    finally:
        cfg.raw.pop("canon", None)


def ready(cfg, texts=(T1, T2), reply="The door swings open."):
    """A save with a transcript, the reader caught up on it, and a model that records
    what it is handed."""
    store = new_save()
    story(store, *texts)
    ChapterPlanner(cfg, store, None).replace_all(ROWS)
    eng = Engine(cfg, store)
    if eng.canon_shadow is not None:
        eng.canon_shadow.scribe = Scribe(Stub())
        eng.canon_shadow.reconcile()                   # synchronous: the snapshot is published
    eng.llm = Cap(reply)
    return store, eng


def cards(msgs):
    return [m["content"] for m in msgs if m["role"] == "system" and m["content"].startswith(IDENTITY_HEADER)]


def rows(store):
    p = Path(store.dir) / "canon" / "injections.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def health(store, stage):
    return [h for h in store.health(50) if h["stage"] == stage]


def test_settings():
    def s(**kw):
        return settings({"canon": {"shadow": True, **kw}})
    assert s()["inject"] == "off" and s(inject=True)["inject"] == "on"
    assert s(inject="preview")["inject"] == "preview" and s(inject=" Preview ")["inject"] == "preview"
    for junk in ("yes", "true", "on", 1, 0, None, [], {}, "previews", False):
        assert s(inject=junk)["inject"] == "off", junk
    assert s()["card_chars"] == 2400 and s(card_chars=10)["card_chars"] == 600
    assert s(card_chars=10 ** 9)["card_chars"] == 4000 and s(card_chars=float("inf"))["card_chars"] == 2400
    assert s(card_chars=True)["card_chars"] == 2400, "YAML true is not a number"
    assert s()["inject_state"] is True and s(inject_state=False)["inject_state"] is False
    for junk in (0, "false", None, "no", []):
        assert s(inject_state=junk)["inject_state"] is True, junk
    print("1. inject is on only for a literal true (preview for that word); the size is bounded; "
          "identity-only needs a literal false")


def test_off_by_default():
    with configured() as cfg:
        store, eng = ready(cfg)
        assert eng._canon_card() == ""
        list(eng.turn("I look around"))
        assert not cards(eng.llm.msgs), "the model was told something without inject being set"
        assert rows(store) == [] and not (Path(store.dir) / "canon" / "card-last.txt").exists()
    print("2. with the shadow running and no `inject`, the prompt gets nothing and nothing is logged")


def test_preview_logs_and_sends_nothing():
    with configured(inject="preview") as cfg:
        store, eng = ready(cfg)
        list(eng.turn("I look around"))
        assert not cards(eng.llm.msgs), "preview sent a card"
        assert [r["mode"] for r in rows(store)] == ["preview"], rows(store)
        last = (Path(store.dir) / "canon" / "card-last.txt").read_text(encoding="utf-8")
        assert "Preview only: NOT sent." in last and "raven hair" in last and "wearing grey coat" in last, last
    print("3. preview builds and logs the card and sends nothing")


def test_on_sends_it_in_the_right_place():
    with configured(inject=True) as cfg:
        store, eng = ready(cfg)
        list(eng.turn("I look around"))
        msgs = eng.llm.msgs
        got = cards(msgs)
        assert len(got) == 1, [m["content"][:30] for m in msgs if m["role"] == "system"]
        card = got[0]
        assert "raven hair" in card and "grey eyes" in card, card
        assert "wearing grey coat" in card and "holding lantern" in card, card
        assert msgs[-1]["role"] == "system" and "THIS CHAPTER" in msgs[-1]["content"], \
            "the chapter goal must stay the last thing read"
        assert msgs[-2]["content"] == card, "the card sits right before the chapter directive"
        assert msgs[-3]["role"] == "user" and "look around" in msgs[-3]["content"], \
            "and after the player's action"
        last = (Path(store.dir) / "canon" / "card-last.txt").read_text(encoding="utf-8")
        assert last.startswith("Turn 6, mode on. Sent."), last[:40]
        assert all(IDENTITY_HEADER not in t["text"] for t in store.turns()), \
            "the card was stored in the transcript"
        r = rows(store)
        assert len(r) == 1 and r[0]["mode"] == "on" and r[0]["state"] is True and r[0]["chars"] == len(card), r
        raw = (Path(store.dir) / "canon" / "injections.jsonl").read_text(encoding="utf-8")
        assert "raven" not in raw and "Odile" not in raw and "stepped in" not in raw, \
            "the log row must hold counts, never the story"
        assert set(r[0]) == {"turn", "mode", "chars", "reason", "state", "cast", "unread",
                             "trusted_through", "hidden"}, set(r[0])
    with configured(inject=True, inject_state=False) as cfg:
        store, eng = ready(cfg)
        list(eng.turn("I look around"))
        card = cards(eng.llm.msgs)[0]
        assert "raven hair" in card and "wearing" not in card and "Scene state" not in card, card
    print("4. on sends one system message after the action and before the chapter directive; "
          "it is never stored; the log holds counts; identity-only drops the state")


def test_a_turn_is_never_delayed_or_broken():
    with configured(inject=True) as cfg:
        store, eng = ready(cfg)
        # a restart: a new engine has published nothing, and the reader holds its lock
        eng2 = Engine(cfg, store)
        eng2.canon_shadow.scribe = Scribe(Stub())
        eng2.llm = Cap()
        lock = _lock_for(eng2.canon_shadow.dir)
        assert lock.acquire(blocking=False)
        try:
            t0 = time.time()
            out = "".join(eng2.turn("I wait again"))
            took = time.time() - t0
        finally:
            lock.release()
        assert out == "The door swings open." and took < 5, (out, took)
        assert not cards(eng2.llm.msgs), "a card was built while the reader held the ledger"
        assert rows(store)[-1]["reason"] == "not_ready", rows(store)[-1]
        # lock free: the snapshot is read from disk. The two replies written since were
        # never read, so the reader is behind and the card is identity only
        list(eng2.turn("I wait once more"))
        card = cards(eng2.llm.msgs)
        assert len(card) == 1 and "grey eyes" in card[0], card     # Corin is still in the scene
        assert "wearing" not in card[0] and "holding" not in card[0], \
            "the reader was behind, so state could contradict the turns just written"
        last = rows(store)[-1]
        assert last["state"] is False and last["unread"] >= 1, last
        # a card builder that explodes costs nothing but the card
        eng2.canon_shadow.card = lambda turns, **kw: (_ for _ in ()).throw(RuntimeError("card exploded"))
        eng2.llm = Cap()
        out = "".join(eng2.turn("I wait a third time"))
        assert out == "The door swings open." and not cards(eng2.llm.msgs)
        assert any("card exploded" in h["reason"] for h in health(store, "canon-shadow")), \
            health(store, "canon-shadow")
        # and one that explodes INSIDE the shadow's own card(): it contains it, says why in
        # the log row, and reports it once however many turns follow
        del eng2.canon_shadow.card                      # back to the real method
        import coderain.canon_shadow as shadow_mod
        real = shadow_mod.build_card
        shadow_mod.build_card = lambda *a, **k: (_ for _ in ()).throw(ValueError("builder exploded"))
        try:
            for _ in range(3):
                eng2.llm = Cap()
                out = "".join(eng2.turn("I wait again"))
                assert out == "The door swings open." and not cards(eng2.llm.msgs)
        finally:
            shadow_mod.build_card = real
        assert rows(store)[-1]["reason"] == "error", rows(store)[-1]
        mine = [h for h in health(store, "canon-shadow") if "builder exploded" in h["reason"]]
        assert len(mine) == 1, ("reported once, not once a turn", mine)
    print("5. a held lock, a restart and a crashing builder each give a turn with prose and no "
          "card, with the reason visible; a restart reads the snapshot from disk and a reader "
          "that is behind gives identity only")


def test_retry_and_edit_never_show_what_was_discarded():
    with configured(inject=True) as cfg:
        store, eng = ready(cfg, reply=T3)
        list(eng.turn("I look around"))                # reply T3 is turn 6
        eng.maybe_fold()
        eng.canon_shadow.wait()
        assert list(eng.canon_shadow._store().canon.current("tamsin", "state.outfit")) == ["red cloak"], \
            "precondition: the reader recorded the reply that is about to be discarded"
        # a retry: the reply and the action are dropped, then the action is sent again
        store.drop_last_turns(2)
        eng.llm = Cap()
        list(eng.turn("I look around"))
        card = cards(eng.llm.msgs)[0]
        assert "red cloak" not in card, "the discarded reply's fact reached the Writer"
        assert "wearing grey coat" in card and "holding lantern" in card, card
        assert rows(store)[-1]["state"] is True, "nothing was unread after the retry"

    with configured(inject=True) as cfg:
        store, eng = ready(cfg, texts=(T1, T2))
        assert store.update_turn(3, "Corin Hale's blue eyes narrowed. Tamsin Reeve sat down.")
        eng.llm = Cap()
        list(eng.turn("I look around"))
        card = cards(eng.llm.msgs)[0]
        assert "raven hair" in card, "what turn 2 established is still true"
        assert "grey eyes" not in card and "lantern" not in card and "grey coat" not in card, \
            "an edited turn's facts, or any state, reached the Writer"
        assert rows(store)[-1]["state"] is False
    print("6. a retry shows nothing the discarded reply stated and keeps state; an edit of an old "
          "turn keeps only what came before it, with no state")


def test_inject_without_the_shadow():
    with configured(canon=False, inject=True) as cfg:
        store = new_save()
        story(store, T1)
        eng = Engine(cfg, store)
        eng.llm = Cap()
        assert eng.canon_shadow is None and eng._canon_card() == ""
        list(eng.turn("I look around"))
        assert not cards(eng.llm.msgs)
        assert any("needs canon.shadow" in h["reason"] for h in health(store, "canon-inject")), \
            "a config that looks on and does nothing must say so"
    with configured(canon=False, inject="off") as cfg:
        assert health(Engine(cfg, new_save()).store, "canon-inject") == []
    print("7. inject without the shadow does nothing and says so; `off` says nothing")


def test_the_echo_filter_catches_a_copied_card():
    with configured(inject=True) as cfg:
        store, eng = ready(cfg)
        list(eng.turn("I look around"))
        line = cards(eng.llm.msgs)[0].splitlines()[1]        # the first character's identity line
        assert ": " in line and line != IDENTITY_HEADER, line
        eng.llm = Cap(line + "\nThe door swings open.")
        out = "".join(eng.turn("I wait for a moment"))
        assert line not in out and "swings open" in out, out
        assert line not in store.turns()[-1]["text"]
        assert any("copied back" in h["reason"] for h in health(store, "writer")), health(store, "writer")
    print("8. a model that copies a card line into its reply has it dropped, and it is reported")


def test_a_correction_reaches_the_writer_on_the_next_turn():
    """D-028. The wrong value the first Writer test found being repeated can now be corrected by hand. The
    card applies corrections.md itself, so the very next turn is right, before the reader has written
    anything, and it stays right after an undo cuts off the ledger records that carried the correction."""
    with configured(inject=True) as cfg:
        store, eng = ready(cfg)
        sh = eng.canon_shadow
        assert sh._store().canon.current("odile", "identity.hair") == "raven"
        store.write("corrections.md", "- Odile Marsh: hair = auburn\n- Corin Hale: eyes is not grey\n")
        list(eng.turn("I look around"))                       # no pass has run since the edit
        card = cards(eng.llm.msgs)[0]
        assert "auburn hair" in card and "raven" not in card, card
        assert "grey eyes" not in card, "a value the author called wrong reached the Writer"
        assert "wearing grey coat" in card and "holding lantern" in card, "the rest of the card is unchanged"
        assert sh._store().canon.current("odile", "identity.hair") == "raven", \
            "the ledger was changed by a card: the overlay must be on the projection only"
        # the reader then writes them into the ledger
        sh.reconcile()
        assert sh._store().canon.current("odile", "identity.hair") == "auburn"
        assert sh._store().canon.current("corin", "identity.eyes") is None
        # an undo back to the first reply cuts the author's records off the ledger's trusted prefix
        store.drop_last_turns(4)
        eng.llm = Cap()
        list(eng.turn("I look around again"))
        card = cards(eng.llm.msgs)[0]
        assert "auburn hair" in card and "raven" not in card, card
        # a hand edit that says nothing sensible costs nothing: the bad line is reported, the card still builds
        store.write("corrections.md", "- Odile Marsh: hair = auburn\n- not a correction at all\n")
        eng.llm = Cap()
        list(eng.turn("I look around once more"))
        assert "auburn hair" in cards(eng.llm.msgs)[0]
        assert [p["line"] for p in sh.view(store.turns())["problems"]] == [2]
    print("9. a correction reaches the Writer on the very next turn without touching the ledger, survives an "
          "undo, and a bad line is reported without costing the card")


def test_a_look_is_shown_only_when_it_matters():
    """10. The engine hands the card the verbatim turns the prompt already carries and the player's action. A look
    is shown only when the character is absent from those turns, the action asks about them, or the turns say a
    different colour (first soak: offering every look every turn made the Writer restate looks about ten times as
    often); the log row counts what was left out, and `identity: always` turns it off."""
    sec = lambda **k: settings({"canon": {"shadow": True, **k}})["identity"]                    # noqa: E731
    assert sec() == "needed" and sec(identity="always") == "always" and sec(identity="ALWAYS ") == "always"
    assert sec(identity="no") == "needed" and sec(identity=True) == "needed" and sec(identity=0) == "needed"
    with configured(inject=True, identity="needed") as cfg:
        store, eng = ready(cfg)                       # the window holds T1 and T2, which name everyone, no clash
        list(eng.turn("I look around"))
        card = [m["content"] for m in eng.llm.msgs if m["role"] == "system" and m["content"].startswith("Scene state")]
        assert len(card) == 1 and "wearing grey coat" in card[0], card
        assert not cards(eng.llm.msgs), "nobody is absent, asked about or contradicted: no identity block at all"
        assert rows(store)[-1]["hidden"] == 2, rows(store)[-1]
        eng.llm = Cap()                               # now the player asks about her hair
        list(eng.turn("I study Odile Marsh's hair"))
        asked = cards(eng.llm.msgs)
        assert len(asked) == 1 and "raven hair" in asked[0] and "grey eyes" not in asked[0], asked
    with configured(inject=True, identity="always") as cfg:
        store, eng = ready(cfg)
        list(eng.turn("I look around"))
        assert "raven hair" in cards(eng.llm.msgs)[0] and "grey eyes" in cards(eng.llm.msgs)[0]
        assert rows(store)[-1]["hidden"] == 0
    print("10. a look is shown only when it matters, the log counts what was left out, and `identity: always` turns it off")


try:
    for fn in (test_settings, test_off_by_default, test_preview_logs_and_sends_nothing,
               test_on_sends_it_in_the_right_place, test_a_turn_is_never_delayed_or_broken,
               test_retry_and_edit_never_show_what_was_discarded, test_inject_without_the_shadow,
               test_the_echo_filter_catches_a_copied_card,
               test_a_correction_reaches_the_writer_on_the_next_turn,
               test_a_look_is_shown_only_when_it_matters):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON INJECT TESTS PASSED")
