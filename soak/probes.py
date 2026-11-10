"""Offline, deterministic probes over a save. No model is ever called.

Every probe answers a question about what the CURRENT engine does with a story's
facts, using the engine's own code (assemble, the entry parser, the transcript
reader). That is the point of Phase 0: a baseline of today's behaviour that a
rewrite has to beat.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from coderain.config import load_config
from coderain.engine import Engine
from soak.facts import names_of, present_in

# ---------------------------------------------------------------------------
# Prompt presence: would the writer actually be shown this fact?
# ---------------------------------------------------------------------------


class PromptProbe:
    """Build the real per-turn prompt for a save and ask what is in it."""

    def __init__(self, store, memory: dict | None = None):
        cfg = load_config()
        # Deterministic and offline: no embedder (it would call a server and
        # build an index inside the copy), no Director pass, no model calls.
        cfg.retrieval["enabled"] = False
        cfg.generation["trinity_brain"] = False
        cfg.memory.update(memory or {})
        self.engine = Engine(cfg, store)
        self.store = store

    def messages(self, player_input: str) -> list[dict]:
        return self.engine._messages(self.engine.history_window(), player_input)

    def presence(self, patterns: tuple[str, ...], names: list[str], slug: str,
                 player_input: str) -> dict:
        """Is the value attached to THIS entity in the memory context, and/or
        anywhere in the prompt?

        Split on purpose: the history window can hold a detail by recency alone,
        which says nothing about whether memory retained it. `system` is memory's
        contribution; `any` includes recent verbatim turns. Both are scoped to
        the entity, so another character's scar is not this character's scar.
        """
        msgs = self.messages(player_input)
        system = msgs[0]["content"] if msgs else ""
        everything = "\n\n".join(m["content"] for m in msgs)
        return {"system": present_in(system, names, slug, patterns),
                "any": present_in(everything, names, slug, patterns)}


# ---------------------------------------------------------------------------
# Transient state frozen into a permanent description
# ---------------------------------------------------------------------------

# Words that mark a SCENE-SPECIFIC state rather than a standing trait. This is a
# heuristic with an unknown false-positive rate, which is why the report shows
# the matched marker and nothing else: it is a lead for review, not a verdict.
_TRANSIENT = re.compile(
    r"\b(gone|torn off|tattered|ripped|soaked|drenched|bleeding|bloodied|"
    r"still healing|freshly|now (?:wearing|bears|bare)|currently)\b",
    re.IGNORECASE)
_VISUAL = re.compile(
    r"(?:\*\*)?Visuals?(?:\*\*)?:\s*(.+?)(?=\s+(?:\*\*)?(?:Mentality|Voice|Skills)"
    r"(?:\*\*)?:|$)", re.IGNORECASE | re.DOTALL)


def transient_in_identity(store) -> dict:
    flagged = []
    entries = store.entries("characters.md")
    for e in entries:
        m = _VISUAL.search(e.body)
        if not m:
            continue
        marker = _TRANSIENT.search(m.group(1))
        if marker:
            flagged.append({"entity": e.slug, "marker": marker.group(1).lower()})
    return {"characters": len(entries), "flagged": flagged,
            "count": len(flagged),
            "caveat": "keyword heuristic; precision and recall unknown"}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_audit(store) -> dict:
    """Scenes stamped with a day that cannot be a day.

    The fold once accepted a calendar YEAR as the story day (fixed in v0.5.1 for
    new folds). Anything above this is a year-shaped value, not a day count.
    """
    scenes = store.entries("memory/scenes.md")
    days = []
    for e in scenes:
        try:
            days.append(int(str(e.attrs.get("day", "")).strip()))
        except ValueError:
            continue
    bad = [d for d in days if d > 1000]
    return {"scenes": len(scenes), "stamped": len(days),
            "year_shaped": len(bad),
            "distinct_year_shaped": sorted(set(bad))[:6]}


# ---------------------------------------------------------------------------
# Does the arc still mention the early cast?
# ---------------------------------------------------------------------------


def _first_mention(names: list[str], turns: list[dict]) -> int | None:
    pats = [re.compile(r"\b" + re.escape(n) + r"\b", re.IGNORECASE)
            for n in names]
    for i, t in enumerate(turns, start=1):
        if any(p.search(t.get("text", "")) for p in pats):
            return i
    return None


def arc_coverage(store) -> dict:
    """Share of characters named in the arc, by when they were introduced.

    The arc is the only long-horizon summary the prompt carries. It is capped at
    a few hundred words by design, so how many characters it can name is bounded
    whatever the story; the useful question is whether it favours the recent or
    the early cast.
    """
    turns = store.turns()
    arc = store.read("memory/arc.md") or ""
    rows = []
    for e in store.entries("characters.md"):
        names = names_of(e)
        first = _first_mention(names, turns) if names else None
        if first is None:
            continue
        in_arc = any(re.search(r"\b" + re.escape(n) + r"\b", arc, re.IGNORECASE)
                     for n in names)
        rows.append((first, in_arc, e.slug))
    rows.sort()
    n = len(rows)
    thirds = [rows[: n // 3], rows[n // 3: 2 * n // 3], rows[2 * n // 3:]]
    labels = ("earliest third", "middle third", "latest third")
    report = []
    for label, chunk in zip(labels, thirds):
        if not chunk:
            continue
        report.append({"cohort": label, "characters": len(chunk),
                       "in_arc": sum(1 for _f, ia, _s in chunk if ia),
                       "first_turns": f"{chunk[0][0]}-{chunk[-1][0]}"})
    return {"arc_chars": len(arc), "introduced": n,
            "named_in_arc": sum(1 for _f, ia, _s in rows if ia),
            "by_cohort": report}


# ---------------------------------------------------------------------------
# Hair and eye colour: what narration asserts, against the sheet
# ---------------------------------------------------------------------------

# Colour words grouped into families so "blonde" and "platinum" agree and
# "raven" and "black" agree. Grouping is a judgement; the report lists every
# conflict with its source sentences so a reader can overrule it.
_FAMILIES = {
    "black": ("black", "raven", "jet", "ebony"),
    "brown": ("brown", "chestnut", "brunette", "chocolate", "hazel"),
    "blond": ("blond", "blonde", "platinum", "golden", "flaxen"),
    "red": ("red", "ginger", "auburn", "copper", "crimson"),
    "pale": ("silver", "white", "grey", "gray", "ash", "snow"),
    "green": ("green", "emerald", "jade"),
    "blue": ("blue", "azure", "sapphire", "ice", "icy"),
    "violet": ("violet", "purple", "amethyst", "lavender"),
    "amber": ("amber", "gold", "yellow"),
}
_WORD_FAMILY = {w: fam for fam, ws in _FAMILIES.items() for w in ws}


def _families(text: str, noun: str = "") -> frozenset[str]:
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        fam = _WORD_FAMILY.get(w)
        if w in ("golden", "gold") and noun == "eyes":
            fam = "amber"        # golden eyes are amber, golden hair is blond
        if fam:
            out.add(fam)
    return frozenset(out)


_PREPOSITIONS = {"in", "on", "at", "of", "with", "from", "by", "into", "like",
                 "as", "through", "over", "under", "behind", "around"}


def _gender(entry) -> str | None:
    """'f', 'm' or None, from the pronouns the entry's own text uses.

    Only used to refuse a pronoun that cannot refer to this character: "Her
    violet eyes" must not be credited to the male protagonist just because he
    was the last name in the turn.
    """
    text = entry.render()
    f = len(re.findall(r"\b(?:she|her|hers|herself)\b", text, re.IGNORECASE))
    m = len(re.findall(r"\b(?:he|his|him|himself)\b", text, re.IGNORECASE))
    if f >= 2 and f >= 2 * m:
        return "f"
    if m >= 2 and m >= 2 * f:
        return "m"
    return None


@dataclass
class _Assertion:
    turn: int
    fams: frozenset
    snippet: str
    how: str          # "possessive" (named owner) or "focus" (pronoun, resolved)


# "<up to 5 words> hair|eyes". The words before the noun carry the colour.
_SPAN = re.compile(r"((?:[\w'’-]+\s+){0,5}?)\b(hair|eyes)\b", re.IGNORECASE)


def _name_regex(names: list[str]) -> re.Pattern:
    alt = "|".join(re.escape(n) for n in names)
    return re.compile(r"(?<![\w'’])(" + alt + r")(?![\w])", re.IGNORECASE)


def _sheet_families(text: str, noun: str) -> frozenset[str]:
    fams: set[str] = set()
    for m in re.finditer(
            r"((?:[\w-]+[ ,/]+){0,4})\b" + noun + r"\b((?:[ ,]+[\w-]+){0,3})",
            text, re.IGNORECASE):
        fams |= _families(m.group(1) + " " + m.group(2), noun)
    return frozenset(fams)


def _collect(turns: list[dict], owner: dict) -> dict:
    """Colour assertions per (entity, noun), attributed two ways.

    Possessive ("Sela's ebony hair") names the owner exactly. A pronoun span
    ("Her long raven hair", the usual form in real play) is attributed
    to the FOCUS character: the single character the narrator turn has most
    recently been about. A paragraph naming two characters clears the focus,
    because "her" could be either, and a turn starts with no focus. That trades
    recall for precision on purpose; the conflicts it reports are reviewed.
    """
    name_re = _name_regex(sorted(owner, key=len, reverse=True))
    genders = {e.slug: _gender(e) for e in {x.slug: x for x in owner.values()}.values()}
    found: dict[tuple[str, str], list[_Assertion]] = {}
    for i, t in enumerate(turns, start=1):
        if t.get("role") != "narrator":
            continue
        focus = None
        for para in t.get("text", "").splitlines():
            if not para.strip():
                continue
            mentioned = {owner[m.group(1).lower()].slug
                         for m in name_re.finditer(para)}
            if len(mentioned) == 1:
                focus = next(iter(mentioned))
            elif len(mentioned) > 1:
                focus = None
            for m in _SPAN.finditer(para):
                pre, noun = m.group(1), m.group(2).lower()
                words = re.findall(r"[\w'’-]+", pre)
                # The colour has to sit in the noun phrase itself: the last
                # three words, after the last preposition. "golden rings in her
                # eyes" is not an eye colour.
                tail = words[-3:]
                cut = max((i for i, w in enumerate(tail)
                           if w.lower() in _PREPOSITIONS), default=-1)
                fams = _families(" ".join(tail[cut + 1:]), noun)
                if not fams:
                    continue
                poss = re.search(
                    r"(?<![\w'’])((?:" + "|".join(
                        re.escape(n) for n in sorted(owner, key=len, reverse=True))
                    + r"))['’]s\b", pre, re.IGNORECASE)
                pron = re.search(r"\b(her|his|their)\b",
                                 " ".join(words[-5:]), re.IGNORECASE)
                if poss:
                    slug, how = owner[poss.group(1).lower()].slug, "possessive"
                elif focus is not None and pron:
                    want = {"her": "f", "his": "m"}.get(pron.group(1).lower())
                    # A gendered pronoun is only attributed when the focus
                    # character's gender is KNOWN and matches. A sheet with too
                    # few pronouns to tell is skipped rather than guessed: the
                    # protagonist was being credited with another woman's eyes.
                    if want and genders.get(focus) != want:
                        continue
                    slug, how = focus, "focus"
                else:
                    continue
                lo, hi = max(0, m.start() - 40), min(len(para), m.end() + 40)
                found.setdefault((slug, noun), []).append(
                    _Assertion(i, fams, " ".join(para[lo:hi].split()), how))
    return found


def attribute_drift(store) -> dict:
    """Colour assertions per character over the whole story, vs the sheet.

    A CONFLICT is two narrated assertions whose colour families are disjoint
    (raven then platinum). Some conflicts are real changes (a dye job, a
    disguise) and some are attribution mistakes, so the count is candidates, not
    errors; every one carries its two source sentences for review.
    """
    turns = store.turns()
    entries = store.entries("characters.md")
    owner: dict[str, object] = {}
    for e in entries:
        for n in names_of(e):
            owner.setdefault(n.lower(), e)
    if not owner:
        return {"pairs": 0, "conflict_count": 0, "conflicts": [], "summary": {}}

    found = _collect(turns, owner)
    by_slug = {e.slug: e for e in entries}
    conflicts, pairs = [], 0
    outcome = {"sheet_matches_first": 0, "sheet_matches_last": 0,
               "sheet_matches_both": 0, "sheet_matches_neither": 0,
               "sheet_silent": 0}
    for (slug, noun), asserts in sorted(found.items()):
        if len(asserts) < 2:
            continue
        pairs += 1
        first = asserts[0]
        later = next((a for a in asserts[1:] if not (a.fams & first.fams)), None)
        if later is None:
            continue
        sheet = _sheet_families(by_slug[slug].render(), noun)
        m_first, m_last = bool(sheet & first.fams), bool(sheet & later.fams)
        key = ("sheet_silent" if not sheet else
               "sheet_matches_both" if m_first and m_last else
               "sheet_matches_first" if m_first else
               "sheet_matches_last" if m_last else "sheet_matches_neither")
        outcome[key] += 1
        conflicts.append({
            "entity": slug, "noun": noun, "assertions": len(asserts),
            "first": {"turn": first.turn, "how": first.how,
                      "families": sorted(first.fams), "snippet": first.snippet},
            "conflicting": {"turn": later.turn, "how": later.how,
                            "families": sorted(later.fams),
                            "snippet": later.snippet},
            "sheet_families": sorted(sheet), "sheet": key})
    return {"pairs": pairs, "conflict_count": len(conflicts),
            "conflicts": conflicts, "summary": outcome,
            "caveat": "owner is a named possessive or the paragraph's single "
                      "focus character; conflicts include real changes such as "
                      "dye or disguise and some misattributions"}
