"""What the per-piece AI assist is told about the world (D-050).

What was wrong. `/api/assist` sent a piece assist (a character, a place, an item ...) the premise and nothing else, so a
character generated from an idea knew nothing of the world's places and factions or of the people already in it, which
the full generator's own entity stages always see. Two pieces generated one after the other could duplicate each other,
and a new character could not refer to a place that exists.

 1) roster_lines: one `[[ref:slug]] Title - status or first line` per character, place, faction and item, in that order,
    bounded in count and in line length; an empty world gives none
 2) assist_context: the premise, then a world excerpt (cut at WORLD_EXCERPT), then the roster under a header that says
    not to duplicate; a section with nothing in it is left out; the opening section of the premise is never included
 3) the route: a PIECE assist (character, location ...) is sent the world excerpt and the roster, while the world,
    premise and introduction fields keep the premise alone, because they rewrite those very texts; an unknown scenario
    still runs context-free as before
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-assist-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import generator                                              # noqa: E402
from coderain.memory import Entry                                           # noqa: E402

import server                                                               # noqa: E402
import srv.authoring                                                        # noqa: E402
from fastapi.testclient import TestClient                                   # noqa: E402

c = TestClient(server.app)


def new_save(title):
    return c.post("/api/saves", json={"title": title, "mode": "simple", "premise": "A ferry town on a saltmarsh."}).json()["slug"]


def store_for(slug):
    return server._engine(slug).store


def add(store, rel, slug, title, body="x", aliases=()):
    store.upsert_entry(rel, Entry(title=title, slug=slug, aliases=list(aliases), importance=3, attrs={}, body=body))


def test_roster_lines():
    store = store_for(new_save("Assist 1"))
    assert generator.roster_lines(store) == [] or all(l.startswith("[[") for l in generator.roster_lines(store))
    for rel in ("characters.md", "locations.md", "factions.md", "items.md"):
        for e in store.entries(rel):
            store.remove_entry(rel, e.slug)
    assert generator.roster_lines(store) == []
    add(store, "items.md", "lantern", "Brass Lantern", "A brass lantern that never goes out. It was her father's.")
    add(store, "factions.md", "the-guild", "The Guild", "The harbour guild.")
    add(store, "locations.md", "the-quay", "The Quay", "A stone quay where the ferry lands.")
    add(store, "characters.md", "odile", "Odile Marsh", "A guarded courier. She keeps a lantern close.")
    lines = generator.roster_lines(store)
    assert [l.split("]]")[0] for l in lines] == ["[[char:odile", "[[location:the-quay", "[[faction:the-guild", "[[item:lantern"], lines
    assert lines[0].startswith("[[char:odile]] Odile Marsh") and "A guarded courier." in lines[0], lines[0]
    assert lines[0].count("Odile Marsh") == 1, "the title is repeated"
    assert all(len(l) <= generator.ROSTER_LINE + 20 for l in lines)
    for k in range(generator.ROSTER_MAX + 15):
        add(store, "characters.md", f"extra-{k}", f"Extra Person {k}", "A person with a long description. " * 20)
    lines = generator.roster_lines(store)
    assert len(lines) == generator.ROSTER_MAX, len(lines)
    assert all(len(l) <= generator.ROSTER_LINE + 20 for l in lines), max(len(l) for l in lines)
    print("1. one [[ref:slug]] Title - sentence per character, place, faction and item in that order, bounded in count and length")


def test_assist_context():
    store = store_for(new_save("Assist 2"))
    for rel in ("characters.md", "locations.md", "factions.md", "items.md"):
        for e in store.entries(rel):
            store.remove_entry(rel, e.slug)
    store.write("world-bible.md", "# World bible\n\n" + "The tide governs everything in Brinewick. " * 80)
    ctx = generator.assist_context(store)
    assert "A ferry town on a saltmarsh." in ctx, ctx[:200]
    assert "WORLD (excerpt):" in ctx and "ALREADY IN THIS WORLD" not in ctx, "an empty roster must leave its section out"
    excerpt = ctx.split("WORLD (excerpt):\n", 1)[1]
    assert len(excerpt) <= generator.WORLD_EXCERPT, len(excerpt)
    store.write("world-bible.md", "# World bible\n")
    assert "WORLD (excerpt)" not in generator.assist_context(store), "an empty world bible must leave its section out"
    add(store, "characters.md", "odile", "Odile Marsh", "A guarded courier.")
    ctx = generator.assist_context(store)
    assert "ALREADY IN THIS WORLD (do not duplicate; you may refer to them):\n[[char:odile]] Odile Marsh" in ctx, ctx
    assert "## Opening" not in ctx and "{{user}}" not in ctx, "the verbatim opening leaked into the assist context"
    print("2. premise, a world excerpt cut at the limit, then the roster under its header; empty sections are left out")


class Capture:
    """Stands in for the model: records what the assist sent and answers with a usable reply for the kind asked."""

    def __init__(self):
        self.sent = []
        self.gen = {}

    def __call__(self, *a, **k):
        return self

    def complete(self, messages, **k):
        self.sent.append(messages)
        return json.dumps({"slug": "new-person", "title": "New Person", "aliases": [], "importance": 3,
                           "visual": "Tall, with raven hair and grey eyes.", "mentality": "Careful.", "voice": "Low.",
                           "world": "More world.", "premise": "More premise."})


def test_the_route():
    slug = new_save("Assist 3")
    store = store_for(slug)
    for rel in ("characters.md", "locations.md", "factions.md", "items.md"):
        for e in store.entries(rel):
            store.remove_entry(rel, e.slug)
    add(store, "characters.md", "odile", "Odile Marsh", "A guarded courier.")
    add(store, "locations.md", "the-quay", "The Quay", "A stone quay where the ferry lands.")
    store.write("world-bible.md", "# World bible\n\nThe tide governs everything in Brinewick.")
    cap = Capture()
    real = srv.authoring.LLM
    srv.authoring.LLM = cap
    try:
        r = c.post("/api/assist", json={"kind": "character", "mode": "seed", "text": "a smuggler", "scenario": slug})
        assert r.status_code == 200, r.text
        sent = cap.sent[-1][-1]["content"]
        assert "ALREADY IN THIS WORLD" in sent and "[[char:odile]] Odile Marsh" in sent and "[[location:the-quay]]" in sent, sent[:500]
        assert "The tide governs everything" in sent and "a smuggler" in sent
        r = c.post("/api/assist", json={"kind": "location", "mode": "seed", "text": "", "scenario": slug})
        assert r.status_code in (200, 502) and "ALREADY IN THIS WORLD" in cap.sent[-1][-1]["content"], "a place assist got no roster"
        for field in ("world", "premise"):
            c.post("/api/assist", json={"kind": field, "mode": "seed", "text": "x", "scenario": slug})
            sent = cap.sent[-1][-1]["content"]
            assert "ALREADY IN THIS WORLD" not in sent and "WORLD (excerpt)" not in sent, f"the {field} field was given the roster"
            assert "A ferry town on a saltmarsh." in sent, f"the {field} field lost its premise"
        # the builder sends a SCENARIO slug: the same rules on that branch of the route
        scen = c.post("/api/scenarios", json={"title": "Assist world", "premise": "A tidal town."}).json()["slug"]
        c.put(f"/api/scenarios/{scen}/pieces/characters.md", json={"entry": {
            "title": "Bram Halloran", "slug": "bram-halloran", "body": "A customs officer.", "importance": 3}})
        r = c.post("/api/assist", json={"kind": "character", "mode": "seed", "text": "", "scenario": scen})
        assert r.status_code == 200, r.text
        assert "[[char:bram-halloran]] Bram Halloran" in cap.sent[-1][-1]["content"], "a scenario piece assist got no roster"
        c.post("/api/assist", json={"kind": "world", "mode": "seed", "text": "x", "scenario": scen})
        assert "ALREADY IN THIS WORLD" not in cap.sent[-1][-1]["content"], "a scenario world field was given the roster"
        n = len(cap.sent)
        c.post("/api/assist", json={"kind": "character", "mode": "seed", "text": "a smuggler", "scenario": "no-such-world"})
        assert "ALREADY IN THIS WORLD" not in cap.sent[-1][-1]["content"] or len(cap.sent) == n, "an unknown scenario got a roster"
    finally:
        srv.authoring.LLM = real
    print("3. a piece assist sees the world excerpt and the roster; the world and premise fields keep the premise alone; "
          "an unknown scenario stays context-free")


for fn in (test_roster_lines, test_assist_context, test_the_route):
    fn()
print("\nASSIST CONTEXT TESTS PASSED")
