"""Two live-play bugs (2026-07-24).

1) A changed API key did not take effect until the app was restarted (and the old
   settings deleted). Root cause: write_env() rewrote .env, but load_dotenv()
   defaults to override=False, so os.environ kept the key loaded at PROCESS START.
   build_profile reads os.getenv, so every reload rebuilt the profile with the OLD
   key. write_env now also updates the live process environment.

2) 'validator: dropped quests.qualifier-fight-siren -> — unknown delta' and
   'dropped characters.incognito.status — unknown delta'. The model flattened
   dotted paths into delta keys (mimicking the state_changes shorthand it sees in
   scene summaries). The validator correctly refused them, but the intent was lost.
   Those keys are now un-flattened into the real deltas and validated normally.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-keyfix-")
os.environ["CODERAIN_HOME"] = HOME

import coderain.config as config_mod  # noqa: E402
from coderain.memory import Library  # noqa: E402
from coderain.validator import validate  # noqa: E402

config_mod.ROOT = Path(HOME)          # keep .env writes inside the temp home


# ---- 1) a changed key reaches the live process, no restart ------------------
KEY = "CR_TEST_API_KEY"
os.environ[KEY] = "old-key-from-boot"          # as if loaded at process start
config_mod.write_env({KEY: "brand-new-key"})

assert os.environ[KEY] == "brand-new-key", \
    f"live env still holds the stale key: {os.environ[KEY]!r}"
on_disk = config_mod.read_env().get(KEY)
assert on_disk == "brand-new-key", on_disk
print("1) write_env updates BOTH .env and the live process env")

# and the profile built afterwards carries the new key (the actual user symptom)
data = {"profiles": {"hosted": {"base_url": "https://api.example/v1",
                                "model": "some-model", "api_key_env": KEY,
                                "context_tokens": 131072}}}
prof = config_mod.build_profile(data, "hosted")
assert prof.api_key == "brand-new-key", prof.api_key
print("   a profile built after the save uses the NEW key (no restart needed)")


# ---- 2) flattened dotted delta keys are repaired, not dropped ---------------
lib = Library(os.path.join(HOME, "lib"))
store = lib.store(lib.create_story("Arena", "A qualifier bout in a neon arena."))
store.write("threads.md",
            "# Threads\n\n## Qualifier Fight: Siren {#qualifier-fight-siren}\n"
            "status: open\nimportance: 4\n\nWin the qualifier.\n")
st = store.rpg_state(); st["enabled"] = True
store.set_rpg_state(st)
ws = store.world_state()
ws["quests"] = {"qualifier-fight-siren": "active"}     # legal: active -> completed
store.set_world_state(ws)

env = {"v": 1, "deltas": {
    "quests.qualifier-fight-siren -> ": "completed",   # the exact reported key
    "characters.incognito.status": "drained but victorious",
    "flag_set": {"wf": 1},                             # a correct key, untouched
}}
clean, rejected = validate(env, store)
deltas = clean.get("deltas", {})

assert deltas.get("quest_update") == {"qualifier-fight-siren": "completed"}, deltas
assert deltas.get("npc_state", {}).get("incognito", {}).get("mood") \
    == "drained but victorious", deltas
assert deltas.get("flag_set") == {"wf": 1}, deltas
assert not rejected, rejected
print("2) dotted keys un-flattened into quest_update / npc_state; nothing dropped")

# the arrow form can also carry the state in the key itself
env2 = {"v": 1, "deltas": {"quests.qualifier-fight-siren -> completed": True}}
clean2, _ = validate(env2, store)
assert clean2.get("deltas", {}).get("quest_update") == \
    {"qualifier-fight-siren": "completed"}, clean2
print("   'quests.slug -> completed' (state in the key) also works")

# a plain wrong NAME is repaired too
env3 = {"v": 1, "deltas": {"quests": {"qualifier-fight-siren": "completed"}}}
clean3, _ = validate(env3, store)
assert clean3.get("deltas", {}).get("quest_update") == \
    {"qualifier-fight-siren": "completed"}, clean3
print("   a plain wrong name ('quests') is corrected to quest_update")

# RULES STILL APPLY: an illegal transition is still refused after repair
ws = store.world_state(); ws["quests"] = {"qualifier-fight-siren": "completed"}
store.set_world_state(ws)
clean4, rejected4 = validate(
    {"v": 1, "deltas": {"quests.qualifier-fight-siren": "active"}}, store)
assert not clean4.get("deltas"), clean4
assert any("illegal transition" in r["reason"] for r in rejected4), rejected4
print("   repair does NOT relax the rules: an illegal transition is still refused")

# a genuinely unknown delta is still reported (no silent swallowing)
_c5, rejected5 = validate({"v": 1, "deltas": {"teleport_player": "moon"}}, store)
assert any(r["delta"] == "teleport_player" for r in rejected5), rejected5
print("   a truly unknown delta is still reported")

shutil.rmtree(HOME, ignore_errors=True)
print("\nKEY-REFRESH + DELTA-REPAIR TESTS PASSED")
