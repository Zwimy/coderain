"""Item 6: attribute baselines in Markdown + NPC stats.

- Entry.stats() parses `stats: strength 3, agility 1` (and `name: value`).
- Save-open sync: player.md `stats:` overwrites state.json baselines (md wins);
  a player.md WITHOUT a stats line gets the current json stats written into it.
- NPC-actor checks: `check.actor: slug` rolls with that NPC's stats + skills;
  unknown actor falls back to the player.
"""
import os, sys, shutil, tempfile
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.modules import rpg as rpg_mod
from coderain.config import load_config
from coderain.memory import Entry, Library

cfg = load_config()
root = os.path.join(tempfile.gettempdir(), "se_statsmd")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)

# ---- 1) Entry.stats() parsing ----
e = Entry(title="X", slug="x",
          attrs={"stats": "strength 3, agility 1, willpower: 2, bogus, luck seven"})
assert e.stats() == {"strength": 3, "agility": 1, "willpower": 2}, e.stats()
assert Entry(title="X", slug="x").stats() == {}
print("1) Entry.stats() parses `name value` / `name: value`, skips junk")

# ---- 2) json -> md: fresh save writes its baselines INTO player.md ----
slug = lib.create_story("SM", "A duelist.")
store = lib.store(slug)                       # sync runs on open
players = store.entries("player.md")
assert players and players[0].stats().get("strength") == 1, players[0].attrs
assert "stats:" in store.read("player.md")
print("2) json baselines written into player.md when the line was missing")

# ---- 3) md -> json: editing player.md wins on next open ----
p = players[0]
p.attrs["stats"] = "strength 4, agility 2"
store.upsert_entry("player.md", p)
store2 = lib.store(slug)                      # reopen -> sync
st = store2.rpg_state()["player"]["stats"]
assert st["strength"] == 4 and st["agility"] == 2, st
assert st["charisma"] == 1                    # unlisted stats keep their json value
print("3) player.md stats overwrite state.json baselines on open (md wins)")

# ---- 4) NPC-actor check uses the NPC's stats + skills ----
store2.upsert_entry("characters.md", Entry(
    title="Kaelen", slug="kaelen",
    attrs={"stats": "agility 5", "skills": "blade (strength)"}))
rs = store2.rpg_state(); rs["enabled"] = True; rs["seed"] = 3
store2.set_rpg_state(rs)

rpg_mod.apply(store2, {"check": {"stat": "agility", "dc": 30, "actor": "kaelen"}},
              cfg.rpg)
lc = store2.rpg_state()["last_check"]
assert lc["actor"] == "kaelen" and lc["mod"] == 5, lc          # NPC agility 5

rs = store2.rpg_state(); rs["rolls"] = 0; store2.set_rpg_state(rs)
rpg_mod.apply(store2, {"check": {"stat": "agility", "dc": 30}}, cfg.rpg)
lc_p = store2.rpg_state()["last_check"]
assert "actor" not in lc_p and lc_p["mod"] == 2, lc_p          # player agility 2
print("4) actor check: kaelen rolls +5, player rolls +2 (same seed)")

# NPC skill bonus stacks on the NPC's stat
rs = store2.rpg_state(); rs["rolls"] = 0; store2.set_rpg_state(rs)
rpg_mod.apply(store2, {"check": {"stat": "strength", "dc": 30, "actor": "kaelen",
                                 "skill": "blade"}}, cfg.rpg)
assert store2.rpg_state()["last_check"]["mod"] == 2, \
    store2.rpg_state()["last_check"]   # kaelen strength 0 + blade bonus 2
print("5) NPC skill bonus applies on the NPC's own check")

# ---- 6) unknown actor falls back to the player ----
rs = store2.rpg_state(); rs["rolls"] = 0; store2.set_rpg_state(rs)
rpg_mod.apply(store2, {"check": {"stat": "agility", "dc": 30, "actor": "ghost"}},
              cfg.rpg)
lc = store2.rpg_state()["last_check"]
assert "actor" not in lc and lc["mod"] == 2, lc
print("6) unknown actor slug -> player roll")

print("\nSTATS-IN-MARKDOWN TESTS PASSED")
