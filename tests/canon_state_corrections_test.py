"""State corrections (D-062): the author can say that a worn or held item the reader filed is wrong.

D-028 let the author correct IDENTITY (hair, eyes, marks...) and left state out on purpose: what someone wears or holds
changes every few turns and is the story's to say. What it left unsolved is the item the reader filed by mistake (a
garment another person wore, a thing that was only mentioned), which then sits on the card and is sent to the Writer until
the story happens to change it. A standing "equals" would fight the story, and `plan` remembers nothing, so it could not
tell a correction from a change of clothes. "is not" is different: it is true once and stays true. Each numbered assertion
pins one promise:

 1) the file: `outfit is not X` and `held is not X` parse, with the words wearing, worn, clothes, holding and carrying
    accepted; "=" on either is a reported problem with its line (never silently dropped, never applied); the header's own
    examples are not read as corrections
 2) `plan` takes the item off the list: the list that is left is written as an author record (state_set for outfit,
    item_moved for held), a list with nothing left is cleared, and nothing is written when nothing matches
 3) matching is by item, never by colour alone: "cloak" takes off "red cloak", "grey coat" does NOT take off "grey scarf"
 4) several lines about one list are applied together: each starts from the original list, so without that the second would
    write back what the first had taken off
 5) it is idempotent, which is what lets it run after every turn and every rollback: applied twice, the second plan is empty
 6) state is not pinned: after a correction the story's next real change of state is believed, and the refused item is
    refused for THAT person only
 7) the validator refuses the item when the Scribe proposes it again (author_refused), by item and not by colour, and a
    different item for the same person goes through
 8) an unknown or ambiguous name is a reported problem and changes nothing
 9) `state_values` lists what canon holds as worn and carried, one row per item, for a person to read before marking one wrong
10) the card applies the correction itself: the item is not sent to the Writer, before the reader has written it
11) removing the line writes nothing (a retraction is not undone), and the release of "=" lines never touches state
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-statecorr-"))

from canon import Store                                                    # noqa: E402
from canon.card import Snapshot, build_card, content_hash                   # noqa: E402
from canon.claims import Claim                                              # noqa: E402
from canon.corrections import HEADER, STATE_SLOTS, add_line, parse, plan, refusals, slot_word, state_values   # noqa: E402
from canon.validate import commit, same_item, validate                     # noqa: E402

_n = [0]
PEOPLE = [("odile", "Odile Marsh", ["The Courier"]), ("corin", "Corin Hale", []), ("finn", "Finn", [])]


def store():
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for slug, name, aliases in PEOPLE:
        s.append(kind="entity_created", entity=slug, slot="character", value=name,
                 authority="scenario", turn=0, aliases=list(aliases))
    return s


def say(s, who, slot, op, value, quote, turn, refused=None):
    c = Claim(who, slot, op, value, quote, "high")
    ds = validate(s.canon, [c], f"{who} stood there, {quote}.", turn=turn, next_id=len(s.ledger) + 1,
                  create_unknown=False, refused=refused)
    commit(s, ds, record_contradictions=True)
    return ds[0]


def dressed():
    s = store()
    for i, item in enumerate(("red cloak", "grey scarf", "leather boots"), 1):
        say(s, "Odile", "state.outfit", "add", item, f"a {item}", i)
    for i, item in enumerate(("brass key", "coil of rope"), 4):
        say(s, "Odile", "state.held", "add", item, f"a {item}", i)
    say(s, "Corin", "state.outfit", "add", "red cloak", "a red cloak", 6)
    return s


def write(s, corr, turn=None):
    last = s.ledger.records[-1].turn
    recs, problems = plan(s.canon, corr, turn=last if turn is None else turn)
    for f in recs:
        s.append(**f)
    return recs, problems


def test_the_file():
    assert parse(HEADER) == ([], []), "the header's own examples were read as corrections"
    c, p = parse("- Odile: outfit is not red cloak\n- Odile: wearing is not boots\n- Corin: holding is not brass key\n"
                 "- Corin: carrying is not a lamp\n- Finn: clothes is not hat\n- Finn: worn is not scarf\n- Odile: held is not rope")
    got = [(x.who, x.slot, x.op, x.value) for x in c]
    assert ("Odile", "outfit", "wrong", "red cloak") in got and ("Odile", "outfit", "wrong", "boots") in got, got
    assert ("Corin", "held", "wrong", "brass key") in got and ("Corin", "held", "wrong", "a lamp") in got, got
    assert ("Finn", "outfit", "wrong", "hat") in got and ("Finn", "outfit", "wrong", "scarf") in got, got
    assert ("Odile", "held", "wrong", "rope") in got and p == [], (got, p)
    assert slot_word("worn") == "outfit" and slot_word("Holding") == "held" and slot_word("jewellery") == "accessories"
    c, p = parse("- Odile: hair = raven\n- Odile: outfit = grey coat\n- Corin: held = a lamp\n- Odile: outfit is not red cloak\n")
    assert [(x.slot, x.op) for x in c] == [("hair", "set"), ("outfit", "wrong")], "a state '=' was kept"
    why = {q["line"]: q["why"] for q in p}
    assert set(why) == {2, 3} and all("only be marked wrong" in w for w in why.values()), why
    c, p = parse("- Odile: outfitt is not red cloak")
    assert c == [] and "unknown slot" in p[0]["why"] and "outfit" in p[0]["why"] and "held" in p[0]["why"], p
    assert STATE_SLOTS == {"outfit": "state.outfit", "held": "state.held"}
    assert add_line("", "Odile", "wearing", "wrong", "red cloak").rstrip().endswith("- Odile: outfit is not red cloak")
    print("1. the file: 'is not' parses for outfit and held (and their other words), '=' is reported and never kept")


def test_plan_takes_the_item_off():
    s = dressed()
    recs, problems = plan(s.canon, parse("- Odile: outfit is not red cloak")[0], turn=9)
    assert problems == [] and len(recs) == 1, recs
    r = recs[0]
    assert (r["entity"], r["slot"], r["kind"], r["authority"], r["span"]) == \
        ("odile", "state.outfit", "state_set", "author", "corrections.md"), r
    assert r["value"] == ["grey scarf", "leather boots"], r
    recs, _ = plan(s.canon, parse("- Odile: held is not brass key")[0], turn=9)
    assert recs[0]["kind"] == "item_moved" and recs[0]["value"] == ["coil of rope"], recs
    # taking off the last item clears the slot (state_cleared takes no value)
    write(s, parse("- Odile: held is not brass key")[0])
    recs, _ = plan(s.canon, parse("- Odile: held is not brass key\n- Odile: held is not rope")[0], turn=9)
    assert [(x["kind"], x["value"]) for x in recs] == [("state_cleared", None)], recs
    # nothing matches: nothing is written (and no problem: the author may be ahead of the reader)
    assert plan(s.canon, parse("- Odile: outfit is not green hat")[0], turn=9) == ([], [])
    print("2. plan writes the list that is left (state_set / item_moved), a clear when none is left, nothing when nothing matches")


def test_matching_is_by_item():
    assert same_item("red cloak", "cloak") and same_item("Cloak", "red cloak") and same_item("red cloak", "red cloak")
    assert not same_item("grey coat", "grey scarf") and not same_item("brass key", "iron key")
    assert not same_item("red cloak", "scarlet cloak"), "a synonym is a different phrase: the author adds the other line"
    s = dressed()
    recs, _ = plan(s.canon, parse("- Odile: outfit is not cloak")[0], turn=9)
    assert recs[0]["value"] == ["grey scarf", "leather boots"], "a shorter phrase should take off the longer item"
    s2 = store()
    say(s2, "Odile", "state.outfit", "add", "grey coat", "a grey coat", 1)
    say(s2, "Odile", "state.outfit", "add", "grey scarf", "a grey scarf", 2)
    recs, _ = plan(s2.canon, parse("- Odile: outfit is not grey coat")[0], turn=9)
    assert recs[0]["value"] == ["grey scarf"], "'grey coat' took off the grey scarf as well: " + str(recs)
    print("3. matching is by item: 'cloak' takes off 'red cloak', 'grey coat' does not take off 'grey scarf'")


def test_several_lines_one_list():
    s = dressed()
    corr = parse("- Odile: outfit is not red cloak\n- Odile: outfit is not leather boots")[0]
    recs, _ = plan(s.canon, corr, turn=9)
    assert len(recs) == 1 and recs[0]["value"] == ["grey scarf"], recs
    write(s, corr)
    assert s.canon.current("odile", "state.outfit") == ["grey scarf"], s.canon.current("odile", "state.outfit")
    print("4. two lines about one list take both items off (one record, not the second writing back the first)")


def test_idempotent():
    s = dressed()
    corr = parse("- Odile: outfit is not red cloak\n- Odile: held is not brass key\n- Corin: outfit is not red cloak")[0]
    first, _ = write(s, corr)
    assert len(first) == 3, first
    second, _ = plan(s.canon, corr, turn=20)
    assert second == [], f"a second plan was not empty: {second}"
    assert s.canon.current("corin", "state.outfit") is None, "Corin's list should be cleared"
    assert s.canon.current("odile", "state.held") == ["coil of rope"]
    print("5. it is idempotent: applied twice the second plan is empty (and Odile's refusal did not touch Corin's list)")


def test_state_is_not_pinned_and_is_per_person():
    s = dressed()
    corr = parse("- Odile: outfit is not red cloak")[0]
    write(s, corr)
    refused = refusals(s.canon, corr)
    assert refused == {("odile", "state.outfit"): ["red cloak"]}, refused
    # the story changes clothes: believed (author authority does not pin state)
    d = say(s, "Odile", "state.outfit", "add", "blue gloves", "blue gloves", 10, refused=refused)
    assert d.status == "commit", (d.status, d.reason)
    assert "blue gloves" in s.canon.current("odile", "state.outfit") and "grey scarf" in s.canon.current("odile", "state.outfit")
    # Corin may still wear a red cloak: the refusal is Odile's
    d = say(s, "Corin", "state.outfit", "add", "red cloak", "a red cloak", 11, refused=refused)
    assert d.status != "reject" or d.reason != "author_refused", (d.status, d.reason)
    print("6. after a correction the story's next change is believed, and the refusal is that person's only")


def test_the_validator_refuses_it_again():
    s = dressed()
    corr = parse("- Odile: outfit is not red cloak\n- Odile: held is not brass key")[0]
    write(s, corr)
    refused = refusals(s.canon, corr)
    again = say(s, "Odile", "state.outfit", "add", "red cloak", "a red cloak", 12, refused=refused)
    assert (again.status, again.reason) == ("reject", "author_refused"), (again.status, again.reason)
    longer = say(s, "Odile", "state.outfit", "add", "worn red cloak", "a worn red cloak", 12, refused=refused)
    assert (longer.status, longer.reason) == ("reject", "author_refused"), "a longer wording of the same item got through"
    key = say(s, "Odile", "state.held", "set", "brass key", "a brass key", 12, refused=refused)
    assert (key.status, key.reason) == ("reject", "author_refused"), (key.status, key.reason)
    other = say(s, "Odile", "state.outfit", "add", "red scarf", "a red scarf", 12, refused=refused)
    assert other.status == "commit", f"a different red item was refused by colour: {other.status} {other.reason}"
    unrefused = say(s, "Odile", "state.outfit", "add", "red cloak", "a red cloak", 12)
    assert unrefused.status == "commit", "without the refusal map the item must be accepted (the map is the only thing refusing)"
    print("7. the validator refuses the item again by item (a longer wording too), and a different red item goes through")


def test_unknown_and_ambiguous():
    s = store()
    say(s, "Odile", "state.outfit", "add", "red cloak", "a red cloak", 1)
    recs, problems = plan(s.canon, parse("- Nobody Here: outfit is not red cloak")[0], turn=5)
    assert recs == [] and "Nobody Here" in problems[0]["why"], (recs, problems)
    s.append(kind="entity_created", entity="odile-2", slot="character", value="Odile Vane", authority="narration", turn=2,
             aliases=["Odile"])
    recs, problems = plan(s.canon, parse("- Odile: outfit is not red cloak")[0], turn=5)
    assert recs == [] and problems, "an ambiguous name changed a list"
    assert s.canon.current("odile", "state.outfit") == ["red cloak"]
    print("8. an unknown or ambiguous name is reported and changes nothing")


def test_state_values():
    s = dressed()
    write(s, parse("- Odile: outfit is not red cloak")[0])
    rows = state_values(s.canon)
    got = [(r["who"], r["slot"], r["value"]) for r in rows]
    assert ("Odile Marsh", "outfit", "grey scarf") in got and ("Odile Marsh", "held", "brass key") in got, got
    assert ("Odile Marsh", "outfit", "red cloak") not in got, "a corrected item is still shown as worn"
    assert ("Corin Hale", "outfit", "red cloak") in got
    assert all(set(r) == {"who", "slug", "slot", "value", "since_turn", "by"} for r in rows)
    assert [r["who"] for r in rows] == sorted((r["who"] for r in rows), key=str.lower)
    write(s, parse("- Odile: outfit is not red cloak\n- Odile: outfit is not grey scarf\n- Odile: outfit is not leather boots")[0])
    assert not any(r["who"] == "Odile Marsh" and r["slot"] == "outfit" for r in state_values(s.canon)), "a cleared list is still listed"
    print("9. state_values lists open worn and carried items, one row each, and not a corrected or cleared one")


def test_the_card():
    s = dressed()
    H = {i: content_hash(f"turn {i}") for i in range(1, 7)}
    snap = Snapshot(tuple(s.ledger.records), dict(H), 1, "finn")
    recent = ["Odile Marsh stepped in. Corin Hale watched her."]
    plain = build_card(snap, H, recent, now=8)
    assert "red cloak" in plain.text, plain.text
    corr = parse("- Odile: outfit is not red cloak")[0]
    got = build_card(snap, H, recent, now=8, corrections=corr)
    odile_line = next(ln for ln in got.text.splitlines() if ln.startswith("Odile") or "Odile" in ln.split(":")[0])
    assert "red cloak" not in odile_line and "grey scarf" in odile_line, got.text
    assert "red cloak" in got.text, "Corin's own red cloak should still be on the card"
    print("10. the card hides the corrected item before the reader has written the correction, and keeps the rest")


def test_removing_the_line():
    s = dressed()
    corr = parse("- Odile: outfit is not red cloak")[0]
    write(s, corr)
    n = len(s.ledger)
    recs, _ = plan(s.canon, [], turn=30)            # the last line removed
    assert recs == [] and len(s.ledger) == n, "removing a state line wrote something"
    assert "red cloak" not in s.canon.current("odile", "state.outfit"), "the retraction was undone"
    # the release of '=' lines must not touch state: an author record on a state slot is not 'this file's own identity value'
    s.append(kind="author_edit", entity="odile", slot="identity.hair", value="raven", authority="author", turn=31, span="corrections.md")
    recs, _ = plan(s.canon, [], turn=32)
    assert [(r["slot"], r["value"]) for r in recs] == [("identity.hair", None)], recs
    print("11. removing a state line writes nothing and the retraction stays; the identity release never touches state")


try:
    test_the_file()
    test_plan_takes_the_item_off()
    test_matching_is_by_item()
    test_several_lines_one_list()
    test_idempotent()
    test_state_is_not_pinned_and_is_per_person()
    test_the_validator_refuses_it_again()
    test_unknown_and_ambiguous()
    test_state_values()
    test_the_card()
    test_removing_the_line()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON STATE CORRECTIONS TESTS PASSED")
