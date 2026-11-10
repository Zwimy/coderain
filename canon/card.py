"""What the Writer is shown: the identity lines and the Scene State Card, built from a
SNAPSHOT of the shadow ledger (D-027).

Everything before this only observed. This is the step that reads canon back into a
prompt, so it is written around what can go wrong when it does:

  * It never touches shared state. The background reader (coderain/canon_shadow.py)
    appends to the live ledger on its own thread, and a turn must never wait for it.
    So the reader PUBLISHES an immutable snapshot (the records so far, a hash of each
    narrator turn it has read) and this module works only from that. Records are
    frozen, so a snapshot cannot change under a reader.

  * It never shows a fact from a turn that is gone. After an undo, a retry or a swipe
    the ledger still holds what the discarded reply stated until the reader catches
    up. Each narrator turn's content hash is compared with the current transcript, the
    ledger is cut back to the turn before the first one that differs, and only that
    prefix is projected. The result equals what a fresh replay of the transcript would
    give, without waiting for one.

  * It never contradicts the turns the Writer can already see. State (what someone
    wears, holds, suffers, where they are) changes every few turns, and the last turns
    ride the prompt verbatim. If the reader has not caught up to the newest narrator
    turn, a card with state could say the old coat while the last turn says the new
    one. So state is shown only when nothing is unread; identity (hair, eyes, marks)
    does not change and is always shown, from the trusted prefix.

  * It is bounded and never quiet about a cut. The whole text fits `max_chars` (about
    600 tokens), a character that does not fit is named, and a card with nothing to
    say is empty, not a header over nothing.

What it cannot do is know a recorded value is right. First write wins, so a wrong
first value is defended against the right ones. Measured on a real save, about one
identity value in twelve was wrong. That is why the flag has a preview mode that
writes the card without sending it, and why the card is what a person should read
before turning injection on.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from canon.scene import (CARD_CHARS, DEFAULT_LIMIT, MIN_CARD_CHARS, bible, find_scene,
                         render_card)
from canon.state import project

IDENTITY_HEADER = "Who they are (fixed canon; match it and do not contradict it):"
IDENTITY_LINE_CHARS = 300     # one character's identity line
IDENTITY_SHARE = 0.45         # the most of the budget identity may take when state follows
FOOTER_ROOM = 90              # the longest "not shown" line, so the cap holds


def content_hash(text: str) -> str:
    """The hash the reader records for each narrator turn it has read. One definition,
    used by both sides, so the comparison cannot drift."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class Snapshot:
    records: tuple                 # the ledger's records, frozen
    hashes: dict                   # narrator turn index -> content hash, as read
    first: int | None              # the first narrator turn the reader started at
    player: str | None             # the slug "you" means


@dataclass(frozen=True)
class Card:
    text: str = ""                 # what to send; "" when nothing should be
    reason: str = ""               # why text is empty ("" when there is a card)
    state: bool = False            # the card carries state, not only identity
    cast: tuple = ()
    unread: int = 0                # narrator turns the reader has not read yet
    trusted_through: int = 0       # the last turn the ledger is trusted through

    def row(self) -> dict:
        """Values and counts only, for the log: never a sentence of the story."""
        return {"chars": len(self.text), "reason": self.reason, "state": self.state,
                "cast": list(self.cast)[:8], "unread": self.unread,
                "trusted_through": self.trusted_through}


def coverage(snap: Snapshot, narr: dict[int, str]) -> tuple[int, int]:
    """(trusted_through, unread). `narr` maps each narrator turn of the CURRENT
    transcript to its content hash.

    The first processed turn that is missing or reads differently marks where the
    ledger stops being true. Everything from there on counts as unread, except that a
    turn which no longer exists cannot be unread: after a retry the ledger is simply
    cut back, nothing is missing, and state is still safe to show."""
    bad = [i for i, h in snap.hashes.items() if narr.get(i) != h]
    cut = min(bad) if bad else None
    trusted = (cut - 1) if cut is not None else max(snap.hashes, default=0)
    first = snap.first if snap.first is not None else 0
    unread = sum(1 for i in narr
                 if i >= first and (i not in snap.hashes or (cut is not None and i >= cut)))
    return trusted, unread


def _identity_block(canon, cast, budget: int) -> str:
    """One line per character who has any identity facts, within `budget`. A name with
    nothing known is left out (an "unknown" would invite the Writer to invent), and a
    character who does not fit is named rather than dropped without a word."""
    if budget < len(IDENTITY_HEADER) + FOOTER_ROOM + 2:
        return ""              # too small to hold the header and an honest "not shown" line
    lines = []
    for eid in cast:
        line = bible(canon, eid, max_chars=IDENTITY_LINE_CHARS)
        if ": " in line:                      # anything beyond the name
            lines.append((eid, line))
    if not lines:
        return ""

    def fit(reserve: int):
        body, used, left = [], len(IDENTITY_HEADER), []
        for eid, line in lines:
            if used + 1 + len(line) + reserve <= budget:
                body.append(line)
                used += 1 + len(line)
            else:
                left.append(eid)
        return body, left

    body, left = fit(0)
    if left:
        body, left = fit(FOOTER_ROOM + 1)     # room for the line that names the rest
    if not body and not left:
        return ""
    out = [IDENTITY_HEADER, *body]
    if left:
        names = [canon.entities[e]["name"][:40] for e in left]
        text = "Also present, identity not shown for space: " + ", ".join(names) + "."
        out.append(text if len(text) <= FOOTER_ROOM else
                   f"Also present, identity not shown for space: {len(names)} more.")
    return "\n".join(out)


def build_card(snap: Snapshot | None, narr: dict[int, str], recent: list[str], *,
               now: int, max_chars: int = CARD_CHARS, state: bool = True,
               limit: int = DEFAULT_LIMIT) -> Card:
    """The text to put in front of the Writer for the turn about to be written, or a
    Card with an empty text and the reason. `recent` is the latest prose, oldest first;
    `now` is the index of the turn being written (it ages values out of the card)."""
    if snap is None or (snap.first is None and not snap.hashes):
        return Card(reason="not_ready")
    trusted, unread = coverage(snap, narr)
    canon = project(r for r in snap.records if r.turn <= trusted)
    if not canon.entities:
        return Card(reason="no_canon", unread=unread, trusted_through=trusted)
    pinned = (snap.player,) if snap.player in canon.entities else ()
    scene = find_scene(canon, recent, pinned=pinned, now=now, limit=limit)
    show_state = state and unread == 0
    identity = _identity_block(canon, scene.cast,
                               max_chars if not show_state else int(max_chars * IDENTITY_SHARE))
    state_text = ""
    if show_state:
        room = max_chars - (len(identity) + 2 if identity else 0)
        if room >= MIN_CARD_CHARS:
            state_text = render_card(canon, scene, max_chars=room, now=now)
    text = "\n\n".join(p for p in (identity, state_text) if p)
    if not text:
        return Card(reason="nothing_to_say", cast=scene.cast, unread=unread,
                    trusted_through=trusted)
    return Card(text=text, state=bool(state_text), cast=scene.cast, unread=unread,
                trusted_through=trusted)
