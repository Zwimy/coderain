"""Shadow canon: the Scribe and ledger run beside the engine and change nothing.

This is the first engine code that uses canon/, so what it must NOT do matters more
than what it does. Each numbered assertion pins one promise.

 1) config: shadow is on only for a literal true; every value is bounded; garbage
    (including `.inf`, which raises OverflowError) falls back to the default
 2) off by default costs nothing: no CanonShadow, and canon/ is never imported
 3) observe only: the prompt the engine builds is identical with the shadow running,
    nothing outside <save>/canon/ is written, and the prompt code does not mention it
 4) a pass reads narrator turns, skips one that names nobody, records a hash of each,
    and its report and rows hold values and counts but none of the story's prose
 5) it follows EVERY way a transcript changes by content: undo, undo to nothing, an
    edit of an old turn, a retry, a swipe, a Continue and a real branch each leave
    canon equal to what a fresh replay of the final transcript gives
 6) it resumes: a second pass over an unchanged transcript sends nothing
 7) backfill bounds what is read the first time
 8) failure is contained and visible: a down model, a refusal to run on a non-local
    model, a crash, a corrupt ledger and a deleted save never raise into a turn, are
    reported once to the health log, and a down model is retried rather than skipped
 9) threads: kick() returns at once, kicks coalesce, a turn that is generating is
    waited for, and a transcript that moves mid-pass is picked up on the next pass
10) the engine hook: a turn plus maybe_fold produces a report, and a shadow that
    explodes does not stop maybe_fold
11) an export does not carry the derived ledger
12) a character met mid-story is seeded at that turn and follows undo and replay
13) the server gives the shadow a probe for a generating turn
"""
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-shadow-"))
os.environ["CODERAIN_HOME"] = str(WORK / "home")      # before coderain is imported

from canon.replay import GenderVotes                                     # noqa: E402
from canon.scribe import Scribe, ScribeError                              # noqa: E402
from coderain.canon_shadow import (BACKFILL_ALL, CanonShadow, settings)   # noqa: E402
from coderain.config import load_config                                   # noqa: E402
from coderain.engine import Engine                                        # noqa: E402
from coderain.memory import Entry, Library, MemoryStore                   # noqa: E402

lib = Library(WORK / "lib")
_n = [0]
PEOPLE = [("odile", "Odile Marsh", ["The Courier"]), ("corin", "Corin Hale", []),
          ("tamsin", "Tamsin Reeve", [])]

M1 = "Odile Marsh stepped in, her raven hair damp. Corin Hale glared at her."
M2 = "Corin Hale's grey eyes narrowed. Tamsin wore a green scarf."
M3 = "Odile's platinum hair caught the lamp."
M4 = "Tamsin picked up the lantern."
M4B = "Tamsin wore a red cloak."
R2 = "Corin Hale's brown eyes narrowed."
NOBODY = "The street was empty."


def claim(entity, slot, op, value, evidence):
    return dict(entity=entity, slot=slot, op=op, value=value, evidence=evidence,
                confidence="high")


SCRIPT = [
    ("raven hair damp", [claim("Odile Marsh", "identity.hair", "set", "raven", "her raven hair damp")]),
    ("grey eyes narrowed", [claim("Corin Hale", "identity.eyes", "set", "grey", "Corin Hale's grey eyes"),
                            claim("Tamsin", "state.outfit", "add", "green scarf", "Tamsin wore a green scarf")]),
    ("platinum hair caught", [claim("Odile", "identity.hair", "set", "platinum", "Odile's platinum hair")]),
    ("picked up the lantern", [claim("Tamsin", "state.held", "add", "lantern", "Tamsin picked up the lantern")]),
    ("red cloak", [claim("Tamsin", "state.outfit", "add", "red cloak", "Tamsin wore a red cloak")]),
    ("brown eyes narrowed", [claim("Corin Hale", "identity.eyes", "set", "brown", "Corin Hale's brown eyes")]),
]


ORIGINAL_SCRIPT = list(SCRIPT)


class Stub:
    stays_local = True

    def __init__(self):
        self.calls, self.hook = [], None

    def complete(self, system, user, schema_=None):
        self.calls.append(user)
        if self.hook:
            self.hook(len(self.calls))
        for needle, claims in SCRIPT:
            if needle in user:
                return json.dumps({"claims": claims})
        return json.dumps({"claims": []})


def new_save(people=PEOPLE):
    _n[0] += 1
    store = lib.store(lib.create_story(f"Shadow {_n[0]}", "A harbour town."))
    for slug, title, aliases in people:
        store.upsert_entry("characters.md", Entry(title=title, slug=slug,
                                                   aliases=list(aliases)))
    return store


def story(store, *texts, player=True):
    for t in texts:
        if player:
            store.append_turn("player", "I wait.")
        store.append_turn("narrator", t)


def shadow(store, **over):
    cfg = settings({"canon": {"shadow": True, "backfill": "all", **over}})
    stub = Stub()
    return CanonShadow(store, cfg, scribe=Scribe(stub)), stub


def view(canon):
    """Every slot canon currently holds, per entity, with ids and creation turns
    left out: two replays of one transcript agree on this even if they got there by
    different routes."""
    out = {}
    for eid in canon.entities:
        cur = {}
        for slot in canon.slots[eid]:
            v = canon.current(eid, slot)
            if v is not None:
                cur[slot] = list(v) if isinstance(v, tuple) else v
        if cur:
            out[eid] = cur
    return out


def fresh_view(*texts, player=True):
    store = new_save()
    story(store, *texts, player=player)
    sh, _ = shadow(store)
    sh.reconcile()
    return view(sh._store().canon)


def tree(store, skip="canon"):
    out = {}
    for p in sorted(Path(store.dir).rglob("*")):
        if p.is_file() and skip not in p.relative_to(store.dir).parts \
                and ".snapshots" not in p.parts:
            out[p.relative_to(store.dir).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
def test_settings():
    assert settings(None)["shadow"] is False and settings({})["shadow"] is False
    assert settings({"canon": None})["shadow"] is False
    for off in ("yes", "true", 1, "on", None, [], {}):
        assert settings({"canon": {"shadow": off}})["shadow"] is False, off
    assert settings({"canon": {"shadow": True}})["shadow"] is True
    s = settings({"canon": {"shadow": True, "model": "  qwen3:4b ", "host": "http://x:1",
                            "num_ctx": 999_999, "backfill": "ALL", "max_errors": 0}})
    assert s["model"] == "qwen3:4b" and s["host"] == "http://x:1"
    assert s["num_ctx"] == 16384 and s["backfill"] == BACKFILL_ALL and s["max_errors"] == 1
    for junk in (float("inf"), float("nan"), True, "lots", -5, None, [1], 10 ** 30):
        got = settings({"canon": {"shadow": True, "backfill": junk, "num_ctx": junk,
                                  "max_errors": junk}})
        assert 0 <= got["backfill"] <= 100_000 and 2048 <= got["num_ctx"] <= 16384, (junk, got)
        assert 1 <= got["max_errors"] <= 20, (junk, got)
    for junk in (7, "", "x" * 500, ["a"], None):
        got = settings({"canon": {"shadow": True, "model": junk, "host": junk}})
        assert got["model"] == "gemma3:4b" and got["host"] == "http://localhost:11434", junk
    assert settings({"canon": {"shadow": True}})["identity_via_pronoun"] is False, "off by default (D-024)"
    for junk in ("true", 1, "on", None, []):
        assert settings({"canon": {"shadow": True, "identity_via_pronoun": junk}})["identity_via_pronoun"] is False, junk
    assert settings({"canon": {"shadow": True, "identity_via_pronoun": True}})["identity_via_pronoun"] is True
    print("1. shadow needs a literal true; every value is bounded; junk falls back")


def test_off_by_default_costs_nothing():
    code = (
        "import os, sys\n"
        "os.environ['CODERAIN_HOME'] = sys.argv[1]\n"
        "from coderain.config import load_config\n"
        "from coderain.engine import Engine\n"
        "from coderain.memory import Library\n"
        "lib = Library(sys.argv[1]); s = lib.store(lib.create_story('X', 'y'))\n"
        "e = Engine(load_config(), s)\n"
        "assert e.canon_shadow is None\n"
        "loaded = [m for m in sys.modules if m == 'canon' or m.startswith('canon.')"
        " or m == 'coderain.canon_shadow']\n"
        "assert not loaded, loaded\n"
        "print('clean')\n")
    r = subprocess.run([sys.executable, "-c", code, str(WORK / "h2")], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "clean" in r.stdout, (r.stdout, r.stderr[-400:])
    cfg = load_config()
    cfg.raw["canon"] = {"shadow": True}
    eng = Engine(cfg, new_save())
    assert isinstance(eng.canon_shadow, CanonShadow)
    cfg.raw["canon"] = {"shadow": "yes"}
    assert Engine(cfg, new_save()).canon_shadow is None
    cfg.raw.pop("canon")
    print("2. off by default: no object, canon/ not even imported; on only for true")


def test_observe_only():
    cfg = load_config()
    store = new_save()
    story(store, M1, M2)
    eng = Engine(cfg, store)
    before_prompt = json.dumps(eng._messages(eng.history_window(), "I look around"))
    before_files = tree(store)
    sh, _ = shadow(store)
    sh.reconcile()
    after_prompt = json.dumps(eng._messages(eng.history_window(), "I look around"))
    assert before_prompt == after_prompt, "the shadow changed the prompt"
    assert tree(store) == before_files, "the shadow wrote outside <save>/canon/"
    assert (Path(store.dir) / "canon" / "shadow.json").exists()
    for fn in (Engine._messages, MemoryStore.assemble, Engine.history_window):
        src = inspect.getsource(fn)
        assert "canon" not in src.lower(), f"{fn.__qualname__} mentions canon"
    print("3. the prompt is byte-identical, nothing outside canon/ changed, and the "
          "prompt code does not mention it")


def test_a_pass_and_its_report():
    store = new_save()
    story(store, M1, M2, M3, M4, NOBODY)
    sh, stub = shadow(store)
    out = sh.reconcile()
    assert out["processed"] == 4 and out["skipped"] == 1 and out["errors"] == 0, out
    assert len(stub.calls) == 4, "a turn naming nobody was sent to the model"
    v = view(sh._store().canon)
    assert v["odile"]["identity.hair"] == "raven", "first narration should hold"
    assert v["corin"]["identity.eyes"] == "grey"
    assert v["tamsin"]["state.outfit"] == ["green scarf"] and v["tamsin"]["state.held"] == ["lantern"]
    state = json.loads((Path(store.dir) / "canon" / "shadow.json").read_text())
    assert sorted(int(k) for k in state["hashes"]) == [2, 4, 6, 8, 10], state
    rows = [json.loads(x) for x in (Path(store.dir) / "canon" / "rows.jsonl").read_text().splitlines()]
    assert [r["turn"] for r in rows] == [2, 4, 6, 8, 10]
    held = [h for r in rows for h in r.get("held_back", [])]
    assert held == [{"entity": "odile", "slot": "identity.hair", "held": "raven",
                     "proposed": "platinum"}], held
    assert rows[0]["next_cast"] and rows[0]["next_card_chars"] == 0,         "turn 1 states identity only, so the state card is empty"
    assert rows[3]["next_card_chars"] > 0, "by turn 4 Tamsin has an outfit and a lantern"
    report = (Path(store.dir) / "canon" / "report.txt").read_text()
    assert "held 'raven'" in report and "story said 'platinum'" in report
    assert "Observe only" in report
    assert "State values and how long ago the story last stated them" in report
    assert "outfit: 1 characters have one, median age" in report and "-turn window" in report
    for name in ("report.txt", "rows.jsonl", "shadow.json"):
        text = (Path(store.dir) / "canon" / name).read_text()
        for prose in (M1, M2, M3, M4, NOBODY, "stepped in", "glared at her",
                      "caught the lamp", "picked up the lantern"):
            assert prose not in text, f"narration reached {name}: {prose!r}"
    print("4. narrator turns are read, one that names nobody is skipped, a held-back "
          "change is reported, and no prose reaches the report")


def test_it_follows_every_kind_of_change():
    def check(label, mutate, final, player=True, rolled=True):
        store = new_save()
        story(store, M1, M2, M3, M4)
        sh, stub = shadow(store)
        sh.reconcile()
        mutate(store)
        out = sh.reconcile()
        got, want = view(sh._store().canon), fresh_view(*final, player=player)
        assert got == want, f"{label}: canon differs from a fresh replay\n{got}\n{want}"
        assert (out["rolled_back_to"] is not None) == rolled, (label, out)
        return store, sh, out

    check("undo", lambda s: s.drop_last_turns(2), [M1, M2, M3])
    store, sh, _ = check("undo to nothing", lambda s: s.drop_last_turns(8), [])
    assert view(sh._store().canon) == {}
    rows = (Path(store.dir) / "canon" / "rows.jsonl").read_text().strip()
    assert rows == "", "rows for turns that no longer exist were kept"
    # update_turn is 0-based over the transcript; the ledger and branch() are 1-based
    check("edit of an old turn", lambda s: s.update_turn(3, R2), [M1, R2, M3, M4])
    check("retry", lambda s: (s.drop_last_turns(2), story(s, M4B)), [M1, M2, M3, M4B])
    check("swipe", lambda s: s.update_turn(7, M4B), [M1, M2, M3, M4B])

    # a Continue appends narration with no player turn: nothing to roll back
    store = new_save()
    story(store, M1, M2)
    sh, _ = shadow(store)
    sh.reconcile()
    store.append_turn("narrator", M4)
    out = sh.reconcile()
    assert out["rolled_back_to"] is None and out["processed"] == 1, out
    plain = new_save()
    story(plain, M1, M2)
    plain.append_turn("narrator", M4)
    sh2, _ = shadow(plain)
    sh2.reconcile()
    assert view(sh._store().canon) == view(sh2._store().canon)

    # a real branch: the save, its canon/ folder and all, is copied and truncated
    store = new_save()
    story(store, M1, M2, M3, M4)
    sh, _ = shadow(store)
    sh.reconcile()
    slug = Path(store.dir).name
    new_slug, _warn = lib.saves.branch(slug, 4)
    bstore = lib.store(new_slug)
    assert (Path(bstore.dir) / "canon" / "shadow.json").exists(), "branch did not copy canon/"
    bsh, bstub = shadow(bstore)
    out = bsh.reconcile()
    # branch keeps turns 1..4, so the first narrator turn that is gone is 6 and the
    # ledger is cut after 5; nothing needs the model again
    assert out["rolled_back_to"] == 5 and bstub.calls == [], out
    assert view(bsh._store().canon) == fresh_view(M1, M2), "a branch kept the future"
    print("5. undo, undo to nothing, an edit, a retry, a swipe, a Continue and a real "
          "branch each leave canon equal to a fresh replay")


def test_it_resumes():
    store = new_save()
    story(store, M1, M2, M3)
    sh, stub = shadow(store)
    sh.reconcile()
    again, stub2 = shadow(store)                 # a new object: a restart
    out = again.reconcile()
    assert stub2.calls == [] and out["processed"] == 0 and out["rolled_back_to"] is None, out
    print("6. a restart over an unchanged transcript sends nothing")


def test_backfill():
    def calls(backfill):
        store = new_save()
        story(store, *[f"Odile Marsh waited, turn {i}." for i in range(10)])
        sh, stub = shadow(store, backfill=backfill)
        sh.reconcile()
        return len(stub.calls)
    assert calls(0) == 1 and calls(3) == 4 and calls(200) == 10 and calls("all") == 10
    # a later turn is always read, whatever the window was
    store = new_save()
    story(store, *[f"Odile Marsh waited, turn {i}." for i in range(10)])
    sh, stub = shadow(store, backfill=2)
    sh.reconcile()
    n = len(stub.calls)
    story(store, "Odile Marsh waited, turn 10.")
    sh.reconcile()
    assert len(stub.calls) == n + 1
    print("7. backfill bounds the first read; later turns are always read")


def _health(store):
    return [h for h in store.health(50) if h["stage"] == "canon-shadow"]


def test_failures_are_contained_and_visible():
    # a model that is down: nothing raised, retried later, reported ONCE
    store = new_save()
    story(store, M1, M2, M3, M4)
    sh, stub = shadow(store, max_errors=3)

    def down(complete_call):
        raise ScribeError("cannot reach localhost:11434")
    stub.hook = down
    out = sh.reconcile()
    assert out["errors"] == 3 and out["processed"] == 0, out
    assert json.loads((Path(store.dir) / "canon" / "shadow.json").read_text())["hashes"] == {}
    sh.reconcile()
    assert len(_health(store)) == 1, _health(store)        # reported once, not per pass
    assert "could not be reached" in _health(store)[0]["reason"]
    stub.hook = None                                       # the model comes back
    out = sh.reconcile()
    assert out["processed"] == 4, "the turns that failed were not retried"
    assert view(sh._store().canon) == fresh_view(M1, M2, M3, M4)

    # a model that is not on this machine: refused, reported, never called
    store = new_save()
    story(store, M1)
    stub = Stub()
    stub.stays_local = False
    sh = CanonShadow(store, settings({"canon": {"shadow": True}}), scribe=Scribe(stub))
    sh.reconcile()
    assert stub.calls == [] and sh.enabled is False
    assert "not this machine" in _health(store)[0]["reason"] or "not a local" in _health(store)[0]["reason"]
    sh.kick()
    sh.wait()
    assert stub.calls == [], "a disabled shadow still worked"
    remote = new_save()
    story(remote, M1)
    cfg = settings({"canon": {"shadow": True, "host": "http://10.0.0.5:11434"}})
    rsh = CanonShadow(remote, cfg)
    rsh.reconcile()
    assert rsh.enabled is False and _health(remote), "a remote host was accepted"

    # a crash in the worker: kick() and the thread swallow it, and say so
    store = new_save()
    story(store, M1)
    sh, stub = shadow(store)

    def boom(rel):
        raise RuntimeError("characters.md exploded")
    real = store.entries
    store.entries = boom
    sh.kick()
    sh.wait()
    store.entries = real
    assert any("exploded" in h["reason"] for h in _health(store)), _health(store)

    # a corrupt ledger is derived data: start over from the transcript
    store = new_save()
    story(store, M1, M2, M3)
    sh, _ = shadow(store)
    sh.reconcile()
    ledger = Path(store.dir) / "canon" / "ledger" / "ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1][:-8] + "0000}}"          # a record that no longer matches its hash
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sh2, _ = shadow(store)
    sh2.reconcile()
    assert view(sh2._store().canon) == fresh_view(M1, M2, M3), "did not recover"
    assert any("unreadable" in h["reason"] or "rebuilding" in h["reason"]
               for h in _health(store)), _health(store)

    # a deleted save is not resurrected by a late pass
    store = new_save()
    story(store, M1)
    sh, _ = shadow(store)
    gone = Path(store.dir)
    shutil.rmtree(gone)
    assert sh.reconcile()["processed"] == 0
    assert not gone.exists(), "the shadow recreated a deleted save's folder"
    print("8. a down model is retried and reported once; a non-local model is refused; "
          "a crash, a corrupt ledger and a deleted save never reach a turn")


def test_threads():
    # kick() returns at once even while the model is slow
    store = new_save()
    story(store, M1, M2)
    sh, stub = shadow(store)
    gate = threading.Event()
    stub.hook = lambda n: gate.wait(10)
    t0 = time.time()
    for _ in range(5):                              # five kicks coalesce
        sh.kick()
    assert time.time() - t0 < 0.5, "kick() blocked"
    gate.set()
    sh.wait()
    assert len(stub.calls) == 2, f"kicks did not coalesce: {len(stub.calls)} calls"
    assert view(sh._store().canon) == fresh_view(M1, M2)

    # a turn that is generating is waited for
    store = new_save()
    story(store, M1)
    sh, stub = shadow(store)
    busy = {"on": True}
    sh.busy = lambda: busy["on"]
    sh.kick()
    time.sleep(1.3)
    assert stub.calls == [], "the shadow ran while a turn was generating"
    busy["on"] = False
    sh.wait()
    assert len(stub.calls) == 1

    # a transcript that moves mid-pass is picked up by the next pass
    store = new_save()
    story(store, M1, M2, M3, M4)
    sh, stub = shadow(store)
    stub.hook = lambda n: store.drop_last_turns(2) if n == 2 else None   # an undo, mid-pass
    sh.reconcile()
    stub.hook = None
    sh.reconcile()
    assert view(sh._store().canon) == fresh_view(M1, M2, M3), "a mid-pass undo was missed"
    print("9. kick() returns at once and coalesces; a generating turn is waited for; "
          "a mid-pass change is picked up")


def test_engine_hook():
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["use_memory_tool"] = False
    cfg.generation["think"] = False
    cfg.raw["canon"] = {"shadow": True, "backfill": "all"}
    try:
        store = new_save()
        eng = Engine(cfg, store)
        stub = Stub()
        eng.canon_shadow.scribe = Scribe(stub)

        class OneShot:
            def stream(self, m, **k):
                yield "Odile Marsh stepped in, her raven hair damp."
        eng.llm = OneShot()
        list(eng.turn("I open the door"))
        eng.maybe_fold()
        eng.canon_shadow.wait()
        report = (Path(store.dir) / "canon" / "report.txt").read_text()
        assert "odile" in view(eng.canon_shadow._store().canon), report
        assert eng.canon_shadow._store().canon.current("odile", "identity.hair") == "raven"

        # a shadow that explodes must not stop maybe_fold
        shadow_real = eng.canon_shadow
        shadow_real.reconcile = lambda: (_ for _ in ()).throw(RuntimeError("reconcile exploded"))
        eng.maybe_fold()
        shadow_real.wait()
        assert any("exploded" in h["reason"] for h in _health(store))
        assert isinstance(eng.maybe_fold(), list)
    finally:
        cfg.raw.pop("canon", None)
    print("10. a turn plus maybe_fold produces a report, and a shadow that explodes "
          "does not stop maybe_fold")


def test_export_does_not_carry_the_ledger():
    store = new_save()
    story(store, M1, M2)
    sh, _ = shadow(store)
    sh.reconcile()
    slug = Path(store.dir).name
    dest = lib.saves.export(slug, WORK / "out.zip")
    names = zipfile.ZipFile(dest).namelist()
    assert "transcript.md" in names and "characters.md" in names, names[:8]
    assert not any(n.split("/")[0] == "canon" for n in names), \
        [n for n in names if n.startswith("canon")]
    print("11. an export carries the story, not the derived ledger")


def test_a_character_who_appears_mid_story():
    """A character sheet created after the shadow started is seeded at the turn it
    is first met, because a ledger's turns never decrease: seeding it at turn 0 would
    be refused and every claim about them would silently go nowhere. An undo past that
    turn takes them out again, and replaying brings them back."""
    store = new_save(PEOPLE[:1])
    story(store, M1)
    sh, _ = shadow(store)
    sh.reconcile()
    assert "corin" not in sh._store().canon.entities
    store.upsert_entry("characters.md", Entry(title="Corin Hale", slug="corin"))
    story(store, M2)
    sh.reconcile()
    assert sh._store().canon.current("corin", "identity.eyes") == "grey",         "a character met mid-story was lost"
    store.drop_last_turns(2)
    sh.reconcile()
    assert "corin" not in sh._store().canon.entities, "an undo kept the entity"
    story(store, M2)
    sh.reconcile()
    assert sh._store().canon.current("corin", "identity.eyes") == "grey"
    print("12. a character met mid-story is seeded at that turn, dropped by an undo "
          "past it, and brought back by replay")


def test_the_server_lets_the_shadow_yield_to_a_turn():
    import importlib
    server = importlib.import_module("server")
    server._cfg.raw["canon"] = {"shadow": True}
    try:
        slug = server.lib.saves.create("Yield", premise="x", mode="simple")
        server._engines.pop(slug, None)
        eng = server._engine(slug)
        assert eng.canon_shadow is not None and eng.canon_shadow.busy is not None
        assert eng.canon_shadow.busy() is False
        assert server._gen_lock.acquire(blocking=False)
        try:
            assert eng.canon_shadow.busy() is True, "the shadow cannot see a turn running"
        finally:
            server._gen_lock.release()
    finally:
        server._cfg.raw.pop("canon", None)
        server._engines.clear()
    print("13. the server gives the shadow a probe for a generating turn")


def test_a_second_person_story_and_a_pronoun_reach_canon():
    """D-024: a story told to "you" names the player almost never, and "she" runs for turns
    after a name. The adapter works out who "you" is from player.md, hands the validator
    the turns before, and a pronoun resolves for a state fact and never an identity fact."""
    people = PEOPLE + [("finn", "Finn", ["Blank"])]
    store = new_save(people)
    store.write("player.md", "# Player character\n\nName: Finn\nInfo: tall, male, a tourist in the harbour town.\n")
    t1 = "Odile Marsh stepped in. She wore a grey coat, her hair raven."
    t2 = "You pull on your hoodie and your hair is wet."
    t3 = "She tilts her head, a silver ring on her finger."
    t4 = "Finn stood there, her green eyes bright."
    story(store, t1, t2, t3, t4)
    script = [("grey coat", [claim("she", "state.outfit", "add", "grey coat", "She wore a grey coat"),
                             claim("she", "identity.hair", "set", "raven", "her hair raven")]),
              ("pull on your hoodie", [claim("you", "state.outfit", "add", "hoodie", "pull on your hoodie"),
                                       claim("you", "identity.hair", "set", "wet", "your hair is wet")]),
              ("silver ring", [claim("Odile Marsh", "state.outfit", "add", "silver ring", "a silver ring on her finger")]),
              ("green eyes bright", [claim("Finn", "identity.eyes", "set", "green", "her green eyes")])]
    sh, stub = shadow(store)
    SCRIPT[:] = script
    try:
        out = sh.reconcile()
    finally:
        SCRIPT[:] = ORIGINAL_SCRIPT
    c = sh._store().canon
    assert out["processed"] == 4 and out["skipped"] == 0, ("the second-person turn is read", out)
    assert len(stub.calls) == 4
    assert list(c.current("odile", "state.outfit")) == ["grey coat", "silver ring"],         "'she' resolved in the same passage, and a Scribe that named her resolved from the turn before"
    assert c.current("odile", "identity.hair") is None, "a pronoun never writes identity"
    assert list(c.current("finn", "state.outfit")) == ["hoodie"], "'you' is Finn, found from player.md"
    report = (Path(store.dir) / "canon" / "report.txt").read_text()
    assert "Facts whose subject the code found" in report and "3 {" in report, \
        "the report says how many facts rest on the code's reading, not a name"
    rows = sh._read_rows()
    assert [r.get("via") for r in (rows[2], rows[4], rows[6], rows[8])] == \
        [{"pronoun": 1}, {"you": 1}, {"context": 1}, None], "each turn's row says how its subjects were found"
    assert c.current("finn", "identity.hair") is None, "wet is not a hair colour"
    assert c.current("finn", "identity.eyes") is None,         "player.md says male, so a quote about 'her' eyes is not a fact about Finn"
    # the same turn with the player named in config instead
    store2 = new_save(people)
    story(store2, t2)
    sh2, _ = shadow(store2, player="finn")
    SCRIPT[:] = script
    try:
        sh2.reconcile()
    finally:
        SCRIPT[:] = ORIGINAL_SCRIPT
    assert list(sh2._store().canon.current("finn", "state.outfit")) == ["hoodie"], "config names the player"
    # with nobody named as the player a second-person turn is skipped, as before
    store3 = new_save(people)
    story(store3, t2)
    sh3, stub3 = shadow(store3)
    out3 = sh3.reconcile()
    assert out3["skipped"] == 1 and stub3.calls == [], "no player.md, no config: nobody to read it for"
    print("14. 'you' is the player from player.md or config, 'she' resolves for state and not identity, "
          "and a second-person turn is read")


def test_gender_votes_follow_the_transcript():
    """A turn's gender votes live in its row, so an edit that drops a turn drops its votes."""
    store = new_save()
    texts = ["Odile Marsh tied her hair.", "Odile Marsh lifted her chin.", "Odile Marsh bit her lip."]
    story(store, *texts)
    sh, _ = shadow(store)
    sh.reconcile()
    rows = sh._read_rows()
    assert sorted(rows) == [2, 4, 6] and all(r.get("votes") == {"odile": [0, 1]} for r in rows.values()), rows
    assert GenderVotes(rows.values()).genders() == {"odile": "F"}
    store.update_turn(5, "Odile Marsh stood still.")                      # turn 6 now says nothing gendered
    sh.reconcile()
    rows = sh._read_rows()
    assert rows[6].get("votes") is None and rows[2]["votes"] == {"odile": [0, 1]}
    assert GenderVotes(rows.values()).genders() == {}, "two votes are not enough, so she is unknown again"
    print("15. a turn's gender votes live in its row and an edit takes them away with the turn")


def test_the_player_is_seeded_from_player_md():
    """D-025: the protagonist's file is the first write for their looks, so a narrated value
    that differs is held back and a pass that repeats writes nothing new."""
    store = new_save(PEOPLE + [("finn", "Finn", ["Blank"])])
    store.write("player.md", "# Player character\n\nName: Finn\nInfo: tall, male, black hair, green eyes.\n")
    t1 = "Finn stood there, his brown eyes bright."
    t2 = "The rain kept falling on the harbour."
    story(store, t1)
    sh, _ = shadow(store)
    SCRIPT[:] = [("brown eyes bright", [claim("Finn", "identity.eyes", "set", "brown", "his brown eyes bright")])]
    try:
        sh.reconcile()
    finally:
        SCRIPT[:] = ORIGINAL_SCRIPT
    c = sh._store().canon
    assert (c.current("finn", "identity.hair"), c.current("finn", "identity.eyes"),
            c.current("finn", "identity.build")) == ("black", "green", "tall")
    assert c.slots["finn"]["identity.eyes"][-1].authority == "scenario"
    held = sh._read_rows()[2].get("held_back")
    assert held == [{"entity": "finn", "slot": "identity.eyes", "held": "green", "proposed": "brown"}], held
    story(store, t2)
    sh.reconcile()
    seeded = [r for r in sh._store().ledger.records if r.authority == "scenario" and r.entity == "finn"
              and r.slot.startswith("identity.")]
    assert len(seeded) == 3, "a later pass seeds nothing again"
    print("16. player.md seeds the protagonist's looks at scenario authority, a different narrated "
          "value is held back, and a repeat pass writes nothing")


def test_the_report_says_what_the_flag_does_and_warns_about_a_partial_read():
    """The report said "Observe only: nothing here reaches a prompt" whatever the config, which became
    false the moment injection existed. It now says what is true, and a partial first read (found in
    the first preview on a real save: 3 of 8 identity values differed from a full read) is named."""
    def report(**over):
        store = new_save()
        story(store, M1, M2, M3, M4)
        sh, _ = shadow(store, **over)
        sh.reconcile()
        return (Path(store.dir) / "canon" / "report.txt").read_text(encoding="utf-8")
    off = report()
    assert "Observe only: nothing here reaches a prompt." in off and "Injection is" not in off
    assert "Note: only the last" not in off, "a full read has nothing to warn about"
    partial = report(backfill=2)
    assert "only the last 2 narrator turns were read the first time" in partial and "first write wins" in partial
    prev = report(inject="preview")
    assert "Injection is in PREVIEW" in prev and "NOT sent" in prev and "Observe only" not in prev, prev[:200]
    on = report(inject=True)
    assert "Injection is ON" in on and "Observe only" not in on, on[:200]
    print("17. the report says whether the card is sent, and names a partial first read")


def test_the_reader_applies_the_authors_corrections():
    """D-028. The author's corrections live in <save>/corrections.md, outside canon/, because nothing derives
    them. The reader puts the ledger in line with them at the start of a pass and after each turn (an entity
    may have just appeared), hands the validator the values the author called wrong, and re-applies after a
    rollback, since an undo cuts the records that carried them."""
    def corr(store, text):
        store.write("corrections.md", text)

    # a) the author's value outranks narration, and a later different narration is held back
    store = new_save()
    corr(store, "- Odile Marsh: hair = auburn\n")
    story(store, M1, M2, M3)
    sh, _ = shadow(store)
    sh.reconcile()
    c = sh._store().canon
    assert c.current("odile", "identity.hair") == "auburn", c.current("odile", "identity.hair")
    assert c.history("odile", "identity.hair")[-1]["authority"] == "author"
    assert any(x["slot"] == "identity.hair" and x["proposed"] == "platinum" and x["reason"] == "identity_locked"
               for x in c.conflicts), "narration was not held back against the author"
    rep = (Path(store.dir) / "canon" / "report.txt").read_text(encoding="utf-8")
    assert "Author corrections (corrections.md): 1 in force." in rep, rep[:400]

    # b) a value called wrong is refused from the first turn, so the story can establish the real one
    store = new_save()
    corr(store, "- Odile: hair is not raven\n")
    story(store, M1, M2, M3)
    sh, _ = shadow(store)
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") == "platinum"
    refused = [r for r in sh._read_rows().values() if "author_refused" in r.get("reasons", {})]
    assert refused, "the refusal never reached a turn's row"

    # c) an edit made by hand AFTER the value was held is picked up by the next pass
    store = new_save()
    story(store, M1, M2)
    sh, _ = shadow(store)
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") == "raven"
    corr(store, "- Odile: hair is not raven\n")
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") is None, "the retraction was not applied"
    n = len(sh._store().ledger)
    sh.reconcile()
    assert len(sh._store().ledger) == n, "a pass with nothing new wrote records"

    # d) it survives an undo and a replay
    store = new_save()
    corr(store, "- Odile Marsh: hair = auburn\n")
    story(store, M1, M2, M3)
    sh, _ = shadow(store)
    sh.reconcile()
    store.drop_last_turns(4)                                   # back to M1 only: rolls the ledger back
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") == "auburn", "an undo lost the correction"
    story(store, M3)
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") == "auburn"
    from canon import Store
    fresh = Store(sh._store().dir)                             # and a reopen of the ledger agrees
    assert fresh.canon.current("odile", "identity.hair") == "auburn"

    # e) a character who appears later is corrected once they exist, and until then it is reported
    store = new_save(PEOPLE[:1])
    story(store, M1)
    sh, _ = shadow(store)
    sh.reconcile()
    store.upsert_entry("characters.md", Entry(title="Corin Hale", slug="corin"))
    corr(store, "- Corin Hale: eyes = hazel\n")
    v = sh.view(store.turns())
    assert any("Corin Hale" in p["why"] for p in v["problems"]), v["problems"]
    story(store, M2)
    sh.reconcile()
    assert sh._store().canon.current("corin", "identity.eyes") == "hazel", "applied once they exist"
    rep = (Path(store.dir) / "canon" / "report.txt").read_text(encoding="utf-8")
    assert "1 in force." in rep and "not applied" not in rep, rep[:500]

    # f) the view is what the app shows: values with whose word, the file, the problems
    v = sh.view(store.turns())
    by = {(r["who"], r["slot"]): r for r in v["values"]}
    assert by[("Corin Hale", "eyes")]["value"] == "hazel" and by[("Corin Hale", "eyes")]["by"] == "author"
    assert by[("Odile Marsh", "hair")]["value"] == "raven" and by[("Odile Marsh", "hair")]["by"] == "narration"
    assert v["shadow"] is True and v["unread"] == 0 and "eyes = hazel" in v["text"]
    assert v["corrections"][0]["who"] == "Corin Hale" and v["problems"] == []
    print("18. the reader applies the author's corrections: they outrank narration, a wrong value is refused "
          "from the first turn, a hand edit is picked up, an undo does not lose them, and a late character "
          "is corrected once present")


def test_removing_the_last_correction_releases_its_value():
    """D-028. The panel's Remove button deletes a line from corrections.md and nothing else. If the reader only
    acted while the file had lines in it, the author's value would stay in the ledger as "yours" next to no
    correction at all, and the story could never say anything else about that slot. An EMPTY file is a state
    like any other: the reader puts the ledger in line with it, which retracts what the file set earlier."""
    store = new_save()
    store.write("corrections.md", "- Odile Marsh: hair = auburn\n")
    story(store, M1, M2)
    sh, _ = shadow(store)
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") == "auburn"
    assert sh.view(store.turns())["values"], "nothing held"
    store.write("corrections.md", "")                       # what Remove does to the only line
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") is None, "the author's value outlived its line"
    v = sh.view(store.turns())
    assert not any(r["who"] == "Odile Marsh" and r["slot"] == "hair" for r in v["values"]), v["values"]
    assert v["corrections"] == [] and v["problems"] == []
    n = len(sh._store().ledger)
    sh.reconcile()
    assert len(sh._store().ledger) == n, "a pass with nothing new wrote records"
    story(store, M3)                                         # and the story may say what it is again
    sh.reconcile()
    assert sh._store().canon.current("odile", "identity.hair") == "platinum", \
        sh._store().canon.current("odile", "identity.hair")
    assert sh._store().canon.history("odile", "identity.hair")[-1]["authority"] == "narration"
    print("19. removing the last correction releases its value at the next pass, writes nothing after that, "
          "and leaves the slot free for the story")


def test_canon_settings_survive_the_config_file():
    """The first sandbox for the Canon panel showed the memory reader silently OFF although config.yaml asked
    for it: the file's active profile could not be built, so load_config fell back to the shipped defaults,
    which have no `canon:` key. Nothing in the tests ever went through the real config file, they all set
    `cfg.raw["canon"]` in memory. This pins the path a person actually uses: a valid file with a `canon:` block
    is read whole, builds the shadow with those settings, and survives the rewrite the Settings page does
    (`save_yaml(cfg.raw)`) with the block intact."""
    import copy
    from coderain.config import save_yaml
    raw = copy.deepcopy(load_config().raw)
    assert "canon" not in raw, "the shipped defaults must not switch the reader on"
    raw["canon"] = {"shadow": True, "inject": "preview", "backfill": "all", "card_chars": 1800}
    path = WORK / "cfgtest" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    save_yaml(raw, path)
    cfg = load_config(path)
    assert cfg.raw["canon"] == raw["canon"], cfg.raw.get("canon")
    sh = CanonShadow.from_config(cfg, new_save())
    assert sh is not None, "a canon block in a valid config did not create the reader"
    assert sh.cfg["inject"] == "preview" and sh.cfg["backfill"] == BACKFILL_ALL and sh.cfg["card_chars"] == 1800, sh.cfg
    save_yaml(cfg.raw, path)                                 # what the Settings page does on every save
    again = load_config(path)
    assert again.raw["canon"] == raw["canon"], "the Settings rewrite lost the canon block"
    assert CanonShadow.from_config(again, new_save()) is not None
    del raw["canon"]                                         # and taking the block out turns it off
    save_yaml(raw, path)
    assert CanonShadow.from_config(load_config(path), new_save()) is None
    print("20. a canon block in a valid config.yaml is read whole, creates the reader with those settings, "
          "survives the Settings rewrite, and is off once removed")


SHEET = "**Visual:** the courier, with grey eyes and raven hair. **Mentality:** wary. She keeps her hair tied."


def sheet_save(sheet=SHEET):
    store = new_save([("odile", "Odile Marsh", ["The Courier"])])
    store.upsert_entry("characters.md", Entry(title="Odile Marsh", slug="odile", aliases=["The Courier"],
                                              body=sheet))
    return store


def run_with(store, script):
    sh, _ = shadow(store)
    SCRIPT[:] = script
    try:
        sh.reconcile()
    finally:
        SCRIPT[:] = ORIGINAL_SCRIPT
    return sh


def test_authored_sheets_seed_a_new_story():
    """D-029. In a plain invented soak the sheet said green eyes, the Writer's first narration said dark,
    first write wins, and the card told the Writer "dark" for 240 turns. A sheet that exists when the story
    is brand new is the author's, so it is the first write, at scenario authority; a narrated value that
    differs is held back."""
    store = sheet_save()
    story(store, "Odile Marsh looked up, her pale eyes tired.")
    sh = run_with(store, [("pale eyes tired", [claim("Odile Marsh", "identity.eyes", "set", "pale", "her pale eyes tired")])])
    c = sh._store().canon
    assert (c.current("odile", "identity.eyes"), c.current("odile", "identity.hair")) == ("grey", "raven")
    assert c.slots["odile"]["identity.eyes"][-1].authority == "scenario"
    assert sh._read_rows()[2].get("held_back") == [
        {"entity": "odile", "slot": "identity.eyes", "held": "grey", "proposed": "pale"}], sh._read_rows()[2]
    assert sh._load_state()["fresh"] is True, "remembered across passes and restarts"
    n = len(sh._store().ledger)
    story(store, "The harbour was quiet.")
    sh.reconcile()
    assert not [r for r in sh._store().ledger.records[n:] if r.authority == "scenario"], "a later pass writes nothing"
    print("21. a sheet's Visual line is the first write on a new story and a differing narrated value is held back")


def test_sheets_are_not_authored_once_a_story_is_under_way():
    """D-029, the guard. On a story that already has narration the sheets were folded out of it (and may
    have drifted), so they are NOT seeded: first narration still wins there, as before. Nor is a character
    who appears after the first turns, and a sheet without a Visual label is never read for looks."""
    store = sheet_save()
    story(store, "Odile Marsh looked up, her pale eyes tired.", "The rain fell.", "The rain kept falling.",
          "The rain fell harder.")
    sh = run_with(store, [("pale eyes tired", [claim("Odile Marsh", "identity.eyes", "set", "pale", "her pale eyes tired")])])
    c = sh._store().canon
    assert c.current("odile", "identity.eyes") == "pale" and c.current("odile", "identity.hair") is None, \
        "a story already under way: nothing seeded, the narration is the first write"
    assert sh._load_state()["fresh"] is False
    late = sheet_save()
    story(late, "The street was empty.")
    sh2, _ = shadow(late)
    sh2.reconcile()
    assert sh2._load_state()["fresh"] is True, "the story was new at the first pass"
    story(late, "The street stayed empty.", "Still empty.", "Nobody came.", "The lamps burned down.")
    late.upsert_entry("characters.md", Entry(title="Corin Hale", slug="corin", aliases=[],
                                             body="**Visual:** with brown eyes."))
    story(late, "Corin Hale arrived.")
    sh2.reconcile()
    assert "corin" in sh2._store().canon.entities
    assert sh2._store().canon.current("corin", "identity.eyes") is None, "met after the first turns: not authored"
    plain = sheet_save("She keeps her hair tied and has grey eyes when she is tired.")
    story(plain, "The street was empty.")
    sh3, _ = shadow(plain)
    sh3.reconcile()
    assert sh3._store().canon.current("odile", "identity.hair") is None, "no Visual label: no looks read"
    print("22. an under-way story, a character met later and a sheet with no Visual label are never seeded")


def test_a_look_through_a_pronoun_reaches_canon_only_when_switched_on():
    """D-035: the reader takes an identity fact said with "she" for the one character the nearest sentences name, only
    when canon.identity_via_pronoun is true; by default (D-024) it never does."""
    texts = ["Odile Marsh looked up from the rope.", "She pushed back her raven hair."]
    script = [("raven hair", [claim("she", "identity.hair", "set", "raven", "her raven hair")])]
    got = {}
    for label, over in (("off", {}), ("on", {"identity_via_pronoun": True})):
        store = new_save()
        story(store, *texts)
        sh, _ = shadow(store, **over)
        SCRIPT[:] = script
        try:
            sh.reconcile()
        finally:
            SCRIPT[:] = ORIGINAL_SCRIPT
        got[label] = sh._store().canon.current("odile", "identity.hair")
    assert got == {"off": None, "on": "raven"}, got
    print("23. a look said with 'she' reaches canon only when identity_via_pronoun is on")


try:
    for fn in (test_settings, test_off_by_default_costs_nothing, test_observe_only,
               test_a_pass_and_its_report, test_it_follows_every_kind_of_change,
               test_it_resumes, test_backfill, test_failures_are_contained_and_visible,
               test_threads, test_engine_hook, test_export_does_not_carry_the_ledger,
               test_a_character_who_appears_mid_story,
               test_the_server_lets_the_shadow_yield_to_a_turn,
               test_a_second_person_story_and_a_pronoun_reach_canon,
               test_gender_votes_follow_the_transcript,
               test_the_player_is_seeded_from_player_md,
               test_the_report_says_what_the_flag_does_and_warns_about_a_partial_read,
               test_the_reader_applies_the_authors_corrections,
               test_removing_the_last_correction_releases_its_value,
               test_canon_settings_survive_the_config_file,
               test_authored_sheets_seed_a_new_story,
               test_sheets_are_not_authored_once_a_story_is_under_way,
               test_a_look_through_a_pronoun_reaches_canon_only_when_switched_on):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON SHADOW TESTS PASSED")
