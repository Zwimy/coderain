"""Phase 2: the Scribe proposes, code decides.

The Scribe is a model, so it will sometimes be wrong, refuse, truncate, or invent
a quote. The design says nothing it proposes reaches the ledger on its word. This
suite uses a stub in place of the model, so it is deterministic and needs no
server, and pins the rules that make that true.

 1) the parser tells a refusal, an empty reply and truncated JSON apart, and
    rejects malformed claims one by one with the reason
 2) a quoted brace inside evidence does not end the object early
 3) evidence has to be in the prose; a paraphrase passes, an invention does not
 4) the value has to be in its own quote (black is not raven)
 5) identity: a new fact commits, the same value corroborates, a different value
    is a CONTRADICTION that is not committed by default
 6) low confidence waits as pending; a pronoun never becomes an entity
 7) a new capitalised name creates an entity (when allowed), a loose name resolves
    to a unique match and an ambiguous one to nothing
 8) state: add and remove build the list, an untracked removal is a no-op, and
    the second claim in a passage sees the first
 9) marks are one slot per mark, so a second scar is novelty, not a contradiction
10) process_turn commits through the ledger, never raises, and reports a failure
11) the Ollama client pins num_ctx, uses temperature 0, drops a field the server
    rejects exactly once, and reports an unreachable server as an error
12) a long passage is read in pieces and the worst status is kept
13) a decision's records are exactly what lands in the ledger
14) a hosted client keeps its key in the environment, drops unsupported
    fields once, never retries a spent quota, and stops at a token budget
15) free-tier runs: paced, a daily cap is final, a per-minute cap retries,
    an error inside a 200 or a truncated reply is never a quiet empty answer
16) a claim must be about someone the passage names; a dream waits as pending
"""
import io
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-scribe-"))

from canon import Store                                                  # noqa: E402
from canon.claims import MAX_CLAIMS, Claim, first_json, parse, schema    # noqa: E402
from canon.pipeline import process_turn, roster_for                      # noqa: E402
from canon.scribe import (CHUNK_CHARS, OllamaChat, Scribe, ScribeError,   # noqa: E402
                          build_prompt, chunks)
from canon.validate import (commit, evidence_ok, looks_like_name,         # noqa: E402
                            resolve_loose, validate, value_supported)

_n = [0]


def _store(*people):
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for i, (eid, name, aliases) in enumerate(people):
        s.append(kind="entity_created", entity=eid, slot="character", value=name,
                 authority="scenario", turn=0, aliases=list(aliases))
    return s


def _c(entity, slot, op, value, evidence, conf="high"):
    return Claim(entity, slot, op, value, evidence, conf)


def _run(store, claims, prose, **kw):
    kw.setdefault("turn", 1)
    return validate(store.canon, claims, prose, next_id=len(store.ledger) + 1, **kw)


class Stub:
    """Stands in for the model."""

    def __init__(self, reply="", error=None):
        self.reply, self.error, self.calls = reply, error, []

    def complete(self, system, user, schema_=None):
        self.calls.append((system, user, schema_))
        if self.error:
            raise self.error
        return self.reply(user) if callable(self.reply) else self.reply


def _json(*claims):
    return json.dumps({"claims": [dict(entity=c[0], slot=c[1], op=c[2], value=c[3],
                                       evidence=c[4], confidence=c[5] if len(c) > 5
                                       else "high") for c in claims]})


GOOD = dict(entity="Odile", slot="identity.hair", op="set", value="raven",
            evidence="raven hair", confidence="high")


# ---------------------------------------------------------------------------
def test_parser_statuses_and_rejects():
    ok = parse(json.dumps({"claims": [GOOD]}))
    assert ok.status == "ok" and len(ok.claims) == 1 and ok.claims[0].value == "raven"
    fenced = parse("Sure!\n```json\n" + json.dumps({"claims": [GOOD]}) + "\n```\nDone.")
    assert fenced.status == "ok" and len(fenced.claims) == 1
    thought = parse("<think>hmm {not json}</think>" + json.dumps({"claims": [GOOD]}))
    assert thought.status == "ok" and len(thought.claims) == 1
    assert parse("").status == "empty_output" and parse("  \n ").status == "empty_output"
    assert parse("I'm sorry, but I can't help with that request.").status == "refusal"
    assert parse("I cannot assist with this.").status == "refusal"
    assert parse('{"claims": [{"entity": "Odile", "slot": "identity.ha').status == "no_json"
    assert parse("the model rambled with no json at all").status == "no_json"
    assert parse('{"claims": "nope"}').status == "bad_shape"
    assert parse(json.dumps({"claims": []})).status == "ok"
    assert parse(json.dumps([GOOD])).claims[0].entity == "Odile"   # bare list accepted

    why = {}
    for label, patch in {
            "unknown_slot": {"slot": "identity.shoes"},
            "unknown_op": {"op": "delete"},
            "bad_confidence": {"confidence": "certain"},
            "no_evidence": {"evidence": ""},
            "bad_entity": {"entity": ""},
            "bad_value": {"value": 7},
            "empty_value": {"value": ""},
            "op_not_allowed_for_slot": {"slot": "identity.marks", "op": "set"}}.items():
        r = parse(json.dumps({"claims": [{**GOOD, **patch}]}))
        assert r.claims == [] and r.rejects[0]["reason"] == label, (label, r.rejects)
        why[label] = True
    # op rules: identity cannot be cleared, state can, scalars cannot be added
    assert parse(json.dumps({"claims": [{**GOOD, "op": "clear"}]})).claims == []
    assert parse(json.dumps({"claims": [{**GOOD, "slot": "state.mood", "op": "clear",
                                         "value": ""}]})).claims
    assert parse(json.dumps({"claims": [{**GOOD, "slot": "state.mood",
                                         "op": "add"}]})).claims == []
    many = parse(json.dumps({"claims": [GOOD] * (MAX_CLAIMS + 5)}))
    assert len(many.claims) == MAX_CLAIMS
    assert many.rejects[-1]["reason"] == "too_many_claims"
    print(f"1. parser: 4 statuses told apart, {len(why)} malformed shapes rejected "
          "with their reason, the claim cap enforced")


def test_brace_in_evidence():
    ev = 'she said "{wait}" and left'
    r = parse(json.dumps({"claims": [{**GOOD, "evidence": ev}]}) + " trailing {")
    assert r.status == "ok" and r.claims[0].evidence == ev, r
    assert first_json('noise {"a": [1, {"b": "}"}]} more') == {"a": [1, {"b": "}"}]}
    assert first_json('{"a": 1') is None                  # truncated stays None
    print("2. a brace inside a quoted string does not end the object; a truncated "
          "object is not repaired")


def test_evidence_must_be_in_the_prose():
    prose = "Odile stepped in. Her long raven hair was tied back with a green ribbon."
    assert evidence_ok("Her long raven hair was tied back", prose)
    assert evidence_ok("HER LONG RAVEN HAIR, was tied back!", prose)      # case, punctuation
    assert evidence_ok("her long raven hair was tied back with the green ribbon", prose)
    assert not evidence_ok("her golden hair hung loose", prose), "an invented quote"
    assert not evidence_ok("silver", prose) and not evidence_ok("", prose)
    assert evidence_ok("raven", prose), "an exact single word is fine"
    print("3. exact, case-insensitive and lightly paraphrased evidence passes; an "
          "invented quote does not")


def test_value_must_be_in_its_quote():
    assert value_supported("raven", "her raven hair")
    assert not value_supported("black", "her raven hair"), "a normalised synonym"
    assert value_supported("grey wool coat", "she pulled on the grey wool coat")
    assert value_supported("gloves", "tugging off a glove") is True     # stem match
    assert not value_supported("scarf", "her grey wool coat")
    print("4. a value must come from its own quote; black is not raven")


def test_identity_commit_corroborate_contradict():
    s = _store(("odile", "Odile Marsh", ["The Courier"]))
    prose = "Odile Marsh's raven hair was tied back."
    claim = _c("Odile Marsh", "identity.hair", "set", "raven", "raven hair")
    d = _run(s, [claim], prose)[0]
    assert d.status == "commit" and d.records[0]["kind"] == "fact_established", d
    commit(s, [d])
    assert s.canon.current("odile", "identity.hair") == "raven"

    again = _run(s, [claim], prose, turn=2)[0]
    assert again.status == "commit"                                   # corroboration
    commit(s, [again])
    assert s.canon.history("odile", "identity.hair")[0]["confirmations"] == 2

    clash_prose = "Odile's platinum hair fell loose."
    clash = _c("Odile Marsh", "identity.hair", "set", "platinum", "platinum hair")
    d = _run(s, [clash], clash_prose, turn=3)[0]
    assert (d.status, d.reason) == ("contradiction", "identity_locked"), d
    before = len(s.ledger)
    assert commit(s, [d]) == [] and len(s.ledger) == before, "committed a contradiction"
    assert commit(s, [d], record_contradictions=True), "the flag should record it"
    assert s.canon.current("odile", "identity.hair") == "raven"
    assert s.canon.conflicts[-1]["reason"] == "identity_locked"
    print("5. new identity commits, a repeat corroborates, a different value is a "
          "contradiction held back unless asked for")


def test_a_restatement_is_not_a_contradiction():
    """The ledger compares identity values as exact strings, so 'raven' and then
    'black' would be a contradiction. A validator that flags a restatement as an
    error teaches the story to stop describing anyone, so the same fact in other
    words is recorded as a corroboration, using the existing wording. A genuinely
    different value is still a contradiction."""
    from canon.validate import same_value
    same = [("raven", "black"), ("raven", "long jet-black"), ("green", "emerald"),
            ("ginger", "red"), ("grey", "gray"), ("blonde", "golden"),
            ("brown", "chestnut"), ("raven", "raven"), ("cropped grey", "grey"),
            ("amethyst", "violet"), ("silver", "white")]
    differ = [("raven", "blonde"), ("grey", "brown"), ("green", "blue"),
              ("ginger", "silver"), ("red", "black"), ("hazel", "green")]
    assert all(same_value(a, b) and same_value(b, a) for a, b in same), \
        [p for p in same if not same_value(*p)]
    assert not any(same_value(a, b) or same_value(b, a) for a, b in differ), \
        [p for p in differ if same_value(*p)]

    s = _store(("odile", "Odile Marsh", []))
    commit(s, _run(s, [_c("Odile", "identity.hair", "set", "raven", "raven hair")],
                   "Odile's raven hair was braided."))
    d = _run(s, [_c("Odile", "identity.hair", "set", "jet-black", "jet-black hair")],
             "Odile's jet-black hair fell loose.", turn=2)[0]
    assert d.status == "commit" and d.records[0]["value"] == "raven", d
    commit(s, [d])
    assert not s.canon.conflicts
    assert s.canon.history("odile", "identity.hair")[0]["confirmations"] == 2
    d = _run(s, [_c("Odile", "identity.hair", "set", "blonde", "blonde hair")],
             "Odile's blonde hair fell loose.", turn=3)[0]
    assert d.status == "contradiction", d
    print("5b. the same fact in other words corroborates (using the existing "
          "wording); a different colour still contradicts")


def test_pending_and_pronouns():
    s = _store(("odile", "Odile Marsh", []))
    low = _c("Odile", "identity.eyes", "set", "green", "green eyes", "low")
    d = _run(s, [low], "Odile's green eyes narrowed.")[0]
    assert (d.status, d.reason) == ("pending", "low_confidence") and not d.records
    d = _run(s, [low], "Odile's green eyes narrowed.", min_confidence="low")[0]
    assert d.status == "commit"
    for pron in ("she", "She", "her", "The woman", "someone"):
        d = _run(s, [_c(pron, "identity.eyes", "set", "green", "green eyes")],
                 "Odile's green eyes narrowed.")[0]
        assert (d.status, d.reason) == ("reject", "unresolved_entity"), (pron, d)
    # a rejected-for-evidence claim is not pending: a quote that is not in the
    # text is wrong regardless of how sure the model was
    d = _run(s, [_c("Odile", "identity.eyes", "set", "green", "blue eyes", "low")],
             "Odile's green eyes narrowed.")[0]
    assert d.reason == "evidence_not_in_text", d
    print("6. low confidence waits as pending (after the evidence checks); a "
          "pronoun is never an entity")


def test_new_and_loose_entities():
    s = _store(("odile", "Odile Marsh", ["The Courier"]),
               ("corin", "Corin Hale", []), ("corin-2", "Corin Ash", []))
    assert resolve_loose(s.canon, "Odile") == "odile"
    assert resolve_loose(s.canon, "the courier") == "odile"
    assert resolve_loose(s.canon, "Corin") is None, "an ambiguous name was guessed"
    assert resolve_loose(s.canon, "Corin Ash") == "corin-2"
    assert resolve_loose(s.canon, "she") is None
    assert looks_like_name("Tamsin") and looks_like_name("Tamsin Reeve")
    assert not looks_like_name("the woman") and not looks_like_name("tamsin")
    assert not looks_like_name("The Stranger") and not looks_like_name("A B C D")
    # A capitalised pronoun fits the shape of a name ("She" at the start of a sentence), and
    # the later check in validate() that refuses pronouns first hid this guard from every
    # test that went through it. It is the second line of defence, so it is pinned here.
    assert not looks_like_name("She") and not looks_like_name("Her") and not looks_like_name("You")

    prose = "Tamsin wore a red scarf."
    claim = _c("Tamsin", "state.outfit", "add", "red scarf", "wore a red scarf")
    d = _run(s, [claim], prose, create_unknown=False)[0]
    assert (d.status, d.reason) == ("reject", "unknown_entity"), d
    d = _run(s, [claim], prose)[0]
    assert d.status == "commit" and d.records[0]["kind"] == "entity_created", d
    assert d.records[0]["entity"] == "tamsin" and d.records[1]["slot"] == "state.outfit"
    commit(s, [d])
    assert s.canon.entities["tamsin"]["name"] == "Tamsin"
    assert s.canon.current("tamsin", "state.outfit") == ("red scarf",) or \
        s.canon.current("tamsin", "state.outfit") == ["red scarf"]
    print("7. a new capitalised name creates an entity; loose names resolve only "
          "when unique")


def test_state_lists_build_and_see_earlier_claims():
    s = _store(("odile", "Odile Marsh", []))
    prose = ("Odile pulled on her grey coat and her leather boots. Then she tugged "
             "off her gloves. Her coat hung open.")
    claims = [
        _c("Odile", "state.outfit", "add", "grey coat", "pulled on her grey coat"),
        _c("Odile", "state.outfit", "add", "leather boots", "her leather boots"),
        _c("Odile", "state.outfit", "remove", "gloves", "tugged off her gloves"),
        # a repeat of an item already worn (the quote must still support the value;
        # "Her coat hung open" would be rejected, correctly, for lacking "grey").
        # It used to be a no-op. It is now RECORDED, as the list with that item newest,
        # because the ledger has to know the story said it again (D-023): that is the
        # only way a card can tell a coat still being worn from one nobody has mentioned
        # for a thousand turns.
        _c("Odile", "state.outfit", "add", "grey coat", "pulled on her grey coat"),
        _c("Odile", "state.outfit", "remove", "grey coat", "pulled on her grey coat"),
        _c("Odile", "state.location", "set", "the harbour", "her grey coat"),
    ]
    ds = _run(s, claims, prose)
    got = [(d.status, d.reason) for d in ds]
    assert got[0][0] == "commit" and got[1][0] == "commit"
    assert got[2] == ("noop", "not_tracked"), got[2]
    assert got[3] == ("commit", "restated"), got[3]
    assert ds[3].records[0]["value"] == ["leather boots", "grey coat"], ds[3].records
    assert got[4][0] == "commit"                    # it SAW the coat the first claim added
    assert got[5] == ("reject", "value_not_in_evidence"), got[5]
    commit(s, ds)
    assert list(s.canon.current("odile", "state.outfit")) == ["leather boots"]
    assert all(r.id == i + 2 for i, r in enumerate(s.ledger.records[1:]))
    # removing the last item clears the slot instead of storing an empty list
    d = _run(s, [_c("Odile", "state.outfit", "remove", "boots", "off her boots")],
             "Odile kicked off her boots.", turn=2)[0]
    assert d.records[0]["kind"] == "state_cleared", d.records
    commit(s, [d])
    assert s.canon.current("odile", "state.outfit") is None
    print("8. add and remove build the list, an untracked removal is a no-op, a repeat is "
          "recorded as newest, and a later claim sees the earlier one")


def test_marks_are_one_slot_each():
    s = _store(("odile", "Odile Marsh", []))
    prose = "Odile turned. A thin scar ran along her jaw, and a green sigil marked her wrist."
    ds = _run(s, [
        _c("Odile", "identity.marks", "add", "thin scar", "A thin scar ran along her jaw"),
        _c("Odile", "identity.marks", "add", "green sigil", "a green sigil marked her wrist"),
        _c("Odile", "identity.marks", "add", "thin scar", "A thin scar"),
    ], prose)
    assert [d.status for d in ds] == ["commit", "commit", "commit"], ds
    commit(s, ds)
    slots = sorted(k for k in s.canon.slots["odile"] if k.startswith("identity.marks."))
    assert slots == ["identity.marks.green-sigil", "identity.marks.thin-scar"], slots
    assert not s.canon.conflicts, "a second mark was treated as a contradiction"
    assert s.canon.history("odile", "identity.marks.thin-scar")[0]["confirmations"] == 2
    print("9. each mark is its own slot: a second scar is novelty, a repeat "
          "corroborates, neither conflicts")


def test_two_hair_colours_in_one_passage():
    s = _store(("odile", "Odile Marsh", []))
    prose = "Odile's raven hair gleamed. Under the lamp her platinum hair shone."
    ds = _run(s, [_c("Odile", "identity.hair", "set", "raven", "raven hair gleamed"),
                  _c("Odile", "identity.hair", "set", "platinum", "her platinum hair shone")],
              prose)
    assert [d.status for d in ds] == ["commit", "contradiction"], ds
    print("   (a second hair colour in the SAME passage contradicts the first)")


def test_a_claim_needs_a_named_character_and_a_real_context():
    """Two attribution errors a model makes and code can catch.

    Given a passage about 'you' and a list of characters, a small model picks a
    likely character and writes the claim on THEIR sheet (measured: gemma3:4b put
    "your coat soaked through" on Odile Marsh). A wrong attribution is the most
    damaging error because nothing downstream can tell. So the passage has to
    name the entity, by name, first name or alias.

    A dream or an imagining states nothing about the world, so a claim whose own
    sentence is one waits as pending. Only that sentence counts: "She had dreamed
    of this. Her hair was raven." still records the hair.
    """
    s = _store(("odile", "Odile Marsh", ["The Courier"]), ("tamsin", "Tamsin Reeve", []))
    coat = _c("Odile Marsh", "state.outfit", "add", "grey coat", "pulled on a grey coat")

    d = _run(s, [_c("Odile Marsh", "state.outfit", "add", "coat soaked through",
                    "your coat soaked through")],
             "You notice your own hands are cold, your coat soaked through.")[0]
    assert (d.status, d.reason) == ("reject", "entity_not_in_passage"), d
    d = _run(s, [coat], "Tamsin pulled on a grey coat.")[0]
    assert (d.status, d.reason) == ("reject", "entity_not_in_passage"), \
        "another character was named, not this one"
    for named in ("Odile pulled on a grey coat.", "Odile Marsh pulled on a grey coat.",
                  "The Courier pulled on a grey coat.", "Odile's hand pulled on a grey coat."):
        assert _run(s, [coat], named)[0].status == "commit", named
    d = _run(s, [_c("Jarrow", "state.outfit", "add", "grey coat", "pulled on a grey coat")],
             "A tall figure pulled on a grey coat.")[0]
    assert (d.status, d.reason) == ("reject", "entity_not_in_passage"), \
        "a new entity the passage never names was invented"
    d = _run(s, [_c("Jarrow", "state.outfit", "add", "grey coat", "pulled on a grey coat")],
             "Jarrow pulled on a grey coat.")[0]
    assert d.status == "commit" and d.records[0]["kind"] == "entity_created", d

    gold = _c("Odile", "identity.hair", "set", "gold", "Odile's hair was gold")
    d = _run(s, [gold], "In the dream, Odile's hair was gold and she wore a crown.")[0]
    assert (d.status, d.reason) == ("pending", "irrealis_context") and not d.records, d
    d = _run(s, [_c("Odile", "state.outfit", "add", "red cloak", "her cloak was red")],
             "Odile imagined her cloak was red.")[0]
    assert d.status == "pending", d
    d = _run(s, [_c("Odile", "identity.hair", "set", "raven", "Her hair was raven")],
             "Odile had dreamed of this for years. Her hair was raven.")[0]
    assert d.status == "commit", "a dream in ANOTHER sentence stopped a real fact"
    d = _run(s, [_c("Odile", "identity.eyes", "set", "green", "dreamy eyes were green")],
             "Odile's dreamy eyes were green.")[0]
    assert d.status == "commit", "'dreamy' was read as 'dream'"
    print("16. a claim must be about someone the passage names, and a dream or an "
          "imagining waits as pending (in its own sentence only)")


def test_process_turn_and_failures():
    s = _store(("odile", "Odile Marsh", ["The Courier"]), ("corin", "Corin", []))
    prose = "Odile pulled on her grey coat. Her raven hair was damp."
    stub = Stub(_json(("Odile", "state.outfit", "add", "grey coat",
                       "pulled on her grey coat"),
                      ("Odile", "identity.hair", "set", "raven", "Her raven hair")))
    rep = process_turn(s, 5, prose, Scribe(stub))
    assert rep.counts()["commit"] == 2 and len(rep.committed) == 2
    assert s.canon.current("odile", "identity.hair") == "raven"
    assert s.ledger.records[-1].turn == 5 and s.ledger.records[-1].source_turn == 5
    assert "Odile Marsh (also called The Courier)" in stub.calls[0][1]
    assert stub.calls[0][1].index("Odile Marsh") < stub.calls[0][1].index("Corin"), \
        "the character named in the prose should be listed first"
    assert roster_for(s.canon, "Corin laughed.")[0]["name"] == "Corin"

    for label, scribe, status in (
            ("down", Stub(error=ScribeError("cannot reach")), "error"),
            ("crash", Stub(error=RuntimeError("boom")), "error"),
            ("refusal", Stub("I'm sorry, I can't help with that."), "refusal"),
            ("empty", Stub(""), "empty_output"),
            ("junk", Stub("lorem ipsum"), "no_json")):
        n = len(s.ledger)
        rep = process_turn(s, 6, prose, Scribe(scribe))      # must not raise
        assert rep.extraction.status == status, (label, rep.extraction.status)
        assert rep.committed == [] and len(s.ledger) == n, label
    print("10. process_turn commits through the ledger; a down, crashing, refusing "
          "or empty model is reported, never raised, and commits nothing")


class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(fn):
    real = urllib.request.urlopen
    urllib.request.urlopen = fn
    return real


def test_ollama_client():
    seen = []

    def ok(req, timeout=None):
        seen.append((req.full_url, json.loads(req.data), timeout))
        return _Resp({"message": {"content": "{\"claims\": []}"}})

    real = _patch_urlopen(ok)
    try:
        c = OllamaChat("gemma3:4b", think=False)
        assert c.complete("sys", "user", schema()) == "{\"claims\": []}"
        url, p, _ = seen[-1]
        assert url.endswith("/api/chat") and p["stream"] is False
        assert p["options"]["num_ctx"] == 4096, "the context window was not pinned"
        assert p["options"]["temperature"] == 0 and "seed" in p["options"]
        assert p["format"]["required"] == ["claims"] and p["think"] is False
        assert "think" not in OllamaChat("m")._payload("s", "u", None)
        assert "format" not in OllamaChat("m")._payload("s", "u", None)
        for bad in (512, 65536, 0):
            try:
                OllamaChat("m", num_ctx=bad)
                raise AssertionError(f"num_ctx {bad} accepted")
            except ValueError:
                pass

        calls = []

        def rejects_format(req, timeout=None):
            body = json.loads(req.data)
            calls.append(sorted(k for k in ("format", "think") if k in body))
            if "format" in body:
                raise urllib.error.HTTPError(
                    req.full_url, 400, "Bad Request", {},
                    io.BytesIO(b'{"error":"json schema format is not supported"}'))
            return _Resp({"message": {"content": "{\"claims\": []}"}})

        urllib.request.urlopen = rejects_format
        c = OllamaChat("m")
        assert c.complete("s", "u", schema()) == "{\"claims\": []}"
        assert calls == [["format"], []], calls          # dropped once
        c.complete("s", "u", schema())
        assert calls[-1] == [], "asked for the rejected field again"

        def unreachable(req, timeout=None):
            raise urllib.error.URLError("refused")
        urllib.request.urlopen = unreachable
        try:
            OllamaChat("m").complete("s", "u")
            raise AssertionError("an unreachable server did not raise")
        except ScribeError as exc:
            assert "cannot reach" in str(exc)
        OllamaChat("m").unload()                         # swallows the failure

        def server_error(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 500, "x", {}, io.BytesIO(b"oops"))
        urllib.request.urlopen = server_error
        try:
            OllamaChat("m").complete("s", "u")
            raise AssertionError("a 500 did not raise")
        except ScribeError:
            pass
    finally:
        urllib.request.urlopen = real
    print("11. the client pins num_ctx, uses temperature 0, drops a rejected "
          "optional field once, and reports a down server as an error")


def test_hosted_client_money_and_secrets():
    """A hosted client can cost money and carries a key. The key lives in an
    environment variable read at call time, and appears nowhere it could leak. A
    hard token budget stops a run that was meant to be free from becoming a paid
    one, and an exhausted quota is never retried."""
    import os
    import canon.scribe as scribe_mod
    from canon.scribe import OpenAIChat, strict_schema
    secret = "sk-test-SECRET-do-not-leak-123"
    os.environ["CR_TEST_KEY"] = secret
    sleeps = []
    real_sleep = scribe_mod.time.sleep
    scribe_mod.time.sleep = sleeps.append
    seen = []

    def reply(content="{\"claims\": []}", pt=100, ct=20):
        return _Resp({"choices": [{"message": {"content": content}}],
                      "usage": {"prompt_tokens": pt, "completion_tokens": ct}})

    def http_err(code, body, headers=None):
        return urllib.error.HTTPError("https://api.example/v1/chat/completions", code,
                                      "x", headers or {}, io.BytesIO(body.encode()))

    def leaked(*things):
        return any(secret in str(t) or secret in repr(t) for t in things)

    real = urllib.request.urlopen
    try:
        # --- request shape --------------------------------------------------
        def ok(req, timeout=None):
            seen.append(req)
            return reply(pt=150, ct=30)
        urllib.request.urlopen = ok
        c = OpenAIChat("gpt-5-nano", key_env="CR_TEST_KEY", reasoning_effort="minimal",
                       base_url="https://api.example/v1/", token_budget=1000)
        assert c.complete("sys", "user", schema()) == "{\"claims\": []}"
        req = seen[-1]
        body = json.loads(req.data)
        assert req.full_url == "https://api.example/v1/chat/completions"
        assert req.get_header("Authorization") == f"Bearer {secret}"
        assert secret not in json.dumps(body), "the key was put in the request body"
        rf = body["response_format"]["json_schema"]
        assert rf["strict"] is True and rf["schema"]["additionalProperties"] is False
        assert "maxItems" not in json.dumps(rf), "strict mode does not take maxItems"
        assert body["reasoning_effort"] == "minimal" and body["temperature"] == 0
        assert (c.tokens_in, c.tokens_out, c.tokens_used) == (150, 30, 180)
        assert not leaked(c)

        # --- a missing key names the variable and nothing else ---------------
        del os.environ["CR_TEST_KEY"]
        try:
            OpenAIChat("m", key_env="CR_TEST_KEY").complete("s", "u")
            raise AssertionError("a missing key did not raise")
        except ScribeError as exc:
            assert "CR_TEST_KEY" in str(exc) and not leaked(exc)
        os.environ["CR_TEST_KEY"] = secret

        # --- optional fields a model does not support are dropped, once -----
        calls = []

        def picky(req, timeout=None):
            b = json.loads(req.data)
            calls.append(sorted(k for k in ("temperature", "reasoning_effort") if k in b))
            for k in ("temperature", "reasoning_effort"):
                if k in b:
                    raise http_err(400, '{"error":{"message":"Unsupported parameter: '
                                        f"'{k}'" + '"}}')
            return reply()
        urllib.request.urlopen = picky
        c = OpenAIChat("m", key_env="CR_TEST_KEY", reasoning_effort="minimal")
        assert c.complete("s", "u") == "{\"claims\": []}"
        # The fake server complains about temperature first, then reasoning_effort.
        assert calls == [["reasoning_effort", "temperature"], ["reasoning_effort"], []], calls
        c.complete("s", "u")
        assert calls[-1] == [], "asked again for a field it had refused"

        # --- an exhausted quota is never retried ---------------------------
        n = []

        def quota(req, timeout=None):
            n.append(1)
            raise http_err(429, '{"error":{"code":"insufficient_quota",'
                                '"message":"You exceeded your current quota"}}')
        urllib.request.urlopen = quota
        try:
            OpenAIChat("m", key_env="CR_TEST_KEY").complete("s", "u")
            raise AssertionError("an exhausted quota did not raise")
        except ScribeError as exc:
            assert "quota" in str(exc) and not leaked(exc)
        assert len(n) == 1 and sleeps == [], "a quota error was retried"

        # --- a plain rate limit waits and retries ----------------------------
        state = {"n": 0}

        def limited_once(req, timeout=None):
            state["n"] += 1
            if state["n"] == 1:
                raise http_err(429, '{"error":{"message":"Rate limit reached"}}',
                               {"retry-after": "3"})
            return reply()
        urllib.request.urlopen = limited_once
        assert OpenAIChat("m", key_env="CR_TEST_KEY").complete("s", "u")
        assert state["n"] == 2 and sleeps == [3.0], (state, sleeps)

        # --- the key never appears in any failure ---------------------------
        for label, fn in (
                ("401", lambda r, timeout=None: (_ for _ in ()).throw(http_err(401, secret))),
                ("500", lambda r, timeout=None: (_ for _ in ()).throw(http_err(500, "boom"))),
                ("down", lambda r, timeout=None: (_ for _ in ()).throw(
                    urllib.error.URLError("refused")))):
            urllib.request.urlopen = fn
            cl = OpenAIChat("m", key_env="CR_TEST_KEY")
            try:
                cl.complete("s", "u")
                raise AssertionError(f"{label} did not raise")
            except ScribeError as exc:
                assert not leaked(exc, cl), f"{label}: the key leaked into {exc}"

        # --- the budget is a hard stop --------------------------------------
        hits = []

        def counted(req, timeout=None):
            hits.append(1)
            return reply(pt=300, ct=100)
        urllib.request.urlopen = counted
        c = OpenAIChat("m", key_env="CR_TEST_KEY", token_budget=1000)
        for _ in range(3):
            c.complete("s", "u")            # 400 tokens each: 400, 800, 1200
        before = len(hits)
        try:
            c.complete("s", "u")
            raise AssertionError("the budget did not stop the run")
        except ScribeError as exc:
            assert "token budget" in str(exc) and not leaked(exc)
        assert len(hits) == before, "a request was sent after the budget was reached"
        # ...and the Scribe reports it as an error instead of raising into a turn
        ext = Scribe(c).extract("Odile stood there.", [])
        assert ext.status == "error" and "token budget" in ext.error
    finally:
        urllib.request.urlopen = real
        scribe_mod.time.sleep = real_sleep
        os.environ.pop("CR_TEST_KEY", None)

    s = strict_schema()
    inner = s["schema"]
    assert s["strict"] and inner["required"] == ["claims"]
    assert inner["properties"]["claims"]["items"]["additionalProperties"] is False
    print("14. the key never leaves the environment variable; unsupported fields "
          "are dropped once; a spent quota is not retried; the token budget stops "
          "the run")


def test_hosted_client_free_tier():
    """OpenRouter's `:free` models allow 20 requests a minute and a fixed number a
    day, and they sometimes report an upstream failure inside an HTTP 200. Four
    things have to hold, or a free run silently turns into a pile of fake results:

      * requests are spaced by min_interval, so the per-minute cap is not hit
      * a DAILY cap is final: not retried, and no later request is sent
      * a per-minute 429 waits and retries, and does not end the run
      * an error delivered with status 200 is an error, not an empty answer, and a
        reply cut off by max_tokens is counted instead of passing as 'no claims'
    """
    import os
    import canon.scribe as scribe_mod
    from canon.scribe import OpenAIChat
    secret = "sk-or-test-SECRET-456"
    os.environ["CR_TEST_KEY"] = secret
    clock, sleeps = [100.0], []

    def fake_sleep(s):
        sleeps.append(s)
        clock[0] += s
    real_sleep, real_mono = scribe_mod.time.sleep, scribe_mod.time.monotonic
    scribe_mod.time.sleep, scribe_mod.time.monotonic = fake_sleep, lambda: clock[0]

    def reply(content="{\"claims\": []}", finish="stop"):
        return _Resp({"choices": [{"message": {"content": content},
                                   "finish_reason": finish}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    def http_err(code, body, headers=None):
        return urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions",
                                      code, "x", headers or {}, io.BytesIO(body.encode()))

    real = urllib.request.urlopen
    try:
        # --- spacing -------------------------------------------------------
        urllib.request.urlopen = lambda req, timeout=None: reply()
        c = OpenAIChat("m:free", key_env="CR_TEST_KEY", min_interval=3.2)
        c.complete("s", "u")
        assert sleeps == [], "the first request waited for nothing"
        c.complete("s", "u")                      # straight after: must wait
        assert sleeps == [3.2], sleeps
        clock[0] += 10                            # ten seconds pass on their own
        c.complete("s", "u")
        assert sleeps == [3.2], "waited although the interval had already passed"
        sleeps.clear()
        OpenAIChat("m", key_env="CR_TEST_KEY").complete("s", "u")
        OpenAIChat("m", key_env="CR_TEST_KEY").complete("s", "u")
        assert sleeps == [], "a client with no min_interval slept"

        # --- a per-minute 429 retries ------------------------------------------
        state = {"n": 0}

        def minute_cap(req, timeout=None):
            state["n"] += 1
            if state["n"] == 1:
                raise http_err(429, '{"error":{"message":"Rate limit exceeded: '
                                    'free-models-per-min. Try again shortly."}}')
            return reply()
        urllib.request.urlopen = minute_cap
        c = OpenAIChat("m:free", key_env="CR_TEST_KEY")
        assert c.complete("s", "u") and state["n"] == 2 and not c.exhausted

        # --- a daily 429 is final, and so is everything after it ------------------
        sent = []

        def day_cap(req, timeout=None):
            sent.append(1)
            raise http_err(429, '{"error":{"message":"Rate limit exceeded: '
                                'free-models-per-day. Add 10 credits to unlock 1000 '
                                'free model requests per day"}}')
        urllib.request.urlopen = day_cap
        sleeps.clear()
        c = OpenAIChat("m:free", key_env="CR_TEST_KEY")
        try:
            c.complete("s", "u")
            raise AssertionError("a daily cap did not raise")
        except ScribeError as exc:
            assert "daily" in str(exc) and secret not in str(exc)
        assert len(sent) == 1 and sleeps == [], "a daily cap was retried"
        assert c.exhausted
        try:
            c.complete("s", "u")
            raise AssertionError("a request was allowed after the daily cap")
        except ScribeError:
            pass
        assert len(sent) == 1, "a request was SENT after the daily cap"
        ext = Scribe(c).extract("Odile stood there.", [])
        assert ext.status == "error" and "daily" in ext.error and len(sent) == 1

        # --- an error inside a 200 is an error, not an empty answer ----------------
        urllib.request.urlopen = lambda req, timeout=None: _Resp(
            {"error": {"message": "Provider returned error", "code": 502}})
        try:
            OpenAIChat("m:free", key_env="CR_TEST_KEY",
                       base_url="https://openrouter.ai/api/v1").complete("s", "u")
            raise AssertionError("an error body with status 200 passed as an answer")
        except ScribeError as exc:
            assert "returned an error" in str(exc) and "openrouter.ai" in str(exc)
        state["n"] = 0

        def limited_in_200(req, timeout=None):
            state["n"] += 1
            if state["n"] == 1:
                return _Resp({"error": {"message": "rate limited upstream", "code": 429}})
            return reply()
        urllib.request.urlopen = limited_in_200
        assert OpenAIChat("m:free", key_env="CR_TEST_KEY").complete("s", "u")
        assert state["n"] == 2

        # --- a wrong key or a data-policy 404 fails every request: say it once -------
        for code, body in ((401, "bad key"),
                           (404, '{"error":{"message":"No endpoints found matching '
                                 'your data policy"}}')):
            hits = []

            def always_fails(req, timeout=None, code=code, body=body):
                hits.append(1)
                raise http_err(code, body)
            urllib.request.urlopen = always_fails
            c = OpenAIChat("m:free", key_env="CR_TEST_KEY",
                           base_url="https://openrouter.ai/api/v1")
            for _ in range(3):
                try:
                    c.complete("s", "u")
                    raise AssertionError(f"{code} did not raise")
                except ScribeError as exc:
                    assert secret not in str(exc)
            assert len(hits) == 1 and c.exhausted, \
                f"{code}: {len(hits)} requests sent for a failure that cannot change"
        # an ordinary server error is NOT final: the next request may succeed
        hits.clear()

        def flaky(req, timeout=None):
            hits.append(1)
            if len(hits) == 1:
                raise http_err(500, "boom")
            return reply()
        urllib.request.urlopen = flaky
        c = OpenAIChat("m:free", key_env="CR_TEST_KEY")
        try:
            c.complete("s", "u")
        except ScribeError:
            pass
        assert not c.exhausted and c.complete("s", "u"), "a 500 ended the run"

        # --- a server that refuses reasoning_effort without naming it ----------------
        seen_fields = []

        def mandatory_reasoning(req, timeout=None):
            body = json.loads(req.data)
            seen_fields.append("reasoning_effort" in body)
            if "reasoning_effort" in body:
                raise http_err(400, '{"error":{"message":"Reasoning is mandatory for '
                                    'this endpoint and cannot be disabled"}}')
            return reply()
        urllib.request.urlopen = mandatory_reasoning
        c = OpenAIChat("m:free", key_env="CR_TEST_KEY", reasoning_effort="none")
        assert c.complete("s", "u") and seen_fields == [True, False], seen_fields
        assert "reasoning_effort" in c.dropped

        # --- when it does give up, it says WHY (an opaque message cost a whole run) ---
        busy = []

        def upstream_busy(req, timeout=None):
            busy.append(1)
            raise http_err(429, '{"error":{"message":"google/gemma-4-31b-it:free is '
                                'temporarily rate-limited upstream"}}')
        urllib.request.urlopen = upstream_busy
        c = OpenAIChat("m:free", key_env="CR_TEST_KEY", attempts=3)
        try:
            c.complete("s", "u")
            raise AssertionError("a permanently busy server did not raise")
        except ScribeError as exc:
            assert "3 attempts" in str(exc) and "temporarily rate-limited upstream" in str(exc), exc
            assert secret not in str(exc)
        assert len(busy) == 3, "attempts was not honoured"
        assert not c.exhausted, "a busy upstream is not final: the next request may work"

        # --- a reply cut off by max_tokens is counted -----------------------------
        urllib.request.urlopen = lambda req, timeout=None: reply("", finish="length")
        c = OpenAIChat("m:free", key_env="CR_TEST_KEY")
        assert c.complete("s", "u") == "" and c.truncated == 1
        ext = Scribe(c).extract("Odile stood there.", [])
        assert ext.status == "empty_output" and c.truncated == 2
        urllib.request.urlopen = lambda req, timeout=None: reply()
        c.complete("s", "u")
        assert c.truncated == 2, "a normal reply was counted as truncated"
    finally:
        urllib.request.urlopen = real
        scribe_mod.time.sleep, scribe_mod.time.monotonic = real_sleep, real_mono
        os.environ.pop("CR_TEST_KEY", None)
    print("15. free-tier runs are paced, a daily cap is final, a per-minute cap "
          "retries, and an error in a 200 or a truncated reply is never a quiet "
          "empty answer")


def test_long_passages_are_chunked():
    para = "Odile walked on. " * 40
    prose = "\n\n".join([para] * 20)
    parts = chunks(prose)
    assert len(parts) > 1 and all(len(p) <= CHUNK_CHARS for p in parts), \
        [len(p) for p in parts]
    assert "".join(parts).count("Odile walked on.") == 800, "text was lost"
    # No sentence breaks at all: it must still be cut, or one "chunk" is larger
    # than the context the request is pinned to.
    one = "x" * (CHUNK_CHARS * 2 + 7)
    pieces = chunks(one + " " + one)
    assert len(pieces) >= 4 and all(len(p) <= CHUNK_CHARS for p in pieces), \
        [len(p) for p in pieces]
    spaced = " ".join(["word"] * 4000)
    assert all(len(p) <= CHUNK_CHARS for p in chunks(spaced))

    replies = iter([_json(("Odile", "identity.eyes", "set", "green", "green eyes")),
                    "I'm sorry, I can't help with that.",
                    _json(("Odile", "identity.hair", "set", "raven", "raven hair"))])
    stub = Stub(lambda user: next(replies))
    ext = Scribe(stub).extract(chunks_text(3), [])
    assert len(stub.calls) == 3 and len(ext.claims) == 2
    assert ext.status == "refusal", "one refused chunk hid behind two that parsed"
    print("12. a long passage is read in pieces, claims are merged, and the worst "
          "status is kept")


def chunks_text(n):
    # 3,600 characters a paragraph: two do not fit one 5,000-character chunk, so
    # each paragraph is its own call.
    return "\n\n".join(("Odile stood there. " * 200) for _ in range(n))


def test_records_are_what_lands_in_the_ledger():
    s = _store(("odile", "Odile Marsh", []))
    prose = "Odile wore a silk robe, and a thin scar ran along her jaw."
    ds = _run(s, [
        _c("Odile", "state.outfit", "add", "silk robe", "wore a silk robe"),
        _c("Odile", "identity.marks", "add", "thin scar", "a thin scar ran along her jaw"),
    ], prose, turn=7, world_time=900)
    written = commit(s, ds)
    want = [f for d in ds for f in d.records]
    assert len(written) == len(want) == 2
    for rec, f in zip(written, want):
        assert (rec.entity, rec.slot, rec.turn, rec.world_time, rec.authority) == \
            (f["entity"], f["slot"], 7, 900, "narration")
        assert rec.source_turn == 7 and rec.span in prose.replace("She", "she") \
            or rec.span.lower() in prose.lower()
    assert [d.status for d in ds] == ["commit", "commit"]
    print("13. each decision's records are exactly what the ledger received, "
          "with turn, story time, authority and source span")


try:
    for fn in (test_parser_statuses_and_rejects, test_brace_in_evidence,
               test_evidence_must_be_in_the_prose, test_value_must_be_in_its_quote,
               test_identity_commit_corroborate_contradict,
               test_a_restatement_is_not_a_contradiction, test_pending_and_pronouns,
               test_new_and_loose_entities, test_state_lists_build_and_see_earlier_claims,
               test_marks_are_one_slot_each, test_two_hair_colours_in_one_passage,
               test_a_claim_needs_a_named_character_and_a_real_context,
               test_process_turn_and_failures, test_ollama_client,
               test_hosted_client_money_and_secrets, test_hosted_client_free_tier,
               test_long_passages_are_chunked, test_records_are_what_lands_in_the_ledger):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON SCRIBE TESTS PASSED")
