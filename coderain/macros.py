"""ST-20 authored-text macros — expanded when a prompt is assembled.

A small, SillyTavern-flavored macro pass over author-controlled text (premise,
world bible, lore bodies, the opening). The random-ish ones ({{random}}, {{roll}})
are seeded off the story seed + turn so a retry of the same turn expands them
identically — replay-safe, like the RPG dice.

Supported:
  {{user}} / {{player}}   -> the player character's name
  {{day}}                 -> current in-world day number
  {{clock}} / {{time}}    -> current in-world time string
  {{random::a::b::c}}     -> one option, chosen reproducibly
  {{roll::2d6}} / {{roll::20}} -> dice (NdM) or 1..N, reproducibly
Unknown macros are left untouched (so stray braces never get mangled).
"""
from __future__ import annotations

import random
import re

# The argument capture is `[^{}]*?` (not `.*?`): forbidding braces inside an arg
# keeps the match local, so a run of UNCLOSED `{{name::` fragments in authored text
# can't make the engine rescan to end-of-string — that was an O(n^2) hang reachable
# every turn from the assembled context.
_MACRO = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*(?:::\s*([^{}]*?))?\s*\}\}")
_DICE = re.compile(r"^(\d*)d(\d+)$", re.IGNORECASE)


def _roll(spec: str, rng: random.Random) -> str:
    spec = spec.strip()
    m = _DICE.match(spec)
    if m:
        count = max(1, min(100, int(m.group(1) or 1)))
        sides = max(1, int(m.group(2)))
        return str(sum(rng.randint(1, sides) for _ in range(count)))
    if spec.isdigit():                      # {{roll::20}} == 1..20
        return str(rng.randint(1, max(1, int(spec))))
    return spec                             # unparseable -> leave the literal


def expand_macros(text: str, *, player: str = "you", clock: str = "",
                  day: str = "", seed: int = 0, turn: int = 0) -> str:
    """Expand the supported macros in `text`. Cheap no-op when there are none."""
    if not text or "{{" not in text:
        return text
    counter = [0]                           # unique nonce per random/roll occurrence

    def sub(m: "re.Match") -> str:
        name = m.group(1).lower()
        arg = m.group(2)
        if name in ("user", "player"):
            return player
        if name == "day":
            return str(day)
        if name in ("clock", "time"):
            return clock
        if name in ("random", "roll") and arg is not None:
            counter[0] += 1
            rng = random.Random(f"{seed}-{turn}-{name}-{counter[0]}")
            if name == "random":
                opts = [o.strip() for o in arg.split("::") if o.strip()]
                return rng.choice(opts) if opts else ""
            return _roll(arg, rng)
        return m.group(0)                   # unknown -> leave untouched

    return _MACRO.sub(sub, text)
