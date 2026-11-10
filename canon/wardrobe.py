"""What a garment is, and which garments cannot be worn together.

One vocabulary serves two rules, so they cannot disagree:

  * ENTRY (shape.py): an outfit item has to be something worn. The real-save gate found
    outfit lists full of a plume of smoke, a teacup, tattoos, bare feet and a stripe
    of rain, because the Scribe files whatever the sentence mentions. A real garment
    always has a garment noun in its phrase ("charcoal dress", "folded pair of black
    shorts"), so that is what is required.
  * SUPERSESSION (validate.py): a person wears one pair of boots. The Scribe almost
    never says a garment was taken off (6 removals in 1,646 turns), so lists only grew.
    A new garment of an exclusive kind replaces the old one of that kind, by rule, and
    the ledger keeps the old one as history.

The categories are plain English clothing, not this story's words. They are a model of
how people dress, and it is wrong in known ways: a hoodie over a tee is two layers
here counted as one top, and a coat picked up to carry replaces the one worn. Those
errors cost one item on a card, and a list that never lets go costs the whole card.
"""
from __future__ import annotations

import re

_WORDS = {
    "top": """shirt shirts tee tees tshirt blouse sweater sweatshirt hoodie hoody jersey top
              tops tank camisole tunic polo pullover cardigan""",
    "bottom": """pants trousers jeans shorts skirt skirts leggings slacks joggers sweatpants
                 trunks chinos khakis""",
    "full": """dress gown bodysuit jumpsuit suit uniform robe kimono cheongsam happi gi
               overalls swimsuit bikini leotard coverall catsuit sundress onesie towel
               fatigues scrubs nightgown nightdress pajamas pyjamas sarong kilt tuxedo sari
               dungarees smock""",
    "outer": """coat jacket cloak cape parka blazer raincoat trench poncho windbreaker
                overcoat vest waistcoat shawl""",
    "footwear": """boots boot shoes shoe sneakers sneaker sandals sandal heels trainers
                   slippers loafers flats clogs""",
    "legwear": "socks sock stockings tights hosiery",
    "headwear": "hat cap hood beanie helmet headband bandana turban cowl",
    "under": """bra panties underwear thong boxers lingerie briefs undies knickers corset slip
                chemise negligee""",
    "hands": "gloves glove mitts wraps gauntlets",
    # worn together with the kinds above
    "neck": "scarf choker necklace collar tie bowtie pendant",
    "face": "mask glasses goggles shades sunglasses spectacles visor",
    "waist": "belt sash harness holster apron",
    "jewellery": """ring rings bracelet bracelets earring earrings watch bangle anklet beads
                    hairpin hairpins barrette barrettes hairclip hairband scrunchie""",
}
CATEGORY = {w: cat for cat, words in _WORDS.items() for w in words.split()}

# One of these at a time. A "full" garment covers the top and the bottom too.
EXCLUSIVE = frozenset({"top", "bottom", "full", "outer", "footwear", "legwear",
                       "headwear", "under", "hands"})
_COVERS = {"full": {"top", "bottom", "full"}, "top": {"top", "full"},
           "bottom": {"bottom", "full"}}

_CUT = {"with", "from", "under", "beneath", "over", "that", "which", "on", "in", "at", "by",
        "to", "into", "onto", "against", "near", "beside", "behind", "across", "around",
        "toward", "towards", "while", "and", "but"}
def _words(text: str) -> list[str]:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", " ", t)
    return [w if w[0].isalnum() else "," for w in re.findall(r"[a-z0-9]+(?:'[a-z]+)?|[,;:—–-]", t)]


def segment(item: str) -> list[str]:
    """The noun phrase an item is about: its words up to the first comma, dash or
    "with", "on", "in", "to"... "fresh fight shorts, black with gold piping" is "fresh
    fight shorts"; "pistol tucked in her belt" is "pistol tucked"."""
    seg: list[str] = []
    for w in _words(item):
        if w == "," or w in _CUT:
            break
        seg.append(w)
    return seg


def last_of(item: str, vocabulary) -> str | None:
    """The last word of the item's noun phrase that is in `vocabulary` (a word or its
    plural or singular), or None.

    Not the last word of the phrase: a value often trails a remark ("vest sweated
    through", "towel a small one"). Not the first vocabulary word either: a garment is
    often a modifier of another ("tuxedo vest" is a vest, "shirt dress" a dress), so the
    noun the phrase is about is the LAST word that is one. The phrase is cut at
    prepositions and commas, so the object of a preposition is not mistaken for the
    thing itself."""
    for w in reversed(segment(item)):
        # A plural is read as its singular, never the other way: "tight" is not "tights".
        if w in vocabulary or (w.endswith("s") and w[:-1] in vocabulary):
            return w
    return None


def category(item: str) -> str | None:
    """The kind of garment an item is, or None when no garment is named in it."""
    w = last_of(item, CATEGORY)
    return None if w is None else (CATEGORY.get(w) or CATEGORY.get(w[:-1]))


def replaced_by(new: str, items: list[str]) -> list[str]:
    """`items` without what wearing `new` takes off. Items that are not garments, and
    garments of a kind that can be worn together, stay."""
    cat = category(new)
    gone = _COVERS.get(cat, {cat}) if cat in EXCLUSIVE else set()
    return [it for it in items if category(it) not in gone]
