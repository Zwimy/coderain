"""Format example for a soak fixture, on an invented story.

Real fixtures quote a real playthrough, so they stay on the author's machine:
name the file `local_<anything>.py` and it is gitignored (see .gitignore). This
one is neutral and tracked so the format is documented and tested.

Each case is a fact the narration established, plus what the engine's memory is
EXPECTED to have done with it. A LOST or DRIFTED case is a failing fixture for a
better engine to turn green; a HELD case is a control that proves the probe can
see a fact when memory does keep one. Run one with:

    python -m soak audit <save dir> --fixture example
"""
from __future__ import annotations

from soak.facts import DRIFTED, HELD, LOST, Fact

FACTS = [
    Fact(id="example-scar", entity="odile", slot="identity.marks",
         truth=(r"\bscar",), source=r"scarred cheek", expect=LOST,
         note="narrated once and recorded nowhere"),
    Fact(id="example-hair", entity="odile", slot="identity.hair",
         truth=(r"\braven\b",), stale=(r"\bplatinum\b",),
         source=r"raven hair", expect=DRIFTED,
         note="narrated one colour; the sheet records another"),
    # `decoys` are strings from THIS story that a pattern must never match. A bare
    # `anchor` would match "Silver Anchor" below and report a missing tattoo as kept.
    Fact(id="example-tattoo", entity="corin", slot="identity.marks",
         truth=(r"tattoo", r"\bblue anchor\b"), source=r"blue anchor",
         decoys=("Holds the Silver Anchor secret.",), expect=LOST),
    Fact(id="example-control", entity="corin", slot="wardrobe.accessory",
         truth=(r"silver ring",), source=r"silver ring", expect=HELD,
         note="control: a detail the sheet does keep"),
]
