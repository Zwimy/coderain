"""Tier 2 — lorebook activation depth.

Covers the refinements layered onto Wave-2 activation:
  ST-11 trigger probability (`chance:`) — reproducible per (seed, turn, entry)
  ST-13 secondary keys (`triggers_all:` AND, `triggers_not:` NOT)
(groups ST-12, timed ST-10, semantic ST-17, recursion ST-14 append here as they land.)
"""
import os, sys, shutil, tempfile, random
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_tier2")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Depths", "A layered mystery."))

# Pin a known seed so probability rolls are reproducible inside the test.
SEED = 1234567
st = store.world_state()
st.setdefault("rpg", {})["seed"] = SEED
store.set_world_state(st)


def sysmsg(text):
    return store.assemble([], text)[0]["content"]


# ---- ST-13: secondary keys (triggers_all = AND, triggers_not = NOT) ----
store.upsert_entry("locations.md", Entry(
    "Night Market", "night-market", importance=3,
    attrs={"triggers": "market", "triggers_all": "night"},
    body="Stalls that only open after dark."))
assert "Night Market" not in sysmsg("I browse the market at noon."), \
    "triggers_all: must require 'night' too"
assert "Night Market" in sysmsg("I browse the market at night."), \
    "market + night should activate"

store.upsert_entry("characters.md", Entry(
    "The Duke", "the-duke", importance=3,
    attrs={"triggers": "duke", "triggers_not": "dead"},
    body="Alive and scheming."))
assert "The Duke" in sysmsg("I greet the duke."), "duke alone should activate"
assert "The Duke" not in sysmsg("The duke is dead in the ballroom."), \
    "triggers_not: 'dead' must suppress the entry"
print("1) ST-13 secondary keys: triggers_all (AND) + triggers_not (NOT)")

# ---- ST-11: probability boundaries + determinism ----
store.upsert_entry("items.md", Entry(
    "Never Charm", "never-charm", importance=3,
    attrs={"triggers": "charm", "chance": "0"}, body="A dud."))
store.upsert_entry("items.md", Entry(
    "Always Ring", "always-ring", importance=3,
    attrs={"triggers": "ring", "chance": "100"}, body="Reliable."))
assert "Never Charm" not in sysmsg("I hold the charm."), "chance:0 must never fire"
assert "Always Ring" in sysmsg("I wear the ring."), "chance:100 must always fire"

# a mid chance is deterministic per (seed, turn, slug): same call, same result,
# and it matches the exact roll we can reproduce here (turn_index == 0, no turns).
store.upsert_entry("items.md", Entry(
    "Maybe Coin", "maybe-coin", importance=3,
    attrs={"triggers": "coin", "chance": "50"}, body="A flipped fate."))
roll = random.Random(f"{SEED}-0-maybe-coin-chance").randint(1, 100)
expected = roll <= 50
got1 = "Maybe Coin" in sysmsg("I flip the coin.")
got2 = "Maybe Coin" in sysmsg("I flip the coin.")
assert got1 == got2, "same turn must give the same activation (replay-safe)"
assert got1 == expected, f"chance:50 roll={roll} expected activate={expected}"
print(f"2) ST-11 probability: 0/100 boundaries + deterministic mid roll "
      f"(coin roll={roll}, active={expected})")

# ---- pinned/critical bypass the Tier-2 gates entirely ----
store.upsert_entry("factions.md", Entry(
    "The Silent Hand", "silent-hand", importance=3,
    attrs={"pinned": "true", "chance": "0", "triggers_not": "anything"},
    body="Always watching."))
assert "The Silent Hand" in sysmsg("An unrelated sentence."), \
    "pinned entries must ignore chance/secondary-key gates"
print("3) pinned/critical bypass chance + secondary keys (always in)")

# ---- ST-12: inclusion groups (exactly one member activates, weighted+seeded) ----
for i, w in enumerate(["minor", "standard", "important"]):
    store.upsert_entry("items.md", Entry(
        f"Rumor {i}", f"rumor-{i}", importance=3,
        attrs={"triggers": "rumor", "group": "tavern-rumor", "weight": w},
        body=f"Whisper number {i}."))
present = [i for i in range(3) if f"Rumor {i}" in sysmsg("I listen for a rumor.")]
assert len(present) == 1, f"exactly one group member expected, got {present}"
present2 = [i for i in range(3) if f"Rumor {i}" in sysmsg("I listen for a rumor.")]
assert present == present2, "group winner must be stable within a turn (seeded)"
print(f"4) ST-12 inclusion groups: 1 of 3 rumors kept (winner=Rumor {present[0]})")


def sys_h(text, history=None):
    return store.assemble(history or [], text)[0]["content"]


# ---- ST-10 delay: dormant until N messages have happened ----
store.upsert_entry("locations.md", Entry(
    "Hidden Vault", "hidden-vault", importance=3,
    attrs={"triggers": "vault", "delay": "3"}, body="Sealed for ages."))
assert "Hidden Vault" not in sys_h("I search for the vault."), \
    "delay:3 must keep it dormant at turn 0"
for _ in range(3):
    store.append_turn("player", "idle chatter")           # now 3 messages exist
assert "Hidden Vault" in sys_h("I search for the vault."), \
    "delay:3 should allow activation from message 3 on"
print("5) ST-10 delay: dormant until turn N")

# ---- ST-10 sticky: stays active N messages after the mention scrolls away ----
store.upsert_entry("characters.md", Entry(
    "The Ghost", "the-ghost", importance=3,
    attrs={"triggers": "ghost", "sticky": "2"}, body="Lingers unseen."))
store.append_turn("player", "I glimpse a ghost in the hall.")   # the mention
# subsequent turns never say 'ghost', and history is empty so it's out of context
assert "The Ghost" in sys_h("I keep walking."), "sticky should hold it (1 msg later)"
store.append_turn("narrator", "The corridor is silent.")
assert "The Ghost" in sys_h("Still nothing."), "sticky should hold it (2 msgs later)"
store.append_turn("player", "I reach the far door.")
assert "The Ghost" not in sys_h("I open it."), "sticky:2 should have expired (3 later)"
print("6) ST-10 sticky: active for N messages past the mention, then drops")

# ---- ST-10 cooldown: quiet for N messages after firing, unless re-mentioned ----
store.upsert_entry("characters.md", Entry(
    "The Herald", "the-herald", importance=3,
    attrs={"triggers": "herald", "cooldown": "2"}, body="Announces news."))
store.append_turn("player", "The herald speaks at court.")      # it just fired
hist = [{"role": "player", "text": "The herald speaks at court."}]  # still in context
assert "The Herald" not in sys_h("I nod politely.", hist), \
    "cooldown:2 should suppress it right after firing (no re-mention)"
assert "The Herald" in sys_h("I ask the herald a question.", hist), \
    "a fresh mention overrides cooldown"
print("7) ST-10 cooldown: suppressed after firing; re-mention overrides")

# ---- ST-17: semantic-triggered lore promoted to first-class via the retriever ----
store.upsert_entry("locations.md", Entry(
    "Sunken Cathedral", "sunken-cathedral", importance=4,
    attrs={"semantic": "true"}, body="A drowned nave far below the tide line."))
store.upsert_entry("locations.md", Entry(
    "Plain Barn", "plain-barn", importance=2, body="Just an ordinary barn."))
sem = next(e for e in store.entries("locations.md") if e.slug == "sunken-cathedral")
plain = next(e for e in store.entries("locations.md") if e.slug == "plain-barn")


def fake_ret(haystack, exclude):
    return [e for e in (sem, plain) if e.slug not in exclude]


# "descend into the deep" keyword-matches NEITHER entry — only the retriever surfaces
# them; the semantic-flagged one must become real lore, the plain one only Recalled.
out = store.assemble([], "I descend into the deep.", retriever=fake_ret)[0]["content"]
assert "Sunken Cathedral" in out, "semantic entry should activate via the retriever"
assert "Recalled (semantically related)" in out, "plain retriever hit -> Recalled"
recalled_sec = out.split("Recalled (semantically related)")[1]
assert "Sunken Cathedral" not in recalled_sec, \
    "semantic:true entry must be first-class lore, not in Recalled"
assert "Plain Barn" in recalled_sec, "unflagged retriever hit belongs in Recalled"
# without the flag it would NOT be promoted: drop the flag, it should leave lore
sem.attrs.pop("semantic")
store.upsert_entry("locations.md", sem)
sem2 = next(e for e in store.entries("locations.md") if e.slug == "sunken-cathedral")


def fake_ret2(haystack, exclude):
    return [e for e in (sem2, plain) if e.slug not in exclude]


out2 = store.assemble([], "I descend into the deep.", retriever=fake_ret2)[0]["content"]
rec2 = out2.split("Recalled (semantically related)")[1]
assert "Sunken Cathedral" in rec2, "unflagged entry should fall back to Recalled only"
print("8) ST-17 semantic: flagged entry promoted to lore; unflagged stays Recalled")

# ---- ST-14: recursion (opt-in, depth-1 with a hard cap) ----
store.upsert_entry("characters.md", Entry(
    "The Prophecy", "the-prophecy", importance=4,
    attrs={"triggers": "prophecy", "recurse": "true"},
    body="It foretells the coming of the chosen one."))
store.upsert_entry("characters.md", Entry(
    "The Chosen One", "the-chosen-one", importance=3,
    attrs={"triggers": "chosen one"},
    body="A destined hero who will one day wield the sword."))
store.upsert_entry("characters.md", Entry(
    "The Sword", "the-sword", importance=3,
    attrs={"triggers": "sword"}, body="An old notched blade."))
out = sys_h("Tell me the prophecy.")
assert "The Prophecy" in out, "direct keyword activation"
assert "The Chosen One" in out, "recursion: prophecy body should pull in chosen one"
assert "The Sword" not in out, "depth cap: chosen-one's body is NOT re-scanned"
print("9) ST-14 recursion: body triggers depth-1; second-level cascade blocked")

# opt-in control: drop the recurse flag → no cascade
store.upsert_entry("characters.md", Entry(
    "The Prophecy", "the-prophecy", importance=4,
    attrs={"triggers": "prophecy"},
    body="It foretells the coming of the chosen one."))
out2 = sys_h("Tell me the prophecy.")
assert "The Prophecy" in out2 and "The Chosen One" not in out2, \
    "recursion must be opt-in (no flag = no cascade)"
print("10) ST-14 recursion is opt-in (no flag -> no cascade)")

# ================= bugsweep regression fixes (2026-07-06) =================

# FIX: a pinned/critical entry that also carries group: must never be swept out
# by the group lottery (the "always in" contract).
store.upsert_entry("factions.md", Entry(
    "Royal Decree", "royal-decree", importance=3,
    attrs={"pinned": "true", "group": "edicts", "triggers": "edict"},
    body="Always proclaimed in the square."))
for i in range(4):
    store.upsert_entry("factions.md", Entry(
        f"Minor Edict {i}", f"minor-edict-{i}", importance=5,
        attrs={"group": "edicts", "triggers": "edict", "weight": "important"},
        body=f"A lesser rule, number {i}."))
for _ in range(6):
    assert "Royal Decree" in sys_h("An edict is read aloud."), \
        "pinned entry in a group must always survive the lottery"
edicts = [i for i in range(4) if f"Minor Edict {i}" in sys_h("An edict is read.")]
assert len(edicts) == 1, f"non-pinned group members still collapse to one: {edicts}"
print("11) FIX pinned/critical in a group is never dropped")

# FIX: recursion must still respect inclusion groups (<=1 member via the cascade).
store.upsert_entry("items.md", Entry(
    "The Seer", "the-seer", importance=4,
    attrs={"triggers": "seer", "recurse": "true"},
    body="The seer mutters of an omen, an omen, a dark omen."))
for i in range(3):
    store.upsert_entry("items.md", Entry(
        f"Omen {i}", f"omen-{i}", importance=3,
        attrs={"triggers": "omen", "group": "omens"}, body=f"An ill sign {i}."))
outr = sys_h("I consult the seer.")
omens = [i for i in range(3) if f"Omen {i}" in outr]
assert "The Seer" in outr and len(omens) == 1, \
    f"recursion must keep at most one group member, got {omens}"
print("12) FIX recursion respects inclusion groups (<=1 member)")

# FIX: a sticky continuation must NOT be dropped by the per-turn chance re-roll.
be = Entry("Beacon Fire", "beacon-fire", importance=3,
           attrs={"triggers": "beacon", "chance": "50", "sticky": "3"})
store.upsert_entry("locations.md", be)
be = next(e for e in store.entries("locations.md") if e.slug == "beacon-fire")
tf = next(t for t in range(500)
          if random.Random(f"{SEED}-{t}-beacon-fire-chance").randint(1, 100) > 50)
assert store._entry_activates(be, "a beacon burns", SEED, tf, [], "a beacon burns") \
    is False, "a FRESH fire on a failing-roll turn is gated by chance"
assert store._entry_activates(be, "quiet night", SEED, tf, ["a beacon burns"],
                              "quiet night") is True, \
    "a sticky continuation on the same turn must ignore the chance re-roll"
print("13) FIX sticky continuation bypasses the chance re-roll")

# FIX: a hidden entry surfaced by the retriever must never leak into "Recalled".
store.upsert_entry("characters.md", Entry(
    "The Mole", "the-mole", importance=4,
    attrs={"hidden": "true"}, body="SECRETLY sells the party to the enemy."))
mole = next(e for e in store.entries("characters.md") if e.slug == "the-mole")
outh = store.assemble([], "who can I trust here?",
                      retriever=lambda hay, exc: [] if mole.slug in exc else [mole]
                      )[0]["content"]
assert "SECRETLY sells" not in outh, "hidden entry leaked via the retriever/Recalled"
print("14) FIX hidden entry never leaks through retriever -> Recalled")

# FIX: semantic promotion honors the hard gates (hidden, chance:0, triggers_not).
store.upsert_entry("locations.md", Entry("Hidden Shrine", "hidden-shrine",
    importance=4, attrs={"semantic": "true", "hidden": "true"},
    body="A CONCEALED altar."))
store.upsert_entry("locations.md", Entry("Warded Gate", "warded-gate",
    importance=4, attrs={"semantic": "true", "chance": "0"}, body="SEALED by wards."))
store.upsert_entry("locations.md", Entry("Quiet Pool", "quiet-pool",
    importance=4, attrs={"semantic": "true", "triggers_not": "storm"},
    body="STILL water."))
trio = [next(e for e in store.entries("locations.md") if e.slug == s)
        for s in ("hidden-shrine", "warded-gate", "quiet-pool")]
o = store.assemble([], "a storm nears the water",
                   retriever=lambda hay, exc: [e for e in trio if e.slug not in exc]
                   )[0]["content"]
# "promoted" = appears as first-class lore (before the supplementary Recalled block).
before = o.split("Recalled (semantically related)")[0]
assert "CONCEALED altar" not in o, "hidden+semantic must not appear ANYWHERE"
assert "SEALED by wards" not in before, "chance:0 semantic must not be promoted to lore"
assert "STILL water" not in before, "triggers_not-hit semantic must not be promoted"
print("15) FIX semantic promotion honors hidden / chance:0 / triggers_not")

# FIX: a malformed rpg block in state.json must degrade to seed 0, not crash.
for bad_rpg in (None, [], {"seed": "not-an-int"}):
    st2 = store.world_state()
    st2["rpg"] = bad_rpg
    store.set_world_state(st2)
    store.assemble([], "does the engine survive a hand-mangled state.json?")
st2 = store.world_state()
st2["rpg"] = {"seed": SEED}
store.set_world_state(st2)                       # restore a sane seed
print("16) FIX malformed rpg block degrades to seed 0 (no crash)")

print("\nALL TIER-2 CHECKS PASSED")
