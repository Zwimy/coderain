"""The card the Writer is shown, built from a snapshot of the shadow ledger (D-027).

This is the step that puts canon in front of the Writer, so the suite is about what
must NOT reach it. Each numbered assertion pins one promise:

 1) coverage: where the ledger stops being true and how many turns are unread. A turn
    that reads differently cuts the ledger back to the turn before it; a turn that no
    longer exists (a retry) cuts it back but leaves nothing unread
 2) nothing to show is said, not faked: no snapshot, an empty one, and a ledger with
    entities but no facts each give an empty card and a reason
 3) identity is always shown; state only when nothing is unread, because the last
    turns ride the prompt verbatim and a card with an older coat would contradict them
 4) a fact from a turn that is gone is never shown: after a retry the dropped reply's
    facts are absent and state still shows; after an edit of an old turn only identity
    from before it shows
 5) the cast: the player is pinned even when nobody is named, a character with no
    identity facts gets no line (an "unknown" invites invention), and one in another
    place is not shown
 6) bounded: whatever the budget, the card never exceeds it, and a character who does
    not fit is named, not dropped
 7) it is pure: the same input gives the same card, and a snapshot is not changed by
    the live ledger growing after it was taken
 8) the reader and the card use one hash function
 9) a look is shown only when it matters (absent from the recent turns, asked about, contradicted) and
    left out and counted otherwise
"""
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-card-"))

from canon import Store                                                    # noqa: E402
from canon.card import (IDENTITY_HEADER, Card, Snapshot, build_card,        # noqa: E402
                        content_hash, coverage)
from canon.claims import Claim                                              # noqa: E402
from canon.scene import CARD_HEADER                                         # noqa: E402
from canon.validate import commit, validate                                 # noqa: E402

_n = [0]
PEOPLE = [("finn", "Finn", []), ("odile", "Odile Marsh", ["The Courier"]),
          ("corin", "Corin Hale", []), ("tamsin", "Tamsin Reeve", []),
          ("ansel", "Ansel", [])]


def store(people=PEOPLE):
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for slug, name, aliases in people:
        s.append(kind="entity_created", entity=slug, slot="character", value=name,
                 authority="scenario", turn=0, aliases=list(aliases))
    return s


def say(s, who, slot, op, value, quote, turn):
    c = Claim(who, slot, op, value, quote, "high")
    ds = validate(s.canon, [c], f"{who} stood there, {quote}.", turn=turn,
                  next_id=len(s.ledger) + 1, create_unknown=False)
    commit(s, ds)
    assert ds[0].status == "commit", (who, slot, value, ds[0].status, ds[0].reason)


def hashes(*turns):
    return {i: content_hash(f"turn {i}") for i in turns}


def snap(s, processed, first=1, player="finn"):
    return Snapshot(tuple(s.ledger.records), dict(processed), first, player)


RECENT = ["Odile Marsh stepped in. Corin Hale watched her."]


def story():
    """Finn (the player) and three people, with facts arriving over three turns."""
    s = store()
    say(s, "Finn", "identity.hair", "set", "black", "his black hair", 1)
    say(s, "Odile", "identity.hair", "set", "raven", "her raven hair", 1)
    say(s, "Corin", "identity.eyes", "set", "grey", "his grey eyes", 1)
    say(s, "Odile", "state.outfit", "add", "grey coat", "a grey coat", 2)
    say(s, "Tamsin", "state.held", "add", "lantern", "a lantern", 2)
    say(s, "Tamsin", "identity.hair", "set", "red", "her red hair", 3)
    say(s, "Tamsin", "state.outfit", "add", "red cloak", "a red cloak", 3)
    return s


def test_coverage():
    s = story()
    p = snap(s, hashes(1, 2, 3))
    assert coverage(p, hashes(1, 2, 3)) == (3, 0), "caught up"
    assert coverage(p, hashes(1, 2, 3, 4)) == (3, 1), "one new turn not read yet"
    changed = {**hashes(1, 2, 3), 2: content_hash("an edited turn 2")}
    assert coverage(p, changed) == (1, 2), \
        "an edit of turn 2 cuts the ledger back to turn 1 and leaves 2 and 3 unread"
    assert coverage(p, hashes(1, 2)) == (2, 0), \
        "a retry removed turn 3: the ledger is cut back, and nothing is unread"
    assert coverage(p, hashes(1, 2, 4)) == (2, 1), \
        "turn 3 replaced by a different one at the same place is unread, 4 too"
    late = snap(s, hashes(3), first=3)
    assert coverage(late, hashes(1, 2, 3)) == (3, 0), "turns before the first one read never count"
    assert coverage(snap(s, {}, first=None), hashes(1, 2)) == (0, 2)
    print("1. coverage: an edit cuts the ledger back and leaves the rest unread; a retry cuts "
          "it back with nothing unread; turns before the first read do not count")


def test_nothing_to_show_is_said():
    for p in (None, Snapshot((), {}, None, None)):
        c = build_card(p, hashes(1), RECENT, now=2)
        assert c.text == "" and c.reason == "not_ready", c
    empty = store()
    c = build_card(snap(empty, hashes(1)), hashes(1), RECENT, now=2)
    assert c.text == "" and c.reason == "nothing_to_say", c
    bare = Snapshot((), hashes(1), 1, None)
    c = build_card(bare, hashes(1), RECENT, now=2)
    assert c.text == "" and c.reason == "no_canon", c
    print("2. no snapshot, an empty one, or a ledger with no facts gives no card and says why")


def test_identity_always_state_only_when_caught_up():
    s = story()
    p = snap(s, hashes(1, 2, 3))
    full = build_card(p, hashes(1, 2, 3), RECENT, now=4)
    assert full.state is True and full.unread == 0 and full.reason == ""
    assert full.text.startswith(IDENTITY_HEADER) and CARD_HEADER in full.text, full.text
    assert "raven hair" in full.text and "grey eyes" in full.text
    assert "wearing grey coat" in full.text, full.text
    behind = build_card(p, hashes(1, 2, 3, 4), RECENT, now=5)
    assert behind.state is False and behind.unread == 1
    assert "raven hair" in behind.text and "grey eyes" in behind.text, "identity does not change"
    assert "wearing" not in behind.text and "holding" not in behind.text \
        and CARD_HEADER not in behind.text, \
        "state shown while a newer turn was unread would contradict what the Writer can read"
    off = build_card(p, hashes(1, 2, 3), RECENT, now=4, state=False)
    assert off.state is False and "raven hair" in off.text and CARD_HEADER not in off.text
    print("3. identity is always shown; state only when nothing is unread, and never when "
          "the config says identity only")


def test_a_discarded_turn_is_never_shown():
    s = story()
    p = snap(s, hashes(1, 2, 3))
    both = ["Odile Marsh stepped in. Tamsin Reeve waited. Corin Hale watched."]
    with_3 = build_card(p, hashes(1, 2, 3), both, now=4)
    assert "red hair" in with_3.text and "wearing red cloak" in with_3.text, with_3.text
    # a retry removed turn 3: what the dropped reply stated must not reach the Writer
    retry = build_card(p, hashes(1, 2), both, now=3)
    assert "red" not in retry.text, retry.text
    assert retry.state is True, "nothing is unread after a retry, so state is safe"
    assert "wearing grey coat" in retry.text and "holding lantern" in retry.text, retry.text
    assert retry.trusted_through == 2 and retry.unread == 0
    # an edit of turn 2: only what turn 1 established may be shown, and no state at all
    edited = {**hashes(1, 2, 3), 2: content_hash("edited")}
    cut = build_card(p, edited, both, now=4)
    assert "raven hair" in cut.text and "grey eyes" in cut.text, cut.text
    assert "grey coat" not in cut.text and "lantern" not in cut.text and "red" not in cut.text, cut.text
    assert cut.state is False and cut.trusted_through == 1 and cut.unread == 2
    print("4. a retry drops the discarded reply's facts and keeps state; an edit keeps only "
          "what came before it and no state")


def test_the_cast():
    s = story()
    p = snap(s, hashes(1, 2, 3))
    quiet = build_card(p, hashes(1, 2, 3), ["The street was quiet."], now=4)
    assert quiet.cast[:1] == ("finn",), quiet.cast
    assert "Finn: black hair" in quiet.text, quiet.text
    assert "Ansel" not in quiet.text, "a character with no identity facts gets no line"
    assert "unknown" not in quiet.text.lower()
    named = build_card(p, hashes(1, 2, 3), ["Ansel nodded. Odile Marsh smiled."], now=4)
    assert "ansel" in named.cast and "Ansel" not in named.text.split(CARD_HEADER)[0], \
        "named but with nothing known: in the cast, no identity line"
    unpinned = build_card(Snapshot(p.records, p.hashes, p.first, None), hashes(1, 2, 3),
                          ["The street was quiet."], now=4)
    assert unpinned.cast == () and unpinned.reason == "nothing_to_say", unpinned
    print("5. the player is pinned though nobody names them; no line for a character with "
          "nothing known; nobody appears from nowhere")


def test_bounded():
    rng = random.Random(7)
    people = [(f"p{i}", f"Person{chr(65 + i)} Long{chr(97 + i)}", []) for i in range(9)]
    s = store([("finn", "Finn", []), *people])
    say(s, "Finn", "identity.hair", "set", "black", "his black hair", 1)
    colours = ["raven", "grey", "red", "silver", "brown", "golden", "white", "auburn", "ginger"]
    for i, (slug, name, _a) in enumerate(people):       # turn 1 first: a ledger never goes back
        first = name.split()[0]
        say(s, first, "identity.hair", "set", colours[i], f"her {colours[i]} hair", 1)
        say(s, first, "identity.eyes", "set", "green", "her green eyes", 1)
        say(s, first, "identity.marks", "add", "scar over her left eye", "a scar over her left eye", 1)
    for slug, name, _a in people:
        first = name.split()[0]
        say(s, first, "state.outfit", "add", "grey coat", "a grey coat", 2)
        say(s, first, "state.held", "add", "brass lantern", "a brass lantern", 2)
    names = ". ".join(n.split()[0] for _s, n, _a in people) + "."
    p = snap(s, hashes(1, 2))
    shown_footer, tight = 0, 0
    # A fine sweep, so some budget lands just short of the next line and the "not shown"
    # line has to fit in what is left (a coarse one never meets that case).
    for max_chars in list(range(600, 4001, 53)) + [600, 4000]:
        for state in (True, False):
            for turns in (hashes(1, 2), hashes(1, 2, 3)):
                c = build_card(p, turns, [names], now=3, max_chars=max_chars, state=state, limit=10)
                assert len(c.text) <= max_chars, (max_chars, state, len(c.text))
                if c.text:
                    assert c.text.startswith(IDENTITY_HEADER), c.text[:80]
                shown_footer += "not shown for space" in c.text
                tight += "not shown for space" in c.text and len(c.text) > max_chars - 60
    assert shown_footer, "at the smaller budgets somebody must have been named instead of shown"
    assert tight, "the sweep never put the footer against the cap, so it proves nothing about it"
    # Below the header plus an honest footer there is room for neither: nothing, not an overrun.
    # Three short names make the footer its long form, the case that overruns.
    trio = "PersonA, PersonB and PersonC waited."
    for cap in (100, 140, 157):
        tiny = build_card(p, hashes(1, 2), [trio], now=3, max_chars=cap, state=False, limit=10)
        assert len(tiny.text) <= cap, (cap, len(tiny.text), tiny.text)
    print("6. whatever the budget the card never exceeds it, and a character who does not fit "
          "is named")


def test_pure_and_isolated_from_the_live_ledger():
    s = story()
    p = snap(s, hashes(1, 2, 3))
    n = len(s.ledger)
    a = build_card(p, hashes(1, 2, 3), RECENT, now=4)
    b = build_card(p, hashes(1, 2, 3), RECENT, now=4)
    assert a == b and len(s.ledger) == n and p.records == tuple(s.ledger.records)
    say(s, "Odile", "state.outfit", "add", "blue scarf", "a blue scarf", 4)
    say(s, "Corin", "identity.hair", "set", "white", "his white hair", 4)
    c = build_card(p, hashes(1, 2, 3), RECENT, now=4)
    assert c == a, "the snapshot changed when the live ledger grew"
    assert "blue scarf" not in c.text and "white" not in c.text
    assert isinstance(a, Card) and a.row()["chars"] == len(a.text) and "text" not in a.row()
    print("7. the same input gives the same card, and a snapshot does not change when the "
          "live ledger grows; the log row holds counts, never the text")


def test_one_hash_for_both_sides():
    import coderain.canon_shadow as shadow_mod
    assert shadow_mod._hash is content_hash
    assert content_hash("x") == content_hash("x") != content_hash("y") and len(content_hash("x")) == 20
    print("8. the reader and the card compare turns with one hash function")


def test_a_look_is_shown_only_when_it_matters():
    """9. The card restores what scrolled out of context and corrects drift; it does not offer every look every
    turn (first soak: that made a 4B Writer restate looks about ten times as often as without the card)."""
    s = story()
    p = snap(s, hashes(1, 2, 3))
    plain = build_card(p, hashes(1, 2, 3), RECENT, now=4)
    assert "raven hair" in plain.text and "grey eyes" in plain.text and plain.hidden == 0
    # the recent turns name Odile and Corin and say nothing against canon: their looks are left out, and counted
    window = ["Odile Marsh stepped in, her raven hair damp.", "Corin Hale shrugged. Finn waited."]
    got = build_card(p, hashes(1, 2, 3), RECENT, now=4, visible=window, action="I wait.")
    assert "raven hair" not in got.text and "grey eyes" not in got.text and "black hair" not in got.text, got.text
    assert got.hidden == 3 and got.row()["hidden"] == 3, got.hidden
    assert IDENTITY_HEADER not in got.text and CARD_HEADER in got.text, "no identity header when nothing is shown"
    # someone not named in the recent turns is shown (Tamsin is in the scene, the Writer has nothing recent)
    away = build_card(p, hashes(1, 2, 3), ["Tamsin Reeve ran in."], now=4, visible=window, action="I wait.")
    assert "red hair" in away.text and "raven hair" not in away.text, away.text
    # the player asks about a look: that character's looks are shown
    asked = build_card(p, hashes(1, 2, 3), RECENT, now=4, visible=window, action="I study Odile Marsh's hair.")
    assert "raven hair" in asked.text and "grey eyes" not in asked.text, asked.text
    # the recent turns say a different colour: the card corrects it
    drift = build_card(p, hashes(1, 2, 3), RECENT, now=4,
                       visible=["Odile Marsh stepped in, her red hair damp.", "Corin Hale shrugged."], action="I wait.")
    assert "raven hair" in drift.text and "grey eyes" not in drift.text, drift.text
    for action in ("I wait.", "Odile Marsh waits."):
        assert build_card(p, hashes(1, 2, 3), RECENT, now=4, visible=(), action=action).text == plain.text, \
            "no window known: nothing is hidden, even for someone the action names"
    print("9. a look is shown when the character is absent, asked about or contradicted, and left out and counted otherwise")


try:
    for fn in (test_coverage, test_nothing_to_show_is_said,
               test_identity_always_state_only_when_caught_up,
               test_a_discarded_turn_is_never_shown, test_the_cast, test_bounded,
               test_pure_and_isolated_from_the_live_ledger, test_one_hash_for_both_sides,
               test_a_look_is_shown_only_when_it_matters):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON CARD TESTS PASSED")
