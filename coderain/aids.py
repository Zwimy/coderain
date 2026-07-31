"""Play-aid bounds: quick actions (ST-30) and output regex rules (ST-31).

These are ENGINE limits, not HTTP ones — 20 actions, 30 rules, a 1000-char
replacement, `ims` flags only, and a ReDoS check on every pattern. They lived in
srv/core.py, which meant the only way to set a play aid was through the web
routes; the desktop UI would have needed its own copy, and a second copy of a
bounds rule is how this repo got a greedy JSON scanner sitting next to a correct
one.
"""
from __future__ import annotations

from .memory import safe_output_regex

MAX_QUICK_ACTIONS = 20
MAX_REGEX_RULES = 30
MAX_REPLACE_CHARS = 1000


def clean_quick_actions(raw) -> list[str]:
    """Normalise quick actions from a list or a newline-separated string."""
    if isinstance(raw, str):
        raw = raw.split("\n")
    if not isinstance(raw, list):
        return []
    return [s.strip() for s in raw
            if isinstance(s, str) and s.strip()][:MAX_QUICK_ACTIONS]


def clean_regex_rules(raw) -> list[dict]:
    """Normalise output-regex rules, dropping anything unsafe or unusable.

    A non-string or ReDoS-prone pattern is dropped on save. Import re-checks at
    exec time as well, because import bypasses this cleaning layer entirely.
    """
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        find = r.get("find")
        if not isinstance(find, str) or not safe_output_regex(find):
            continue
        out.append({"find": find,
                    "replace": str(r.get("replace", ""))[:MAX_REPLACE_CHARS],
                    "flags": "".join(c for c in str(r.get("flags", "")).lower()
                                     if c in "ims")})
        if len(out) >= MAX_REGEX_RULES:
            break
    return out
