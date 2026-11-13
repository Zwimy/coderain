"""Who is in the scene, and what the Writer is shown about each of them.

Phase 3 of the consistency design, the half that reads canon and writes no prose.
Two jobs, both pure functions of canon plus the recent prose:

  find_scene   the cast: everyone pinned, everyone named in the last few turns, and
               everyone canon puts in the same place. A character who is standing
               in the room but has not been named for a few turns still gets their
               sheet. In the engine today an unnamed character in the scene gets
               none, which is how a described scar stops being described.
  bible        a character's identity (hair, eyes, build, age, marks), which does
               not change, rendered as one short line.
  render_card  the Scene State Card: each present character's current outfit, held
               items, injuries, mood and place, restated every turn at the end of
               the context where the Writer is about to write.

Everything here is bounded. The values come from a model through the validator and
end up in every later turn's context, so each is cut to a length, each list to a
count, and the card as a whole to a character budget. Nothing is dropped quietly:
a list that was cut says "(+N more)", and a character who did not fit is named in a
last line. A cast larger than the cap is reported in `Scene.omitted`.

Rendering is plain text with no dashes: the card is read by the Writer, which copies
what it sees, and a dash in a value would come back out in the story.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from canon.state import Canon
# The validator decides whether a passage names someone; the scene must decide the
# same way, or a claim could be accepted for a character the cast then ignores. So
# the word lists and tokeniser are shared, not copied.
from canon.validate import _STOP, _TITLES, _tokens

CARD_HEADER = "Scene state (current canon; match it and do not contradict it):"
DEFAULT_LIMIT = 6          # characters shown in full; the plan caps the scene at about six
CARD_CHARS = 2400          # about 600 tokens, the tail budget in the plan
LINE_CHARS = 360           # one character's line on the card
BIBLE_CHARS = 600          # one character's identity line
VALUE_CHARS = 80           # one value on the card
MAX_ITEMS = 6              # items of one list shown before "(+N more)"
MIN_CARD_CHARS = 200       # below this the header and footer alone do not fit
MIN_LINE_CHARS = 120       # a name (60) plus one short field and the "more" note
_MORE = "; more not shown"

# How long a state value stays on the card after the story LAST said it, in ledger
# turns (the player's turns count as well as the narrator's, so 120 is about 60 of the
# narrator's). Past it the card says nothing about that field rather than something that
# may no longer be true: unknown is honest, a coat worn 900 turns ago is not. The ledger
# keeps the value. These are guesses, to be set from the ages the shadow report shows.
FRESH_TURNS = {"outfit": 120, "held": 30, "injury": 120, "location": 40, "mood": 15}

# What the card says about a character, in the order it is written. When a line is
# too long the fields are dropped from the BOTTOM of this priority, so an injury or
# an outfit survives a mood.
_STATE = (("outfit", "wearing"), ("held", "holding"), ("injury", "injured"),
          ("mood", "mood"), ("location", "at"))
_STATE_PRIORITY = ("injury", "outfit", "held", "location", "mood")
_IDENTITY_PRIORITY = ("hair", "eyes", "marks", "accessories", "build", "age")
_IDENTITY_ORDER = ("hair", "eyes", "build", "age", "marks", "accessories")


# --- text hygiene -------------------------------------------------------------
def _clean(text, limit: int) -> str:
    """One line, no separators a value could use to forge another field, no dashes,
    cut at a word boundary. The cut is visible only as the shorter value."""
    s = str(text)
    s = re.sub(r"\s*[–—]\s*", ", ", s)           # en and em dash
    # ";" and ":" are the card's own punctuation ("Name: field; field"). A value
    # that kept them could write "Corin Hale: wearing a crown" inside someone
    # else's line, so they become commas.
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", s).replace(";", ",").replace(":", ",")
    s = re.sub(r"\s*,(?:\s*,)*\s*", ", ", " ".join(s.split())).strip(" ,")
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if " " in cut and s[limit] != " ":
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip(" ,.")


def _items(value) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def _listed(value, limit: int = VALUE_CHARS, cap: int = MAX_ITEMS) -> str:
    """The MOST RECENT `cap` items of a list, with a visible count of the rest."""
    items = [c for c in (_clean(v, limit) for v in _items(value)) if c]
    hidden = max(0, len(items) - cap)
    shown = ", ".join(items[hidden:])
    return f"{shown} (+{hidden} more)" if hidden else shown


# --- who is named -------------------------------------------------------------
def _name_words(canon: Canon) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(owners, whole): the loose words that can name an entity, with who they name.

    `owners` holds each distinctive word of an entity's NAME and any one-word alias.
    `whole` holds the words that are some entity's entire label. The words of a
    multi-word alias are not loose words ("The Old Man" must not make every
    capitalised "Old" a character); such an alias matches only as a phrase."""
    owners: dict[str, set[str]] = {}
    whole: dict[str, set[str]] = {}

    def distinct(t: str) -> bool:
        return len(t) >= 2 and t not in _STOP and t not in _TITLES

    for eid, e in canon.entities.items():
        for t in _tokens(e["name"]):
            if distinct(t):
                owners.setdefault(t, set()).add(eid)
        for label in (e["name"], *e["aliases"]):
            toks = _tokens(label)
            if len(toks) == 1 and distinct(toks[0]):
                owners.setdefault(toks[0], set()).add(eid)
                whole.setdefault(toks[0], set()).add(eid)
    return owners, whole


def mention_spans(canon: Canon, prose: str) -> list[tuple[int, int, str]]:
    """Every place the prose names a character: (start, end, entity id), in order.

    A multi-word name or alias ("Odile Marsh", "the courier") matches as a phrase in
    any case, and uses up its words. A word left over ("Odile") must be capitalised
    in the prose and identify exactly one entity: "ash" in "streaked with ash" is
    not the character Ash, and a bare "Corin" is nobody when there are two Corins,
    because a wrong match is worse than a missed one. A word that is some entity's
    whole name wins over the same word inside other names.
    """
    low = prose.lower().replace("’", "'")
    words = [(m.group(), m.start(), m.end()) for m in re.finditer(r"[a-z0-9']+", low)]
    # What _tokens makes of each word, so spans and mentions() cannot disagree.
    toks = [(_tokens(w)[:1] or [""])[0] for w, _s, _e in words]
    padded = " " + " ".join(_tokens(prose)) + " "
    caps = set(_tokens(" ".join(re.findall(r"[A-Z][\w'’-]*", prose))))
    owners, whole = _name_words(canon)
    used: set[str] = set()
    out: list[tuple[int, int, str]] = []
    for eid, e in canon.entities.items():
        for label in (e["name"], *e["aliases"]):
            want = _tokens(label)
            if len(want) < 2 or " " + " ".join(want) + " " not in padded:
                continue
            used.update(want)
            for i in range(len(toks) - len(want) + 1):
                if toks[i:i + len(want)] == want:
                    out.append((words[i][1], words[i + len(want) - 1][2], eid))
            break
    for (w, s0, e0), t in zip(words, toks):
        # Capitalised AT THIS OCCURRENCE: "Rowan" is a character, "the rowan tree" is not,
        # even in a passage that names Rowan elsewhere.
        if t in caps and t not in used and prose[s0:s0 + 1].isupper():
            ids = whole.get(t) or owners.get(t) or set()
            if len(ids) == 1:
                out.append((s0, e0, next(iter(ids))))
    return sorted(out)


def mentions(canon: Canon, prose: str) -> set[str]:
    """Entity ids the prose names (see mention_spans for what counts as a name)."""
    return {eid for _s, _e, eid in mention_spans(canon, prose)}


def _fresh(canon: Canon, eid: str, key: str, now: int | None):
    """The current value of a state field, or None when `now` is given and the story
    has not stated it for longer than FRESH_TURNS allows."""
    value = canon.current(eid, f"state.{key}")
    seen = canon.last_seen(eid, f"state.{key}")
    if now is not None and seen is not None and now - seen > FRESH_TURNS[key]:
        return None
    return value


def _place(value) -> str:
    """A place compared loosely: case, punctuation and a leading article ignored."""
    if not isinstance(value, str):
        return ""
    toks = _tokens(value)
    while toks and toks[0] in ("the", "a", "an"):
        toks = toks[1:]
    return " ".join(toks)


# --- the cast -----------------------------------------------------------------
@dataclass(frozen=True)
class Scene:
    cast: tuple[str, ...]                       # entity ids, in the order they are shown
    reasons: dict = field(default_factory=dict)  # id -> why they are in the cast
    omitted: tuple[str, ...] = ()               # wanted in the cast but past the cap
    location: str | None = None                 # the place the cast was matched against


def find_scene(canon: Canon, recent: list[str], *, pinned: tuple[str, ...] = (),
               location: str | None = None, limit: int = DEFAULT_LIMIT,
               now: int | None = None) -> Scene:
    """The characters the Writer must be shown. `recent` is the last few turns of
    prose, oldest first; the caller decides the window.

    Order: pinned (never dropped, even past `limit`, like pinned facts in the engine),
    then those named in the newest turn, then those named earlier in the window by
    how recently and how often, then anyone canon puts in the same place who was not
    named. The place is `location` if given, else the first pinned character's, else
    the best-ranked named character's. With `now`, a place the story last stated
    longer ago than FRESH_TURNS allows puts nobody anywhere.
    """
    pinned = tuple(dict.fromkeys(p for p in pinned if p in canon.entities))
    seen: dict[str, list[int]] = {}
    for i, prose in enumerate(recent):
        for eid in mentions(canon, prose):
            seen.setdefault(eid, []).append(i)
    newest = len(recent) - 1

    def made(eid: str) -> int:
        return canon.entities[eid]["created_id"]

    named = sorted((e for e in seen if e not in pinned),
                   key=lambda e: (-seen[e][-1], -len(seen[e]), made(e)))

    place = location
    if place is None:
        for eid in (*pinned, *named):
            loc = _fresh(canon, eid, "location", now)
            if isinstance(loc, str) and loc:
                place = loc
                break
    here: list[str] = []
    if place and _place(place):
        want = _place(place)
        here = [e for e in sorted(canon.entities, key=made)
                if e not in pinned and e not in seen
                and _place(_fresh(canon, e, "location", now)) == want]

    room = max(0, limit - len(pinned))
    wanted = named + here
    cast = (*pinned, *wanted[:room])
    reasons = {e: "pinned" for e in pinned}
    for e in wanted[:room]:
        reasons[e] = ("same place" if e not in seen else
                      "named in the newest turn" if seen[e][-1] == newest
                      else "named recently")
    return Scene(cast, reasons, tuple(wanted[room:]), place)


# --- one line, fitted to a budget ----------------------------------------------
def _compose(head: str, fields: dict[str, str], priority: tuple[str, ...],
             order: tuple[str, ...], budget: int) -> str:
    """`head: field; field` with the fields in `order`, within `budget` characters.

    Fields are taken from the top of `priority` and the first one that does not fit
    ends the line, so a lower-priority field never shows while a higher one is
    missing. Whenever anything was left out the line ends "more not shown", and a
    line whose first field alone is too long gets that field cut instead of being
    left empty. A line is never quietly shorter than canon.
    """
    def body(keys) -> str:
        return "; ".join(fields[k] for k in order if k in keys)

    def take(room: int) -> list[str]:
        kept: list[str] = []
        for key in priority:
            if key not in fields:
                continue
            if len(head) + 2 + len(body({*kept, key})) > room:
                break
            kept.append(key)
        return kept

    kept = take(budget)
    if len(kept) == len(fields):
        return f"{head}: {body(kept)}"
    kept = take(budget - len(_MORE))                       # leave room for the note
    if kept:
        return f"{head}: {body(kept)}{_MORE}"
    top = next(k for k in priority if k in fields)
    room = budget - len(head) - 2 - len(_MORE)
    return f"{head}: {_clean(fields[top], room)}{_MORE}"


# --- identity: what does not change --------------------------------------------
_HAS_HAIR = re.compile(r"\bhair(?:ed)?\b|\bhaired\b", re.I)
_HAS_EYES = re.compile(r"\beyes?\b|\beyed\b", re.I)


def _identity_phrase(key: str, value: str) -> str:
    """One identity fact as a plain phrase ("black hair", "dark eyes"), not a label
    ("hair: black"). Measured in the first long soak (a local 4B Writer, 240 turns): with
    `hair: black; eyes: dark` lines in the card the Writer copied that syntax into its
    prose in 153 of 210 turns, from turn 39 on, and a copied line in the history makes
    the next copy more likely. A phrase it copies still reads as prose."""
    v = _clean(value, VALUE_CHARS)
    if not v:
        return ""
    if key == "hair":
        return v if _HAS_HAIR.search(v) else f"{v} hair"
    if key == "eyes":
        return v if _HAS_EYES.search(v) else f"{v} eyes"
    if key == "age":
        return f"age {v}"
    return v                                   # build: the value is already a description


def _identity(canon: Canon, eid: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("hair", "eyes", "build", "age"):
        v = canon.current(eid, f"identity.{key}")
        if v:
            out[key] = _identity_phrase(key, v)
    marks = [(ivs[-1].start_id, ivs[-1].value)
             for slot, ivs in canon.slots[eid].items()
             if slot.startswith("identity.marks.") and ivs and ivs[-1].end_id is None]
    if marks:
        out["marks"] = _listed([v for _i, v in sorted(marks)], 60, 4)
    worn = [(ivs[-1].start_id, ivs[-1].value)
            for slot, ivs in canon.slots[eid].items()
            if slot.startswith("identity.accessories.") and ivs and ivs[-1].end_id is None]
    if worn:
        out["accessories"] = "wears " + _listed([v for _i, v in sorted(worn)], 60, 4)   # a phrase, like the others (D-029)
    return {k: v for k, v in out.items() if v}


def bible(canon: Canon, eid: str, *, max_chars: int = BIBLE_CHARS,
          hide: frozenset | set = frozenset()) -> str:
    """One character's identity as a line. Fields nobody has stated are left out,
    not marked unknown: an "unknown" invites the Writer to invent, and the first
    thing it invents becomes canon. `hide` names fields to leave out because the
    Writer does not need them this turn (see identity_needed)."""
    if max_chars < MIN_LINE_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_LINE_CHARS}")
    e = canon.entities[eid]
    aliases = [_clean(a, 40) for a in e["aliases"][:3] if _clean(a, 40)]
    head = _clean(e["name"], 60) + (f" (also called {', '.join(aliases)})" if aliases else "")
    have = {k: v for k, v in _identity(canon, eid).items() if k not in hide}
    if not have:
        return head
    return _compose(head, have, _IDENTITY_PRIORITY, _IDENTITY_ORDER, max_chars)


# --- identity only when it matters -------------------------------------------------
_LOOK_NOUNS = {"hair": ("hair", "haired"), "eyes": ("eyes", "eye", "eyed")}
_ASKS_ABOUT_LOOKS = re.compile(
    r"\b(hair|eyes?|face|looks?|looking|stud(?:y|ies|ying)|appearance|describe|notice|stares?|staring|gaze|"
    r"examine|scars?|tattoos?|marks?|jewel\w*|necklaces?|earrings?|bracelets?|accessor\w+)\b", re.IGNORECASE)


def _identity_raw(canon: Canon, eid: str) -> dict[str, list[str]]:
    """The values behind `_identity`, not yet turned into phrases: field -> values."""
    out: dict[str, list[str]] = {}
    for key in ("hair", "eyes", "build", "age"):
        v = canon.current(eid, f"identity.{key}")
        if v:
            out[key] = [str(v)]
    marks = [ivs[-1].value for slot, ivs in canon.slots[eid].items()
             if slot.startswith("identity.marks.") and ivs and ivs[-1].end_id is None]
    if marks:
        out["marks"] = [str(m) for m in marks]
    worn = [ivs[-1].value for slot, ivs in canon.slots[eid].items()
            if slot.startswith("identity.accessories.") and ivs and ivs[-1].end_id is None]
    if worn:
        out["accessories"] = [str(w) for w in worn]
    return out


def _drifted(canon: Canon, eid: str, texts) -> set[str]:
    """Hair or eyes that `texts` state for this character with a colour that is not canon's: a sentence
    that names exactly this character and nobody else, a hair or eye word, and a colour near it that
    says something else (same_value is generous: "black" is "raven"). Only colours are judged: a build
    or an age is worded too many ways to call a difference a drift."""
    from canon.shape import _COLOURS
    from canon.validate import same_value
    out: set[str] = set()
    for slot, nouns in _LOOK_NOUNS.items():
        value = canon.current(eid, f"identity.{slot}")
        if not value:
            continue
        for text in texts:
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
                words = _tokens(sentence)
                colours = {w for k, n in enumerate(words) if n in nouns
                           for w in words[max(0, k - 4):k + 9] if w in _COLOURS}
                if colours and not any(same_value(str(value), c) for c in colours) \
                        and mentions(canon, sentence) == {eid}:
                    out.add(slot)
    return out


def identity_needed(canon: Canon, cast, texts, action: str = "") -> dict[str, set[str]]:
    """Per character, the identity fields the card should show THIS turn. Everything else is left out.

    The card exists to restore what has scrolled out of context and to correct drift, so a look is shown
    only when one of these holds: the character is not named anywhere in `texts` (the verbatim turns the
    prompt already carries, plus the player's action), so the Writer has nothing recent about them; the
    player's action names them and asks about looks ("I study Odile's hair"); or `texts` state a
    different colour for them (drift in the context is corrected where it is read).

    Why not list the looks every turn: in the first long soak, a card that listed every look every turn
    made a 4B Writer name a hair or eye colour in 3.5 sentences a turn (0.3 with the card off) and
    27% of the wording of a turn repeated the previous turn's (2% off). Leaving out the ones that were
    already stated in the recent turns cut that only to 2.8 and 22%; what the Writer did not need to be told
    was most of them. Rewording the header ("reference only, do not restate") made it WORSE (3.7 look
    sentences a reply against 2.9, and 1.4 with no card), so the lever is whether a look is offered at all."""
    texts = [t for t in texts if t]
    named: set[str] = set()
    for t in texts:
        named |= mentions(canon, t)
    asked = mentions(canon, action) if action and _ASKS_ABOUT_LOOKS.search(action) else set()
    out: dict[str, set[str]] = {}
    for eid in cast:
        raw = set(_identity_raw(canon, eid))
        if not raw:
            out[eid] = set()
        elif eid not in named or eid in asked:
            out[eid] = raw
        else:
            out[eid] = _drifted(canon, eid, texts) & raw
    return out


def bibles(canon: Canon, scene: Scene) -> str:
    return "\n".join(bible(canon, e) for e in scene.cast)


# --- state: what changes -------------------------------------------------------
def _state(canon: Canon, eid: str, now: int | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, label in _STATE:
        v = _fresh(canon, eid, key, now)
        if v is None:
            continue
        text = _listed(v) if isinstance(v, (list, tuple)) else _clean(v, VALUE_CHARS)
        if text:
            out[key] = f"{label} {text}"
    return out


def card_line(canon: Canon, eid: str, *, max_chars: int = LINE_CHARS,
              now: int | None = None) -> str:
    """One character's current state, or '' when canon records none (or, with `now`,
    none the story has stated recently enough)."""
    if max_chars < MIN_LINE_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_LINE_CHARS}")
    have = _state(canon, eid, now)
    if not have:
        return ""
    return _compose(_clean(canon.entities[eid]["name"], 60), have, _STATE_PRIORITY,
                    tuple(k for k, _l in _STATE), max_chars)


def render_card(canon: Canon, scene: Scene, *, max_chars: int = CARD_CHARS,
                line_chars: int = LINE_CHARS, now: int | None = None) -> str:
    """The Scene State Card, never longer than `max_chars`. A character whose line
    does not fit is named in a last line instead of being dropped without a word."""
    if max_chars < MIN_CARD_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_CARD_CHARS}")
    lines = [(e, card_line(canon, e, max_chars=line_chars, now=now)) for e in scene.cast]
    lines = [(e, text) for e, text in lines if text]
    # Characters past the cast cap are named too, but only when canon has something
    # to say about them: naming a blank is noise.
    extra = [e for e in scene.omitted if card_line(canon, e, max_chars=line_chars, now=now)]
    if not lines and not extra:
        return ""
    footer_room = 130                       # the footer is never longer than this
    body, used, left = [], len(CARD_HEADER), []
    for n, (eid, text) in enumerate(lines):
        # Once anything is left out, or anything follows, room must stay for the
        # footer that names them; otherwise the footer would overrun the budget.
        footer_needed = bool(left) or n < len(lines) - 1 or bool(extra)
        reserve = footer_room + 1 if footer_needed else 0
        if used + 1 + len(text) + reserve <= max_chars:
            body.append(text)
            used += 1 + len(text)
        else:
            left.append(eid)
    left += extra
    out = [CARD_HEADER, *body]
    if left:
        names = [_clean(canon.entities[e]["name"], 40) for e in left]
        lead = "Also present, state not shown for space: "
        text = lead + ", ".join(names) + "."
        if len(text) > footer_room:
            text = lead + f"{len(names)} more."
        out.append(text)
    return "\n".join(out)
