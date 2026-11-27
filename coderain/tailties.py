"""The ties line: who is tied to whom and who carries what, said again at the END of the prompt, after the player's action (D-063).

The graph probe (D-058, D-059, D-061) found a gap that retrieval does not close: with the evidence already in the prompt, a 4B Writer
answered a "who is her brother" or "who carries the key" question wrongly about a third of the time. The facts sit in the middle of
a long system message, a long way from the question. The canon card (D-027) is the one thing the engine already puts at the tail,
after the player's action, but it is built from the canon ledger, which knows looks and what people wear, not ties and possessions.
Those live in the story's own files: a character's `relationships:` line and an item's `holder:` attr (D-059).

This builds ONE short system message from those files for the things the player's action and the last reply name, plus one hop
(an item to its holder, then the holder's ties), and the engine appends it right after the card. Since D-074 the facts come from
the lore web, so a tie or holder is said whichever of its two ends was named, and `links:` count too. On unless
`memory: {tail_ties: false}` (D-078): measured on a model only together with follow_links (D-073).

Rules it keeps, because they were paid for elsewhere in the engine:
  * A hidden entry (a secret), one whose `chance` is 0, one whose `delay` has not passed and one whose `triggers_not` is in the text
    are never said (the same gates as the follow pass).
  * A tie or a holder that names no entry in the registries is left out, never guessed.
  * Everything it reads is the files and the text so far, so a retry of the turn builds the same line (invariant 5).
  * Bounded: at most MAX_FACTS facts and MAX_LINE characters, the later ones dropped, never the earlier ones cut in half.
"""
from __future__ import annotations

from .loreweb import HOLDS, TIE, edges_of, fact, neighbours
from .memory import trigger_hit

MAX_FACTS = 8
MAX_LINE = 600
HEAD = "Facts in play, from the story's own files (they are true; use them as written): "


def _names(e, firsts: set[str]) -> list[str]:
    """What the story may call an entry: its title, its aliases and, when no other entry shares it, its first name."""
    out = [e.title, *e.aliases]
    first = e.title.split()[0] if e.title.split() else ""
    if len(first) >= 3 and first.lower() in firsts:
        out.append(first)
    return out


def tail_ties(store, text: str, turn_index: int) -> str:
    """The ties line for a turn whose player action and last reply are `text`, or "" when there is nothing to say."""
    hay = text.lower()
    by_slug: dict = {}
    for rel in store.gated_registries():
        for e in store.entries(rel):
            by_slug.setdefault(e.slug, e)
    first_words: dict[str, int] = {}
    for e in by_slug.values():
        w = e.title.split()[0].lower() if e.title.split() else ""
        first_words[w] = first_words.get(w, 0) + 1
    unique_firsts = {w for w, n in first_words.items() if n == 1}
    web = edges_of(by_slug)

    def speakable(e) -> bool:
        if e.hidden() or e.chance() == 0:
            return False
        dly = e.delay()
        if dly is not None and turn_index < dly:
            return False
        return not any(trigger_hit(tok, hay) for tok in e.triggers_not())

    named = [e.slug for e in by_slug.values() if speakable(e)
             and any(trigger_hit(n, hay) for n in _names(e, unique_firsts))]
    facts: list[str] = []
    seen_slugs: set[str] = set()
    holders: list[str] = []
    # Every holder, tie and link touching what was named, what the entry itself states first (D-074): naming the person who carries
    # the key now says so, as naming the key always did.
    for slug in named:
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        for edge, other, outgoing in neighbours(slug, web):
            if not speakable(by_slug[other]):
                continue
            facts.append(fact(edge, by_slug))
            if edge.kind == HOLDS and outgoing:
                holders.append(other)
    # One hop: whoever holds a named item has their own ties, and the question is often about them.
    for slug in holders:
        if slug not in seen_slugs:
            seen_slugs.add(slug)
            for edge, other, outgoing in neighbours(slug, web, (TIE,)):
                if outgoing and speakable(by_slug[other]):
                    facts.append(fact(edge, by_slug))

    kept: list[str] = []
    total = len(HEAD)
    for said in dict.fromkeys(facts):                       # in order, each once
        if len(kept) >= MAX_FACTS or total + len(said) + 2 > MAX_LINE:
            break
        kept.append(said)
        total += len(said) + 2
    return HEAD + ". ".join(kept) + "." if kept else ""
