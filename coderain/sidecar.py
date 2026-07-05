"""Sidecar channel + RPG state-block defaults — CORE module (MIT).

Split out of the Pro mechanics module (open-core, 2026-07-05) because the free
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
_FENCE_RE = re.compile(r"```rpg\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


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


def _first_json_object(s: str) -> str | None:
    """Extract the first brace-balanced {...} object (string-aware), so an
    unfenced/truncated sidecar with trailing braces isn't grabbed greedily."""
    start = s.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def parse_sidecar(text: str) -> dict | None:
    """Pull the {check, deltas} object out of a narrator response. Prefers the LAST
    fenced ```rpg block; falls back to a brace-balanced object after a bare marker.
    Returns None if absent/unparseable."""
    blocks = _FENCE_RE.findall(text)
    raw = blocks[-1] if blocks else None
    if raw is None:
        idx = text.find(SIDECAR_MARKER)
        if idx != -1:
            raw = _first_json_object(text[idx + len(SIDECAR_MARKER):])
    if raw is None:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def strip_sidecar(text: str) -> tuple[str, dict | None]:
    """Split full narrator text into (visible prose, sidecar dict|None)."""
    sidecar = parse_sidecar(text)
    idx = text.find(SIDECAR_MARKER)
    visible = text[:idx] if idx != -1 else text
    return visible.rstrip(), sidecar


def _partial_tail(buffer: str, tag: str) -> int:
    tail = 0
    for t in range(1, len(tag)):
        if buffer.endswith(tag[:t]):
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
        idx = buffer.find(SIDECAR_MARKER)
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
