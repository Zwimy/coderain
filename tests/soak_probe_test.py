"""Phase 0 soak harness: the probes have to be able to see, and not touch live data.

Why this exists. A long real playthrough showed three failures nobody had
measured: a scar narrated once and recorded nowhere, hair narrated ebony and then
recorded flaxen for hundreds of turns, and a transient state frozen into a
permanent description. Phase 0 of the consistency design is a harness that
measures this on any save. A harness that cannot tell a kept fact from a lost one
is worse than none, and one that writes to a real save is dangerous, so this
suite pins both. Every name below is invented.

 1) classify separates HELD / LOST / DRIFTED / CONFLICT
 2) evaluate reads the entry, finds the source turn and its age
 3) a fact that exists only in a scene summary is LOST on the sheet, and the
    report says where it survives
 4) a fact about a missing entry is NO_ENTITY, not LOST
 5) copy_save leaves the source byte-identical and drops snapshots and indexes
 6) a source that changes mid-copy is rejected and the half copy removed
 7) unsafe destinations and non-saves are refused
 8) the home guard refuses the repo root
 9) the prompt probe sees a named character, misses an unnamed one, and sees a
    pinned one regardless (so it can tell the difference)
10) colour drift: ebony then flaxen is flagged, a consistent character is not,
    and a pronoun-only mention is ignored
11) transient state in a Visual facet is flagged, a standing trait is not
12) year-shaped scene days are counted
13) the arc audit reports early characters missing while late ones are present
14) run_audit works end to end, offline, and writes no vector index
15) another character's scar is not this character's scar (the first real run
    reported it as found elsewhere and on the prompt)
16) fixture patterns are not so loose they match an unrelated word (a bare
    `ink` reported Corin's missing tattoos as held)
16b) pronoun colours go to the focus character, and a two-name paragraph clears
    the focus (a possessive-only miner found 0 conflicts and missed Sela)
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-soak-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.memory import Entry, Library                      # noqa: E402
from soak import facts as F                                      # noqa: E402
from soak import home as H                                       # noqa: E402
from soak import probes as P                                     # noqa: E402
from soak.audit import run_audit                                 # noqa: E402
from soak.report import to_markdown                              # noqa: E402

lib = Library(WORK / "lib")
_n = [0]


def _story(chars, narration, scenes="", arc=""):
    """A throwaway save: characters, then alternating player/narrator turns."""
    _n[0] += 1
    slug = lib.create_story(f"S{_n[0]}", "A long enough premise for a story.")
    store = lib.store(slug)
    for e in chars:
        store.upsert_entry("characters.md", e)
    for text in narration:
        store.append_turn("player", "I continue.")
        store.append_turn("narrator", text)
    if scenes:
        store.write("memory/scenes.md", scenes)
    if arc:
        store.write("memory/arc.md", arc)
    return store


def _char(slug, title, body, **attrs):
    return Entry(title=title, slug=slug, aliases=[], importance=3,
                 attrs=dict(attrs), body=body)


def test_classify():
    assert F.classify(True, False) == F.HELD
    assert F.classify(False, False) == F.LOST
    assert F.classify(False, True) == F.DRIFTED
    assert F.classify(True, True) == F.CONFLICT
    print("1. classify separates held, lost, drifted and conflict")


def test_evaluate_status_and_age():
    store = _story(
        [_char("sela", "Sela", "Flaxen hair sleek, wearing a green dress.")],
        ["Rain. A corridor.", "Sela's long ebony hair spills over the "
         "cushion.", "Another room.", "More rain."])
    fact = F.Fact(id="sela-hair", entity="sela", truth=(r"\bebony\b",),
                  stale=(r"\bflaxen\b",), source=r"ebony hair",
                  expect=F.DRIFTED)
    turns = store.turns()
    res = F.evaluate(store, fact, turns)
    assert res.status == F.DRIFTED, res.status
    assert res.source_turn == 4, res.source_turn      # p1 n1 p2 N2 -> turn 4
    assert res.age_turns == len(turns) - 4, res.age_turns
    held = F.evaluate(store, F.Fact(id="x", entity="sela",
                                    truth=(r"green dress",)), turns)
    assert held.status == F.HELD, held.status
    print(f"2. DRIFTED found at turn {res.source_turn}, age {res.age_turns}; "
          "a present detail is HELD")


def test_elsewhere_survival():
    scenes = ("## Scene 1  {#scene-1}\nimportance: 3\n\n"
              "Corin, scarred face lit by lamplight, watches the road.\n")
    store = _story([_char("corin", "Corin", "Lean man, green eyes.")],
                   ["Corin's scarred face is lit by lamplight."], scenes=scenes)
    fact = F.Fact(id="corin-scar", entity="corin", truth=(r"\bscar",))
    res = F.evaluate(store, fact, store.turns())
    assert res.status == F.LOST, res.status
    assert "memory/scenes.md" in res.elsewhere, res.elsewhere
    bare = _story([_char("corin", "Corin", "Lean man, green eyes.")],
                  ["Corin's scarred face is lit by lamplight."])
    assert F.evaluate(bare, fact, bare.turns()).elsewhere == []
    print("3. a scar only in a scene summary is LOST on the sheet, "
          "and the summary is named")


def test_no_entity():
    store = _story([], ["Nothing here."])
    res = F.evaluate(store, F.Fact(id="g", entity="ghost", truth=(r"x",)),
                     store.turns())
    assert res.status == F.NO_ENTITY, res.status
    print("4. a missing entry is NO_ENTITY, not LOST")


def _make_source():
    """A save in its own library, with the things a copy must leave behind."""
    src_lib = Library(WORK / "source-lib")
    _n[0] += 1
    slug = src_lib.create_story(f"Src{_n[0]}", "A long enough premise here.")
    store = src_lib.store(slug)
    store.append_turn("player", "hi")
    store.append_turn("narrator", "Hello.")
    snap = store.dir / ".snapshots" / "20260101-000000"
    snap.mkdir(parents=True)
    (snap / "transcript.md").write_text("old", encoding="utf-8")
    (store.dir / "index.db").write_bytes(b"sqlite")
    return store.dir


def test_copy_never_touches_source():
    src = _make_source()
    before = H.fingerprint(src)
    iso = Path(tempfile.mkdtemp(prefix="cr-iso-"))
    slug = H.copy_save(src, iso)
    dst = iso / "saves" / slug
    assert H.fingerprint(src) == before, "the source changed"
    assert (dst / "transcript.md").exists()
    assert not (dst / ".snapshots").exists(), "snapshots were copied"
    assert not (dst / "index.db").exists(), "the vector index was copied"
    assert not (src / ".env").exists() and not (dst / ".env").exists()
    print("5. source byte-identical; snapshots and index left behind")


def test_copy_rejects_a_changing_source():
    src = _make_source()
    iso = Path(tempfile.mkdtemp(prefix="cr-iso-"))

    def writer():
        with open(src / "transcript.md", "a", encoding="utf-8") as fh:
            fh.write("\n<!-- @narrator -->\nWritten while copying.\n")
    try:
        H.copy_save(src, iso, _between=writer)
        raise AssertionError("a source that changed mid-copy was accepted")
    except H.SourceChanged:
        pass
    assert not (iso / "saves" / src.name).exists(), "half copy left behind"
    print("6. a source that changes mid-copy is rejected and the copy removed")


def test_copy_refuses_unsafe_targets():
    src = _make_source()
    for bad_home in (H.REPO_ROOT, src, src / "nested"):
        try:
            H.copy_save(src, bad_home)
            raise AssertionError(f"copied into {bad_home}")
        except H.UnsafeHome:
            pass
    try:
        H.copy_save(WORK, Path(tempfile.mkdtemp(prefix="cr-iso-")))
        raise AssertionError("a non-save was accepted")
    except ValueError:
        pass
    print("7. repo root, the source itself and a non-save are all refused")


def test_home_guard():
    assert H.assert_isolated() == WORK.resolve()
    try:
        H.assert_isolated(H.REPO_ROOT)
        raise AssertionError("the repo root passed the guard")
    except H.UnsafeHome:
        pass
    print("8. the guard accepts the temp home and refuses the repo root")


def test_prompt_probe_sees_the_difference():
    named = _story([_char("odile", "Odile", "Tall, with an emerald scarf.")],
                   ["Rain on the harbour.", "A gull circles.", "Night falls."])
    pats, names = (r"emerald scarf",), ["Odile"]
    probe = P.PromptProbe(named)
    assert probe.presence(pats, names, "odile", "I turn to Odile.")["system"]
    assert not probe.presence(pats, names, "odile", "I wait.")["system"], \
        "an unnamed character reached the prompt"
    pinned = _story([_char("odile", "Odile", "Tall, with an emerald scarf.",
                           pinned="true")], ["Rain on the harbour."])
    assert P.PromptProbe(pinned).presence(
        pats, names, "odile", "I wait.")["system"] is True
    print("9. named: seen. unnamed: missed. pinned: seen. The probe discriminates")


def test_attribute_drift():
    sheet = [_char("sela", "Sela", "Flaxen hair sleek, hazel eyes."),
             _char("corin", "Corin", "Lean man, green eyes.")]
    narration = [
        "Sela's long ebony hair spills over the cushion.",
        "Corin's green eyes narrow at the door.",
        "Her green eyes narrowed. His hair was grey.",      # pronouns: ignored
        "Sela's flaxen hair gleams under the lamps.",
        "Corin's green eyes stay on the door.",
    ]
    store = _story(sheet, narration)
    d = P.attribute_drift(store)
    flagged = {(c["entity"], c["noun"]) for c in d["conflicts"]}
    assert flagged == {("sela", "hair")}, flagged
    c = d["conflicts"][0]
    assert c["sheet"] == "sheet_matches_last", c["sheet"]
    assert c["first"]["families"] == ["black"], c["first"]
    assert c["conflicting"]["families"] == ["blond"], c["conflicting"]
    assert d["pairs"] == 2, d["pairs"]       # sela hair, corin eyes; no pronoun
    print("10. ebony->flaxen flagged; consistent eyes and pronouns are not")


def test_another_characters_detail_is_not_this_ones():
    """The first real run reported Corin's scar as found elsewhere in memory and
    on the prompt, because `\\bscar` matched OTHER characters' scars. A detail
    has to be attached to the right entity."""
    store = _story(
        [_char("corin", "Corin", "Lean man, green eyes."),
         _char("rook", "Rook", "Stocky. A burn scar down one forearm.")],
        ["Rook leans on the wall.", "Corin's scarred face catches the light."])
    fact = F.Fact(id="corin-scar", entity="corin", truth=(r"\bscar",))
    res = F.evaluate(store, fact, store.turns())
    assert res.status == F.LOST, res.status
    assert res.elsewhere == [], f"Rook's scar counted: {res.elsewhere}"
    probe = P.PromptProbe(store)
    ask = "I turn to Corin."
    # The control: Rook's scar really is in this prompt, so the miss for Corin
    # is the scoping working, not an empty prompt.
    assert probe.presence((r"burn scar",), ["Rook"], "rook", ask)["system"], \
        "the control failed: Rook was not in the prompt"
    assert not probe.presence(fact.truth, F.names_of(
        store.entries("characters.md")[0]), "corin", ask)["system"]
    print("15. Rook's scar is not Corin's scar, in memory or on the prompt")


def test_fixture_validation_refuses_loose_patterns():
    """The first real run reported a missing tattoo as HELD: a bare `anchor` pattern
    matched "Silver Anchor" on the sheet, a different concept. A fixture is the
    harness's ground truth, so a loose one is refused before any audit runs."""
    decoy = ("Holds the Silver Anchor secret.",)
    loose = F.Fact(id="t", entity="corin", truth=(r"\banchor\b",), decoys=decoy,
                   expect=F.LOST)
    tight = F.Fact(id="t", entity="corin", truth=(r"tattoo",), decoys=decoy,
                   expect=F.LOST)
    try:
        F.validate_fixture([loose])
        raise AssertionError("a pattern that matches its decoy was accepted")
    except ValueError as exc:
        assert "decoy" in str(exc), exc
    F.validate_fixture([tight])
    for bad in (F.Fact(id="a", entity="x", truth=(r"y",)),            # no expect
                F.Fact(id="a", entity="x", truth=(), expect=F.LOST)):  # no truth
        try:
            F.validate_fixture([bad])
            raise AssertionError(f"accepted a bad fixture: {bad}")
        except ValueError:
            pass
    try:
        F.validate_fixture([tight, tight])
        raise AssertionError("a duplicate id was accepted")
    except ValueError:
        pass
    from soak.fixtures.example import FACTS
    F.validate_fixture(FACTS)           # the shipped example must itself be valid
    # ...and run_audit enforces it, so a loose fixture cannot reach a report.
    store = _story([_char("corin", "Corin", "Lean man.")], ["x"])
    try:
        run_audit(store, [loose])
        raise AssertionError("run_audit ran a loose fixture")
    except ValueError:
        pass
    print("16. a pattern matching its decoy, a missing expectation or a duplicate "
          "id is refused, in the tests and in run_audit")


def test_pronoun_attribution_follows_focus():
    """Real play writes 'Her long ebony hair', not "Sela's". A name-possessive
    miner found 0 conflicts on a real save and missed the clearest case."""
    # Real sheets use pronouns, and the miner needs them: a pronoun is only
    # attributed to a character whose gender the sheet makes clear.
    sheet = [_char("sela", "Sela", "Flaxen hair sleek. She keeps her guard "
                   "up and her stance wide."),
             _char("corin", "Corin", "Lean man, green eyes. He keeps his "
                   "counsel and his distance.")]
    # The two-name line FOLLOWS a single-name line in the same turn, so the
    # focus is Sela going in. Only an engine that clears the focus on an
    # ambiguous paragraph skips "Her green eyes". (A first draft put the two-name
    # line first, the focus was empty anyway, and removing the reset passed.)
    ambiguous = ("Sela steps in.\nSela and Corin stand together.\n"
                 "Her green eyes narrow.")
    narration = [
        "Sela steps through the steam.\nHer long ebony hair sways.",
        ambiguous,
        ambiguous,
        "Sela leans close.\nHer flaxen hair falls across her cheek.",
    ]
    d = P.attribute_drift(_story(sheet, narration))
    assert [(c["entity"], c["noun"]) for c in d["conflicts"]] == \
        [("sela", "hair")], d["conflicts"]
    c = d["conflicts"][0]
    assert c["first"]["how"] == "focus" and c["conflicting"]["how"] == "focus", c
    assert d["pairs"] == 1, d["pairs"]       # the ambiguous eyes line is skipped
    print("16b. pronoun colour attributed to the focus character; "
          "an ambiguous two-name paragraph is skipped")


def test_pronoun_gender_and_noun_phrase_guards():
    """Two false positives found by reading the first real conflict list: the
    male protagonist was credited with "Her hazel eyes" because he was the last
    name in the turn, and "golden rings in her eyes" was read as an eye colour."""
    sheet = [_char("ansel", "Ansel", "Lean man. He keeps his guard up and his coat "
                   "buttoned."),
             _char("tamsin", "Tamsin", "She is lean. Her hands are scarred."),
             # No pronouns on the sheet, so no known gender: "her" is not guessed.
             _char("nameless", "Nameless", "A courier of no fixed address.")]
    narration = [
        "Nameless nods.\nHer hazel eyes gleam.",
        "Nameless nods.\nHer grey eyes hold yours.",
        "Ansel walks in.\nHer hazel eyes gleam.",
        # grey, not "pale": "pale" is a family NAME, not a word in it, so a first
        # draft produced no assertion and the gender guard could be removed
        # without this test noticing.
        "Ansel waits.\nHer grey eyes hold yours.",
        "Tamsin pauses.\nThe golden rings in her eyes freeze mid-spin.",
        "Tamsin waits.\nHer amber eyes find yours.",
    ]
    d = P.attribute_drift(_story(sheet, narration))
    assert d["conflicts"] == [], d["conflicts"]
    assert d["pairs"] == 0, d["pairs"]
    print("16c. 'her' is not credited to a male character; "
          "'golden rings in her eyes' is not a colour")


def test_transient_in_identity():
    store = _story([
        _char("veda", "Veda", "Short baker. Visual: tattered apron, sleeves gone. "
              "Mentality: cold."),
        _char("perrin", "Perrin", "**Visual:** grey hair in a bun. **Mentality:** calm."),
    ], ["x"])
    t = P.transient_in_identity(store)
    assert [f["entity"] for f in t["flagged"]] == ["veda"], t
    assert t["flagged"][0]["marker"] in ("gone", "tattered"), t
    print("11. a scene-specific Visual is flagged; a standing one is not")


def test_clock_audit():
    scenes = "".join(
        f"## Scene {i}  {{#scene-{i}}}\nimportance: 3\nday: {d}\n\nText.\n\n"
        for i, d in enumerate([1, 3, 1987, 1987, 5, 1987], start=1))
    store = _story([], ["x"], scenes=scenes)
    c = P.clock_audit(store)
    assert c["year_shaped"] == 3 and c["distinct_year_shaped"] == [1987], c
    print("12. three year-shaped day stamps counted")


def test_arc_coverage():
    chars = [_char("oldie", "Oldie", "Early cast."),
             _char("midge", "Midge", "Middle cast."),
             _char("newbie", "Newbie", "Late cast.")]
    narration = ["Oldie arrives.", "Filler.", "Midge arrives.", "Filler.",
                 "Newbie arrives."]
    store = _story(chars, narration, arc="Newbie now leads the story.")
    a = P.arc_coverage(store)
    by = {r["cohort"]: r for r in a["by_cohort"]}
    assert by["earliest third"]["in_arc"] == 0, a
    assert by["latest third"]["in_arc"] == 1, a
    print("13. the arc names the latest character and none of the earliest")


def test_run_audit_end_to_end():
    store = _story(
        [_char("sela", "Sela", "Flaxen hair sleek.")],
        ["Sela's ebony hair spills.", "More story.", "Even more."])
    fixture = [F.Fact(id="sela-hair", entity="sela", truth=(r"\bebony\b",),
                      stale=(r"\bflaxen\b",), source=r"ebony hair",
                      expect=F.DRIFTED)]
    rep = run_audit(store, fixture)
    assert rep["facts"][0]["status"] == F.DRIFTED, rep["facts"]
    assert rep["fact_summary"]["diverged_from_expectation"] == []
    assert rep["facts"][0]["prompt"]["stale_named_system"] is True, \
        "the stale value should be in the prompt when she is named"
    assert not (store.dir / "index.db").exists(), "an index was built"
    md = to_markdown(rep)
    assert "| sela-hair | DRIFTED | DRIFTED |" in md, md
    bad = F.Fact(id="b", entity="sela", truth=(r"\bebony\b",),
                 stale=(r"\bflaxen\b",), expect=F.HELD)
    assert run_audit(store, [bad])["fact_summary"]["diverged_from_expectation"] \
        == ["b"]
    print("14. end to end: offline, no index, and a wrong expectation is reported")


try:
    for fn in (test_classify, test_evaluate_status_and_age,
               test_elsewhere_survival, test_no_entity,
               test_copy_never_touches_source,
               test_copy_rejects_a_changing_source,
               test_copy_refuses_unsafe_targets, test_home_guard,
               test_prompt_probe_sees_the_difference, test_attribute_drift,
               test_another_characters_detail_is_not_this_ones,
               test_fixture_validation_refuses_loose_patterns,
               test_pronoun_attribution_follows_focus,
               test_pronoun_gender_and_noun_phrase_guards,
               test_transient_in_identity, test_clock_audit,
               test_arc_coverage, test_run_audit_end_to_end):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nSOAK PROBE TESTS PASSED")
