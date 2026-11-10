"""The Scribe evaluation corpus and scorer have to be right before any model is
measured with them.

A corpus with a wrong label or a quote that is not in its own text produces a
confident wrong score, and nobody can tell from the number. So a perfect
"oracle" Scribe, built from the labels themselves, must score perfectly, and
that is only possible when every quote is really in its passage, every value
pattern matches its own quote, and every pair behaves as its kind says.

 1) the corpus is well formed: unique ids, known entities, quotes in the text,
    patterns that match their own quote, both splits present in every group
 2) the oracle scores 100% recall and precision, raw and validated, per case
 3) the scorer counts what it should: a miss, an extra, a duplicate, a wrong op,
    a wrong value, an off-roster name (not a false positive), a pronoun (one)
 4) trap passages have no labels, so any claim on one is a false positive
 5) on the oracle the sequences behave as designed: every restatement
    corroborates, every changed identity is caught, every novel fact is accepted
 6) a Scribe that never speaks scores zero recall and a Scribe that contradicts
    everything is caught being wrong, so the metrics can actually fail
"""
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-corpus-"))

from canon.claims import Claim                                          # noqa: E402
from canon.scribe import Scribe                                         # noqa: E402
from canon.validate import evidence_ok, norm, validate                  # noqa: E402
from soak.scribe_cases import CASES, PAIRS, ROSTER, T                      # noqa: E402
from soak.scribe_eval import (add, fresh_store, oracle_claims, prf,     # noqa: E402
                              run_extraction, run_sequences, score)

_n = [0]


def _root():
    _n[0] += 1
    return WORK / f"r{_n[0]}"


def test_corpus_is_well_formed():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    roster = {e for e, _d, _a in ROSTER}
    groups = Counter()
    for c in CASES:
        groups[(c.group, c.split)] += 1
        assert c.split in ("dev", "test"), c.id
        for t in c.truth:
            assert t.entity in roster, (c.id, t.entity)
            assert norm(t.evidence) in norm(c.text), (c.id, "quote not in text", t.evidence)
            if t.op != "clear":
                assert re.search(t.value, t.evidence, re.I), \
                    (c.id, "pattern does not match its own quote", t.value)
    for g in {c.group for c in CASES}:
        assert groups[(g, "dev")] and groups[(g, "test")], f"{g} missing a split"
    assert {c.group for c in CASES} == {"identity", "state", "multi", "trap"}
    pids = [p.id for p in PAIRS]
    assert len(pids) == len(set(pids))
    assert Counter(p.kind for p in PAIRS) == {"restate": 6, "contradict": 3, "novel": 3}
    for p in PAIRS:
        assert p.entity in roster
        if p.kind == "novel":
            assert p.setup_slot and p.setup_slot != p.slot, (p.id, "novel needs its own setup slot")
    print(f"1. {len(CASES)} passages and {len(PAIRS)} pairs: ids unique, quotes in "
          "their text, patterns match their quotes, every group in both splits")


# Two labelled claims are quoted without the word that names their slot ("the colour of
# straw" says nothing of hair, "small for his age" says nothing of whose build). The
# validator refuses a quote like that on purpose (canon/shape.py, D-022): a value is
# attached to its noun, because the first value written to a slot is permanent and
# nearly every wrong one the real-save gate saw was a word attached to something else
# ("violet eyes" filed as hair). The cost is these elliptical sentences, and it is
# listed here so that a looser or stricter rule shows up as a change in this set.
#
# The third is not elliptical, it is the oracle's own doing (D-026). It builds each value
# from the first word the label's pattern matches, and id-6's pattern ("raven|tattoo")
# matches "raven" in "a black raven tattooed on his forearm". "raven" alone names no mark,
# exactly like a bare colour word held as a mark by the real-save gate, so the marks rule
# refuses it. The label stays as it is (a Scribe that answers "raven tattoo" or "tattoo"
# still scores a hit, and changing the pattern would break comparison with every Scribe run
# measured so far); the loss is listed instead.
SHAPE_LOSSES = {("id-4", "identity.build"), ("mu-2", "identity.hair"),
                ("id-6", "identity.marks")}
SHAPE_REASONS = ("slot_not_in_evidence", "value_not_on_slot", "not_a_mark")


def test_oracle_scores_perfectly():
    raw = {"tp": 0, "fp": 0, "fn": 0, "off_roster": 0}
    val = dict(raw)
    seen_losses = set()
    for c in CASES:
        store = fresh_store(_root(), c.id)
        claims = oracle_claims(c)
        s = score(c.truth, claims, store.canon)
        assert (s["fp"], s["fn"], s["tp"]) == (0, 0, len(c.truth)), (c.id, s)
        ds = validate(store.canon, claims, c.text, turn=1,
                      next_id=len(store.ledger) + 1, create_unknown=False)
        # A removal of something never tracked is a valid claim with nothing to do,
        # so it is a no-op, not a rejection. Anything else must commit, except the
        # listed shape losses.
        lost = {(c.id, d.claim.slot) for d in ds
                if d.status == "reject" and d.reason in SHAPE_REASONS}
        seen_losses |= lost
        bad = [(d.claim.slot, d.status, d.reason) for d in ds
               if d.status not in ("commit", "noop") and (c.id, d.claim.slot) not in lost]
        assert not bad, (c.id, "the validator rejected a perfect claim", bad)
        assert lost <= SHAPE_LOSSES, (c.id, "a new shape loss", lost - SHAPE_LOSSES)
        passed = [d.claim for d in ds if d.status in ("commit", "noop")]
        raw, val = add(raw, s), add(val, score(c.truth, passed, store.canon))
    assert seen_losses == SHAPE_LOSSES, ("a listed loss is no longer one", SHAPE_LOSSES - seen_losses)
    assert prf(raw)["recall"] == 1.0 and prf(raw)["precision"] == 1.0, prf(raw)
    assert val["tp"] == raw["tp"] - len(SHAPE_LOSSES) and val["fp"] == 0, (val, raw)
    print(f"2. the oracle scores 1.00 / 1.00 over {raw['tp']} labelled claims raw; the validator "
          f"accepts {val['tp']} and refuses exactly the {len(SHAPE_LOSSES)} listed claims")


def test_scorer_counts_what_it_should():
    store = fresh_store(_root(), "sc")
    truth = (next(c for c in CASES if c.id == "id-1").truth)
    hair = Claim("Odile Marsh", "identity.hair", "set", "raven", "raven hair", "high")
    eyes = Claim("Odile Marsh", "identity.eyes", "set", "grey", "grey eyes", "high")
    assert score(truth, [hair, eyes], store.canon) == \
        {"tp": 2, "fp": 0, "fn": 0, "off_roster": 0}
    assert score(truth, [hair], store.canon)["fn"] == 1, "a miss"
    s = score(truth, [hair, eyes, Claim("Odile Marsh", "identity.build", "set", "tall",
                                        "tall", "high")], store.canon)
    assert (s["tp"], s["fp"]) == (2, 1), s
    s = score(truth, [hair, hair, eyes], store.canon)
    assert (s["tp"], s["fp"]) == (2, 1), "a duplicate claim matched twice"
    s = score(truth, [Claim("Odile Marsh", "identity.hair", "add", "raven", "x", "high"),
                      eyes], store.canon)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 1, 1), "a wrong op"
    s = score(truth, [Claim("Odile Marsh", "identity.hair", "set", "blonde", "x", "high"),
                      eyes], store.canon)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 1, 1), "a wrong value"
    s = score(truth, [hair, eyes, Claim("The Innkeeper", "identity.hair", "set", "red",
                                        "x", "high")], store.canon)
    assert (s["fp"], s["off_roster"]) == (0, 1), "an off-roster name is not a false positive"
    s = score(truth, [hair, eyes, Claim("She", "identity.hair", "set", "red", "x", "high")],
              store.canon)
    assert s["fp"] == 1, "a pronoun entity is a false positive"
    # A "clear" label: the outfit is empty, whatever the Scribe words it as. Built here
    # because no passage in the corpus needs one.
    clear = (T("ansel", "state.location", "set", r"river", "dove into the cold river"),
             T("ansel", "state.outfit", "clear", r".*", "stripped to the skin"))
    s = score(clear, [Claim("Ansel", "state.location", "set", "river", "x", "high"),
                      Claim("Ansel", "state.outfit", "clear", "", "x", "high")],
              store.canon)
    assert s["tp"] == 2, "a clear claim should match whatever its value"
    assert prf({"tp": 0, "fp": 0, "fn": 3, "off_roster": 0})["recall"] == 0.0
    assert prf({"tp": 0, "fp": 0, "fn": 0, "off_roster": 0})["precision"] is None
    print("3. the scorer counts a miss, an extra, a duplicate, a wrong op, a wrong "
          "value, an off-roster name and a pronoun correctly")


def test_traps_have_no_labels():
    traps = [c for c in CASES if c.group == "trap"]
    assert len(traps) == 8 and all(not c.truth for c in traps)
    store = fresh_store(_root(), "trap")
    s = score((), [Claim("Odile Marsh", "identity.hair", "set", "gold", "x", "high")],
              store.canon)
    assert (s["tp"], s["fp"], s["fn"]) == (0, 1, 0)
    print("4. the eight trap passages carry no labels, so any claim on one counts "
          "against the model")


class Oracle:
    """A model that answers every passage with exactly the right claims."""

    def __init__(self, by_text):
        self.by_text = by_text

    def complete(self, system, user, schema_=None):
        m = re.search(r'"""\n(.*)\n"""', user, re.S)
        text = m.group(1).strip() if m else ""
        return json.dumps({"claims": [
            dict(entity=e, slot=s, op=o, value=v, evidence=ev, confidence="high")
            for (e, s, o, v, ev) in self.by_text.get(text, [])]})


ORACLE_PAIRS = {
    "re-1": (("odile", "identity.hair", "set", "raven", "raven hair"),
             ("odile", "identity.hair", "set", "black", "black hair")),
    "re-2": (("corin", "identity.eyes", "set", "green", "green eyes"),
             ("corin", "identity.eyes", "set", "emerald", "emerald eyes")),
    "re-3": (("tamsin", "identity.hair", "set", "ginger", "ginger hair"),
             ("tamsin", "identity.hair", "set", "red", "red hair")),
    "re-4": (("ansel", "identity.eyes", "set", "grey", "grey eyes"),
             ("ansel", "identity.eyes", "set", "gray", "gray eyes")),
    "re-5": (("odile", "identity.hair", "set", "blonde", "long blonde hair"),
             ("odile", "identity.hair", "set", "golden", "golden hair")),
    "re-6": (("corin", "identity.hair", "set", "brown", "brown hair"),
             ("corin", "identity.hair", "set", "chestnut", "chestnut hair")),
    "co-1": (("corin", "identity.eyes", "set", "grey", "grey eyes"),
             ("corin", "identity.eyes", "set", "brown", "brown eyes")),
    "co-2": (("odile", "identity.hair", "set", "raven", "raven hair"),
             ("odile", "identity.hair", "set", "blonde", "blonde hair")),
    "co-3": (("tamsin", "identity.hair", "set", "ginger", "ginger hair"),
             ("tamsin", "identity.hair", "set", "silver", "silver hair")),
    "no-1": (("tamsin", "identity.hair", "set", "red", "red hair"),
             ("tamsin", "identity.eyes", "set", "pale blue", "eyes were a pale blue")),
    "no-2": (("ansel", "identity.age", "set", "sixteen", "barely sixteen"),
             ("ansel", "identity.hair", "set", "ginger", "mop of ginger hair")),
    "no-3": (("corin", "identity.eyes", "set", "grey", "grey eyes"),
             ("corin", "identity.marks", "add", "thin scar", "A thin scar ran across")),
}


def test_sequences_behave_as_designed_on_the_oracle():
    by_text = {}
    for p in PAIRS:
        a, b = ORACLE_PAIRS[p.id]
        by_text[p.setup] = [a]
        by_text[p.probe] = [b]
        for claim, text in ((a, p.setup), (b, p.probe)):
            assert norm(claim[4]) in norm(text), (p.id, "quote not in passage", claim[4])
    r = run_sequences(Scribe(Oracle(by_text)), PAIRS, _root(), log=lambda *_: None)
    assert r["by_kind"] == {"restate": {"ok": 6}, "contradict": {"caught": 3},
                            "novel": {"accepted": 3}}, r["by_kind"]
    print("5. on the oracle: 6 of 6 restatements corroborate, 3 of 3 changed "
          "identities are caught, 3 of 3 novel facts are accepted")


def test_the_metrics_can_fail():
    silent = Scribe(Oracle({}))
    r = run_extraction(silent, CASES, _root(), log=lambda *_: None)
    assert r["raw"]["all"]["recall"] == 0.0 and r["raw"]["all"]["precision"] is None
    assert r["raw"]["trap"]["fp"] == 0
    s = run_sequences(silent, PAIRS, _root(), log=lambda *_: None)
    assert all(set(v) == {"setup_failed"} for v in s["by_kind"].values()), s["by_kind"]

    # A model that contradicts itself: it reads the first hair colour as the setup
    # and always claims a DIFFERENT one on the probe, even for restatements.
    by_text = {}
    for p in PAIRS:
        a, b = ORACLE_PAIRS[p.id]
        by_text[p.setup] = [a]
        by_text[p.probe] = [(b[0], b[1], b[2], "violet" if b[1] != "identity.marks" else b[3],
                             b[4])] if p.kind == "restate" else [b]
    # (violet is not in its evidence, so the validator rejects it: the evidence
    # check is what stops a model inventing a value, and it must show up here)
    r = run_sequences(Scribe(Oracle(by_text)), PAIRS, _root(), log=lambda *_: None)
    assert r["by_kind"]["restate"].get("ok", 0) == 0, r["by_kind"]
    assert r["by_kind"]["restate"].get("missed", 0) == 6, r["by_kind"]
    print("6. a silent Scribe scores zero recall, and one that invents a value is "
          "stopped by the evidence check and shows up as missed, not as success")


def test_a_run_stops_when_the_model_cannot_be_asked_again():
    """A free tier's daily cap ends the run. Finishing the corpus anyway would
    record every remaining passage as a transport error, which reads as the model
    failing them. The run must stop, and say how far it got."""
    from canon.scribe import ScribeError
    from soak.scribe_eval import RunAborted, make_llm

    class Capped:
        """Answers `limit` requests, then reports the cap like OpenAIChat does."""
        exhausted = ""

        def __init__(self, limit):
            self.limit, self.calls = limit, 0

        def complete(self, system, user, schema_=None):
            if self.exhausted:
                raise ScribeError(self.exhausted)
            self.calls += 1
            if self.calls > self.limit:
                self.exhausted = "daily request limit reached"
                raise ScribeError(self.exhausted)
            return json.dumps({"claims": []})

    llm = Capped(limit=4)
    try:
        run_extraction(Scribe(llm), CASES, _root(), log=lambda *_: None)
        raise AssertionError("the run carried on past the daily cap")
    except RunAborted as exc:
        assert "daily request limit" in str(exc) and "after 4 of" in str(exc), exc
    assert llm.calls == 5, "requests kept being sent after the cap"
    llm = Capped(limit=7)
    try:
        run_sequences(Scribe(llm), PAIRS, _root(), log=lambda *_: None)
        raise AssertionError("the sequences carried on past the daily cap")
    except RunAborted:
        pass
    # An ordinary model that fails now and then is NOT aborted: only exhaustion is.
    run_extraction(Scribe(Capped(limit=10 ** 6)), CASES[:3], _root(), log=lambda *_: None)

    # The OpenRouter provider fills in its own URL and key variable, and paces only
    # the free models.
    free = make_llm("openrouter", "google/gemma-4-31b-it:free")
    assert free.base_url == "https://openrouter.ai/api/v1"
    assert free.key_env == "OPENROUTER_API_KEY" and free.min_interval == 3.2
    assert free.attempts == 8, "a free pool that is busy needs more patience"
    try:
        make_llm("openrouter", "deepseek/deepseek-v4-flash")
        raise AssertionError("a paid OpenRouter model was accepted without allow_paid")
    except ValueError as exc:
        assert "not a ':free' model" in str(exc)
    paid = make_llm("openrouter", "deepseek/deepseek-v4-flash", allow_paid=True)
    assert paid.min_interval == 0.0 and paid.key_env == "OPENROUTER_API_KEY"
    assert make_llm("openrouter", "m:free", min_interval=0.5).min_interval == 0.5
    oa = make_llm("openai", "gpt-5-nano")
    assert oa.base_url == "https://api.openai.com/v1" and oa.key_env == "OPENAI_API_KEY"
    assert make_llm("openai", "m", key_env="MY_KEY").key_env == "MY_KEY"
    print("7. a run stops at a daily cap instead of recording errors as answers, and "
          "the openrouter provider sets its URL, key variable and free-tier pacing")


try:
    for fn in (test_corpus_is_well_formed, test_oracle_scores_perfectly,
               test_scorer_counts_what_it_should, test_traps_have_no_labels,
               test_sequences_behave_as_designed_on_the_oracle,
               test_the_metrics_can_fail,
               test_a_run_stops_when_the_model_cannot_be_asked_again):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nSOAK SCRIBE CORPUS TESTS PASSED")
