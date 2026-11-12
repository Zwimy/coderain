"""The pieces a replay of a story through canon needs, shared by the real-save gate
(soak/canon_gate.py) and the engine's shadow mode (coderain/canon_shadow.py).

Nothing here knows about a save's layout: characters arrive as anything with
`title`, `slug` and `aliases`, and a turn's outcome arrives as a TurnReport. That is
what lets the same code replay a copy of a save in a harness and a live save inside
the engine.

Every function that returns something a person will read returns values, counts and
turn numbers, never narration. A canon record carries the quoted evidence sentence,
which is the story's own prose, so records are summarised, not dumped.
"""
from __future__ import annotations

import re
from collections import Counter

from canon import shape
from canon.ledger import AUTHORITY, LedgerError
from canon.referents import genders_from, make_who
from canon.scene import mentions
from canon.validate import F_WORDS, M_WORDS, YOU_WORDS, Who, _STOP, _slugify, _tokens

_GENERIC = {"the", "you", "him", "her", "them", "she", "his", "man", "woman"}


# --- names ------------------------------------------------------------------------
def names_of(entry) -> list[str]:
    """Title and aliases as they appear in narration, longest first."""
    out: list[str] = []
    for raw in [entry.title, *entry.aliases]:
        cleaned = re.sub(r"[\"“”]", "", raw).strip()
        for cand in (cleaned, re.sub(r"\s*\(.*?\)", "", cleaned).strip()):
            if len(cand) >= 3 and cand.lower() not in _GENERIC and cand not in out:
                out.append(cand)
    return sorted(out, key=len, reverse=True)


def display_name(entry) -> str:
    cleaned = re.sub(r"[\"“”]", "", entry.title).strip()
    return re.sub(r"\s*\(.*?\)", "", cleaned).strip() or cleaned


def seed_entities(store, entries, *, turn: int = 0) -> dict:
    """One scenario-authored entity per character sheet, so the Scribe is given the
    story's real names and a claim can resolve to them. Safe to repeat.

    `turn` is the turn the entity is first known at. A ledger's turns never decrease,
    so a character who turns up mid-story has to be created AT that turn, not at 0:
    that is also what makes an undo past it drop the entity along with its claims.
    """
    made, skipped = [], []
    for e in entries:
        if e.slug in store.canon.entities:
            continue
        name = display_name(e)
        aliases = [a for a in names_of(e) if a.lower() != name.lower()][:15]
        try:
            store.append(kind="entity_created", entity=e.slug, slot="character",
                         value=name, authority="scenario", turn=turn, aliases=aliases)
        except LedgerError as exc:
            skipped.append({"entity": e.slug, "why": str(exc)[:120]})
            continue
        made.append(e.slug)
    return {"made": len(made), "skipped": skipped}


# --- who is who -------------------------------------------------------------------
def player_entity(entries, player_text: str, configured: str | None = None) -> str | None:
    """The character "you" means, or None. `configured` (a slug from config) wins. Else the
    "Name:" line of player.md, matched against a character's WHOLE name or alias; else the
    ONE character with a name word among the capitalised words of the file. Two matches, or
    none, is None: a guess about the protagonist would put their facts on someone else.
    (One real player.md said "Name: Finn ... well read", and matching every word of it
    found a second character through "well".)"""
    slugs = {e.slug for e in entries}
    if configured and configured in slugs:
        return configured
    m = re.search(r"(?im)^\s*name\s*:\s*(.+?)\s*$", player_text)
    if m:
        want = _tokens(m.group(1))
        hits = {e.slug for e in entries if any(_tokens(n) == want for n in names_of(e))}
        return next(iter(hits)) if len(hits) == 1 else None
    words = {t for t in _tokens(" ".join(re.findall(r"\b[A-Z][a-z]{2,}\b", player_text)))
             if t not in _STOP}
    hits = {e.slug for e in entries
            if any(t in words for name in names_of(e) for t in _tokens(name) if len(t) >= 3)}
    return next(iter(hits)) if len(hits) == 1 else None


def player_gender(player_text: str) -> str | None:
    """"M" or "F" when player.md says one ("male", "a woman"), else None."""
    toks = set(_tokens(player_text))
    m, f = bool(toks & {"male", "man", "boy"}), bool(toks & {"female", "woman", "girl"})
    return "M" if m and not f else "F" if f and not m else None


# --- what the player's own file says about the player's looks ------------------------
_PRONOUN = {"M": "He", "F": "She", None: "They"}
_MARK = re.compile(
    r"((?:[\w-]+\s+){0,2}?)\b(scars?|tattoos?|birthmarks?)\b"
    r"((?:\s+(?:on|over|across|above|below|along|through|under)\s+(?:(?:his|her|their|the|my)\s+)?"
    r"[\w-]+(?:\s+[\w-]+)?)?)", re.IGNORECASE)
_NOT_PART_OF_A_MARK = frozenset("a an the and with has have had his her their my of or".split())
# Words that can stand right before an adjective in a sentence and are never part of one:
# "grey eyes AND raven hair" must offer "raven", not "and raven".
_LEAD_WORDS = frozenset("a an the and or with has have had his her their its my of was is are but".split())


def _mark_phrase(clause: str) -> str | None:
    """"a thin scar over his left eye" -> "thin scar over his left eye": the adjective before
    the noun, if any, and where it is, if it says. None when the clause names no mark."""
    m = _MARK.search(clause)
    if m is None:
        return None
    lead: list[str] = []
    for w in reversed(m.group(1).split()):
        if w.lower() in _NOT_PART_OF_A_MARK:
            break
        lead.insert(0, w)
    return " ".join([*lead, m.group(2), *m.group(3).split()])[:60]
_HEIGHT = re.compile(r"(?:about |around )?(?:\d{3}\s?cm|\d['’]\s?\d{1,2}[\"”]?)\s*tall", re.IGNORECASE)
_BUILD_CLAUSE = re.compile(
    r"(?:very |quite )?(?:tall|short|slim|lean|muscular|athletic|stocky|slender|petite|"
    r"broad[- ]shouldered)(?: build| frame)?", re.IGNORECASE)


def player_facts(player_text: str) -> list[tuple[str, str, str]]:
    """What the player's own file says about the player's looks, as (slot, value, quote).

    Plain code, no model: the file is the person's own description of the protagonist, and
    every candidate has to pass the same shape rules a claim from the Scribe does
    (canon/shape.py), so "black hair" is hair, "200cm tall" is build and "versed in chess"
    is neither. At most one value per slot, the first the file states; marks are one each."""
    text = player_text
    pron = _PRONOUN[player_gender(player_text)]
    found: dict[str, tuple[str, str]] = {}
    marks: list[tuple[str, str]] = []

    def offer(slot: str, value: str, evidence: str, quote: str | None = None) -> None:
        value = " ".join(value.split())
        if value and slot not in found and shape.problem(slot, value, evidence) is None:
            found[slot] = (value, " ".join((quote or evidence).split())[:200])

    for clause in (c.strip() for c in re.split(r"[,;\n]|\.\s", text)):
        clause = re.sub(r"^[A-Za-z ]{2,20}:\s*", "", clause)          # "Info: 200cm tall"
        if not clause:
            continue
        for slot, noun in (("identity.hair", "hair"), ("identity.eyes", "eyes")):
            for m in re.finditer(rf"\b((?:[\w-]+\s+)?[\w-]+)\s+{noun}\b", clause, re.IGNORECASE):
                words = m.group(1).split()
                while words and words[0].lower() in _LEAD_WORDS:     # "grey eyes AND raven hair"
                    words.pop(0)
                if not words:
                    continue
                for k in (len(words), 1):               # "long black", then "black"
                    offer(slot, " ".join(words[-k:]), clause)
        age = re.search(r"\b(\d{1,3})[- ]years?[- ]old\b|\baged?\s+(\d{1,3})\b", clause, re.IGNORECASE)
        if age:
            offer("identity.age", f"{age.group(1) or age.group(2)} years old", clause)
        if _HEIGHT.fullmatch(clause) or _BUILD_CLAUSE.fullmatch(clause):
            offer("identity.build", clause, f"{pron} is {clause}", clause)
        mark = _mark_phrase(clause)
        if mark and len(marks) < 4:
            marks.append(("identity.marks", mark))
    out = [(slot, v, q) for slot, (v, q) in found.items()]
    return out + [(slot, v, v) for slot, v in marks]


def seed_player(store, player: str | None, player_text: str, *, turn: int = 0) -> list[tuple[str, str]]:
    """Write what player.md says about the player's looks into the ledger at SCENARIO
    authority, and return what was written, as (slot, value).

    Scenario outranks narration, so the Scribe's later claims can agree with these but a
    different value is held back as a conflict, instead of the protagonist's hair being
    whatever the first sentence about a "you" happened to say. Safe to repeat: a value
    already there is skipped, so is one an author set (an edit outranks the file), and one
    the narration wrote first is replaced once, by the higher authority."""
    if not player or player not in store.canon.entities:
        return []
    return seed_looks(store, player, player_text, turn=turn)


def seed_looks(store, entity: str, text: str, *, turn: int = 0) -> list[tuple[str, str]]:
    """The shared core of seed_player and seed_sheets: what `text` says about one entity's
    looks, written at SCENARIO authority; returns what was written as (slot, value)."""
    wrote = []
    for slot, value, quote in player_facts(text):
        key = f"identity.marks.{_slugify(value)}" if slot == "identity.marks" else slot
        ivs = store.canon.slots.get(entity, {}).get(key)
        live = ivs[-1] if ivs and ivs[-1].end_id is None else None
        if live is not None and (live.value == value
                                 or AUTHORITY[live.authority] >= AUTHORITY["scenario"]):
            continue
        try:
            store.append(kind="fact_established", entity=entity, slot=key, value=value,
                         authority="scenario", turn=turn, span=quote)
        except LedgerError:
            continue                      # e.g. a turn before the ledger's last: next pass
        wrote.append((key, value))
    return wrote


# The first narrator turns of a story: a sheet that already exists then was written by the
# author or came with the world, not folded out of the narration (nothing has been folded yet).
AUTHORED_UNTIL = 3
_VISUAL = re.compile(r"\*\*Visuals?:?\*\*:?\s*(.*?)(?=\*\*[A-Z][^*\n]{0,30}:?\*\*|\Z)", re.DOTALL)


def sheet_looks(body: str) -> str:
    """The part of a character sheet that describes looks: the text after its **Visual:** label.
    Nothing when there is no such label. The rest of a sheet (mentality, voice, a fold's prose)
    is never read for looks, because "hair" in a sentence about a habit is not a trait."""
    m = _VISUAL.search(body or "")
    return " ".join(m.group(1).split()) if m else ""


def seed_sheets(store, entries, player: str | None = None, *, turn: int = 0) -> dict[str, list[tuple[str, str]]]:
    """Write what each character sheet's Visual line says into the ledger at SCENARIO authority,
    the same way seed_player does for player.md, and return what was written per entity.

    Measured in the first long play-through (an invented story, a local 4B Writer, 240 turns):
    a character's sheet said green eyes, the Writer's first narration said dark, first write wins,
    and the card then told the Writer "dark" for the rest of the story. The sheet the author wrote
    is the better first write. The caller decides WHEN this is safe (only while a story is new, see
    AUTHORED_UNTIL): a sheet a fold wrote from the narration, seeded as if authored, would lock in
    whatever the narrator drifted to."""
    out: dict[str, list[tuple[str, str]]] = {}
    for e in entries:
        if e.slug == player or e.slug not in store.canon.entities:
            continue
        looks = sheet_looks(e.body)
        wrote = seed_looks(store, e.slug, looks, turn=turn) if looks else []
        if wrote:
            out[e.slug] = wrote
    return out


def reads_anyone(canon, prose: str, player: str | None, before: str = "") -> bool:
    """Is there anyone in this passage worth sending to the Scribe? Someone named; the
    player when the passage speaks to "you" (a story told in the second person names the
    protagonist almost never); or a "she" or "he" when the turns just before name someone,
    because that is who a pronoun-only passage is about."""
    if mentions(canon, prose):
        return True
    toks = set(_tokens(prose))
    if player and toks & YOU_WORDS:
        return True
    return bool(toks & (F_WORDS | M_WORDS) and before and mentions(canon, before))


class GenderVotes:
    """Gender, read from the story as it is replayed. Each processed turn records its own
    votes in its row, so an undo that drops rows drops their votes, and a replay from any
    turn rebuilds the same genders (they are a function of the turns before it)."""

    def __init__(self, rows=()):
        self.total: dict[str, list[int]] = {}
        for row in rows:
            self.add(row.get("votes"))

    def add(self, votes) -> None:
        for eid, (he, she) in (votes or {}).items():
            t = self.total.setdefault(eid, [0, 0])
            t[0] += he
            t[1] += she

    def genders(self) -> dict[str, str]:
        return genders_from(self.total)


def passage_who(canon, prose: str, *, votes: GenderVotes, player: str | None,
                before: list[str], player_is: str | None = None) -> Who:
    """The validator's view of this turn, from the turns replayed so far. `player_is` is the
    player's gender when player.md states it, and wins over the votes."""
    genders = votes.genders()
    if player and player_is:
        genders[player] = player_is
    return make_who(canon, prose, genders=genders, player=player,
                    before="\n".join(before[-BEFORE_TURNS:]))


BEFORE_TURNS = 5        # narrator turns before this one that a pronoun may look back into


# --- one turn ---------------------------------------------------------------------
def skipped_row(idx: int) -> dict:
    return {"turn": idx, "skipped": True, "seconds": 0.0}


def turn_row(idx: int, rep, votes: dict | None = None) -> dict:
    """What happened to one turn, as plain counts. `votes` is the turn's own gender votes
    ({entity: [he, she]}), kept so an undo takes them away with the turn."""
    reasons = Counter(d.reason for d in rep.decisions if d.reason)
    via = Counter(d.via for d in rep.decisions if d.via and d.status == "commit")
    extra = {**({"votes": votes} if votes else {}), **({"via": dict(via)} if via else {})}
    return {**extra, "turn": idx, "skipped": False,
            "status": rep.extraction.status,
            "error": rep.extraction.error[:120],
            "claims": len(rep.extraction.claims),
            "rejected_shape": len(rep.extraction.rejects),
            "decisions": dict(Counter(d.status for d in rep.decisions)),
            "reasons": dict(reasons),
            "seconds": round(rep.extraction.seconds, 2)}


# --- reading canon back -----------------------------------------------------------
def identity_history(canon, eid: str) -> dict:
    """Values and counts only. An interval also holds the quoted evidence sentence,
    which is the story's own prose, so it is deliberately left out."""
    out = {}
    for slot, ivs in canon.slots.get(eid, {}).items():
        if slot.startswith("identity."):
            out[slot] = [{"value": iv.value, "from_turn": iv.start_turn,
                          "confirmations": iv.confirmations,
                          "current": iv.end_id is None} for iv in ivs]
    return out


def identity_table(canon) -> list[dict]:
    """Every character's CURRENT identity values, with when they were first written
    and how often they were repeated. A fixture covers a handful of facts; this is
    the whole picture, and the way to see a wrong value the Scribe wrote first and
    canon then defended (first write wins). Values and turn numbers only."""
    rows = []
    for eid, e in canon.entities.items():
        fields, marks = {}, []
        for slot, ivs in identity_history(canon, eid).items():
            live = [h for h in ivs if h["current"]]
            if not live:
                continue
            h = live[-1]
            if slot.startswith("identity.marks."):
                marks.append(h["value"])
            else:
                fields[slot.split(".", 1)[1]] = [h["value"], h["from_turn"],
                                                 h["confirmations"]]
        if fields or marks:
            rows.append({"entity": eid, "name": e["name"], "fields": fields,
                         "marks": marks})
    return rows


def state_ages(canon, now: int, windows: dict) -> dict:
    """For each state field: how many characters have a current value, how old those are
    (turns since the story last stated them) and how many are past `windows[field]`, the
    age at which a card would leave them out. Counts and ages only. It is the evidence for
    moving a window: a coat still worn 150 turns on shows as old, and so does a place that
    stopped being true."""
    out = {}
    for key, window in windows.items():
        ages = sorted(now - seen for e in canon.entities
                      if (seen := canon.last_seen(e, f"state.{key}")) is not None)
        out[key] = {"values": len(ages), "window": window,
                    "past_window": sum(1 for a in ages if a > window),
                    "median_age": ages[len(ages) // 2] if ages else None}
    return out


def totals(rows: dict, canon) -> dict:
    ran = [r for r in rows.values() if not r.get("skipped")]
    status, decisions, reasons, via = Counter(), Counter(), Counter(), Counter()
    for r in ran:
        status[r["status"]] += 1
        decisions.update(r.get("decisions", {}))
        reasons.update(r.get("reasons", {}))
        via.update(r.get("via", {}))
    secs = [r["seconds"] for r in ran]
    identity_owners = {e for e, slots in canon.slots.items()
                       if any(s.startswith("identity.") for s in slots)}
    return {
        "narrator_turns": len(rows), "sent_to_model": len(ran),
        "skipped_nobody_named": len(rows) - len(ran),
        "scribe_status": dict(status), "decisions": dict(decisions),
        "reasons": dict(reasons.most_common(12)), "via": dict(via),
        "claims": sum(r.get("claims", 0) for r in ran),
        "seconds_mean": round(sum(secs) / len(secs), 2) if secs else 0,
        "seconds_total": round(sum(secs), 1),
        "ledger_records": canon.last_id, "entities": len(canon.entities),
        "entities_with_identity": len(identity_owners),
        "conflicts_recorded": len(canon.conflicts),
    }
