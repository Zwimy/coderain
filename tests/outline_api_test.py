"""Chapter-outline HTTP API — the book-plan panel's backend (2026-07-23).

Round-trips: generate (seed), get, edit title/goal, insert a planned chapter,
reorder planned chapters, delete a planned chapter, guard rails (can't delete/move
a done or active chapter), and manual advance (roll forward with top-up).

The engine's planner LLM is swapped for a deterministic stub so no model is needed.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-outapi-")
os.environ["CODERAIN_HOME"] = HOME

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(server.app)


class PlanStub:
    def __init__(self):
        self.extend_calls = 0

    def complete(self, messages, **k):
        if "extending" in messages[0]["content"]:
            self.extend_calls += 1
            return json.dumps({"title": f"Extension {self.extend_calls}",
                               "goal": "carry the arc onward"})
        return json.dumps({"chapters": [
            {"title": f"Chapter {i}", "goal": f"goal {i}"} for i in range(1, 5)]})


slug = c.post("/api/saves", json={
    "title": "Plotted", "mode": "simple",
    "premise": "A lighthouse keeper starts receiving letters from a ship that sank "
               "a hundred years ago, and must decide whether to answer."}).json()["slug"]
eng = server._engine(slug)
stub = PlanStub()
eng.planner.llm = stub                     # deterministic; no real model


def _titles():
    return [ch["title"] for ch in c.get(f"/api/saves/{slug}/outline").json()["chapters"]]


# ---- generate (seed) ----
r = c.post(f"/api/saves/{slug}/outline/generate")
assert r.status_code == 200, r.text
chs = r.json()["chapters"]
assert len(chs) == 4 and chs[0]["status"] == "active", chs
assert all(ch["status"] == "planned" for ch in chs[1:]), chs
print("1) generate seeds 4 chapters, ch-1 active")

# ---- edit title + goal ----
r = c.put(f"/api/saves/{slug}/outline/1", json={"title": "The First Letter",
                                                "goal": "the keeper reads letter one"})
assert r.status_code == 200, r.text
chs = r.json()["chapters"]
assert chs[1]["title"] == "The First Letter" and "letter one" in chs[1]["goal"], chs[1]
print("2) edit updates a chapter's title + goal in place")

# ---- insert a planned chapter after index 1 ----
r = c.post(f"/api/saves/{slug}/outline", json={"title": "A Storm Rises",
                                               "goal": "weather traps the keeper",
                                               "after": 1})
assert r.status_code == 200, r.text
titles = _titles()
assert titles[2] == "A Storm Rises" and len(titles) == 5, titles
print("3) insert adds a planned chapter at the chosen position")

# ---- reorder: move the inserted chapter (idx 2) down ----
r = c.post(f"/api/saves/{slug}/outline/2/move", json={"dir": 1})
assert r.status_code == 200, r.text
titles = _titles()
assert titles[3] == "A Storm Rises", titles
print("4) move reorders planned chapters")

# ---- delete a planned chapter ----
r = c.delete(f"/api/saves/{slug}/outline/3")     # "A Storm Rises"
assert r.status_code == 200, r.text
assert "A Storm Rises" not in _titles(), _titles()
print("5) delete removes a planned chapter")

# ---- guard: can't delete the active chapter (index 0) ----
r = c.delete(f"/api/saves/{slug}/outline/0")
assert r.status_code == 400, r.text
r = c.post(f"/api/saves/{slug}/outline/0/move", json={"dir": 1})
assert r.status_code == 400, r.text
print("6) done/active chapters are protected from delete/reorder")

# ---- manual advance: roll forward (+ top-up via the stub) ----
before = len(_titles())
r = c.post(f"/api/saves/{slug}/outline/advance")
assert r.status_code == 200, r.text
chs = r.json()["chapters"]
assert chs[0]["status"] == "done", chs[0]
active = [ch for ch in chs if ch["status"] == "active"]
assert len(active) == 1, chs
non_done = [ch for ch in chs if ch["status"] != "done"]
assert len(non_done) == eng.planner.horizon, [(ch["title"], ch["status"]) for ch in chs]
assert stub.extend_calls >= 1, "advance did not top the plan back up"
print("7) advance: chapter done, next active, plan topped back to the horizon")

shutil.rmtree(HOME, ignore_errors=True)
print("\nOUTLINE-API TESTS PASSED")
