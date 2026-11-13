"""Evaluation corpus for the Scribe: hand-written, exhaustively labelled, invented.

Every case lists ALL the slot facts its text states, so precision is meaningful: a
claim that is not in the label is a false positive. The labels are deliberately
about the closed slot list in canon.claims, so a fact outside it (a ribbon, a
beard) is simply not stated in these texts.

Groups:
  identity   stable traits stated plainly
  state      things that change: clothing, carried items, injuries, place, mood
  multi      two or more characters in one passage (attribution)
  trap       passages that look like they state something and do not: hypotheticals,
             dreams, wishes, similes, plans, the reader, an ambiguous pronoun.
             The right answer is no claim.

`split` is dev or test. Tune prompts against dev only, and report test, so a prompt
that merely fits the corpus is not mistaken for one that works.

PAIRS are two-passage sequences for the validator rather than the Scribe: a
restatement must NOT contradict, a changed identity MUST, and a new slot is novelty.
"""
from __future__ import annotations

from dataclasses import dataclass

# id, name, aliases. Four characters, two women and two men, named so a pronoun
# usually has one plausible referent.
ROSTER = [
    ("odile", "Odile Marsh", ["The Courier"]),
    ("corin", "Corin Hale", []),
    ("tamsin", "Tamsin Reeve", []),
    ("ansel", "Ansel", []),
]


@dataclass(frozen=True)
class Truth:
    entity: str
    slot: str
    op: str
    value: str          # regex: any acceptable wording of the value
    evidence: str       # words that really appear in the text


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    split: str
    text: str
    truth: tuple[Truth, ...] = ()


def T(entity, slot, op, value, evidence):
    return Truth(entity, slot, op, value, evidence)


CASES: list[Case] = [
    # --- identity -----------------------------------------------------------
    Case("id-1", "identity", "dev",
         "Odile Marsh stepped out of the rain. Her long raven hair was plastered to "
         "her cheeks, and her grey eyes searched the empty street.",
         (T("odile", "identity.hair", "set", r"raven", "Her long raven hair"),
          T("odile", "identity.eyes", "set", r"gr[ae]y", "her grey eyes"))),
    Case("id-2", "identity", "test",
         "Corin Hale was a broad-shouldered man of about fifty.",
         (T("corin", "identity.build", "set", r"broad", "broad-shouldered man"),
          T("corin", "identity.age", "set", r"fifty", "about fifty"))),
    Case("id-3", "identity", "dev",
         "Tamsin grinned. A thin white scar ran from her left ear to the corner of "
         "her mouth.",
         (T("tamsin", "identity.marks", "add", r"scar",
            "A thin white scar ran from her left ear"),)),
    Case("id-4", "identity", "test",
         "Ansel was barely sixteen, small for his age, with a mop of ginger hair.",
         (T("ansel", "identity.age", "set", r"sixteen", "barely sixteen"),
          T("ansel", "identity.build", "set", r"small", "small for his age"),
          T("ansel", "identity.hair", "set", r"ginger", "a mop of ginger hair"))),
    Case("id-5", "identity", "dev",
         "Odile waited by the door. She had green eyes that missed nothing and dark "
         "curls cut short.",
         (T("odile", "identity.eyes", "set", r"green", "green eyes that missed nothing"),
          T("odile", "identity.hair", "set", r"dark|curl", "dark curls cut short"))),
    Case("id-6", "identity", "test",
         "Corin pushed up his sleeve, showing a black raven tattooed on his forearm.",
         (T("corin", "identity.marks", "add", r"raven|tattoo",
            "a black raven tattooed on his forearm"),)),
    # --- accessories (D-044): jewellery and ornaments worn on the person -----------
    Case("ac-1", "accessory", "dev",
         "Odile Marsh bent over the map. Her hair was pinned up with gold hairpins, "
         "and a silver ring shone on her finger.",
         (T("odile", "identity.accessories", "add", r"hairpins", "pinned up with gold hairpins"),
          T("odile", "identity.accessories", "add", r"ring", "a silver ring shone on her finger"))),
    Case("ac-2", "accessory", "test",
         "Ansel wore round glasses that kept sliding down his nose, and a jade pendant "
         "hung at his throat.",
         (T("ansel", "identity.accessories", "add", r"glasses", "wore round glasses"),
          T("ansel", "identity.accessories", "add", r"pendant", "a jade pendant hung at his throat"))),
    Case("ac-3", "accessory", "dev",
         "Tamsin turned, and the jade beads threaded through her braids clicked softly.",
         (T("tamsin", "identity.accessories", "add", r"beads", "the jade beads threaded through her braids"),)),
    Case("ac-4", "accessory", "test",
         "Corin Hale wore a gold hoop in his left ear and a scowl on his face.",
         (T("corin", "identity.accessories", "add", r"hoop", "wore a gold hoop in his left ear"),)),
    # --- state --------------------------------------------------------------
    Case("st-1", "state", "dev",
         "Odile shrugged off her wet coat and hung it by the door.",
         (T("odile", "state.outfit", "remove", r"coat", "shrugged off her wet coat"),)),
    Case("st-2", "state", "test",
         "Tamsin pulled on a heavy wool cloak and tied it at her throat.",
         (T("tamsin", "state.outfit", "add", r"cloak", "pulled on a heavy wool cloak"),)),
    Case("st-3", "state", "dev",
         "Corin picked up the lantern and checked the oil.",
         (T("corin", "state.held", "add", r"lantern", "picked up the lantern"),)),
    Case("st-4", "state", "test",
         "Ansel dropped the knife and it clattered on the stones.",
         (T("ansel", "state.held", "remove", r"knife", "dropped the knife"),)),
    Case("st-5", "state", "dev",
         "Odile limped across the room, her left ankle swollen and purple.",
         (T("odile", "state.injury", "add", r"ankle swollen|swollen|ankle", "her left ankle swollen and purple"),)),
    Case("st-6", "state", "test",
         "Tamsin crossed the market square and ducked into the chandler's shop.",
         (T("tamsin", "state.location", "set", r"chandler",
            "ducked into the chandler's shop"),)),
    Case("st-7", "state", "dev",
         "Corin was furious. He slammed the ledger shut.",
         (T("corin", "state.mood", "set", r"furious", "Corin was furious"),)),
    Case("st-8", "state", "test",
         "The cut on Ansel's palm had finally closed; it was only a pink line now.",
         (T("ansel", "state.injury", "remove", r"cut",
            "The cut on Ansel's palm had finally closed"),)),
    # --- multi-character ----------------------------------------------------
    Case("mu-1", "multi", "dev",
         "Odile wore a red scarf, and Tamsin wore a green scarf.",
         (T("odile", "state.outfit", "add", r"red scarf", "Odile wore a red scarf"),
          T("tamsin", "state.outfit", "add", r"green scarf", "Tamsin wore a green scarf"))),
    Case("mu-2", "multi", "test",
         "Corin's hair was iron grey; Ansel's was the colour of straw.",
         (T("corin", "identity.hair", "set", r"gr[ae]y", "Corin's hair was iron grey"),
          T("ansel", "identity.hair", "set", r"straw", "the colour of straw"))),
    Case("mu-3", "multi", "dev",
         "Tamsin stood by the window. Odile sat in the corner, her right arm in a sling.",
         (T("tamsin", "state.location", "set", r"window", "Tamsin stood by the window"),
          T("odile", "state.injury", "add", r"arm in a sling|sling|arm", "her right arm in a sling"))),
    Case("mu-4", "multi", "test",
         "Corin and Ansel waited at the gate. Corin held a torch while Ansel "
         "stamped his feet against the cold.",
         (T("corin", "state.held", "add", r"torch", "Corin held a torch"),)),
    # --- traps: the right answer is no claim ---------------------------------
    Case("tr-1", "trap", "dev",
         "\"We leave at dawn,\" Corin said. \"Bring food, and say nothing to the "
         "guards.\""),
    Case("tr-2", "trap", "test",
         "If Odile had a scar, she would hide it under her hair. She did not like to "
         "think about it."),
    Case("tr-3", "trap", "dev",
         "The sea was as grey as Tamsin's mood, and just as restless."),
    Case("tr-4", "trap", "test",
         "Ansel wished he had his brother's broad shoulders and dark curls."),
    Case("tr-5", "trap", "dev",
         "In the dream, Odile's hair was gold and she wore a crown of ice."),
    Case("tr-6", "trap", "test",
         "Corin planned to wear the captain's coat to the feast."),
    Case("tr-7", "trap", "dev",
         "You notice your own hands are cold, your coat soaked through."),
    Case("tr-8", "trap", "test",
         "Odile met Tamsin at the bridge. She wore a yellow cloak."),
    # ornament look-alikes (D-044): a liquid, an ornament being taken off, other meanings of the word
    Case("tr-9", "trap", "dev",
         "Beads of sweat ran down Corin's brow as he hauled the net."),
    Case("tr-10", "trap", "test",
         "Odile took off her ring and dropped it into the dish by the door."),
    Case("tr-11", "trap", "dev",
         "A ring of men stood around the pit while the glasses on the bar rattled."),
]


# The passages added with the accessory slot (D-044). The report scores everything else as the "legacy" slice, so a
# run with and without the slot can be compared on exactly the passages that existed before it.
D044_IDS = frozenset({"ac-1", "ac-2", "ac-3", "ac-4", "tr-9", "tr-10", "tr-11"})


@dataclass(frozen=True)
class Pair:
    id: str
    kind: str           # restate | contradict | novel
    entity: str
    slot: str           # the claim slot the probe is about (identity.marks matches any mark)
    setup: str
    probe: str
    # The slot the SETUP establishes, when it differs from the probe's. A novel
    # fact is by definition about a slot the setup left empty.
    setup_slot: str = ""


PAIRS: list[Pair] = [
    # A restatement in other words must corroborate, never contradict.
    Pair("re-1", "restate", "odile", "identity.hair",
         "Odile Marsh's raven hair was braided down her back.",
         "Odile undid the braid, and her black hair fell loose around her shoulders."),
    Pair("re-2", "restate", "corin", "identity.eyes",
         "Corin Hale's green eyes missed nothing.",
         "Corin's emerald eyes narrowed at the stranger."),
    Pair("re-3", "restate", "tamsin", "identity.hair",
         "Tamsin Reeve had ginger hair she kept cropped short.",
         "Tamsin ran a hand through her red hair."),
    Pair("re-4", "restate", "ansel", "identity.eyes",
         "Ansel's grey eyes were wide with fear.",
         "Ansel's gray eyes darted to the door."),
    Pair("re-5", "restate", "odile", "identity.hair",
         "Odile Marsh's long blonde hair was tied with twine.",
         "Odile's golden hair caught the light."),
    Pair("re-6", "restate", "corin", "identity.hair",
         "Corin Hale's brown hair was thinning at the crown.",
         "Corin's chestnut hair was streaked with ash."),
    # A changed identity value MUST be flagged: this is the drift being caught.
    Pair("co-1", "contradict", "corin", "identity.eyes",
         "Corin Hale's grey eyes held hers.",
         "Corin's brown eyes crinkled as he laughed."),
    Pair("co-2", "contradict", "odile", "identity.hair",
         "Odile Marsh's raven hair was braided down her back.",
         "Odile's blonde hair fell across her face."),
    Pair("co-3", "contradict", "tamsin", "identity.hair",
         "Tamsin Reeve's ginger hair was tied back.",
         "Tamsin's silver hair gleamed in the moonlight."),
    # A fact about a slot that was empty is novelty and must be accepted.
    Pair("no-1", "novel", "tamsin", "identity.eyes",
         "Tamsin Reeve's red hair was tied up.",
         "Tamsin's eyes were a pale blue.", setup_slot="identity.hair"),
    Pair("no-2", "novel", "ansel", "identity.hair",
         "Ansel was barely sixteen.",
         "Ansel's mop of ginger hair stuck out in every direction.",
         setup_slot="identity.age"),
    Pair("no-3", "novel", "corin", "identity.marks",
         "Corin Hale's grey eyes held hers.",
         "A thin scar ran across Corin's knuckles.", setup_slot="identity.eyes"),
]
