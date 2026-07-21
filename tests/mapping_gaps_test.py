"""Engine features that had no web endpoint at all (2026-07-21 mapping audit).

Each of these existed in the engine (and mostly in the legacy Tk app) but was
unreachable from the main UI:
  - rule-layer overrides: editing rules in Settings changed them GLOBALLY for
    every story; there was no way to scope or revert per story.
  - raw memory files: a bad fold (wrong scene summary, false "fact") was
    permanent, because the builder only reaches world pieces.
  - retrieval/vector + memory tuning: config-file-only, so semantic recall was
    permanently OFF for anyone who never hand-edited config.yaml.
  - RPG mode was fixed at creation.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="coderain-map-")
os.environ["CODERAIN_HOME"] = HOME

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

client = TestClient(server.app)
SLUG = server.lib.saves.create("Map Run", premise="A premise.", mode="simple")


def test_raw_file_editor_round_trip():
    files = client.get(f"/api/saves/{SLUG}/files").json()["files"]
    rels = [f["rel"] for f in files]
    for must in ("memory/scenes.md", "memory/arc.md", "memory/facts.md",
                 "memory/timeline.md", "transcript.md", "state.json"):
        assert must in rels, f"{must} not exposed"

    r = client.put(f"/api/saves/{SLUG}/files/memory/facts.md",
                   json={"text": "# Facts\n\n- The sky is green.\n"})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/saves/{SLUG}/files/memory/facts.md").json()
    assert "sky is green" in got["text"], got
    print("raw memory files are listable, readable and repairable")


def test_json_file_is_validated_before_writing():
    r = client.put(f"/api/saves/{SLUG}/files/state.json",
                   json={"text": "{ not json at all "})
    assert r.status_code == 400, r.status_code
    # the good file survived
    assert json.loads(client.get(f"/api/saves/{SLUG}/files/state.json")
                      .json()["text"])
    print("bad JSON is refused instead of bricking the story")


def test_unknown_file_is_rejected():
    for bad in ("secrets.txt", "../config.yaml"):
        assert client.get(f"/api/saves/{SLUG}/files/{bad}").status_code == 404
    print("only known editable files are reachable")


def test_rule_override_scopes_to_one_story():
    before = client.get(f"/api/saves/{SLUG}/files/writer-rules.md").json()
    assert before["layer"] in ("global", "scenario"), before

    r = client.post(f"/api/saves/{SLUG}/rules/writer-rules.md/override")
    assert r.status_code == 200, r.text
    assert r.json()["layer"] == "save", r.json()

    # editing now touches only this story
    client.put(f"/api/saves/{SLUG}/files/writer-rules.md",
               json={"text": "# Just this story\nWrite tersely.\n"})
    glob = (server.lib.instructions_dir / "writer-rules.md").read_text(encoding="utf-8")
    assert "Just this story" not in glob, "the GLOBAL rule master was overwritten"

    # a second override is refused, and revert puts it back
    assert client.post(f"/api/saves/{SLUG}/rules/writer-rules.md/override"
                       ).status_code == 400
    r = client.delete(f"/api/saves/{SLUG}/rules/writer-rules.md/override")
    assert r.status_code == 200 and r.json()["layer"] != "save", r.json()
    print("rule overrides scope per story and revert cleanly")


def test_retrieval_and_memory_settings_round_trip():
    s = client.get("/api/settings").json()
    assert "retrieval" in s and "memory" in s, list(s)
    r = client.put("/api/settings", json={
        "mode": s["mode"],
        "local": s["local"], "hosted": s["hosted"],
        "retrieval": {"enabled": True, "top_k": 7, "min_similarity": 0.4},
        "memory": {"short_term_turns": 9, "context_budget_tokens": "auto"},
        "generation": {"use_memory_tool": True},
    })
    assert r.status_code == 200, r.text
    out = client.get("/api/settings").json()
    assert out["retrieval"]["enabled"] is True and out["retrieval"]["top_k"] == 7
    assert out["memory"]["short_term_turns"] == 9
    assert out["memory"]["context_budget_tokens"] == "auto"
    assert out["generation"]["use_memory_tool"] is True
    print("retrieval + memory tuning + memory tool are settable from the web")


def test_rpg_mode_can_change_after_creation():
    r = client.put(f"/api/saves/{SLUG}/mode", json={"mode": "rpg"})
    if r.status_code == 402:
        print("rpg mode gated (Pro absent) — 402 is correct")
        return
    assert r.status_code == 200, r.text
    assert client.get(f"/api/saves/{SLUG}").json()["rpg"] is True
    assert client.put(f"/api/saves/{SLUG}/mode",
                      json={"mode": "simple"}).status_code == 200
    assert client.get(f"/api/saves/{SLUG}").json()["rpg"] is False
    assert client.put(f"/api/saves/{SLUG}/mode",
                      json={"mode": "nonsense"}).status_code == 400
    print("rpg mode toggles after creation")


def test_orphan_generate_route_is_gone():
    paths = {r.path for r in server.app.routes if hasattr(r, "path")}
    assert "/api/scenarios/generate" not in paths, "dead route still registered"
    print("orphan /api/scenarios/generate removed")


for fn in (test_raw_file_editor_round_trip,
           test_json_file_is_validated_before_writing,
           test_unknown_file_is_rejected,
           test_rule_override_scopes_to_one_story,
           test_retrieval_and_memory_settings_round_trip,
           test_rpg_mode_can_change_after_creation,
           test_orphan_generate_route_is_gone):
    fn()
shutil.rmtree(HOME, ignore_errors=True)
print("\nMAPPING GAP TESTS PASSED")
