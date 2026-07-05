import os, sys, shutil, tempfile
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.memory import Library
from coderain.config import load_config
from coderain.engine import Engine

root = os.path.join(tempfile.gettempdir(), "se_p5")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
lib.scenarios.ensure_default()

# ---- 0) instructions are global masters, seeded once, not inside saves ----
for r in ("writer-rules.md", "memory-rules.md", "rpg-rules.md"):
    assert (lib.instructions_dir / r).exists(), r
assert (root and os.path.isdir(os.path.join(root, "instructions")))
print("0) global instructions/ seeded")

# ---- 1) scenario = authored world only (no rules, no play state) ----
scen = lib.scenarios.create("Lighthouse", "You keep a lighthouse on a storm coast.",
                            world="Storms rule the coast; ships fear the reef.")
sdir = lib.scenarios.dir(scen)
assert (sdir / "premise.md").exists() and (sdir / "world-bible.md").exists()
assert not (sdir / "writer-rules.md").exists()      # rules inherited, not authored here
assert not (sdir / "transcript.md").exists()        # no play state in a scenario
print("1) scenario holds world only (rules inherited, no play state)")

# ---- 2) a save copies the world in; play files are fresh; rules stay global ----
a = lib.saves.create("Run A", scen)
sa = lib.saves.store(a)
assert "lighthouse" in sa.read("premise.md").lower()
assert "Storms rule the coast" in sa.read("world-bible.md")
assert sa.read("transcript.md") and sa.read("memory/arc.md")   # created fresh
assert sa.layer_of("writer-rules.md") == "global"
assert not sa.path("writer-rules.md").exists()
assert sa.read("writer-rules.md").strip()                      # inherited from global
print("2) save = copied world + fresh play state + inherited global rules")

# ---- 3) editing a rule edits the GLOBAL master -> all saves see it ----
b = lib.saves.create("Run B", scen)
sb = lib.saves.store(b)
MARK = "<!-- GLOBAL-RULE-EDIT -->"
sa.write("writer-rules.md", sa.read("writer-rules.md") + "\n" + MARK)
assert MARK in sb.read("writer-rules.md"), "global rule edit not shared"
assert not sa.path("writer-rules.md").exists(), "edit wrongly forked into the save"
print("3) rule edits are central (shared live across saves)")

# ---- 4) per-save override isolates; revert restores the shared version ----
assert sa.make_override("writer-rules.md")
sa.write("writer-rules.md", "SAVE-ONLY RULES")
assert sa.layer_of("writer-rules.md") == "save"
assert "SAVE-ONLY" not in sb.read("writer-rules.md")           # B still on global
assert sa.remove_override("writer-rules.md")
assert MARK in sa.read("writer-rules.md")                      # reverted to shared
print("4) per-save rule override + revert works")

# ---- 5) scenario-level rule override sits between save and global ----
(sdir / "memory-rules.md").write_text("SCENARIO MEMORY RULES", encoding="utf-8")
c = lib.saves.create("Run C", scen)
sc = lib.saves.store(c)
assert sc.layer_of("memory-rules.md") == "scenario"
assert "SCENARIO MEMORY RULES" in sc.read("memory-rules.md")
print("5) scenario rule override resolves above global")

# ---- 6) save-local world edits don't leak to the scenario or sibling saves ----
sa.write("premise.md", "# Premise\n\nSolo premise for A only.\n")
assert "Solo premise for A" not in sb.read("premise.md")
assert "lighthouse" in (sdir / "premise.md").read_text(encoding="utf-8").lower()
print("6) save world edits are isolated (scenario + siblings intact)")

# ---- 7) duplicate is independent; rename; export/import round-trip ----
sa.append_turn("player", "turn in A")
d = lib.saves.duplicate(a)
sd = lib.saves.store(d)
assert "turn in A" in sd.read("transcript.md")
sd.append_turn("player", "turn only in D")
assert "turn only in D" not in sa.read("transcript.md")        # independent copies
assert lib.saves.rename(a, "Renamed A") and lib.saves.meta(a)["title"] == "Renamed A"

zp = os.path.join(root, "a_export.zip")
lib.saves.export(a, zp)
imp = lib.saves.import_(zp, title="Imported A")
si = lib.saves.store(imp)
assert "turn in A" in si.read("transcript.md")
assert lib.saves.meta(imp)["title"] == "Imported A"
print("7) duplicate/rename/export/import handled correctly")

# ---- 8) delete removes exactly one save ----
n0 = len(lib.saves.list())
assert lib.saves.delete(d)
assert len(lib.saves.list()) == n0 - 1
print("8) delete removes one save")

# ---- 9) the engine assembles narrator context from the GLOBAL rules ----
cfg = load_config()
Engine(cfg, sb)                                                # constructs cleanly
sysmsg = sb.assemble([], "look around")[0]["content"]
assert "Second person" in sysmsg, "global writer-rules not injected into context"
print("9) engine reads global rules into assembled context")

print("\nPHASE 5 (saves/scenarios/instructions) TESTS PASSED")
