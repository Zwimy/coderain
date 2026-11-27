"""The lore web (D-074): every way one entry points at another, as one graph, walked both ways.

The files already say "this entry points at that one" in four ways: a `relationships:` line (on any entry), an item's `holder:`, a `links:`
line, and a `[[slug]]` reference in the text. Each was followed differently or not at all, and only the way it was written: naming the person
who carries the key never brought the key. Here they are one set of edges, read from the Markdown every time (nothing is stored, so nothing can
fall out of step with the files) and walked in both directions. A fact is never turned around: it is said in the direction its file states it
("Brass lamp key is held by Hollis Wren"), whichever end the story named.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import templates
from .memory import _LINK_RE, Entry, name_key

HOLDS, TIE, LINK, MENTION = "holds", "tie", "link", "mention"
STRENGTH = {HOLDS: 0, TIE: 1, LINK: 2, MENTION: 3}
# A mention is one entry naming another in its prose: it is drawn, and referenced as before, but never walked. Half the entries mention the
# town, and following a mention back would bring all of them whenever the town is named.
FOLLOWED = (HOLDS, TIE, LINK)


@dataclass(frozen=True)
class Edge:
    src: str                    # the entry whose file states it
    dst: str                    # the entry it points at
    kind: str
    note: str = ""              # a tie's note, e.g. "his sister"


def resolver(by_slug: dict[str, Entry]):
    """A function that turns what a file wrote (a slug, or a name or alias) into a slug of `by_slug`, or None. A reference that names no
    entry is left out, never guessed."""
    titles: dict[str, str] = {}
    for slug, e in by_slug.items():
        for name in [e.title, *e.aliases]:
            titles.setdefault(name_key(name), slug)

    def resolve(raw: str) -> str | None:
        slug = templates.slugify(raw)
        return slug if slug in by_slug else titles.get(name_key(raw))
    return resolve


def edges_of(by_slug: dict[str, Entry]) -> list[Edge]:
    """Every edge between two entries of `by_slug`, in the order the files state them. No edge from an entry to itself, one edge per kind
    between the same two in the same direction, and no mention where the same entry already points there more strongly."""
    resolve = resolver(by_slug)
    out: list[Edge] = []
    for slug, e in by_slug.items():
        stated: list[tuple[str, str, str]] = []
        holder = e.attrs.get("holder", "").strip()
        if holder:
            stated.append((holder, HOLDS, ""))
        stated += [(other, TIE, note) for other, note in e.relationships()]
        stated += [(other, LINK, "") for other in e.links()]
        stated += [(ref, MENTION, "") for ref in _LINK_RE.findall(e.body)]
        seen: set[tuple[str, str]] = set()
        pointed: set[str] = set()
        for raw, kind, note in stated:                     # strongest kinds first, so `pointed` is complete before the mentions
            dst = resolve(raw)
            if dst is None or dst == slug or (dst, kind) in seen or (kind == MENTION and dst in pointed):
                continue
            seen.add((dst, kind))
            pointed.add(dst)
            out.append(Edge(slug, dst, kind, note))
    return out


def neighbours(slug: str, edges: list[Edge], kinds=FOLLOWED) -> list[tuple[Edge, str, bool]]:
    """(edge, the other end, whether this entry states it) for every edge touching `slug`: what this entry states first, then what others state
    about it, each strongest kind first and otherwise in file order. What the entry states comes first so that a crowded web still brings
    what the one-way pass brought before."""
    found = [(e, e.dst, True) for e in edges if e.src == slug and e.kind in kinds]
    found += [(e, e.src, False) for e in edges if e.dst == slug and e.kind in kinds]
    return sorted(found, key=lambda item: (not item[2], STRENGTH[item[0].kind]))


def fact(edge: Edge, by_slug: dict[str, Entry]) -> str:
    """The edge as one sentence, in the direction its file states it."""
    a, b = by_slug[edge.src].title, by_slug[edge.dst].title
    if edge.kind == HOLDS:
        return f"{a} is held by {b}"
    if edge.kind == TIE:
        return f"{a} is tied to {b}" + (f" ({edge.note})" if edge.note else "")
    if edge.kind == LINK:
        return f"{a} is linked to {b}"
    return f"{a} mentions {b}"
