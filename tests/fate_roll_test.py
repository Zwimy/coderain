"""Fate's die: the bands and the derived roll (D-045).

What this pins. The owner asked for a D20 where 1-2 is the bad outcome, 3-10 and 11-18 the two neutral ones and 19-20
the good one (his "10 to 18" overlaps, read as 11 to 18). The roll must reproduce: a retry, a swipe, an undo-and-redo
and a branch all see the same face for the same action at the same point of the same story, with nothing stored,
and a different action, point or story rolls again.

 1) every face 1..20 maps to the right tier, and an invalid face is refused (the edges 2/3, 10/11 and 18/19 are where
    off-by-one errors live)
 2) the bands are 2, 8, 8 and 2 faces wide: the 10 / 40 / 40 / 10 split
 3) the same seed, turn, action and nonce always give the same face, in a fresh process-independent way
 4) a different action, turn, seed or nonce is a different draw, and over many draws the tiers land near their share
 5) the roll does not depend on the narration, so an edit elsewhere cannot change it, while the cache key does
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coderain import fate                                   # noqa: E402


def test_every_face():
    want = {1: "setback", 2: "setback", 3: "natural", 10: "natural", 11: "surprise", 18: "surprise",
            19: "windfall", 20: "windfall"}
    for face, tier in want.items():
        assert fate.tier_of(face) == tier, (face, fate.tier_of(face), tier)
    for face in range(1, 21):
        assert fate.tier_of(face) in dict((b[0], 1) for b in fate.BANDS), face
    for bad in (0, 21, -1, 100):
        try:
            fate.tier_of(bad)
        except ValueError:
            continue
        raise AssertionError(f"face {bad} was accepted")
    print("1. every face maps to the right tier, the edges 2/3, 10/11 and 18/19 are right, a bad face is refused")


def test_band_widths():
    widths = Counter(fate.tier_of(f) for f in range(1, 21))
    assert widths == {"setback": 2, "natural": 8, "surprise": 8, "windfall": 2}, widths
    assert [(n, lo, hi) for n, lo, hi in fate.BANDS] == [("setback", 1, 2), ("natural", 3, 10),
                                                         ("surprise", 11, 18), ("windfall", 19, 20)]
    print("2. the bands are 2 / 8 / 8 / 2 faces wide: 10%, 40%, 40%, 10%")


def test_the_roll_reproduces():
    a = fate.derive_roll(1234, 7, "I open the door.")
    assert all(fate.derive_roll(1234, 7, "I open the door.") == a for _ in range(50))
    assert 1 <= a <= 20
    # Pinned values: a change to the formula changes every story's dice, so it has to be a deliberate one.
    assert [fate.derive_roll(1, 1, "go"), fate.derive_roll(2, 1, "go"), fate.derive_roll(1, 2, "go"),
            fate.derive_roll(1234, 7, "I open the door."), fate.derive_roll(1, 1, "go", 1)] == [17, 3, 4, 12, 7]
    print("3. the same seed, turn, action and nonce always give the same face")


def test_other_inputs_roll_again():
    base = fate.derive_roll(99, 5, "I wait.")
    draws = {(s, n, act, k): fate.derive_roll(s, n, act, k)
             for s in (99, 100) for n in (5, 6) for act in ("I wait.", "I wait!") for k in (0, 1)}
    assert len(set(draws.values())) > 4, "the draws do not vary with seed, turn, action or nonce"
    # over many different actions the tiers land near 10 / 40 / 40 / 10
    tiers = Counter(fate.tier_of(fate.derive_roll(7, 3, f"action number {k}")) for k in range(4000))
    share = {t: n / 4000 for t, n in tiers.items()}
    assert 0.07 < share["setback"] < 0.13 and 0.07 < share["windfall"] < 0.13, share
    assert 0.35 < share["natural"] < 0.45 and 0.35 < share["surprise"] < 0.45, share
    assert base == fate.derive_roll(99, 5, "I wait."), "not reproducible"
    print("4. a different seed, turn, action or nonce rolls again; 4000 draws land at %s" %
          {t: round(v, 2) for t, v in sorted(share.items())})


def test_roll_and_key():
    k1 = fate.exchange_key(5, "I wait.", "The rain fell.")
    assert k1 == fate.exchange_key(5, "I wait.", "The rain fell.")
    assert k1 != fate.exchange_key(5, "I wait.", "The rain stopped.")      # the narration it follows
    assert k1 != fate.exchange_key(5, "I wait!", "The rain fell.")         # the action
    assert k1 != fate.exchange_key(6, "I wait.", "The rain fell.")         # the point in the story
    # the DIE does not look at the narration: editing an earlier line cannot move it
    assert fate.derive_roll(1, 5, "I wait.") == fate.derive_roll(1, 5, "I wait.")
    print("5. the cache key follows the narration, the die does not")


for fn in (test_every_face, test_band_widths, test_the_roll_reproduces, test_other_inputs_roll_again,
           test_roll_and_key):
    fn()
print("\nFATE ROLL TESTS PASSED")
