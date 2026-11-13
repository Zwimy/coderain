"""Accessories: jewellery and ornaments worn on a person are a slot of their own (D-044).

What broke. Nothing in the slot list could hold a ring, a pair of hairpins or a string of beads. The real-story gate
lost two of its controls that way (a character's hairpins, another's jade beads), and in a later soak the reader's
only way to file "iridescent beads in her braids" was as hair, which the shape rules rightly refused, so the beads
were dropped. Marks are the model: one ledger slot per item, first write wins per item, nothing ages off.

 1) the shape rule: an ornament noun, worn (a place on the body or a verb for wearing it), not taken off, not carried;
    words with other meanings (ring, beads, glasses) need that cue; "beads of sweat" and a locket on a table are not one
 2) the validator files one slot per item; the same item worded another way is the item said again; a different
    item (another colour, another noun) is a new slot; no conflict is ever recorded between items
 3) a character holds at most MAX_ACCESSORIES, the next is refused with a reason
 4) the claim schema and the prompt ask about the slot only when told to (it changes the prompt every other slot is read
    through, so it is off until measured), the Scribe passes that on, and the op rules are add only
 5) the card shows "wears ..." as an identity phrase, and it can be left out for a turn like the other fields
 6) corrections: `Name: accessories = x` adds one at author authority, `is not x` retracts the matching one and is
    refused when the story proposes it, a removed line releases it, and `jewellery` is the same slot
 7) the identity table and the held-values list carry accessories as their own key
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-acc-"))

from canon import Store, shape                                         # noqa: E402
from canon.claims import OPTIONAL_SLOTS, SLOT_HELP, SLOTS, Claim, op_ok, parse, schema, slots  # noqa: E402
from canon.corrections import apply_to, held_values, parse as parse_corr, plan, refusals  # noqa: E402
from canon.replay import identity_table                                # noqa: E402
from canon.scene import bible, identity_needed                         # noqa: E402
from canon.scribe import Scribe, build_prompt, strict_schema           # noqa: E402
from canon.validate import MAX_ACCESSORIES, commit, validate           # noqa: E402

ACC = "identity.accessories"
NOT_ACC, NOT_WORN = "not_an_accessory", "not_worn"
_n = [0]


def _store():
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for eid, name in (("odile", "Odile Marsh"), ("corin", "Corin Hale")):
        s.append(kind="entity_created", entity=eid, slot="character", value=name,
                 authority="scenario", turn=0, aliases=[])
    return s


def say(s, entity, value, quote, turn=1, **kw):
    d = validate(s.canon, [Claim(entity, ACC, "add", value, quote, "high")], quote, turn=turn,
                 next_id=len(s.ledger) + 1, create_unknown=False, **kw)
    commit(s, d, record_contradictions=True)
    return d[0]


def items(s, eid):
    return {k.split(".", 2)[2]: s.canon.current(eid, k) for k in s.canon.slots.get(eid, {})
            if k.startswith("identity.accessories.") and s.canon.current(eid, k) is not None}


def test_the_shape_rule():
    rows = [
        ("gold hairpins", "Her hair was pinned up with gold hairpins", None),
        ("jade beads", "jade beads woven through her braids", None),
        ("silver ring", "She wore a silver ring", None),
        ("silver ring", "a silver ring on her finger", None),
        ("round glasses", "round glasses perched on his nose", None),
        ("round glasses", "He wore round glasses", None),
        ("hairpins", "her hair held back by hairpins", None),                  # "held" is not carrying here
        ("silver locket", "the silver locket at her throat", None),
        ("beads", "beads of sweat on her brow", NOT_ACC),                      # a liquid
        ("sweat beads", "sweat beads on her wrist", NOT_ACC),
        ("red scarf", "a red scarf", NOT_ACC),                                 # a garment is the outfit's
        ("silver locket", "the silver locket gleamed on the table", NOT_WORN),  # an object, not worn
        ("silver locket", "She clutched the silver locket in her fist", NOT_WORN),
        ("silver locket", "He wore a coat and clutched the silver locket", NOT_WORN),
        ("silver ring", "She took off her silver ring", NOT_WORN),             # being removed
        ("silver ring", "She slipped the silver ring off her finger", NOT_WORN),   # removed, though a body place is named
        ("ring", "a ring of men closed round him", NOT_WORN),
        ("glasses", "He set the glasses on the table", NOT_WORN),
    ]
    for value, quote, want in rows:
        got = shape.problem(ACC, value, quote)
        assert got == want, (value, quote, "expected", want, "got", got)
    print("1. an ornament that is worn passes; sweat, a garment, a locket on a table, a held locket, one taken off and a ring of men do not")


def test_one_slot_per_item():
    s = _store()
    d = say(s, "Odile Marsh", "gold hairpins", "Odile Marsh's hair was pinned up with gold hairpins", 1)
    assert d.status == "commit", d
    assert items(s, "odile") == {"gold-hairpins": "gold hairpins"}, items(s, "odile")
    say(s, "Odile Marsh", "gold hairpins", "Odile Marsh touched the gold hairpins in her hair", 2)
    say(s, "Odile Marsh", "hairpins", "Odile Marsh's hairpins caught the lamp, pinned in her hair", 3)      # the same item, shorter
    say(s, "Odile Marsh", "gold hairpins", "Odile Marsh wore gold hairpins", 4)
    assert items(s, "odile") == {"gold-hairpins": "gold hairpins"}, items(s, "odile")
    iv = s.canon.slots["odile"]["identity.accessories.gold-hairpins"]
    assert len(iv) == 1 and iv[0].confirmations == 4 and iv[0].authority == "narration", iv
    say(s, "Odile Marsh", "jade beads", "Odile Marsh's braids were threaded with jade beads", 5)
    say(s, "Odile Marsh", "green beads", "Odile Marsh's braids showed green beads at the ends", 6)          # jade is green: the same item
    say(s, "Odile Marsh", "silver ring", "Odile Marsh wore a silver ring", 7)
    say(s, "Odile Marsh", "silver hairpins", "Odile Marsh's hair was pinned with silver hairpins", 8)         # another colour: another item
    assert sorted(items(s, "odile")) == ["gold-hairpins", "jade-beads", "silver-hairpins", "silver-ring"], items(s, "odile")
    assert not s.canon.conflicts, s.canon.conflicts
    print("2. one slot per item; the same item worded another way is a restatement; another colour or noun is a new item; no conflict")


def test_the_bound():
    s = _store()
    nouns = ["hairpin", "ring", "earring", "necklace", "pendant", "bracelet", "anklet", "brooch", "circlet",
             "tiara", "headband", "choker"]
    assert len(nouns) == MAX_ACCESSORIES
    for k, noun in enumerate(nouns):
        d = say(s, "Odile Marsh", f"tin {noun}", f"Odile Marsh wore a tin {noun}", k + 1)
        assert d.status == "commit", (noun, d)
    assert len(items(s, "odile")) == MAX_ACCESSORIES, items(s, "odile")
    d = say(s, "Odile Marsh", "brass locket", "Odile Marsh wore a brass locket", 99)
    assert (d.status, d.reason) == ("reject", "too_many_accessories"), d
    assert len(items(s, "odile")) == MAX_ACCESSORIES
    d = say(s, "Odile Marsh", "tin ring", "Odile Marsh wore a tin ring again", 100)                      # a known item still counts
    assert d.status == "commit" and len(items(s, "odile")) == MAX_ACCESSORIES, d
    assert s.canon.slots["odile"]["identity.accessories.tin-ring"][0].confirmations == 2
    print("3. a character holds at most %d; the next is refused with a reason, a known item is still confirmed" % MAX_ACCESSORIES)


def test_schema_prompt_and_ops():
    assert ACC in SLOTS and ACC in SLOT_HELP and SLOTS[ACC] == "list"
    enum = lambda s: s["properties"]["claims"]["items"]["properties"]["slot"]["enum"]      # noqa: E731
    # the prompt line is OFF unless asked for: it changes what the reader does with every other slot (D-044)
    assert ACC not in enum(schema()) and ACC in enum(schema(True)), "the schema gate is wrong"
    assert ACC in OPTIONAL_SLOTS and ACC not in slots() and ACC in slots(True)
    off, _u = build_prompt("Odile wore a ring.", [])
    on, _u = build_prompt("Odile wore a ring.", [], True)
    assert ACC not in off and "hairpins" not in off, "the default prompt mentions accessories"
    assert ACC in on and "hairpins" in on and "not a garment" in on, "the Scribe is not told what the slot is for"
    # the Scribe hands the gate to its model, prompt and schema alike
    seen = []

    class Spy:
        def complete(self, system, user, schema_=None):
            seen.append((system, schema_))
            return '{"claims": []}'
    Scribe(Spy()).extract("Odile wore a ring.", [])
    Scribe(Spy(), accessories=True).extract("Odile wore a ring.", [])
    assert ACC not in seen[0][0] and ACC not in enum(seen[0][1]), "the default Scribe asked about accessories"
    assert ACC in seen[1][0] and ACC in enum(seen[1][1]), "an accessories Scribe did not"
    assert ACC in enum(strict_schema(schema(True))["schema"]) and ACC not in enum(strict_schema()["schema"])
    assert op_ok(ACC, "add") and not op_ok(ACC, "remove") and not op_ok(ACC, "set") and not op_ok(ACC, "clear")
    body = json.dumps({"claims": [{"entity": "Odile", "slot": ACC, "op": "remove", "value": "ring",
                                   "evidence": "took off the ring", "confidence": "high"}]})
    p = parse(body)
    assert not p.claims and [r["reason"] for r in p.rejects] == ["op_not_allowed_for_slot"], p
    print("4. the schema and prompt ask about the slot only when told to, the Scribe passes the gate on, and the op rules are add only")


def test_the_card():
    s = _store()
    say(s, "Odile Marsh", "gold hairpins", "Odile Marsh's hair was pinned up with gold hairpins", 1)
    say(s, "Odile Marsh", "jade beads", "Odile Marsh's braids were threaded with jade beads", 2)
    s.append(kind="fact_established", entity="odile", slot="identity.hair", value="raven",
             authority="narration", turn=3)
    line = bible(s.canon, "odile")
    assert "raven hair" in line and "wears gold hairpins, jade beads" in line, line
    assert "wears" not in bible(s.canon, "odile", hide={"accessories"}), "a hidden field was shown"
    needed = identity_needed(s.canon, ["odile"], [], "")
    assert needed["odile"] == {"hair", "accessories"}, needed
    assert identity_needed(s.canon, ["odile"], ["Odile Marsh walked in."], "") == {"odile": set()}
    print("5. the card says 'wears ...' as a phrase, can leave it out, and offers it when the character has dropped out of the recent turns")


def test_corrections():
    s = _store()
    say(s, "Odile Marsh", "gold hairpins", "Odile Marsh's hair was pinned up with gold hairpins", 1)
    corr, problems = parse_corr("- Odile: accessories = silver ring\n- Odile: jewellery is not gold hairpins\n")
    assert not problems and [(c.slot, c.op) for c in corr] == [("accessories", "set"), ("accessories", "wrong")], (corr, problems)
    recs, why = plan(s.canon, corr, turn=5)
    assert not why, why
    got = sorted((r["slot"], r["value"], r["authority"]) for r in recs)
    assert got == [("identity.accessories.gold-hairpins", None, "author"),
                   ("identity.accessories.silver-ring", "silver ring", "author")], got
    apply_to(s.canon, corr, turn=5)
    assert s.canon.current("odile", "identity.accessories.silver-ring") == "silver ring"
    assert s.canon.current("odile", "identity.accessories.gold-hairpins") is None, "the wrong item was kept"
    assert refusals(s.canon, corr) == {("odile", ACC): ["gold hairpins"]}
    d = say(s, "Odile Marsh", "gold hairpins", "Odile Marsh's hair was pinned up with gold hairpins", 6,
            refused=refusals(s.canon, corr))
    assert d.reason == "author_refused", d
    rows = [r for r in held_values(s.canon) if r["slot"] == "accessories"]
    assert [(r["value"], r["by"]) for r in rows] == [("silver ring", "author")], rows
    # removing the line releases what it set
    t = _store()
    corr1, _ = parse_corr("- Odile: accessories = silver ring\n")
    apply_to(t.canon, corr1, turn=1)
    assert t.canon.current("odile", "identity.accessories.silver-ring") == "silver ring"
    recs, _ = plan(t.canon, [], turn=2)
    assert [(r["slot"], r["value"]) for r in recs] == [("identity.accessories.silver-ring", None)], recs
    print("6. corrections add and retract an accessory, refuse it when the story proposes it, release it with the line, and take 'jewellery'")


def test_the_tables():
    s = _store()
    say(s, "Odile Marsh", "gold hairpins", "Odile Marsh's hair was pinned up with gold hairpins", 1)
    s.append(kind="fact_established", entity="odile", slot="identity.eyes", value="grey",
             authority="narration", turn=2)
    row = [r for r in identity_table(s.canon) if r["entity"] == "odile"][0]
    assert row["accessories"] == ["gold hairpins"] and "accessories.gold-hairpins" not in row["fields"], row
    assert "eyes" in row["fields"] and row["marks"] == [], row
    held = [r for r in held_values(s.canon) if r["slug"] == "odile"]
    assert sorted(r["slot"] for r in held) == ["accessories", "eyes"], held
    print("7. the identity table and the held-values list carry accessories under their own key")


try:
    for fn in (test_the_shape_rule, test_one_slot_per_item, test_the_bound, test_schema_prompt_and_ops,
               test_the_card, test_corrections, test_the_tables):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON ACCESSORIES TESTS PASSED")
