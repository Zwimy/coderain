"""The lore web for the browser (D-074): what points at what, and adding or taking away a connection, in a save or a world.

A connection is written into the Markdown of the entry that states it, as the author would write it by hand: a labelled or plain tie on its
`relationships:` line (which a fold keeps, and whose note it never rewrites), an item's `holder:`, or its `links:` line. A `[[mention]]` is
part of the entry's text and is changed there.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from coderain.loreweb import HOLDS, LINK, MENTION, TIE, edges_of, fact, resolver
from coderain.memory import Entry, MemoryStore, parse_ties

from .core import _exclusive
from .pieces import _save_store, _scen_store

router = APIRouter()

NOTE_LIMIT = 120
MAX_CONNECTIONS = 40            # on one entry's `relationships:` line, added by hand


def _entries(store: MemoryStore) -> dict[str, tuple[str, Entry]]:
    """slug -> (file, entry), the first file to name a slug winning, as the engine reads them."""
    out: dict[str, tuple[str, Entry]] = {}
    for rel in store.gated_registries():
        for e in store.entries(rel):
            out.setdefault(e.slug, (rel, e))
    return out


def graph(store: MemoryStore) -> dict:
    found = _entries(store)
    by_slug = {slug: e for slug, (_rel, e) in found.items()}
    nodes = [{"slug": slug, "title": e.title, "file": rel, "type": rel.removesuffix(".md"), "hidden": e.hidden(),
              "pinned": e.pinned(), "importance": e.importance} for slug, (rel, e) in found.items()]
    edges = [{"from": edge.src, "to": edge.dst, "kind": edge.kind, "note": edge.note, "fact": fact(edge, by_slug)}
             for edge in edges_of(by_slug)]
    return {"nodes": nodes, "edges": edges}


def _pair_text(pairs: list[tuple[str, str]]) -> str:
    return "; ".join(f"{who}: {note}" if note else who for who, note in pairs)


def _pick(store: MemoryStore, body: dict) -> tuple[dict, str, str]:
    found = _entries(store)
    src, dst = str(body.get("from") or ""), str(body.get("to") or "")
    if src not in found or dst not in found:
        raise HTTPException(404, "no such entry")
    if src == dst:
        raise HTTPException(400, "an entry cannot be connected to itself")
    return found, src, dst


def connect(store: MemoryStore, body: dict) -> dict:
    """Tie `from` to `to` with an optional note. A tie already there gets the new note: the author's word wins."""
    found, src, dst = _pick(store, body)
    # `;` separates ties on the line, so a note cannot hold one
    note = " ".join(str(body.get("note") or "").split()).replace(";", ",")
    if len(note) > NOTE_LIMIT:
        raise HTTPException(400, f"keep the note under {NOTE_LIMIT} characters")
    rel, entry = found[src]
    resolve = resolver({slug: e for slug, (_r, e) in found.items()})
    pairs = parse_ties(entry.attrs.get("relationships", ""))
    for i, (who, _old) in enumerate(pairs):
        if resolve(who) == dst:
            pairs[i] = (who, note)
            break
    else:
        if len(pairs) >= MAX_CONNECTIONS:
            raise HTTPException(400, f"one entry holds at most {MAX_CONNECTIONS} ties")
        pairs.append((dst, note))
    entry.attrs["relationships"] = _pair_text(pairs)
    store.upsert_entry(rel, entry)
    return graph(store)


def disconnect(store: MemoryStore, body: dict) -> dict:
    """Take away what `from` states about `to`, of one kind."""
    found, src, dst = _pick(store, body)
    kind = str(body.get("kind") or "")
    if kind == MENTION:
        raise HTTPException(400, "a [[mention]] is part of the entry's text: edit the text to remove it")
    if kind not in (TIE, LINK, HOLDS):
        raise HTTPException(400, "unknown kind of connection")
    rel, entry = found[src]
    resolve = resolver({slug: e for slug, (_r, e) in found.items()})
    if kind == TIE:
        pairs = parse_ties(entry.attrs.get("relationships", ""))
        kept = [(who, note) for who, note in pairs if resolve(who) != dst]
        if len(kept) == len(pairs):
            raise HTTPException(404, "no such connection")
        entry.attrs["relationships"] = _pair_text(kept)
    elif kind == LINK:
        parts = [p.strip() for p in entry.attrs.get("links", "").split(",") if p.strip()]
        kept_links = [p for p in parts if resolve(p) != dst]
        if len(kept_links) == len(parts):
            raise HTTPException(404, "no such connection")
        entry.attrs["links"] = ", ".join(kept_links)
    else:
        if resolve(entry.attrs.get("holder", "")) != dst:
            raise HTTPException(404, "no such connection")
        entry.attrs.pop("holder", None)
    store.upsert_entry(rel, entry)                 # an emptied line is left out of the file (Entry.render skips empty attrs)
    return graph(store)


@router.get("/api/saves/{slug}/web")
def save_web(slug: str):
    return graph(_save_store(slug))


@router.post("/api/saves/{slug}/web/connect")
def save_web_connect(slug: str, body: dict):
    store = _save_store(slug)
    with _exclusive():
        return connect(store, body)


@router.post("/api/saves/{slug}/web/disconnect")
def save_web_disconnect(slug: str, body: dict):
    store = _save_store(slug)
    with _exclusive():
        return disconnect(store, body)


@router.get("/api/scenarios/{slug}/web")
def scenario_web(slug: str):
    return graph(_scen_store(slug))


@router.post("/api/scenarios/{slug}/web/connect")
def scenario_web_connect(slug: str, body: dict):
    store = _scen_store(slug)
    with _exclusive():
        return connect(store, body)


@router.post("/api/scenarios/{slug}/web/disconnect")
def scenario_web_disconnect(slug: str, body: dict):
    store = _scen_store(slug)
    with _exclusive():
        return disconnect(store, body)
