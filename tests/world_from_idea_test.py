"""A whole world from one sentence, over HTTP (D-052).

What was missing. The web app could build a world only by hand: open the builder, write a premise, then press "Generate
the rest". The full generator (a title, a premise, a world bible, factions, characters, places, items, threads and an
opening message) existed for the desktop app and the command line but had no route, so the browser could not use it.

 1) POST /api/scenarios-generate streams stage frames and a done frame carrying the new world's slug; the sentence is the
    brief the premise stage reads, the world has the generated title and pieces, and they are copied to the library
 1b) a stage that produced nothing is named in the done frame's events
 2) the idea is validated before anything runs: empty, blank, too long are 400; line breaks and runs of spaces collapse
 3) the knobs are bounded and passed through: counts clamp to 0..12, a bad count falls back to 5, only "fast" is fast,
    the type and tone are cut to length
 4) a failed premise stage sends an error frame, creates NO world and releases the lock for the next run; a generation
    already running is refused with a frame, and the generator is never called
 5) "Generate the rest" on an existing world still works through the shared streaming helper: the same frames, the same
    slug, the author's own text kept
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-worldidea-")
os.environ["CODERAIN_HOME"] = HOME

import server                                                               # noqa: E402,F401
import srv.authoring                                                        # noqa: E402
from srv import core                                                        # noqa: E402
from coderain.generator import ScenarioSpec                                 # noqa: E402
from fastapi.testclient import TestClient                                   # noqa: E402

c = TestClient(server.app)
IDEA = "A lamplighter finds out someone else has been lighting the harbour lamps."

PREMISE = {"title": "Lamp Harbour", "premise": "You keep the harbour lamps, and tonight one is already lit.",
           "world_bible": "Salt air, tall lamps, a tide that keeps its own hours.", "tone_lock": "quiet mystery",
           "factions": [{"slug": "lamp-guild", "title": "The Lamp Guild", "importance": 3, "detail": "Keepers of the lamps."}]}


def char(i):
    return {"slug": f"keeper-{i}", "title": f"Keeper {i}", "importance": 3, "status": "wary", "visual": "Weathered face.",
            "mentality": "Careful.", "voice": 'Clipped. e.g. "Mind the step."', "detail": f"Keeper {i} walks the quay."}


class Stub:
    """Answers each generator stage by its STAGE marker; remembers what the premise stage was asked."""

    def __init__(self, premise_ok=True, empty=""):
        self.premise_ok, self.empty, self.briefs, self.calls = premise_ok, empty, [], 0

    def __call__(self, *a, **k):
        return self

    def complete(self, messages, **k):
        self.calls += 1
        s = messages[0]["content"]
        if "STAGE: premise" in s:
            self.briefs.append(messages[1]["content"])
            return json.dumps(PREMISE) if self.premise_ok else "I would rather not."
        if "STAGE: characters" in s:
            return json.dumps({"characters": [char(i) for i in range(2)]})
        if "STAGE: locations" in s:
            return json.dumps({"locations": [{"slug": "the-quay", "title": "The Quay", "importance": 3,
                                              "detail": "A stone quay."}]})
        if "STAGE: items" in s:
            if self.empty == "items":
                return "{}"
            return json.dumps({"items": [{"slug": "taper", "title": "Taper", "importance": 2, "detail": "A long taper."}]})
        if "STAGE: threads" in s:
            return json.dumps({"threads": [{"slug": "the-lit-lamp", "title": "The Lit Lamp", "importance": 4,
                                            "detail": "Who lit it?"}], "canon_events": []})
        if "STAGE: introduction" in s:
            return json.dumps({"introduction": "The first lamp is already burning when you reach the quay."})
        if "STAGE: world" in s or "world" in s.lower():
            return json.dumps({"world": "More world."})
        return "{}"


def frames(response):
    out = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def worlds():
    return {w["slug"] for w in core.lib.scenarios.list()}


def run(stub, body, path="/api/scenarios-generate"):
    real = srv.authoring.LLM
    srv.authoring.LLM = stub
    try:
        return c.post(path, json=body)
    finally:
        srv.authoring.LLM = real


def test_stream_and_world():
    stub = Stub()
    before = worlds()
    r = run(stub, {"idea": IDEA, "detail": "fast", "n_npcs": 2, "n_locations": 1, "n_items": 1})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream"), r.status_code
    fs = frames(r)
    kinds = [f["t"] for f in fs]
    assert kinds[-1] == "done" and kinds.count("done") == 1 and "error" not in kinds, fs
    assert any(f["t"] == "stage" and f["text"] == "premise" for f in fs), fs
    slug = fs[-1]["slug"]
    assert slug and worlds() - before == {slug}, (slug, worlds() - before)
    assert IDEA in stub.briefs[0], "the sentence never reached the premise stage"
    full = c.get(f"/api/scenarios/{slug}/full").json()
    assert full["title"] == "Lamp Harbour" and "lamps" in full["premise"], full["title"]
    assert full["introduction"].startswith("The first lamp"), full["introduction"]
    assert [e["slug"] for e in full["pieces"]["characters.md"]] == ["keeper-0", "keeper-1"]
    assert any("library" in e for e in fs[-1]["events"]), fs[-1]
    print("1. one sentence streams its stages and ends with the new world's slug; the world and the library hold its pieces")


def test_warnings_reach_the_reader():
    r = run(Stub(empty="items"), {"idea": IDEA, "detail": "fast", "n_npcs": 1, "n_locations": 1, "n_items": 1})
    fs = frames(r)
    assert fs[-1]["t"] == "done", fs
    assert any("items" in e for e in fs[-1]["events"]), f"a stage that produced nothing was not reported: {fs[-1]}"
    print("1b. a stage that produced nothing is reported in the done frame, not hidden")


def test_validation():
    before = worlds()
    stub = Stub()
    for idea in ("", "   \n\t ", None):
        r = run(stub, {"idea": idea})
        assert r.status_code == 400, (idea, r.status_code)
    r = run(stub, {"idea": "x" * (srv.authoring.IDEA_MAX + 1)})
    assert r.status_code == 400 and str(srv.authoring.IDEA_MAX) in r.text, r.text
    r = run(stub, {"idea": "y" * srv.authoring.IDEA_MAX, "detail": "fast"})
    assert r.status_code == 200, "an idea at the limit was refused"
    assert stub.calls > 0 and worlds() - before, "the limit case did not run"
    stub2 = Stub()
    run(stub2, {"idea": "A  lamplighter\n\n  finds   a lit lamp.", "detail": "fast"})
    assert "A lamplighter finds a lit lamp." in stub2.briefs[0], stub2.briefs[0]
    print("2. empty, blank and over-long ideas are 400 and run nothing; line breaks and extra spaces collapse")


def test_knobs():
    seen = {}
    real = srv.authoring.generate_scenario

    def capture(lib, llm, spec, on_stage=None):
        seen["spec"] = spec
        return real(lib, Stub(), ScenarioSpec(premise="x", detail="fast", n_npcs=0, n_locations=0, n_items=0))
    srv.authoring.generate_scenario = capture
    try:
        run(Stub(), {"idea": IDEA, "n_npcs": 99, "n_locations": -4, "n_items": "many", "detail": "fast",
                     "type": "t" * 500, "tone": "q" * 500, "improve": 1})
        s = seen["spec"]
        assert (s.n_npcs, s.n_locations, s.n_items) == (12, 0, 5), (s.n_npcs, s.n_locations, s.n_items)
        assert s.detail == "fast" and s.improve is True and s.premise == IDEA
        assert len(s.type) == 80 and len(s.tone) == 200, (len(s.type), len(s.tone))
        run(Stub(), {"idea": IDEA, "detail": "turbo"})
        assert seen["spec"].detail == "rich" and seen["spec"].improve is False and seen["spec"].n_npcs == 5
    finally:
        srv.authoring.generate_scenario = real
    print("3. counts clamp to 0..12 (a bad one falls back to 5), only 'fast' is fast, type and tone are cut")


def test_failure_and_lock():
    before = worlds()
    r = run(Stub(premise_ok=False), {"idea": IDEA, "detail": "fast"})
    fs = frames(r)
    assert fs[-1]["t"] == "error" and "Premise generation failed" in fs[-1]["text"], fs
    assert not any(f["t"] == "done" for f in fs)
    assert worlds() == before, "a failed run left a world behind"
    assert core._gen_lock.acquire(blocking=False), "the lock was not released after a failed run"
    core._gen_lock.release()
    # the lock is held: refused, and the generator never runs
    stub = Stub()
    assert core._gen_lock.acquire(blocking=False)
    try:
        r = run(stub, {"idea": IDEA, "detail": "fast"})
    finally:
        core._gen_lock.release()
    fs = frames(r)
    assert [f["t"] for f in fs] == ["error"] and "another generation" in fs[0]["text"], fs
    assert stub.calls == 0 and worlds() == before
    print("4. a failed premise stage sends an error frame, creates no world and frees the lock; a busy lock is refused")


def test_complete_still_streams():
    slug = c.post("/api/scenarios", json={"title": "Mine", "premise": "My own premise about a quiet harbour town."}).json()["slug"]
    stub = Stub()
    r = run(stub, {"n_npcs": 1, "n_locations": 0, "n_items": 0, "detail": "fast"}, f"/api/scenarios/{slug}/complete")
    fs = frames(r)
    assert fs[-1]["t"] == "done" and fs[-1]["slug"] == slug and any(f["t"] == "stage" for f in fs), fs
    full = c.get(f"/api/scenarios/{slug}/full").json()
    assert full["premise"].startswith("My own premise"), "the author's premise was overwritten"
    assert full["title"] == "Mine"
    print("5. 'Generate the rest' on an existing world streams the same frames and keeps what the author wrote")


for fn in (test_stream_and_world, test_warnings_reach_the_reader, test_validation, test_knobs, test_failure_and_lock, test_complete_still_streams):
    fn()
print("\nWORLD FROM IDEA TESTS PASSED")
