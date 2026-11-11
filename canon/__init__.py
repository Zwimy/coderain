"""The canon ledger: an append-only record of every fact change, and a projection.

Phase 1 of the consistency design. Standalone on purpose: nothing in coderain
imports this yet (see docs/DECISIONS.md D-017). It is the part of the design that
everything else will rest on, so it is built and proven on its own first.

  ledger.py    the append-only, hash-chained record of what happened (the truth)
  state.py     the projection: current and historical canon, derived from it
  store.py     ledger + projection + a snapshot that is only a cache

Phase 2, which writes into it:
  claims.py    the closed claim schema and a defensive parser
  scribe.py    reads finished prose and PROPOSES claims (a model; never writes)
  validate.py  decides in code which claims become ledger records
  shape.py     does the quote describe THIS slot of a person (D-022, D-023)
  wardrobe.py  what a garment is, and which garments replace each other (D-023)
  referents.py who "you", "she" and "he" mean, and who is which gender (D-024)
  pipeline.py  one turn: prose -> Scribe -> validate -> commit

Phase 3, which reads canon back out for the Writer:
  scene.py     who is in the scene (pinned, named, same place), each character's
               identity line, and the bounded Scene State Card
  card.py      what the Writer is shown: identity lines plus the card, built from an
               immutable snapshot of the ledger and cut back to the turns the
               transcript still has (D-027)
  corrections.py  what the author says is true or false about a character, kept in
               corrections.md (outside canon/), outranking the story, and applied
               by a pure plan that is safe to repeat (D-028)

Standard library only.
"""
from canon.ledger import (AUTHORITY, KINDS, Ledger, LedgerCorrupt, LedgerError,
                          Record, slot_class)
from canon.state import Canon, project
from canon.store import Store

__all__ = ["AUTHORITY", "KINDS", "Canon", "Ledger", "LedgerCorrupt",
           "LedgerError", "Record", "Store", "project", "slot_class"]
