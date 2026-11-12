"""Author-given character traits: strengths, weaknesses, a personality type and goals (D-032).

The author states these once, in the Plan panel, and they are the author's: the fold never rewrites them. They
live where everything about a character lives, as header lines of the character's entry (Markdown is the source
of truth, invariant 7):

    ## Odile Marsh  {#odile}
    importance: 4
    strengths: reads a room in seconds; fast with a knife
    weaknesses: cannot lie to a child; afraid of deep water
    personality: ISTJ, a stoic who keeps her promises
    goals: clear her brother's name; get out of the Ring alive
    wants: ...            <- live, kept by the fold (what they are after RIGHT NOW)

So the Writer reads them in the sheet it is already given when the character is in play (the writer rules say
how to use them), the memory fold keeps them (it only rewrites status, wants and the like), the chapter planner
reads them when it plans, and a hand edit of characters.md is the same thing as the panel.

`goals` is the author's long-term goal and is not `wants`: `wants` and `motivation` are LIVE and the fold rewrites
them as the story moves; `goals` stays until the author changes it. Nothing here is a number or a rule the
engine enforces: they steer the prose and the plan.

Bounded at the boundary (the HTTP body or a hand edit): every value is one line and has a limit, and the block the
planner reads has a size cap, because anything stored on an entry is sent again with every turn it is active.
"""
from __future__ import annotations

from .memory import Entry, MemoryStore

FIELDS = ("strengths", "weaknesses", "personality", "goals")
LIMITS = {"strengths": 300, "weaknesses": 300, "personality": 80, "goals": 300}
PLAYER = "player"                 # the key of the protagonist's sheet (player.md)
BLOCK_CHARS = 2400                # the most the chapter planner reads, whatever the cast size


class CastError(ValueError):
    """A refusal the caller can show: `missing` marks an unknown character (a 404), anything else a 400."""

    def __init__(self, message: str, missing: bool = False):
        super().__init__(message)
        self.missing = missing


def clean(field: str, value) -> str:
    """One line, trimmed, within the field's limit. Raises CastError for a non-string or an over-long value:
    cutting an author's words in the middle is worse than saying no."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CastError(f"{field} must be text")
    text = " ".join(value.split())
    if len(text) > LIMITS[field]:
        raise CastError(f"{field} is limited to {LIMITS[field]} characters (this is {len(text)})")
    return text


def _sources(store: MemoryStore) -> list[tuple[str, str, Entry]]:
    """(key, file, entry): the protagonist first when player.md has a sheet, then everyone in characters.md."""
    out: list[tuple[str, str, Entry]] = []
    for e in store.entries("player.md")[:1]:
        out.append((PLAYER, "player.md", e))
    for e in store.entries("characters.md"):
        out.append((e.slug, "characters.md", e))
    return out


def _row(key: str, rel: str, e: Entry) -> dict:
    return {"key": key, "title": e.title, "player": rel == "player.md", "importance": e.importance,
            **{f: e.attrs.get(f, "") for f in FIELDS},
            "wants": e.attrs.get("wants", ""), "motivation": e.attrs.get("motivation", "")}


def roster(store: MemoryStore) -> list[dict]:
    """Everyone who can be given traits: the protagonist, then the characters by importance and name."""
    rows = [_row(k, rel, e) for k, rel, e in _sources(store)]
    head = [r for r in rows if r["player"]]
    rest = sorted((r for r in rows if not r["player"]), key=lambda r: (-r["importance"], r["title"].lower()))
    return head + rest


def set_traits(store: MemoryStore, key: str, traits: dict) -> dict:
    """Set (or, with an empty value, clear) some of one character's four fields. Fields not named are left alone,
    and so is everything else about the entry: its body, its other lines, its aliases and its importance."""
    if not isinstance(traits, dict):
        raise CastError("the traits must be an object")
    unknown = [k for k in traits if k not in FIELDS]
    if unknown:
        raise CastError(f"unknown field {unknown[0]!r}; the fields are {', '.join(FIELDS)}")
    values = {f: clean(f, v) for f, v in traits.items()}
    found = next(((rel, e) for k, rel, e in _sources(store) if k == key), None)
    if found is None:
        raise CastError(f"no such character: {key}", missing=True)
    rel, e = found
    attrs = dict(e.attrs)
    for f, v in values.items():
        if v:
            attrs[f] = v
        else:
            attrs.pop(f, None)
    store.upsert_entry(rel, Entry(e.title, e.slug, list(e.aliases), e.importance, attrs, e.body))
    return next(_row(k, r, x) for k, r, x in _sources(store) if k == key)


def traits_block(store: MemoryStore, limit: int = BLOCK_CHARS) -> str:
    """The characters who have any of the four fields, one line each, for the chapter planner. Within `limit`
    characters, with a visible count of anyone left out; empty when nobody has any."""
    lines = []
    for r in roster(store):
        got = [f"{f}: {r[f]}" for f in FIELDS if r[f]]
        if got:
            lines.append(f"- {r['title']}{' (the player)' if r['player'] else ''}: " + "; ".join(got))
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 > limit:
            out.append(f"(and {len(lines) - i} more not shown)")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)
