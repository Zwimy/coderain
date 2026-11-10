"""A fact the story established, and what became of it in the engine's memory.

The classification is the harness's core measurement, so it is deliberately
small. For one established fact there are two patterns: `truth` (the value the
narration established) and `stale` (a different value that should not be there).
Looking at the entity's current entry gives four outcomes:

  HELD      truth present, no stale value: the memory kept what happened.
  LOST      neither present: the detail is gone from this entry.
  DRIFTED   a stale value present, truth absent: the memory holds a different
            value than the one narrated.
  CONFLICT  both present: the entry now disagrees with itself.

LOST and DRIFTED are different failures and the distinction is the reason this
is not a boolean. A lost detail can be re-derived from the transcript; a drifted
one is actively wrong in every prompt that includes the entry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HELD, LOST, DRIFTED, CONFLICT, NO_ENTITY = (
    "HELD", "LOST", "DRIFTED", "CONFLICT", "NO_ENTITY")

# Files searched for "is the fact anywhere in memory, even if not on the sheet".
# Order is only for stable reporting.
MEMORY_FILES = (
    "memory/arc.md", "memory/scenes.md", "memory/facts.md", "memory/timeline.md",
    "characters.md", "locations.md", "factions.md", "items.md",
    "canon-events.md", "threads.md",
)


@dataclass(frozen=True)
class Fact:
    id: str
    entity: str                              # slug of the owning entry
    truth: tuple[str, ...]                   # regexes: any hit = value present
    registry: str = "characters.md"
    slot: str = ""                           # label only, e.g. "identity.hair"
    stale: tuple[str, ...] = ()              # regexes: any hit = wrong value
    source: str = ""                         # regex locating the narration
    note: str = ""
    expect: str = ""                         # status the fixture author expects
    # Text that appears in this story and must NOT count as the fact. A pattern
    # that is too loose matches it, and validate_fixture() refuses the fixture.
    # Added after a bare `anchor` pattern matched "Silver Anchor secret" (a world
    # concept) on a sheet and reported a missing tattoo as kept.
    decoys: tuple[str, ...] = ()


def _hit(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def validate_fixture(facts: list["Fact"]) -> None:
    """Refuse a fixture whose patterns are too loose or that has no expectation.

    A fixture is the harness's ground truth, so a mistake in one produces a
    confident wrong baseline. Cheap to check, expensive to discover later.
    """
    seen: set[str] = set()
    for f in facts:
        if f.id in seen:
            raise ValueError(f"duplicate fixture id: {f.id}")
        seen.add(f.id)
        if not f.expect:
            raise ValueError(f"{f.id}: no expected status")
        if not f.truth:
            raise ValueError(f"{f.id}: no truth pattern")
        for decoy in f.decoys:
            if _hit(f.truth, decoy):
                raise ValueError(
                    f"{f.id}: a truth pattern matches the decoy {decoy!r}")


from canon.replay import names_of  # noqa: E402,F401  (one implementation)


def entity_names(store, fact: "Fact") -> list[str]:
    for e in store.entries(fact.registry):
        if e.slug == fact.entity:
            return names_of(e)
    return []


# A paragraph, or one bullet of a bullet list. Facts and timeline are bullet
# files with no blank lines between items, so blank-line splitting alone would
# make the whole list one "paragraph" and everything would appear to co-occur.
_PARAS = re.compile(r"\n\s*\n|\n(?=- )")


def mentions(text: str, names: list[str], patterns: tuple[str, ...]) -> bool:
    """One paragraph both names the entity and carries the value.

    This is the rule that stops another character's detail counting as this
    one's. The first real run reported a character's scar as "found elsewhere"
    and "on the prompt" because `\\bscar` matched OTHER characters' scars.
    """
    name_res = [re.compile(r"\b" + re.escape(n) + r"\b", re.IGNORECASE)
                for n in names]
    if not name_res:
        return False
    return any(_hit(patterns, para) and any(r.search(para) for r in name_res)
               for para in _PARAS.split(text))


def present_in(text: str, names: list[str], slug: str,
               patterns: tuple[str, ...]) -> bool:
    """Is the value attached to THIS entity somewhere in `text`?

    Two ways it can be: inside the entity's own entry block (a "## Title
    {#slug}" heading through the next heading), whose body often never repeats
    the name, or in any paragraph that names the entity and carries the value.
    """
    if not patterns:
        return False
    for block in re.split(r"\n(?=## )", text):
        first = block.split("\n", 1)[0]
        if first.startswith("## ") and (
                f"{{#{slug}}}" in first
                or any(re.search(r"\b" + re.escape(n) + r"\b", first,
                                 re.IGNORECASE) for n in names)):
            if _hit(patterns, block):
                return True
    return mentions(text, names, patterns)


def classify(truth_present: bool, stale_present: bool) -> str:
    if truth_present and stale_present:
        return CONFLICT
    if truth_present:
        return HELD
    return DRIFTED if stale_present else LOST


def entity_text(store, fact: Fact) -> str | None:
    """The rendered entry for the fact's entity, or None when it has none."""
    for e in store.entries(fact.registry):
        if e.slug == fact.entity:
            return e.render()
    return None


def locate_source(fact: Fact, turns: list[dict]) -> int | None:
    """1-based index of the first NARRATOR turn matching `fact.source`."""
    if not fact.source:
        return None
    for i, t in enumerate(turns, start=1):
        if t.get("role") == "narrator" and re.search(
                fact.source, t.get("text", ""), re.IGNORECASE):
            return i
    return None


# Files whose content is a list of entries. Everything else in MEMORY_FILES is
# prose or bullets and is searched as text.
_ENTRY_FILES = {
    "memory/scenes.md", "characters.md", "locations.md", "factions.md",
    "items.md", "canon-events.md", "threads.md",
}


def _searchable(store, rel: str, skip_slug: str | None = None) -> str:
    """What the engine would treat as this file's content.

    Two traps this avoids, both found by the harness's own test. Seeded files
    carry example entries inside HTML comments (one is a "burn scar"), and the
    engine ignores them, so searching raw text reported template text as a
    memory of the story. And excluding the owning entry by string replacement
    fails whenever the rendered entry differs from the file text, so entries are
    parsed and filtered by slug instead.
    """
    from coderain.memory import _strip_comments
    if rel in _ENTRY_FILES:
        return "\n".join(e.render() for e in store.entries(rel)
                         if e.slug != skip_slug)
    return _strip_comments(store.read(rel) or "")


def elsewhere(store, fact: Fact) -> list[str]:
    """Memory files OTHER than the entity's own entry that carry the truth.

    Answers "is it recoverable from memory at all": a fact absent from the sheet
    but present in a scene summary is in a different situation from one that
    exists only in the raw transcript.
    """
    found = []
    names = entity_names(store, fact)
    for rel in MEMORY_FILES:
        try:
            text = _searchable(
                store, rel, fact.entity if rel == fact.registry else None)
        except (FileNotFoundError, OSError):
            continue
        if text and mentions(text, names, fact.truth):
            found.append(rel)
    return found


@dataclass
class FactResult:
    fact: Fact
    status: str
    source_turn: int | None = None
    age_turns: int | None = None
    elsewhere: list[str] = field(default_factory=list)
    prompt: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"id": self.fact.id, "entity": self.fact.entity,
                "slot": self.fact.slot, "status": self.status,
                "expected": self.fact.expect, "source_turn": self.source_turn,
                "age_turns": self.age_turns, "elsewhere": self.elsewhere,
                "prompt": self.prompt, "note": self.fact.note}


def evaluate(store, fact: Fact, turns: list[dict],
             prompt: dict[str, bool] | None = None) -> FactResult:
    text = entity_text(store, fact)
    src = locate_source(fact, turns)
    age = (len(turns) - src) if src is not None else None
    if text is None:
        return FactResult(fact, NO_ENTITY, src, age, elsewhere(store, fact),
                          prompt or {})
    status = classify(_hit(fact.truth, text), _hit(fact.stale, text))
    return FactResult(fact, status, src, age, elsewhere(store, fact),
                      prompt or {})
