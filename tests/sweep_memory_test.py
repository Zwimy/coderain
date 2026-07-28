"""Context-assembly and recall defects found in the 2026-07-28 bug sweep.

assemble() decides what the model can possibly know this turn. Anything it drops
is invisible — the story just "forgets", with no error anywhere.

Asserts:
 1) pinned/critical lore really is always in context, even at the tightest budget;
 2) always-on sections share the budget instead of each claiming all of it, and
    an over-large section is trimmed rather than dropped;
 3) recall_turns prefers the timeline over an incidental number range;
 4) the recursion pass judges triggers_not against the STORY, not its own fuel;
 5) the player's current location cannot lose the inclusion-group lottery;
 6) hidden entries do not consume the retriever's top-K slots.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-swm-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.memory import Entry, Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


def _story(name):
    return lib.store(lib.create_story(name, "A lighthouse keeper answers letters "
                                            "from a ship that sank."))


def _sys(store, **kw):
    return store.assemble(history=[{"role": "player", "text": "I look around"}],
                          player_input="north", **kw)[0]["content"]


# ---- 1) pinned/critical survive any budget -----------------------------
s1 = _story("Pinned")
s1.upsert_entry("characters.md", Entry(
    "Mara Vell", "mara-vell", attrs={"pinned": "true"},
    body="The keeper's sister. " + ("She waits by the glass. " * 90)))
s1.upsert_entry("characters.md", Entry(
    "The Drowned Captain", "drowned-captain", attrs={"weight": "critical"},
    body="He writes the letters. " + ("Ink runs on wet paper. " * 90)))
s1.write("world-bible.md", "# World\n\n" + ("The coast is long. " * 400))
s1.write("memory/arc.md", "# Arc synopsis (long-term)\n\n" + ("It began. " * 300))
s1.add_facts([f"Established fact number {i}." for i in range(40)])
for n in range(1, 7):
    s1.upsert_entry("memory/scenes.md", Entry(
        f"Scene {n}", f"scene-{n}", attrs={"turns": f"{n * 2 - 1}-{n * 2}"},
        body="A scene happened. " * 30))
for budget in (2000, 2500, 3000, 4000, 8000):
    txt = _sys(s1, budget_tokens=budget)
    assert "Mara Vell" in txt, f"pinned entry dropped at budget {budget}"
    assert "Drowned Captain" in txt, f"critical entry dropped at budget {budget}"
print("1) pinned + critical present at budgets 2000-8000")

# ---- 2) always-on sections share the budget ----------------------------
s2 = _story("Budget")
s2.write("premise.md", "# Premise\n\n" + ("A long premise sentence. " * 400))
s2.write("player.md", "## You {#player}\n\n" + ("A long player line. " * 400))
s2.write("world-bible.md", "# World\n\n" + ("World detail. " * 800))
for budget in (2000, 3000):
    txt = _sys(s2, budget_tokens=budget)
    ctx = txt.split("# STORY & MEMORY CONTEXT", 1)[-1]
    assert len(ctx) <= budget * 4 * 1.35, (
        f"budget {budget} tokens ({budget * 4} chars) produced {len(ctx)} chars "
        "— always-on sections each claimed the whole budget")
    assert "## Premise" in ctx and "## You" in ctx, "an always-on section vanished"
# an over-large lower-priority section is trimmed, not dropped whole
s3 = _story("Huge")
s3.write("world-bible.md", "# World\n\n" + ("Every stone is named. " * 3000))
txt = _sys(s3, budget_tokens=2000)
assert "## World" in txt, "an over-large section was dropped instead of trimmed"
assert "…(truncated)" in txt
print("2) always-on sections share the budget; an over-large one is trimmed")

# ---- 3) recall_turns prefers the timeline -----------------------------
s4 = _story("Recall")
for i in range(1, 41):
    s4.append_turn("player" if i % 2 else "narrator", f"TURN-{i} text")
s4.write("memory/timeline.md",
         "# Timeline (turn index)\n"
         "- [T1-5] Day 1: the courier set out\n"
         "- [T31-35] Day 4: the siege lasted 2-3 days and broke at dawn\n")
got = s4.recall_turns("the siege lasted 2-3 days")
assert "TURN-31" in got, f"an incidental '2-3' beat the timeline lookup:\n{got}"
assert "TURN-2" not in got.split("TURN-31")[0], got
# an explicit range still works
assert "TURN-2" in s4.recall_turns("T2-3")
assert "TURN-2" in s4.recall_turns("2-3")
print("3) recall_turns resolves the timeline line, not an incidental range")

# ---- 4) recursion judges triggers_not against the story ---------------
s5 = _story("Recurse")
s5.upsert_entry("characters.md", Entry(
    "The Duke", "the-duke", attrs={"triggers": "duke", "triggers_not": "dead"},
    body="The Duke rules from the ballroom."))
s5.upsert_entry("factions.md", Entry(
    "Court Gossip", "court-gossip",
    attrs={"triggers": "gossip", "recurse": "true"},
    body="They whisper about the duke and his debts."))
txt = s5.assemble(history=[], player_input="I listen to the gossip. The duke is dead.",
                  budget_tokens=8000)[0]["content"]
assert "rules from the ballroom" not in txt, (
    "triggers_not was checked against the recursion fuel, so a suppressed entry "
    "came back anyway")
# without the suppressing word, recursion still pulls it in
txt2 = s5.assemble(history=[], player_input="I listen to the gossip.",
                   budget_tokens=8000)[0]["content"]
assert "rules from the ballroom" in txt2, "recursion stopped working entirely"
print("4) recursion still fires, but triggers_not judges the real context")

# ---- 5) the current location cannot lose the group lottery ------------
s6 = _story("Groups")
for n in range(6):
    s6.upsert_entry("locations.md", Entry(
        f"Tavern {n}", f"tavern-{n}", attrs={"group": "taverns"},
        body=f"Tavern {n} has a crooked sign."))
ws = s6.world_state()
ws["player"]["location"] = "Tavern 0"
s6.set_world_state(ws)
for seed in (7, 11, 42, 99):
    rpg = s6.world_state().get("rpg") or {}
    rpg["seed"] = seed
    ws = s6.world_state()
    ws["rpg"] = rpg
    s6.set_world_state(ws)
    txt = _sys(s6, budget_tokens=8000)
    assert "Tavern 0 has a crooked sign" in txt, (
        f"seed {seed}: the room the player is standing in lost the group lottery")
print("5) the current location is exempt from the group lottery (4 seeds)")

# ---- 6) hidden entries don't burn the retriever's slots ---------------
s7 = _story("Hidden")
for n in range(4):
    s7.upsert_entry("canon-events.md", Entry(
        f"Secret {n}", f"secret-{n}", attrs={"hidden": "true"},
        body=f"Secret {n} must not be recalled."))
for n in range(4):
    s7.upsert_entry("items.md", Entry(
        f"Relic {n}", f"relic-{n}", body=f"Relic {n} is ordinary."))
order = [f"secret-{n}" for n in range(4)] + [f"relic-{n}" for n in range(4)]


def _retriever(query, exclude):
    """Ranks hidden entries highest, then slices top-K — like the real one."""
    idx = s7.index().entries
    ranked = [idx[s][1] for s in order if s in idx and s not in exclude]
    return ranked[:4]


txt = s7.assemble(history=[], player_input="tell me about the relics",
                  budget_tokens=8000, retriever=_retriever)[0]["content"]
assert "Recalled (semantically related)" in txt, (
    "hidden entries consumed every top-K slot, so nothing was recalled")
assert "must not be recalled" not in txt, "a hidden entry surfaced in Recalled"
assert "is ordinary" in txt
print("6) hidden entries are excluded before the top-K slice")

shutil.rmtree(HOME, ignore_errors=True)
print("\nMEMORY SWEEP TESTS PASSED")
