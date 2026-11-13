"""A character's own name beats another character's alias.

What broke: the fold's alias union only sees the entry it is merging, so a model that wrote
one character's SLUG as another's alias ("tamsin-reeve" under a different woman) got it
kept. canon.validate.norm() reads that slug as the name "tamsin reeve", so the exact name
matched two entities, resolve_loose() called it ambiguous and returned nothing, and every
claim about the real Tamsin Reeve was refused as `unknown_entity` (28 refused claims for
one character in one soak, among them her eye colour, which the story had stated plainly).

 1) the own name wins over a stray alias that normalises to the same words
 2) a claim about that character is no longer refused, and lands on the right entity
 3) two entities with the SAME own name stay ambiguous (still a guess)
 4) two entities that only share an ALIAS stay ambiguous
 5) an alias that is nobody's own name still resolves to its owner, and a loose short
    name still resolves only when unique
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-alias-"))

from canon import Store                                    # noqa: E402
from canon.claims import Claim                             # noqa: E402
from canon.validate import resolve_loose, validate         # noqa: E402

_n = [0]


def _store(*people):
    _n[0] += 1
    s = Store(WORK / f"s{_n[0]}")
    for eid, name, aliases in people:
        s.append(kind="entity_created", entity=eid, slot="character", value=name,
                 authority="scenario", turn=0, aliases=list(aliases))
    return s


def test_own_name_beats_a_stray_alias():
    s = _store(("ines-bray", "Ines Bray", ["the ropewalker", "tamsin-reeve", "Ines"]),
               ("tamsin-reeve", "Tamsin Reeve", ["the tavern keeper", "Tamsin"]))
    assert resolve_loose(s.canon, "Tamsin Reeve") == "tamsin-reeve", "the true owner of the name lost"
    assert resolve_loose(s.canon, "tamsin reeve") == "tamsin-reeve"
    assert resolve_loose(s.canon, "Ines Bray") == "ines-bray"
    print("1. an entity's own name beats another entity's alias that reads the same")


def test_a_claim_about_her_is_kept():
    s = _store(("ines-bray", "Ines Bray", ["tamsin-reeve"]),
               ("tamsin-reeve", "Tamsin Reeve", []))
    prose = "Tamsin Reeve polishes a glass, her surprisingly sharp blue eyes on the door."
    claim = Claim("Tamsin Reeve", "identity.eyes", "set", "blue", "surprisingly sharp blue eyes", "high")
    d = validate(s.canon, [claim], prose, turn=1, next_id=len(s.ledger) + 1, create_unknown=False)[0]
    assert (d.status, d.reason, d.entity) == ("commit", "", "tamsin-reeve"), d
    print("2. a claim about her is committed to her, not refused as an unknown name")


def test_shared_own_names_and_shared_aliases_stay_ambiguous():
    s = _store(("corin-hale", "Corin Hale", []), ("corin-hale-2", "Corin Hale", []))
    assert resolve_loose(s.canon, "Corin Hale") is None, "two people with one name were guessed"
    t = _store(("odile", "Odile Marsh", ["the courier"]), ("ivo", "Ivo Dane", ["the courier"]))
    assert resolve_loose(t.canon, "the courier") is None, "a shared alias was guessed"
    print("3-4. the same own name twice, or the same alias twice, is still ambiguous")


def test_ordinary_resolution_is_unchanged():
    s = _store(("odile", "Odile Marsh", ["The Courier"]),
               ("corin", "Corin Hale", []), ("corin-2", "Corin Ash", []))
    assert resolve_loose(s.canon, "the courier") == "odile"
    assert resolve_loose(s.canon, "Odile") == "odile"
    assert resolve_loose(s.canon, "Corin") is None
    assert resolve_loose(s.canon, "Corin Ash") == "corin-2"
    print("5. aliases and short names resolve exactly as before")


try:
    for fn in (test_own_name_beats_a_stray_alias, test_a_claim_about_her_is_kept,
               test_shared_own_names_and_shared_aliases_stay_ambiguous,
               test_ordinary_resolution_is_unchanged):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCANON ALIAS COLLISION TESTS PASSED")
