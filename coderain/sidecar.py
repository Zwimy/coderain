"""Sidecar channel + RPG state-block defaults — CORE module (MIT).

Split out of the RPG module because the
engine needs both halves even when the paid RPG layer is absent:

- **Sidecar filtering** is leak-prevention, not mechanics: any model may emit a
  fenced ```rpg block regardless of licensing, and the reader must never see it.
  `filter_sidecar` / `strip_sidecar` / `parse_sidecar` run in EVERY mode.
- **`default_block`** keeps `state.json` shape-stable: every save carries the
  `rpg` block (inert when disabled), so saves round-trip cleanly between free
  and Pro installs.

The mechanics themselves (rolls, apply, sheet) live in `coderain.modules.rpg`.
"""
from __future__ import annotations

import json
import random
import re

from .streaming import first_json_object

# Config defaults; overridden by the `rpg:` block in config.yaml.
DEFAULT_CFG = {
    "stats": ["strength", "agility", "intelligence", "knowledge",
              "willpower", "charisma"],
    "base_hp": 20,
    "base_mana": 5,
    "xp_per_level": 100,
    "hp_per_level": 5,
    "mana_per_level": 2,
    "default_dc": 12,
    "skill_bonus": 2,   # flat bonus when the actor is trained in a named skill
}

SIDECAR_MARKER = "```rpg"
# Case-INSENSITIVE throughout. A model that answers with ```RPG used to defeat
# every check here at once: parse_sidecar returned None, strip_sidecar handed the
# whole envelope back as visible prose, and filter_sidecar diverted nothing — so
# the reader saw raw JSON and every delta in it was silently dropped.
_FENCE_RE = re.compile(r"```rpg\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


_MARKER_RE = re.compile(re.escape(SIDECAR_MARKER), re.IGNORECASE)


def find_marker(text: str, start: int = 0) -> int:
    """Index of the sidecar fence in TEXT, ignoring case. -1 when absent.

    Matched with a regex, not `text.lower().find(...)`: lower() is not
    length-preserving (İ folds to two code points), so an index into the folded
    copy drifts past the real fence. Turkish prose was enough to make
    strip_sidecar leave the fence visible while filter_sidecar diverted only
    part of the envelope — which then failed to parse, losing every delta.
    """
    m = _MARKER_RE.search(text, start)
    return m.start() if m else -1


def cfg_get(cfg: dict | None, key: str):
    if cfg and key in cfg and cfg[key] is not None:
        return cfg[key]
    return DEFAULT_CFG[key]


# --- default state block (seeded into a new story's state.json) ---
def default_block(cfg: dict | None = None) -> dict:
    stats = list(cfg_get(cfg, "stats"))
    hp = int(cfg_get(cfg, "base_hp"))
    mana = int(cfg_get(cfg, "base_mana"))
    # A flat, neutral baseline; the player/scenario tunes it in state.json / player.md.
    return {
        "enabled": False,
        "seed": random.randint(1, 2_000_000_000),
        "rolls": 0,
        "player": {
            "stats": {s: 1 for s in stats},
            "hp": hp, "hp_max": hp,
            "mana": mana, "mana_max": mana,
            "xp": 0, "level": 1,
            "conditions": [],
            "abilities": [],    # Wave 3 level-up grants ("name (stat)")
            "titles": [],
        },
        "inventory": {},    # slug -> {"qty": int, "equipped": bool}  (mirror;
                            # the item itself lives on items.md)
        "pending_grant": 0,  # level-ups awaiting an ability/title choice
        "companions": {},   # slug -> {"trust": int, "mood": str, "disposition": str}
        "enemies": {},      # slug -> {"hp": int, "hp_max": int}  (ephemeral)
        "last_check": None,
    }


# The scanner moved to streaming.py so llm.extract_json could stop using a
# greedy regex that only claimed to be brace-balanced. Re-exported under the old
# private name because rpg.py imports it from here.
_first_json_object = first_json_object


def parse_sidecar(text: str) -> dict | None:
    """Pull the {check, deltas} object out of a narrator response. Prefers the LAST
    fenced ```rpg block; falls back to a brace-balanced object after a bare marker.
    Returns None if absent/unparseable."""
    blocks = _FENCE_RE.findall(text)
    raw = blocks[-1] if blocks else None
    if raw is None:
        idx = find_marker(text)
        if idx != -1:
            raw = _first_json_object(text[idx + len(SIDECAR_MARKER):])
    if raw is None:
        return None
    try:
        obj = json.loads(raw)
    except ValueError:      # see llm.extract_json: an integer literal past
        return None         # Python's digit limit raises a BARE ValueError
    return obj if isinstance(obj, dict) else None


def strip_sidecar(text: str) -> tuple[str, dict | None]:
    """Split full narrator text into (visible prose, sidecar dict|None)."""
    sidecar = parse_sidecar(text)
    idx = find_marker(text)
    visible = text[:idx] if idx != -1 else text
    return drop_status_label(visible.rstrip())[0], sidecar


# --- the status label small models copy -------------------------------------------------------------------------------------
# The world-sidecar instruction (templates.WORLD_SIDECAR) puts a label over each of its two example blocks, "Nothing changed:"
# and "Something changed ...:". Small models copy the label into the reply, above the block they send or instead of it. In the
# long test runs it ended 74% of gemma3:4b's replies and half of Gemma 4 E4B's: the reader saw it, the transcript kept it, and
# each kept one taught the model to do it again. The instruction stays as it is (its wording is what got small models to send
# the block at all); the label is removed here instead (D-080).
#
# Removed only at the very END of a reply, when the label is alone on its line, or when the block's own JSON follows it without
# the ```rpg fence (a few replies did that, and showed the reader raw JSON). "Nothing changed." with a full stop, a sentence that
# starts with the words, and a label with more story after it are all left alone.
_LABEL_WORDS = ("nothing changed", "something changed")
_LABEL = (r"[ \t>*_#]*(?:nothing|something) changed(?:[ \t]*[—–-][^:\n]{0,80})?[ \t*_]*:[ \t*_]*")
_BLOCK_JSON = r"(?:```\w*[ \t]*\s*)?\{\s*\"(?:deltas|v|check)\""
_TRAILING_LABEL = re.compile(r"(?:\A|(?<=\n))" + _LABEL + r"(?:\s*\Z|\s*" + _BLOCK_JSON + r".*\Z)", re.IGNORECASE | re.DOTALL)
# What may still turn into the match above while a reply is arriving: the label (so far), then only space and perhaps a block.
_STILL_POSSIBLE = re.compile(r"(?:[ \t]*(?:[—–-][^:\n]{0,80})?)?[ \t*_]*(?::[ \t*_]*(?:\s*(?:`{1,3}\w*[ \t]*\s*)?(?:\{.*)?)?)?",
                             re.DOTALL)
_LINE_DONE = re.compile(r"(?:[ \t]*(?:[—–-][^:\n]{0,80})?)?[ \t*_]*:[ \t*_]*\n\s*")     # a label line that has ended


def drop_status_label(text: str) -> tuple[str, str]:
    """(`text` without a leftover status label at its end, what was removed or "")."""
    kept, gone = text, ""
    while True:                                   # a model that wrote it twice loses both
        m = _TRAILING_LABEL.search(kept)
        if m is None:
            return kept, gone
        gone = kept[m.start():] + gone
        kept = kept[:m.start()].rstrip()


def _could_become_label(rest: str) -> bool:
    """Could `rest`, text from the start of a line, still turn out to be the label (and nothing but its block) at the reply's end?"""
    text = rest.lstrip(" \t>*_#")
    low = text.lower()
    for words in _LABEL_WORDS:
        if words.startswith(low):                 # the words are still arriving (or only decoration so far)
            return True
        if low.startswith(words):
            after = text[len(words):]
            if _STILL_POSSIBLE.fullmatch(after):
                return True
            done = _LINE_DONE.match(after)        # a second label under the first: both may go
            return bool(done) and _could_become_label(after[done.end():])
    return False


def filter_status_label(chunks, removed: list[str]):
    """Stream prose, holding back any line that may be a leftover status label until what follows shows whether it is. At the
    end a real one is dropped (and put in `removed`); anything else held is released unchanged."""
    held, at_line_start = "", True
    for piece in chunks:
        if not piece:
            continue
        held += piece
        starts = ([0] if at_line_start else []) + [i + 1 for i, ch in enumerate(held) if ch == "\n"]
        cut = next((p for p in starts if p < len(held) and _could_become_label(held[p:])), len(held))
        out, held = held[:cut], held[cut:]
        if out:
            at_line_start = out.endswith("\n")
            yield out
    if held:
        # `held` begins at a line start, so it is read as the tail of a reply.
        kept, gone = drop_status_label(held)
        if gone:
            removed.append(gone)
        if kept:
            yield kept


def _partial_tail(buffer: str, tag: str) -> int:
    tail = 0
    for t in range(1, len(tag)):
        # casefold the SLICE, not the whole buffer: comparing suffixes needs no
        # index arithmetic, so this stays correct for non-length-preserving folds.
        if buffer[-t:].lower() == tag[:t]:
            tail = t
    return tail


def filter_sidecar(chunks, hidden_out: list[str]):
    """Stream visible prose, diverting everything from the ```rpg fence onward into
    `hidden_out` (so the reader never sees the sidecar). Mirrors llm.filter_think's
    split-safe buffering so a marker split across chunks still gets caught."""
    buffer = ""
    started = False
    for piece in chunks:
        if not piece:
            continue
        if started:
            hidden_out.append(piece)
            continue
        buffer += piece
        idx = find_marker(buffer)
        if idx != -1:
            if buffer[:idx]:
                yield buffer[:idx]
            hidden_out.append(buffer[idx:])
            buffer, started = "", True
            continue
        tail = _partial_tail(buffer, SIDECAR_MARKER)
        safe = buffer[:-tail] if tail else buffer
        buffer = buffer[-tail:] if tail else ""
        if safe:
            yield safe
    if buffer:
        yield buffer
