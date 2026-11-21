"""The ties line: who is tied to whom and who carries what, said again at the END of the prompt, after the player's action (D-063).

The graph probe (D-058, D-059, D-061) found a gap that retrieval does not close: with the evidence already in the prompt, a 4B Writer
answered a "who is her brother" or "who carries the key" question wrongly about a third of the time. The facts sit in the middle of
a long system message, a long way from the question. The canon card (D-027) is the one thing the engine already puts at the tail,
after the player's action, but it is built from the canon ledger, which knows looks and what people wear, not ties and possessions.
Those live in the story's own files: a character's `relationships:` line and an item's `holder:` attr (D-059).

This builds ONE short system message from those files for the things the player's action and the last reply name, plus one hop
(an item to its holder, then the holder's ties), and the engine appends it right after the card. Off unless
`memory: {tail_ties: true}`; nothing here has been measured on a model yet, which is why it is off.

Rules it keeps, because they were paid for elsewhere in the engine:
  * A hidden entry (a secret), one whose `chance` is 0, one whose `delay` has not passed and one whose `triggers_not` is in the text
    are never said (the same gates as the follow pass).
  * A tie or a holder that names no entry in the registries is left out, never guessed.
  * Everything it reads is the files and the text so far, so a retry of the turn builds the same line (invariant 5).
  * Bounded: at most MAX_FACTS facts and MAX_LINE characters, the later ones dropped, never the earlier ones cut in half.
"""
from __future__ import annotations

from . import templates
from .memory import name_key, trigger_hit

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
    entries = [(rel, e) for rel in store.gated_registries() for e in store.entries(rel)]
    by_slug = {e.slug: e for _rel, e in entries}
    titles: dict[str, str] = {}
    first_words: dict[str, int] = {}
    for e in by_slug.values():
        for name in [e.title, *e.aliases]:
            titles.setdefault(name_key(name), e.slug)
        w = e.title.split()[0].lower() if e.title.split() else ""
        first_words[w] = first_words.get(w, 0) + 1
    unique_firsts = {w for w, n in first_words.items() if n == 1}

    def resolve(raw: str) -> str | None:
        slug = templates.slugify(raw)
        return slug if slug in by_slug else titles.get(name_key(raw))

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

    def add_ties(slug: str) -> None:
        e = by_slug[slug]
        for other, note in e.relationships():
            target = resolve(other)
            if target is None or target == slug or not speakable(by_slug[target]):
                continue
            who = by_slug[target].title
            facts.append(f"{e.title} is tied to {who}" + (f" ({note})" if note else ""))

    for slug in named:
        e = by_slug[slug]
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        raw_holder = e.attrs.get("holder", "").strip()
        if raw_holder:
            holder = resolve(raw_holder)
            if holder is not None and holder != slug and speakable(by_slug[holder]):
                facts.append(f"{e.title} is held by {by_slug[holder].title}")
                holders.append(holder)
        add_ties(slug)
    # One hop: whoever holds a named item has their own ties, and the question is often about them.
    for slug in holders:
        if slug not in seen_slugs:
            seen_slugs.add(slug)
            add_ties(slug)

    kept: list[str] = []
    total = len(HEAD)
    for fact in dict.fromkeys(facts):                       # in order, each once
        if len(kept) >= MAX_FACTS or total + len(fact) + 2 > MAX_LINE:
            break
        kept.append(fact)
        total += len(fact) + 2
    return HEAD + ". ".join(kept) + "." if kept else ""
