"""Phase 1 of the consistency design: the canon ledger.

The gate this suite has to pass, taken from the plan:

  * replay equals state
  * undo equals truncating the ledger
  * rebuilding from the ledger reproduces canon

and the failure each one exists to prevent. In the current engine a fact lives in
a paragraph that a model rewrites, state and the replay ledger can disagree, and
a snapshot can outlive the timeline it described (docs/DECISIONS.md D-006). Here
the ledger is the only truth and everything else is derived, so those become
properties that can be tested instead of bugs that can be found.

 1) append, reopen: same records and the same chain head
 2) a tampered, reordered or shortened ledger is detected on open
 3) a torn final line is dropped and reported; an earlier one is corruption
 4) every bound rejects (and leaves the ledger untouched): length, cardinality,
    ids, types, time going backwards
 5) the layer rule: identity and state cannot be written through each other
 6) identity is first-write-wins; a clash is a recorded conflict, never applied
 7) state is latest-wins, keeps history, and answers "as of turn N"
 8) an unknown entity or nothing-to-clear is a conflict, not an exception
 9) story-time queries use valid time and never guess a missing one
10) aliases resolve, and an ambiguous alias resolves to nothing
11) replay equals state, over 25 random ledgers
12) undo equals truncation, and as-of-turn agrees with it, over 15 random ledgers
13) a snapshot is only a cache: missing, stale, behind, rewritten, altered or
    garbage, the canon that results is always the ledger's
14) projection invariants hold on random ledgers
15) projection is deterministic

The random ledgers use a seeded generator from the standard library. `hypothesis`
would shrink failures, and it is not installed; a failing seed is printed instead.
"""
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-canon-"))

from canon import (AUTHORITY, Canon, Ledger, LedgerCorrupt, LedgerError,  # noqa: E402
                   Store, project)
from canon.ledger import Record                                           # noqa: E402

_n = [0]


def _dir():
    _n[0] += 1
    return WORK / f"s{_n[0]}"


def _expect(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}: {a} {k}")


def _create(store, ent, name, turn=0, aliases=()):
    return store.append(kind="entity_created", entity=ent, slot="character",
                        value=name, authority="scenario", turn=turn,
                        aliases=list(aliases))


def _fact(store, ent, slot, value, turn, authority="narration", **kw):
    return store.append(kind="fact_established", entity=ent, slot=slot,
                        value=value, authority=authority, turn=turn, **kw)


def _state(store, ent, slot, value, turn, authority="narration",
           kind="state_set", **kw):
    return store.append(kind=kind, entity=ent, slot=slot, value=value,
                        authority=authority, turn=turn, **kw)


# ---------------------------------------------------------------------------
# The ledger itself
# ---------------------------------------------------------------------------

def test_append_and_reopen():
    d = _dir()
    s = Store(d)
    _create(s, "odile", "Odile")
    _fact(s, "odile", "identity.hair", "raven", 1)
    _state(s, "odile", "state.outfit", ["grey coat", "boots"], 2)
    again = Ledger(d / "ledger.jsonl")
    assert [r.to_dict() for r in again.records] == \
        [r.to_dict() for r in s.ledger.records]
    assert again.head == s.ledger.head and len(again) == 3
    assert again.records[2].value == ("grey coat", "boots")
    print("1. append then reopen: same records, same chain head")


def test_tampering_is_detected():
    d = _dir()
    s = Store(d)
    _create(s, "odile", "Odile")
    _fact(s, "odile", "identity.hair", "raven", 1)
    _fact(s, "odile", "identity.eyes", "green", 2)
    path = d / "ledger.jsonl"
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    path.write_text(original.replace("raven", "ravex"), encoding="utf-8")
    _expect(LedgerCorrupt, Ledger, path)                    # a value edited
    path.write_text("".join([lines[0], lines[2], lines[1]]), encoding="utf-8")
    _expect(LedgerCorrupt, Ledger, path)                    # two lines swapped
    path.write_text("".join([lines[0], lines[2]]), encoding="utf-8")
    _expect(LedgerCorrupt, Ledger, path)                    # a middle line gone
    path.write_text(original + "not json\n", encoding="utf-8")
    _expect(LedgerCorrupt, Ledger, path)                    # garbage line
    path.write_text(original, encoding="utf-8")
    assert len(Ledger(path)) == 3                           # the control: intact
    print("2. an edited, reordered, shortened or garbled ledger is detected")


def test_torn_write_is_recovered_once():
    d = _dir()
    s = Store(d)
    _create(s, "odile", "Odile")
    _fact(s, "odile", "identity.hair", "raven", 1)
    path = d / "ledger.jsonl"
    with open(path, "ab") as fh:
        fh.write(b'{"r":{"id":3,"turn":2,"kind":"fact_est')    # cut short
    led = Ledger(path)
    assert led.recovered == 1 and len(led) == 2, (led.recovered, len(led))
    assert path.read_bytes().endswith(b"\n"), "the partial line stayed in the file"
    led.append(kind="fact_established", entity="odile", slot="identity.eyes",
               value="green", authority="narration", turn=2)
    assert len(Ledger(path)) == 3 and Ledger(path).recovered == 0
    print("3. a torn final line is dropped, reported once, and appends continue")


def test_bounds_reject_and_leave_the_ledger_alone():
    d = _dir()
    s = Store(d)
    _create(s, "odile", "Odile")
    base = dict(kind="state_set", entity="odile", slot="state.outfit",
                value="coat", authority="narration", turn=1)
    cases = {
        "value too long": {"value": "x" * 401},
        "empty value": {"value": "   "},
        "non-text value": {"value": 7},
        "list too long": {"value": ["a"] * 17},
        "empty list": {"value": []},
        "list item too long": {"value": ["x" * 121]},
        "bad entity": {"entity": "Odile"},
        "entity too long": {"entity": "a" * 65},
        "bad slot": {"slot": "state outfit"},
        "unknown kind": {"kind": "state_gone"},
        "unknown authority": {"authority": "god"},
        "boolean turn": {"turn": True},
        "negative turn": {"turn": -1},
        "float turn": {"turn": 1.5},
        "span too long": {"span": "x" * 401},
    }
    for label, patch in cases.items():
        _expect(LedgerError, s.append, **{**base, **patch})
    assert len(s.ledger) == 1, "a rejected record reached the ledger"
    assert s.ledger.path.read_text().count("\n") == 1
    s.append(**{**base, "turn": 5})
    _expect(LedgerError, s.append, **{**base, "turn": 4})   # never goes back
    s.append(**{**base, "value": "x" * 400, "turn": 5})     # exactly at the bound
    s.append(**{**base, "value": ["y"] * 16, "turn": 5})    # exactly 16 items
    _expect(LedgerError, s.append, kind="entity_created", entity="z",
            slot="character", value="Z", authority="scenario", turn=5,
            aliases=["a"] * 17)
    print(f"4. {len(cases) + 2} bound violations rejected; the ledger kept its "
          "length; the limits themselves are accepted")


def test_the_layer_rule():
    d = _dir()
    s = Store(d)
    _create(s, "odile", "Odile")
    _expect(LedgerError, _fact, s, "odile", "state.outfit", "coat", 1)
    _expect(LedgerError, _state, s, "odile", "identity.hair", "raven", 1)
    _expect(LedgerError, _state, s, "odile", "identity.hair", None, 1,
            kind="state_cleared")
    _expect(LedgerError, s.append, kind="state_cleared", entity="odile",
            slot="state.outfit", value="x", authority="narration", turn=1)
    _expect(LedgerError, s.append, kind="author_edit", entity="odile",
            slot="identity.hair", value="red", authority="narration", turn=1)
    _expect(LedgerError, s.append, kind="retcon", entity="odile",
            slot="identity.hair", value="red", authority="narration", turn=1)
    # The overrides exist to cross the layer, and may.
    s.append(kind="author_edit", entity="odile", slot="identity.hair",
             value="red", authority="author", turn=1)
    s.append(kind="retcon", entity="odile", slot="state.outfit", value="robe",
             authority="scenario", turn=1)
    assert len(s.ledger) == 3
    print("5. identity and state cannot be written through each other; only an "
          "explicit override crosses")


# ---------------------------------------------------------------------------
# The projection's rules
# ---------------------------------------------------------------------------

def test_identity_is_first_write_wins():
    s = Store(_dir())
    _create(s, "odile", "Odile")
    _fact(s, "odile", "identity.hair", "raven", 1, source_turn=1, span="raven hair")
    _fact(s, "odile", "identity.hair", "platinum", 9)           # the drift
    assert s.canon.current("odile", "identity.hair") == "raven"
    c = s.canon.conflicts[-1]
    assert (c["reason"], c["proposed"], c["existing"]) == \
        ("identity_locked", "platinum", "raven"), c
    _fact(s, "odile", "identity.hair", "raven", 10)             # corroboration
    iv = s.canon.history("odile", "identity.hair")
    assert len(iv) == 1 and iv[0]["confirmations"] == 2 and iv[0]["span"] == "raven hair"
    _fact(s, "odile", "identity.hair", "silver", 11, authority="scenario")
    assert s.canon.current("odile", "identity.hair") == "silver", "higher authority"
    _fact(s, "odile", "identity.hair", "black", 12)             # narration now loses
    assert s.canon.current("odile", "identity.hair") == "silver"
    s.append(kind="retcon", entity="odile", slot="identity.hair", value="red",
             authority="author", turn=13, span="author changed it")
    s.append(kind="author_edit", entity="odile", slot="identity.hair",
             value="auburn", authority="author", turn=14)
    h = s.canon.history("odile", "identity.hair")
    assert [x["value"] for x in h] == ["raven", "silver", "red", "auburn"], h
    assert all(h[i]["end_id"] is not None for i in range(3)) and h[3]["end_id"] is None
    assert len(s.canon.conflicts) == 2
    print("6. raven stays canon against platinum; same value corroborates; higher "
          "authority and explicit overrides supersede; history is kept")


def test_an_author_can_retract_an_identity_fact():
    """First write wins, so a wrong first value used to be permanent. Retraction is the way out: an
    author_edit or retcon with no value closes the fact and opens nothing, and the story may then
    establish the real one. State already has state_cleared; narration cannot retract at all."""
    s = Store(_dir())
    _create(s, "odile", "Odile")
    _fact(s, "odile", "identity.hair", "raven", 1)
    s.append(kind="author_edit", entity="odile", slot="identity.hair", value=None,
             authority="author", turn=2, span="the author says this is wrong")
    assert s.canon.current("odile", "identity.hair") is None, "the retracted value is still held"
    h = s.canon.history("odile", "identity.hair")
    assert len(h) == 1 and h[0]["value"] == "raven" and h[0]["end_turn"] == 2, h
    assert s.canon.value_at_turn("odile", "identity.hair", 1) == "raven", "history is kept"
    assert s.canon.value_at_turn("odile", "identity.hair", 2) is None
    _fact(s, "odile", "identity.hair", "silver", 3)                  # the story may now say what it is
    assert s.canon.current("odile", "identity.hair") == "silver"
    # retcon retracts too (scenario or author), and nothing to retract is a conflict, not a crash
    s.append(kind="retcon", entity="odile", slot="identity.hair", value=None, authority="scenario", turn=4)
    assert s.canon.current("odile", "identity.hair") is None
    n = len(s.canon.conflicts)
    s.append(kind="author_edit", entity="odile", slot="identity.hair", value=None, authority="author", turn=5)
    assert s.canon.conflicts[-1]["reason"] == "nothing_to_clear" and len(s.canon.conflicts) == n + 1
    # what it refuses: a state slot (it has state_cleared), narration, a plain fact with no value
    _expect(LedgerError, s.append, kind="author_edit", entity="odile", slot="state.outfit",
            value=None, authority="author", turn=6)
    _expect(LedgerError, s.append, kind="retcon", entity="odile", slot="identity.hair",
            value=None, authority="narration", turn=6)
    _expect(LedgerError, s.append, kind="author_edit", entity="odile", slot="identity.hair",
            value=None, authority="scenario", turn=6)
    _expect(LedgerError, s.append, kind="fact_established", entity="odile", slot="identity.hair",
            value=None, authority="author", turn=6)
    # replay, reopen and undo all agree
    assert project(s.ledger.records).as_dict() == s.canon.as_dict()
    assert Store(s.dir).canon.as_dict() == s.canon.as_dict()
    s.undo_to(1)
    assert s.canon.current("odile", "identity.hair") == "raven", "undo past the retraction restores it"
    print("6b. an author can retract an identity fact: nothing replaces it, history is kept, the story "
          "can establish the real one; state slots, narration and valueless facts are refused")


def test_state_is_latest_wins_with_history():
    s = Store(_dir())
    _create(s, "odile", "Odile")
    _state(s, "odile", "state.outfit", "travelling cloak", 1, authority="scenario")
    _state(s, "odile", "state.outfit", "grey coat", 3)          # narration may change it
    _state(s, "odile", "state.outfit", "grey coat", 4)          # no churn
    _state(s, "odile", "state.outfit", "wet grey coat", 6)
    _state(s, "odile", "state.outfit", None, 9, kind="state_cleared")
    _state(s, "odile", "state.outfit", "silk robe", 12)
    h = s.canon.history("odile", "state.outfit")
    assert [x["value"] for x in h] == \
        ["travelling cloak", "grey coat", "wet grey coat", "silk robe"], h
    assert h[1]["confirmations"] == 2, "the repeat opened a new interval"
    assert [x["end_turn"] for x in h] == [3, 6, 9, None], h
    expected = {1: "travelling cloak", 2: "travelling cloak", 3: "grey coat",
                5: "grey coat", 6: "wet grey coat", 9: None, 11: None,
                12: "silk robe", 20: "silk robe"}
    got = {t: s.canon.value_at_turn("odile", "state.outfit", t) for t in expected}
    assert got == expected, got
    _state(s, "odile", "state.mood", "calm", 13, authority="narration")
    _state(s, "odile", "state.mood", "furious", 14, authority="inferred")
    assert s.canon.current("odile", "state.mood") == "calm"
    assert s.canon.conflicts[-1]["reason"] == "lower_authority"
    _state(s, "odile", "state.held", "lantern", 15, authority="inferred")
    assert s.canon.current("odile", "state.held") == "lantern", "a guess may fill a gap"
    print("7. state is latest-wins; history and as-of-turn are exact; a guess "
          "cannot overwrite narration")


def test_conflicts_are_recorded_not_raised():
    s = Store(_dir())
    _create(s, "odile", "Odile")
    before = s.canon.digest()
    _fact(s, "ghost", "identity.hair", "raven", 1)               # unknown entity
    _state(s, "odile", "state.outfit", None, 1, kind="state_cleared")  # nothing open
    _create(s, "odile", "Other Odile", turn=1)                     # duplicate id
    reasons = [c["reason"] for c in s.canon.conflicts]
    assert reasons == ["unknown_entity", "nothing_to_clear", "entity_exists"], reasons
    assert s.canon.entities["odile"]["name"] == "Odile"
    assert "ghost" not in s.canon.entities
    after = s.canon.as_dict()
    after["conflicts"], after["last_id"] = [], 0
    clean = project([]).as_dict()
    clean["entities"] = s.canon.entities
    clean["slots"] = {"odile": {}}
    assert after["slots"] == clean["slots"], "a conflict changed canon"
    print("8. an unknown entity, nothing to clear and a duplicate entity are "
          "recorded as conflicts and change nothing")


def test_story_time_queries():
    s = Store(_dir())
    _create(s, "odile", "Odile")
    _state(s, "odile", "state.location", "harbour", 1, world_time=100)
    _state(s, "odile", "state.location", "market", 2, world_time=250)
    _state(s, "odile", "state.location", "tower", 3)               # no story time
    q = lambda t: s.canon.value_at_world_time("odile", "state.location", t)
    assert (q(50), q(100), q(249), q(250), q(900)) == \
        (None, "harbour", "harbour", "market", None), \
        [q(x) for x in (50, 100, 249, 250, 900)]
    # market has no known END, so 900 is unknown rather than 'still market'.
    print("9. story-time queries use valid time and decline to guess a missing one")


def test_alias_resolution():
    s = Store(_dir())
    _create(s, "odile", "Odile Marsh", aliases=["The Courier", "Odile"])
    _create(s, "corin", "Corin", aliases=["The Courier"])
    r = s.canon.resolve
    assert r("odile") == "odile" and r("ODILE MARSH") == "odile" and r("  Odile  ") == "odile"
    assert r("corin") == "corin"
    assert r("The Courier") is None, "an ambiguous alias was guessed"
    assert r("nobody") is None
    print("10. names, ids and aliases resolve; an ambiguous alias resolves to "
          "nothing")


# ---------------------------------------------------------------------------
# Random ledgers: the gate
# ---------------------------------------------------------------------------

ENTS = ["odile", "corin", "tamsin", "ansel", "veda", "rook"]
IDENT = ["identity.hair", "identity.eyes", "identity.marks"]
STATE = ["state.outfit", "state.location", "state.held", "state.mood"]
VALS = ["red", "blue", "grey", "gold", "silk", "wool"]     # small, so values collide
STATE_KINDS = ["state_set", "item_moved", "location_changed", "relationship_set"]


def gen(seed, n=260):
    """A random but valid stream of record field-dicts."""
    rng = random.Random(seed)
    out = [dict(kind="entity_created", entity=e, slot="character",
                value=e.title(), authority="scenario", turn=0,
                aliases=[e.upper()]) for e in ENTS]
    turn = 0
    for _ in range(n):
        turn += rng.choice([0, 0, 1, 2])
        e = rng.choice(ENTS + ["ghost"])
        world = rng.choice([None, turn * 10])
        r = rng.random()
        if r < 0.28:
            f = dict(kind="fact_established", slot=rng.choice(IDENT),
                     authority=rng.choice(["inferred", "narration", "narration",
                                           "scenario", "author"]))
        elif r < 0.64:
            f = dict(kind=rng.choice(STATE_KINDS), slot=rng.choice(STATE),
                     authority=rng.choice(["inferred", "narration", "narration",
                                           "scenario", "author"]))
        elif r < 0.80:
            f = dict(kind="state_cleared", slot=rng.choice(STATE),
                     authority=rng.choice(["inferred", "narration", "scenario"]),
                     value=None)
        elif r < 0.90:
            f = dict(kind="author_edit", slot=rng.choice(IDENT + STATE),
                     authority="author")
        else:
            f = dict(kind="retcon", slot=rng.choice(IDENT + STATE),
                     authority=rng.choice(["scenario", "author"]))
        f.setdefault("value", rng.choice(VALS))
        f.update(entity=e, turn=turn, world_time=world)
        out.append(f)
    return out


def build(seed):
    s = Store(_dir())
    for f in gen(seed):
        s.append(**f)
    return s


def test_replay_equals_state():
    for seed in range(1, 26):
        s = build(seed)
        batch = project(s.ledger.records)
        assert s.canon.as_dict() == batch.as_dict(), f"seed {seed}: online != batch"
        reopened = Store(s.dir)
        assert reopened.canon.as_dict() == batch.as_dict(), f"seed {seed}: reopen"
        inc = Canon()
        for rec in Ledger(s.dir / "ledger.jsonl").records:
            inc.apply(rec)
        assert inc.as_dict() == batch.as_dict(), f"seed {seed}: incremental"
        assert batch.conflicts, f"seed {seed}: no conflicts; the generator is too tame"
    print("11. replay equals state: online, batch, reopened and incremental agree "
          "on 25 random ledgers")


def test_undo_equals_truncation():
    rng = random.Random(7)
    for seed in range(1, 16):
        s = build(seed)
        full = project(s.ledger.records)
        top = s.ledger.records[-1].turn
        for cut in sorted({rng.randint(0, top) for _ in range(4)} | {0, top}):
            expect = project([r for r in s.ledger.records if r.turn <= cut])
            # The bi-temporal view of the FULL canon at `cut` must equal the
            # canon of the truncated ledger, slot by slot.
            for e in expect.entities:
                for slot in set(full.slots.get(e, {})) | set(expect.slots.get(e, {})):
                    assert full.value_at_turn(e, slot, cut) == \
                        expect.current(e, slot), (seed, cut, e, slot)
            # Undo acts on a COPY of the directory. (A first draft opened the same
            # directory, so the undo truncated the original ledger underneath it.)
            copy_dir = _dir()
            shutil.copytree(s.dir, copy_dir)
            twin = Store(copy_dir)
            removed = twin.undo_to(cut)
            assert twin.canon.as_dict() == expect.as_dict(), (seed, cut)
            assert removed == len(s.ledger) - len(twin.ledger)
            assert Store(copy_dir).canon.as_dict() == expect.as_dict(), \
                f"seed {seed} cut {cut}: reopened after undo"
            assert len(Ledger(s.dir / "ledger.jsonl")) == len(s.ledger), \
                "the original ledger was modified by an undo on its copy"
    print("12. undo equals truncating the ledger, and as-of-turn agrees with it, "
          "on 15 random ledgers at several cut points")


def test_snapshot_is_only_a_cache():
    s = build(3)
    s.save_snapshot()
    want = project(s.ledger.records).as_dict()
    snap = s.dir / "canon.snapshot.json"
    assert Store(s.dir).opened_from == "snapshot"

    snap.unlink()                                              # missing
    t = Store(s.dir)
    assert (t.opened_from, t.canon.as_dict()) == ("rebuild", want)

    s.save_snapshot()                                          # behind the ledger
    for f in gen(99, 40)[len(ENTS):]:
        f["turn"] = s.ledger.records[-1].turn + f["turn"] + 1
        s.append(**f)
    t = Store(s.dir)
    assert t.opened_from == "snapshot+replay"
    assert t.canon.as_dict() == project(t.ledger.records).as_dict()

    s.save_snapshot()                                          # ledger shortened
    Ledger(s.dir / "ledger.jsonl").truncate(5)
    t = Store(s.dir)
    assert t.opened_from == "rebuild"
    assert t.canon.as_dict() == project(t.ledger.records).as_dict()

    s2 = build(4)                                              # same length, other history
    s2.save_snapshot()
    n = len(s2.ledger)
    led = Ledger(s2.dir / "ledger.jsonl")
    last_turn = led.records[-3].turn
    led.truncate(last_turn)
    kept = len(led)
    while len(led) < n:
        led.append(kind="state_set", entity="odile", slot="state.held",
                   value="a different history", authority="narration",
                   turn=led.records[-1].turn)
    assert len(led) == n and kept < n
    t = Store(s2.dir)
    assert t.opened_from == "rebuild", "a snapshot of another history was trusted"
    assert t.canon.as_dict() == project(t.ledger.records).as_dict()

    s3 = build(5)                                              # contents altered
    s3.save_snapshot()
    data = json.loads((s3.dir / "canon.snapshot.json").read_text())
    first = next(iter(data["canon"]["slots"]["odile"].values()))
    first[0]["value"] = "TAMPERED"
    (s3.dir / "canon.snapshot.json").write_text(json.dumps(data))
    t = Store(s3.dir)
    assert t.opened_from == "rebuild"
    assert "TAMPERED" not in json.dumps(t.canon.as_dict())

    (s3.dir / "canon.snapshot.json").write_text("{not json")   # garbage
    assert Store(s3.dir).opened_from == "rebuild"

    s4 = build(6)                                              # undo drops a stale one
    s4.save_snapshot()
    s4.undo_to(3)
    assert not (s4.dir / "canon.snapshot.json").exists()
    print("13. missing, behind, shortened, rewritten, altered and garbage "
          "snapshots all end in the ledger's canon; none is trusted")


def test_projection_invariants():
    for seed in range(1, 26):
        s = build(seed)
        for e, slots in s.canon.slots.items():
            for slot, ivs in slots.items():
                opened = [iv for iv in ivs if iv.end_id is None]
                assert len(opened) <= 1 and (not opened or ivs[-1] is opened[0]), \
                    (seed, e, slot, "more than one open interval")
                for a, b in zip(ivs, ivs[1:]):
                    assert a.end_id is not None and a.end_id <= b.start_id, \
                        (seed, e, slot, "intervals overlap")
                    assert a.end_turn <= b.start_turn, (seed, e, slot)
                for iv in ivs:
                    assert iv.end_turn is None or iv.end_turn >= iv.start_turn
                if slot.startswith("identity."):
                    # A plain claim only ever replaces something with STRICTLY
                    # higher authority. (Overrides are explicit and exempt.)
                    for a, b in zip(ivs, ivs[1:]):
                        if b.kind == "fact_established":
                            assert AUTHORITY[b.authority] > AUTHORITY[a.authority], \
                                (seed, e, slot, a.authority, b.authority)
    print("14. one open interval per slot, no overlaps, and identity changes "
          "only by higher authority, on 25 random ledgers")


def test_projection_is_deterministic():
    s = build(8)
    a, b = project(s.ledger.records), project(list(s.ledger.records))
    assert a.digest() == b.digest() == s.canon.digest()
    assert Store(s.dir).canon.digest() == a.digest()
    other = build(9)
    assert other.canon.digest() != a.digest()
    print("15. the same ledger always projects to the same canon; different "
          "ledgers do not")


try:
    for fn in (test_append_and_reopen, test_tampering_is_detected,
               test_torn_write_is_recovered_once,
               test_bounds_reject_and_leave_the_ledger_alone,
               test_the_layer_rule, test_identity_is_first_write_wins,
               test_an_author_can_retract_an_identity_fact,
               test_state_is_latest_wins_with_history,
               test_conflicts_are_recorded_not_raised, test_story_time_queries,
               test_alias_resolution, test_replay_equals_state,
               test_undo_equals_truncation, test_snapshot_is_only_a_cache,
               test_projection_invariants, test_projection_is_deterministic):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON LEDGER TESTS PASSED")
