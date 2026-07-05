"""Feature 3: character/player schema (visual · mentality · voice · skills, tiered).

Covers the structured `skills:` parser and the tiered RPG skill bonus:
- Entry.skills() parses "name (stat)" and bare "name" forms.
- rpg.skill_mod() returns the proficiency bonus only when the actor is trained,
  else 0 (missing skill, missing actor).
- apply() adds the bonus on top of the governing stat when a check names a trained
  skill, and leaves untrained/RPG-off checks unmodified.
"""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.modules import rpg as rpg_mod
from coderain.config import load_config
from coderain.memory import Entry, Library

cfg = load_config()

# ---- 1) Entry.skills() parsing ----
e = Entry(title="You", slug="player",
          attrs={"skills": "blade (strength), oath-sense (willpower), climbing"})
assert e.skills() == [("blade", "strength"), ("oath-sense", "willpower"),
                      ("climbing", None)], e.skills()
assert Entry(title="X", slug="x").skills() == []                     # no attr -> []
assert Entry(title="X", slug="x", attrs={"skills": "  ,  "}).skills() == []  # blanks
print("1) Entry.skills() parses (stat) and bare skills, ignores blanks")

# ---- 2) skill_mod: trained -> bonus, else 0 ----
root = os.path.join(tempfile.gettempdir(), "se_charschema")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("CS", "A duelist with trained hands."))

store.upsert_entry("player.md", Entry(
    title="You", slug="player", importance=5,
    attrs={"skills": "blade (strength), climbing"},
    body="**Visual:** Lean, scarred.\n**Voice:** Terse."))

assert rpg_mod.skill_mod(store, "player", "blade", cfg.rpg) == 2
assert rpg_mod.skill_mod(store, "player", "Climbing", cfg.rpg) == 2   # case-insensitive
assert rpg_mod.skill_mod(store, "player", "swim", cfg.rpg) == 0       # untrained
assert rpg_mod.skill_mod(store, "player", "", cfg.rpg) == 0           # no skill named
print("2) skill_mod: trained->+2, untrained/blank->0")

# NPC skills resolve by slug from characters.md; missing actor -> 0.
store.upsert_entry("characters.md", Entry(
    title="Kaelen", slug="kaelen", attrs={"skills": "oath-sense (willpower)"}))
assert rpg_mod.skill_mod(store, "kaelen", "oath-sense", cfg.rpg) == 2
assert rpg_mod.skill_mod(store, "ghost", "oath-sense", cfg.rpg) == 0  # no such actor
print("3) skill_mod resolves NPCs by slug; unknown actor -> 0")

# ---- 4) tiered: apply() adds the bonus to the governing stat ----
st = store.rpg_state()
st["enabled"] = True
st["seed"] = 11
st["player"]["stats"]["strength"] = 1
store.set_rpg_state(st)

rpg_mod.apply(store, {"check": {"stat": "strength", "dc": 25, "skill": "blade"}}, cfg.rpg)
trained = store.rpg_state()["last_check"]
assert trained["mod"] == 3, trained         # stat 1 + skill bonus 2
assert trained["skill"] == "blade"

st = store.rpg_state(); st["rolls"] = 0; store.set_rpg_state(st)  # reset nonce
rpg_mod.apply(store, {"check": {"stat": "strength", "dc": 25}}, cfg.rpg)
untrained = store.rpg_state()["last_check"]
assert untrained["mod"] == 1, untrained      # stat only, no skill
# same (seed,nonce) roll; the +2 is exactly the skill bonus
assert trained["total"] - untrained["total"] == 2, (trained, untrained)
print("4) apply(): trained skill adds +2 over the stat; untrained unmodified")

# ---- 5) RPG off: apply is inert, skill never consulted ----
store2 = lib.store(lib.create_story("CSoff", "A quiet scribe."))  # rpg disabled
store2.upsert_entry("player.md", Entry(title="You", slug="player",
                                       attrs={"skills": "blade (strength)"}))
assert rpg_mod.apply(store2, {"check": {"stat": "strength", "skill": "blade"}},
                     cfg.rpg) == []
assert store2.rpg_state().get("last_check") in (None, {}), "off engine rolled a check"
print("5) RPG off: apply() inert, no roll")

print("\nCHARACTER SCHEMA TESTS PASSED")
