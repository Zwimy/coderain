"""Author corrections (D-028): the way out of first-write-wins for a value that is wrong.

The first Writer test on a real save showed a WRONG held value being repeated by the Writer, and the card
not always winning. This is the mechanism that lets the author say what is true and what is false, so each
promise below is about the ways it could quietly stop working. Each assertion pins one:

 1) the file: only bullets are read, the header's own examples are not, notes are ignored, a bullet that does
    not parse is reported with its line (never dropped), a contradiction and a replaced value are reported
 2) writing a line adds the header once, keeps the file's order and never adds the same correction twice
 3) `plan` returns only what is still needed: an author value where the canon differs, a retraction where a
    wrong value is held, nothing otherwise; an unknown or ambiguous name is a reported problem, not a crash
 4) it is idempotent, which is what lets it run after every turn and every rollback: applying it twice
    changes nothing the second time, across set, wrong and marks
 5) authority: the author's value outranks narration (a later different value is held back as a conflict); a
    retraction empties the slot and the story may then establish the real one; history is kept
 6) a value the author called wrong is refused when proposed, by the validator, whatever the Scribe says
 7) the card applies them itself: it shows the author's value and hides a retracted one even when the ledger
    has not been told yet, and after an undo has cut off the records that carried them
 8) `held_values` lists what canon holds for a person to read: open values only, with whose word it is
 9) removing a "=" line releases what it set and only that (the story's own values and an author edit made
    another way stay), changing a value is a replacement, a retraction is not undone by removing its line, a
    name that matches nobody shields no other release and an ambiguous one shields both characters
10) with the last line removed the card drops the author's value at once, not after the reader's next pass
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-corr-"))

from canon import Store                                                    # noqa: E402
from canon.card import Snapshot, build_card, content_hash                   # noqa: E402
from canon.claims import Claim                                              # noqa: E402
from canon.corrections import (HEADER, add_line, apply_to, describe, held_values, parse,   # noqa: E402
                               plan, refusals, slot_word)
from canon.validate import commit, validate                                 # noqa: E402

_n = [0]
PEOPLE = [("odile", "Odile Marsh", ["The Courier"]), ("corin", "Corin Hale", []),
          ("tamsin", "Tamsin Reeve", []), ("finn", "Finn", [])]


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


def write(s, corr, turn=None):
    """What the reader does: put the ledger in line with the corrections."""
    last = s.ledger.records[-1].turn
    recs, problems = plan(s.canon, corr, turn=last if turn is None else turn)
    for f in recs:
        s.append(**f)
    return recs, problems


def test_the_file():
    c, p = parse(HEADER)
    assert (c, p) == ([], []), "the header's own examples were read as corrections"
    text = HEADER + """
Some note a person wrote, with Odile: hair = red in it, which is not a bullet.
- Odile: hair = raven -- she dyed it back in chapter 3
- Corin: eye = grey
- Corin: eyes is not green
* Tamsin: mark = scar on her chin
- Tamsin: marks = scar on her chin
- Tamsin: marks = tattoo of a heron
- Odile: hair = raven
- Finn: hairstyle = long
- no colon here
- Odile: hair =
- Odile: hair = """ + "x" * 100 + """
- Corin: eyes = green
- Corin: eyes is not grey
- Odile: hair = auburn
"""
    c, p = parse(text)
    got = [(x.who, x.slot, x.op, x.value) for x in c]
    assert ("Odile", "hair", "set", "raven") not in got, "an earlier value for the same slot should be replaced"
    assert ("Odile", "hair", "set", "auburn") in got and ("Corin", "eyes", "set", "grey") in got
    assert ("Corin", "eyes", "wrong", "green") in got and ("Tamsin", "marks", "set", "scar on her chin") in got
    assert ("Tamsin", "marks", "set", "tattoo of a heron") in got, "marks is a list: several lines all count"
    assert len(c) == len(set(got)), "said twice, kept twice"
    assert got.count(("Tamsin", "marks", "set", "scar on her chin")) == 1, \
        "a mark written twice (with a different bullet) was kept twice"
    assert not any("Some note" in q["text"] for q in p), "a note was reported as a malformed correction"
    why = {q["line"]: q["why"] for q in p}
    assert any("unknown slot" in w for w in why.values()), why
    assert any("expected" in w for w in why.values()), why
    assert any("no value" in w for w in why.values()), why
    assert any("longer than" in w for w in why.values()), why
    assert any("contradicts" in w and "wrong" in w for w in why.values()), \
        "Corin eyes = green after eyes is not green"
    assert any("contradicts" in w and "right" in w for w in why.values()), \
        "Corin eyes is not grey after eye = grey"
    assert any("replaced by line" in w for w in why.values()), why
    assert all(q["line"] > 0 and q["text"] for q in p)
    assert describe(text)["corrections"][0]["who"] and slot_word("eye") == "eyes" and slot_word("mark") == "marks"
    assert slot_word("hairstyle") is None
    print("1. only bullets are read; the header's examples and notes are not; a bad bullet, a "
          "contradiction and a replaced value are reported with their line")


def test_writing_a_line():
    t = add_line("", "Odile", "hair", "set", "raven")
    assert t.startswith("# Canon corrections") and t.count("# Canon corrections") == 1
    t2 = add_line(t, "Odile", "hair", "set", "raven")
    t2 = add_line(t2, "odile", "hair", "set", "Raven")
    assert t2 == t, "the same correction was added twice"
    t3 = add_line(t2, "Corin", "mark", "wrong", "scarred features")
    assert t3.endswith("- Corin: marks is not scarred features\n") and t3.startswith(t.rstrip("\n"))
    assert [(x.who, x.slot, x.op) for x in parse(t3)[0]] == [("Odile", "hair", "set"), ("Corin", "marks", "wrong")]
    assert add_line("", "A", "hair", "set", "x").count("\n") > 3 and add_line("   ", "A", "hair", "set", "x").startswith("#")
    print("2. writing a line adds the header once, never adds the same correction twice, and reads back")


def test_plan_returns_only_what_is_needed():
    s = store()
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 1)
    say(s, "Corin", "identity.eyes", "set", "green", "his green eyes", 1)
    say(s, "Tamsin", "identity.marks", "add", "scar over her left eye", "a scar over her left eye", 1)
    say(s, "Tamsin", "identity.marks", "add", "tattoo of a heron", "a tattoo of a heron", 1)

    def recs(text):
        return plan(s.canon, parse(text)[0], turn=2)

    r, pr = recs("- Odile: hair = raven")
    assert [(x["entity"], x["slot"], x["value"], x["kind"], x["authority"]) for x in r] == \
        [("odile", "identity.hair", "raven", "author_edit", "author")] and pr == []
    assert recs("- Odile: hair = Platinum")[0] == [], "the same value after normalising needs nothing"
    r, _ = recs("- Odile: hair is not platinum")
    assert [(x["slot"], x["value"]) for x in r] == [("identity.hair", None)], "a held wrong value is retracted"
    assert recs("- Odile: hair is not black")[0] == [], "black is not what is held, so nothing to retract"
    assert recs("- Odile: hair is not silver")[0] == [], "and a colour that is not held is not touched"
    r, _ = recs("- Tamsin: marks is not heron tattoo")
    assert [x["slot"] for x in r] == ["identity.marks.tattoo-of-a-heron"], r      # only the matching mark
    r, _ = recs("- Tamsin: marks = scar on her chin")
    assert [x["slot"] for x in r] == ["identity.marks.scar-on-her-chin"] and r[0]["value"] == "scar on her chin"
    assert recs("- Tamsin: marks = tattoo of a heron")[0] == [], "that mark is already held"
    r, pr = recs("- The Courier: eyes = grey")
    assert r and r[0]["entity"] == "odile", "an alias names the character"
    r, pr = recs("- Nobody: hair = red\n- Odile: hair = red")
    assert [x["entity"] for x in r] == ["odile"] and len(pr) == 1 and "Nobody" in pr[0]["why"], pr
    s.append(kind="entity_created", entity="odile-2", slot="character", value="Odile", authority="scenario",
             turn=2, aliases=[])                  # "Odile" now names two characters: odile by id, this by name
    r, pr = plan(s.canon, parse("- Odile: hair = red")[0], turn=2)
    assert r == [] and pr and "no single character" in pr[0]["why"], "an ambiguous name is never guessed"
    r, pr = plan(s.canon, parse("- Odile Marsh: hair = red")[0], turn=2)
    assert r and r[0]["entity"] == "odile" and pr == [], "the full name still names exactly one"
    print("3. plan returns an author value where canon differs, a retraction where a wrong value is held, "
          "nothing otherwise; unknown and ambiguous names are reported, not guessed")


def test_it_is_idempotent():
    s = store()
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 1)
    say(s, "Corin", "identity.eyes", "set", "green", "his green eyes", 1)
    say(s, "Tamsin", "identity.marks", "add", "scar over her left eye", "a scar over her left eye", 1)
    corr = parse("""- Odile: hair = raven
- Corin: eyes is not green
- Tamsin: marks = tattoo of a heron
- Tamsin: marks is not scar over her left eye
- Finn: age = thirty""")[0]
    first, _ = write(s, corr)
    assert len(first) == 5, first
    n = len(s.ledger)
    again, _ = write(s, corr)
    assert again == [] and len(s.ledger) == n, "applying the corrections again wrote something"
    other = Store(s.dir)                                        # a reopen replays the same
    assert plan(other.canon, corr, turn=9)[0] == []
    print("4. applying the corrections twice writes nothing the second time (set, wrong, marks, a new slot)")


def test_authority_and_history():
    s = store()
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 1)
    write(s, parse("- Odile: hair = raven")[0])
    assert s.canon.current("odile", "identity.hair") == "raven"
    d = say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 5)
    assert d.status == "contradiction" and d.reason == "identity_locked", d
    assert s.canon.current("odile", "identity.hair") == "raven", "narration beat the author"
    iv = s.canon.history("odile", "identity.hair")
    assert [x["value"] for x in iv] == ["platinum", "raven"] and iv[1]["authority"] == "author"
    # a retraction empties the slot, and the story may then say what it is
    s2 = store()
    say(s2, "Corin", "identity.eyes", "set", "green", "his green eyes", 1)
    write(s2, parse("- Corin: eyes is not green")[0])
    assert s2.canon.current("corin", "identity.eyes") is None
    d = say(s2, "Corin", "identity.eyes", "set", "brown", "his brown eyes", 6)
    assert d.status == "commit" and s2.canon.current("corin", "identity.eyes") == "brown"
    h = s2.canon.history("corin", "identity.eyes")
    assert [x["value"] for x in h] == ["green", "brown"] and h[0]["end_id"] is not None, \
        "history keeps what was believed, closed by the retraction"
    print("5. the author's value outranks narration; a retraction empties the slot and the story can "
          "establish the real one; history is kept")


def test_a_refused_value_is_refused():
    s = store()
    corr = parse("- Odile: hair is not raven\n- Corin: marks is not scarred features\n"
                 "- Tamsin: hair = red\n- Finn: marks = scar on his chin")[0]
    ref = refusals(s.canon, corr)
    assert ref == {("odile", "identity.hair"): ["raven"], ("corin", "identity.marks"): ["scarred features"]}, ref
    d = say(s, "Odile", "identity.hair", "set", "raven", "her raven hair", 2, refused=ref)
    assert d.status == "reject" and d.reason == "author_refused", d
    assert s.canon.current("odile", "identity.hair") is None, "a refused value reached the ledger"
    d = say(s, "Odile", "identity.hair", "set", "black", "her black hair", 2, refused=ref)
    assert d.reason == "author_refused", "black is the same colour as raven, so it is refused too"
    d = say(s, "Odile", "identity.hair", "set", "auburn", "her auburn hair", 2, refused=ref)
    assert d.status == "commit" and s.canon.current("odile", "identity.hair") == "auburn", d
    d = say(s, "Tamsin", "identity.hair", "set", "raven", "her raven hair", 2, refused=ref)
    assert d.status == "commit", "another character's raven hair is not refused"
    d = say(s, "Corin", "identity.marks", "add", "scarred features", "his scarred features", 2, refused=ref)
    assert d.reason == "author_refused", d
    d = say(s, "Corin", "identity.marks", "add", "jagged scar over his eyebrow", "a jagged scar over his eyebrow",
            2, refused=ref)
    assert d.status == "commit", "a different mark is not refused"
    d = say(s, "Odile", "identity.eyes", "set", "raven", "her raven eyes", 3, refused=ref)
    assert d.reason != "author_refused", "the refusal is per slot"
    assert refusals(s.canon, parse("- Nobody: hair is not red")[0]) == {}
    print("6. a value the author called wrong is refused by the validator, for that character and slot only")


def test_the_card_applies_corrections_itself():
    s = store()
    say(s, "Finn", "identity.hair", "set", "black", "his black hair", 1)
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 1)
    say(s, "Corin", "identity.eyes", "set", "green", "his green eyes", 1)
    say(s, "Odile", "state.outfit", "add", "grey coat", "a grey coat", 2)
    say(s, "Odile", "identity.eyes", "set", "violet", "her violet eyes", 3)
    H = {i: content_hash(f"turn {i}") for i in (1, 2, 3)}
    snap = Snapshot(tuple(s.ledger.records), dict(H), 1, "finn")
    recent = ["Odile Marsh stepped in. Corin Hale watched her."]
    corr = parse("- Odile: hair = raven\n- Corin: eyes is not green")[0]
    plain = build_card(snap, H, recent, now=4)
    assert "hair: platinum" in plain.text and "eyes: green" in plain.text, plain.text
    got = build_card(snap, H, recent, now=4, corrections=corr)
    assert "hair: raven" in got.text and "platinum" not in got.text, got.text
    assert "eyes: green" not in got.text, "a retracted value reached the Writer"
    assert "eyes: violet" in got.text and "wearing grey coat" in got.text, "the rest of the card is unchanged"
    # a retry cut the ledger back to turn 2: whatever the reader had written at turn 3 is gone, but the
    # author's word is applied to the projection anyway
    cut = build_card(snap, {1: H[1], 2: H[2]}, recent, now=3, corrections=corr)
    assert "hair: raven" in cut.text and "platinum" not in cut.text and "eyes: green" not in cut.text, cut.text
    assert "eyes: violet" not in cut.text, "and the turn-3 fact stays cut"
    none = build_card(snap, H, recent, now=4, corrections=parse("- Nobody: hair = red")[0])
    assert none.text == plain.text, "a correction about nobody changed the card"
    print("7. the card shows the author's value and hides a retracted one, before the reader has written "
          "them and after an undo has cut them off")


def test_held_values():
    s = store()
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 1)
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 2)
    say(s, "Corin", "identity.eyes", "set", "green", "his green eyes", 2)
    say(s, "Tamsin", "identity.marks", "add", "tattoo of a heron", "a tattoo of a heron", 2)
    say(s, "Tamsin", "identity.marks", "add", "scar over her left eye", "a scar over her left eye", 2)
    write(s, parse("- Corin: eyes is not green\n- Odile: hair = raven")[0])
    rows = held_values(s.canon)
    by = {(r["who"], r["slot"], r["value"]): r for r in rows}
    assert ("Odile Marsh", "hair", "raven") in by and by[("Odile Marsh", "hair", "raven")]["by"] == "author"
    assert not any(r["slot"] == "eyes" for r in rows), "a retracted value is not held"
    assert ("Tamsin Reeve", "marks", "tattoo of a heron") in by and ("Tamsin Reeve", "marks", "scar over her left eye") in by
    assert [r["who"] for r in rows] == sorted((r["who"] for r in rows), key=str.lower)
    assert all(set(r) == {"who", "slug", "slot", "value", "since_turn", "confirmations", "by"} for r in rows)
    print("8. held_values lists the open identity values with whose word each is, and leaves out what was retracted")


def test_removing_a_line_releases_what_it_set():
    # a "=" line locked the value in as the author's; removing the line must let go, or the panel would show
    # "yours" next to no correction and the story could never say anything else about that slot
    s = store()
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 1)
    say(s, "Tamsin", "identity.marks", "add", "tattoo of a heron", "a tattoo of a heron", 1)
    write(s, parse("- Odile: hair = raven\n- Tamsin: marks = scar on her chin")[0])
    assert s.canon.current("odile", "identity.hair") == "raven"
    assert s.canon.current("tamsin", "identity.marks.scar-on-her-chin") == "scar on her chin"
    recs, _ = write(s, [])
    assert sorted((r["entity"], r["slot"], r["value"]) for r in recs) == \
        [("odile", "identity.hair", None), ("tamsin", "identity.marks.scar-on-her-chin", None)], recs
    assert s.canon.current("odile", "identity.hair") is None, "the author's value stayed after its line went"
    assert s.canon.current("tamsin", "identity.marks.tattoo-of-a-heron") == "tattoo of a heron", \
        "a value the story set was released with the author's"
    assert write(s, [])[0] == [], "releasing twice wrote something"
    d = say(s, "Odile", "identity.hair", "set", "auburn", "her auburn hair", 7)
    assert d.status == "commit" and s.canon.current("odile", "identity.hair") == "auburn", \
        "the slot was not free for the story afterwards"
    assert write(s, [])[0] == [], "the story's own value was released as if it were the author's"
    # the history keeps what was believed, closed by the release
    h = s.canon.history("odile", "identity.hair")
    assert [x["value"] for x in h] == ["platinum", "raven", "auburn"] and h[1]["end_id"] is not None, h

    # changing the value is a replacement, not a release followed by a second write
    s = store()
    write(s, parse("- Odile: hair = raven")[0], turn=1)
    recs, _ = write(s, parse("- Odile: hair = auburn")[0], turn=2)
    assert [(r["slot"], r["value"]) for r in recs] == [("identity.hair", "auburn")], recs
    assert s.canon.current("odile", "identity.hair") == "auburn"
    # a mark that is swapped for another: the old one goes and the new one comes
    write(s, parse("- Tamsin: marks = scar on her chin")[0], turn=2)
    recs, _ = write(s, parse("- Tamsin: marks = tattoo of a heron")[0], turn=3)
    assert sorted((r["slot"], r["value"]) for r in recs) == \
        [("identity.marks.scar-on-her-chin", None), ("identity.marks.tattoo-of-a-heron", "tattoo of a heron")], recs
    assert write(s, parse("- Tamsin: marks = tattoo of a heron")[0])[0] == []

    # an author value turned into "is not that value" is retracted ONCE: the retraction the wrong line plans
    # and the release of the value the old line set are the same act
    s = store()
    write(s, parse("- Odile: hair = raven")[0], turn=1)
    recs, _ = write(s, parse("- Odile: hair is not raven")[0], turn=2)
    assert [(r["slot"], r["value"]) for r in recs] == [("identity.hair", None)], recs
    assert s.canon.conflicts == [], "a second retraction found nothing to clear: " + str(s.canon.conflicts)

    # a retraction is not undone when its line is removed: the ledger no longer holds the value, and the
    # story may say it again if it is true
    s = store()
    say(s, "Corin", "identity.eyes", "set", "green", "his green eyes", 1)
    write(s, parse("- Corin: eyes is not green")[0])
    assert write(s, [])[0] == [] and s.canon.current("corin", "identity.eyes") is None
    d = say(s, "Corin", "identity.eyes", "set", "green", "his green eyes", 5)
    assert d.status == "commit" and s.canon.current("corin", "identity.eyes") == "green"

    # only this file's own words are released: an author edit that came another way stays
    s = store()
    s.append(kind="author_edit", entity="finn", slot="identity.age", value="thirty", authority="author",
             turn=1, span="a hand edit")
    s.append(kind="author_edit", entity="finn", slot="identity.hair", value="black", authority="author",
             turn=1, span="corrections.md")
    recs, _ = write(s, [])
    assert [(r["slot"], r["value"]) for r in recs] == [("identity.hair", None)], recs
    assert s.canon.current("finn", "identity.age") == "thirty"

    # a name that matches nobody shields nothing: a line about a character who has not appeared yet must not
    # hold up another line's release
    s = store()
    write(s, parse("- Odile: hair = raven")[0])
    recs, pr = write(s, parse("- Nobody: hair = red")[0])
    assert [(r["entity"], r["value"]) for r in recs] == [("odile", None)] and len(pr) == 1, (recs, pr)
    # but a name that now matches two characters shields both: it may be the line that set their value, and a
    # value must not be wiped by a guess
    s = store()
    write(s, parse("- Odile Marsh: hair = raven")[0])
    s.append(kind="entity_created", entity="odile-2", slot="character", value="Odile", authority="scenario",
             turn=2, aliases=[])                                   # "Odile" now answers to two characters
    recs, pr = write(s, parse("- Odile: eyes = grey")[0])
    assert recs == [] and len(pr) == 1 and s.canon.current("odile", "identity.hair") == "raven", (recs, pr)
    recs, _ = write(s, [])
    assert [(r["entity"], r["value"]) for r in recs] == [("odile", None)], "with no lines left, nothing shields it"
    print("9. removing a line releases what it set (and only that), a changed value is a replacement, a "
          "retraction is not undone, an unresolved name shields no one and an ambiguous one shields both")


def test_the_card_drops_a_released_value_at_once():
    s = store()
    say(s, "Odile", "identity.hair", "set", "platinum", "her platinum hair", 1)
    say(s, "Odile", "identity.eyes", "set", "violet", "her violet eyes", 1)
    write(s, parse("- Odile: hair = raven")[0])
    H = {1: content_hash("turn 1")}
    snap = Snapshot(tuple(s.ledger.records), dict(H), 1, "finn")
    recent = ["Odile Marsh stepped in."]
    held = build_card(snap, H, recent, now=2, corrections=parse("- Odile: hair = raven")[0])
    assert "hair: raven" in held.text, held.text
    gone = build_card(snap, H, recent, now=2, corrections=[])
    assert "raven" not in gone.text and "eyes: violet" in gone.text, \
        "the line is gone but the card still tells the Writer the author's value: " + gone.text
    assert "hair: raven" in build_card(snap, H, recent, now=2).text, \
        "no corrections argument means 'do not apply', so the ledger is shown as it is"
    print("10. with the last line removed the card drops the author's value before the reader has written the "
          "release, and a card built without corrections shows the ledger as it is")


try:
    for fn in (test_the_file, test_writing_a_line, test_plan_returns_only_what_is_needed, test_it_is_idempotent,
               test_authority_and_history, test_a_refused_value_is_refused,
               test_the_card_applies_corrections_itself, test_held_values,
               test_removing_a_line_releases_what_it_set, test_the_card_drops_a_released_value_at_once):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON CORRECTIONS TESTS PASSED")
