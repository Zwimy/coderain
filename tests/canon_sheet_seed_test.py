"""D-029: a character sheet the author wrote is the first write for that character's looks.

What broke (found by the first long soak, an invented story played through a local 4B Writer): a sheet said
"green eyes", the Writer's first narration said "dark", first write wins, and the card then told the Writer
"dark" for the rest of the story. The player's own file already seeded the protagonist (D-025); this does the
same for every character sheet, under one condition the reader decides (the story was brand new when it first
looked, see canon_shadow_test 21-22).

  1. sheet_looks reads only the text after a **Visual:** label, and stops at the next label
  2. no label, no looks: a sentence about a habit mentioning hair is not a trait
  3. "grey eyes and raven hair" gives raven, not "and raven" (the first sheet written in running prose lost
     its hair that way)
  4. seed_sheets writes scenario-authority facts per character, never for the player or an unknown entity
  5. it is safe to repeat, never overwrites an author edit, and replaces a narrated first write once
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-sheetseed-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from canon import Store                                                     # noqa: E402
from canon.replay import player_facts, seed_sheets, sheet_looks            # noqa: E402
from coderain.memory import Entry                                           # noqa: E402


def entry(slug, body, title=None):
    return Entry(title=title or slug.title(), slug=slug, aliases=[], body=body)


def store_with(*slugs):
    s = Store(WORK / f"s{len(os.listdir(WORK))}")
    for slug in slugs:
        s.append(kind="entity_created", entity=slug, slot="character", value=slug.title(),
                 authority="scenario", turn=1, aliases=[])
    return s


def test_sheet_looks_reads_the_visual_part_only():
    """1, 2."""
    body = "**Visual:** tall, with grey eyes. **Mentality:** wary, blue-eyed about money. **Voice:** low."
    assert sheet_looks(body) == "tall, with grey eyes.", sheet_looks(body)
    assert sheet_looks("**Visuals:** dark hair.") == "dark hair.", "the plural label is the same label"
    assert sheet_looks("She keeps her hair tied and has grey eyes.") == "", "no label, no looks"
    assert sheet_looks("") == "" and sheet_looks(None) == ""
    print("1-2. only the Visual part is read, and nothing without the label")


def test_running_prose_keeps_the_adjective():
    """3."""
    got = dict((s, v) for s, v, _q in player_facts("the courier, with grey eyes and raven hair."))
    assert got == {"identity.eyes": "grey", "identity.hair": "raven"}, got
    got2 = dict((s, v) for s, v, _q in player_facts("long black hair, green eyes"))
    assert got2["identity.hair"] == "long black" and got2["identity.eyes"] == "green", got2
    print("3. 'grey eyes and raven hair' gives raven; a real two-word value is kept")


def test_seed_sheets_scopes_and_authority():
    """4, 5."""
    s = store_with("odile", "finn")
    entries = [entry("odile", "**Visual:** with grey eyes and raven hair."),
               entry("finn", "**Visual:** with black hair."),
               entry("ghost", "**Visual:** with red hair."),                 # not in the ledger
               entry("plain", "No label here, red hair.")]
    wrote = seed_sheets(s, entries, player="finn", turn=2)
    assert set(wrote) == {"odile"}, wrote                                      # not the player, not an unknown one
    assert (s.canon.current("odile", "identity.eyes"), s.canon.current("odile", "identity.hair")) == ("grey", "raven")
    assert all(r.authority == "scenario" for r in s.ledger.records if r.slot.startswith("identity."))
    n = len(s.ledger)
    assert seed_sheets(s, entries, player="finn", turn=3) == {} and len(s.ledger) == n, "a repeat writes nothing"
    # an author edit is never overwritten; a narrated first write is replaced once
    s2 = store_with("odile")
    s2.append(kind="fact_established", entity="odile", slot="identity.eyes", value="brown", authority="author", turn=2)
    s2.append(kind="fact_established", entity="odile", slot="identity.hair", value="platinum", authority="narration", turn=2)
    seed_sheets(s2, entries[:1], turn=3)
    assert s2.canon.current("odile", "identity.eyes") == "brown", "the author's edit stands"
    assert s2.canon.current("odile", "identity.hair") == "raven", "the sheet outranks a narrated first write"
    # a narrated first write that already AGREES with the sheet is left as it is, not rewritten at a higher authority
    s3 = store_with("odile")
    s3.append(kind="fact_established", entity="odile", slot="identity.eyes", value="grey", authority="narration", turn=2)
    n3 = len(s3.ledger)
    seed_sheets(s3, entries[:1], turn=3)
    eyes = [r for r in s3.ledger.records[n3:] if r.slot == "identity.eyes"]
    assert eyes == [], "an agreeing narrated value needs no second record"
    print("4-5. per-character, never the player or an unknown name, repeat-safe, and authority is respected")


for fn in (test_sheet_looks_reads_the_visual_part_only, test_running_prose_keeps_the_adjective,
           test_seed_sheets_scopes_and_authority):
    fn()
print("ALL OK")
