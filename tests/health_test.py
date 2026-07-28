"""Silent failures must leave a trace + the context inspector (2026-07-27).

The engine is deliberately forgiving: a dead retriever, a failed fold, a bad regex
rule must never break a turn. But `except: pass` also let semantic recall report
"enabled" while doing nothing for weeks. Degrading is fine; degrading INVISIBLY is
not, so every fallback now writes to memory/health.jsonl and surfaces in the
context inspector.

Asserts:
 1) a dead embedder is logged ONCE (not once per turn — it fails every turn);
 2) a stubbed fold and an unsafe regex rule are logged;
 3) health logging never itself breaks a turn, and the log is bounded;
 4) the context inspector reports the real assembled payload and the health lines.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-health-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom "
                                            "carrying a sealed box."))


# ---- 1) a dead embedder is logged once ------------------------------------
cfg = load_config()
cfg.retrieval.update({"enabled": True, "embed_model": "nope", "profile": ""})
cfg.profile.base_url = "http://127.0.0.1:1/v1"          # nothing listening
store = _story("Dead")
eng = Engine(cfg, store)
if eng.retriever is not None:
    # Two failures on the SAME turn must not trip the breaker: assemble() calls
    # the retriever twice per turn whenever any entry is `semantic: true`, so
    # counting raw calls meant a single blip disabled recall for the session.
    assert eng.retriever("one", set()) == [], "a dead retriever must return []"
    assert eng.retriever("one again", set()) == []
    assert not [h for h in store.health() if h["stage"] == "semantic-recall"], \
        "two failures inside ONE turn tripped the breaker"
    for q in ("two", "three"):                    # now on later turns
        store.append_turn("player", f"turn for {q}")
        assert eng.retriever(q, set()) == [], "a dead retriever must return []"
    rec = [h for h in store.health() if h["stage"] == "semantic-recall"]
    assert len(rec) == 1, f"expected exactly ONE log line, got {len(rec)}"
    assert "returning nothing" in rec[0]["reason"] \
        or "embedding failed" in rec[0]["reason"], rec
    # ...and Settings > Check can re-arm it rather than needing a restart.
    eng.retriever.reset()
    assert not eng.retriever._failed and eng.retriever._fails == 0
    print("1) a dead embedder is logged once, not once per turn; reset re-arms")

# ---- 2) fold stub + unsafe regex are logged -------------------------------
store2 = _story("Traces")
cfg2 = load_config()
eng2 = Engine(cfg2, store2)
store2.log_degraded("fold", "scene 3 produced no summary")
ws = store2.world_state()
ws["regex_rules"] = [{"find": "(a+)+b", "replace": "x"}]   # catastrophic backtrack
store2.set_world_state(ws)
out = eng2._apply_output_regex("aaab")
assert out == "aaab", "an unsafe rule must leave the text untouched"
stages = {h["stage"] for h in store2.health()}
assert {"fold", "output-regex"} <= stages, stages
print("2) a stubbed fold and an unsafe regex rule both leave a trace")

# ---- 3) never breaks a turn; bounded --------------------------------------
for i in range(260):
    store2.log_degraded("spam", f"entry {i}")
lines = (Path(store2.dir) / "memory" / "health.jsonl").read_text(
    encoding="utf-8").splitlines()
assert len(lines) <= 200, f"health log is unbounded: {len(lines)} lines"
assert len(store2.health(limit=5)) == 5, "health() ignores its limit"
assert store2.health()[0]["stage"] == "spam", "health() is not newest-first"
# a store whose dir is gone must not raise
gone = _story("Gone")
shutil.rmtree(gone.dir, ignore_errors=True)
gone.log_degraded("x", "y")                    # must not raise
print("3) the log is bounded, newest-first, and never raises")

# ---- 4) the context inspector ---------------------------------------------
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(server.app)
slug = c.post("/api/saves", json={
    "title": "Inspect", "mode": "simple",
    "premise": "A lighthouse keeper answers letters from a ship that sank."}).json()["slug"]
r = c.get(f"/api/saves/{slug}/context")
assert r.status_code == 200, r.text
d = r.json()
for key in ("model", "brain", "budget_tokens", "system_chars", "approx_tokens",
            "budget_used_pct", "sections", "semantic_recall", "health",
            "history_msgs", "lore_check"):
    assert key in d, f"inspector is missing {key}"
titles = [s["title"] for s in d["sections"]]
assert any(t.startswith("Premise") for t in titles), titles
assert d["approx_tokens"] > 0 and d["system_chars"] > 0
assert d["sections"] == sorted(d["sections"], key=lambda s: -s["chars"]), \
    "sections should be biggest-first (that's the point)"
# entry headings belong to their section, not split out as sections of their own
assert not any("{#" in t for t in titles), titles
print(f"4) inspector: {len(titles)} sections, {d['approx_tokens']} tokens, "
      f"{d['budget_used_pct']}% of budget")

shutil.rmtree(HOME, ignore_errors=True)
print("\nHEALTH + INSPECTOR TESTS PASSED")
