"""The AI must not act/speak for the player unless allowed (2026-07-22 play-test:
'it takes a lot of action on my behalf'). Default off = a firm directive rides
every generation path; on = no directive. Settings round-trips the flag."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from coderain.config import load_config      # noqa: E402
from coderain.engine import Engine           # noqa: E402
from coderain.memory import Library          # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="cr-agency-"))
lib = Library(WORK)


def test_directive_present_by_default_absent_when_allowed():
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    store = lib.store(lib.create_story("Agency", "A town."))
    eng = Engine(cfg, store)

    cfg.generation["ai_acts_as_player"] = False
    sys_off = eng._messages([], "look")[0]["content"]
    assert "PLAYER AGENCY" in sys_off, "default must forbid acting for the player"

    cfg.generation["ai_acts_as_player"] = True
    sys_on = eng._messages([], "look")[0]["content"]
    assert "PLAYER AGENCY" not in sys_on, "allowing it must drop the directive"
    print("agency directive: present by default, gone when allowed")


def test_settings_round_trip():
    os.environ["CODERAIN_HOME"] = str(WORK / "srv")
    import importlib
    server = importlib.import_module("server")
    from fastapi.testclient import TestClient
    c = TestClient(server.app)

    s = c.get("/api/settings").json()
    assert "ai_acts_as_player" in s["generation"], "flag missing from GET"
    r = c.put("/api/settings", json={"mode": s["mode"], "local": s["local"],
              "hosted": s["hosted"],
              "generation": {"ai_acts_as_player": True}})
    assert r.status_code == 200, r.text
    assert c.get("/api/settings").json()["generation"]["ai_acts_as_player"] is True
    print("ai_acts_as_player round-trips through /api/settings")


for fn in (test_directive_present_by_default_absent_when_allowed,
           test_settings_round_trip):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nAGENCY TESTS PASSED")
