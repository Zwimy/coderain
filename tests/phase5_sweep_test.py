"""Regressions for the pre-Phase-5 bug sweep — storage/saves (agent B findings)."""
import os, sys, shutil, tempfile, zipfile
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.memory import Library, MemoryStore

root = os.path.join(tempfile.gettempdir(), "se_p5_sweep")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)

# H1 — create_story must NOT register a throwaway scenario.
assert lib.scenarios.list() == []
a = lib.create_story("One-off", "A lonely premise about a bell.")
assert lib.scenarios.list() == [], "create_story leaked a scenario"
assert "bell" in lib.saves.store(a).read("premise.md").lower()   # premise seeded inline
print("H1) create_story no longer proliferates scenarios")

# M2 — layer_of agrees with resolve_write_path when no instructions_dir is set.
bare = MemoryStore(lib.saves.dir(a))            # constructed WITHOUT instructions dir
assert bare.layer_of("writer-rules.md") == "save"          # matches where a write lands
assert bare.resolve_write_path("writer-rules.md") == bare.dir / "writer-rules.md"
# and the normal (wired) store still reports global
assert lib.saves.store(a).layer_of("writer-rules.md") == "global"
print("M2) layer_of matches the real write target")

# --- build a save with snapshot history + a stray temp file for M6 ---
scen = lib.scenarios.create("World", "A premise about a harbor.")
b = lib.saves.create("Run B", scen)
sb = lib.saves.store(b)
sb.append_turn("player", "hello harbor")
snap1 = sb.snapshot(); snap2 = sb.snapshot()          # two snapshots, same second
(sb.dir / "stray.tmp").write_text("junk", encoding="utf-8")

# L9 — snapshots taken within the same second get distinct dirs.
assert snap1 != snap2 and snap1.exists() and snap2.exists()
print("L9) same-second snapshots don't collide")

# M6 — export excludes .snapshots/ and *.tmp; duplicate does too.
zp = os.path.join(root, "b.zip")
lib.saves.export(b, zp)
with zipfile.ZipFile(zp) as z:
    names = z.namelist()
assert not any(".snapshots" in n for n in names), names
assert not any(n.endswith(".tmp") for n in names), names
assert "meta.json" in names and "transcript.md" in names
dup = lib.saves.duplicate(b)
ddir = lib.saves.dir(dup)
assert not (ddir / ".snapshots").exists() and not (ddir / "stray.tmp").exists()
assert "hello harbor" in lib.saves.store(dup).read("transcript.md")
print("M6) export/duplicate drop snapshot history + temp files")

# M4 — a nested archive (save under a subfolder) imports; colliding top-level files
# outside the save root are ignored, not clobbering the real (inner) ones.
nz = os.path.join(root, "nested.zip")
with zipfile.ZipFile(nz, "w") as z:
    for p in sorted(lib.saves.dir(b).rglob("*")):
        rel = p.relative_to(lib.saves.dir(b))
        if p.is_file() and ".snapshots" not in rel.parts and p.suffix != ".tmp":
            z.write(p, "inner/" + rel.as_posix())
    z.writestr("premise.md", "# Premise\n\nTOP-LEVEL STRAY — must be ignored\n")
imp = lib.saves.import_(nz, title="Nested")
si = lib.saves.store(imp)
assert "harbor" in si.read("premise.md").lower()
assert "TOP-LEVEL STRAY" not in si.read("premise.md")
assert "hello harbor" in si.read("transcript.md")
print("M4) nested archive imports; stray top-level files ignored")

# M5 — an archive with no meta.json is rejected (no malformed save fabricated).
bad = os.path.join(root, "nometa.zip")
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("premise.md", "# Premise\n\nnot a save\n")
before = len(lib.saves.list())
try:
    lib.saves.import_(bad)
    assert False, "import of a meta-less archive should raise"
except ValueError:
    pass
assert len(lib.saves.list()) == before, "a rejected import must not create a save"
print("M5) meta-less archive is rejected cleanly")

print("\nPHASE 5 SWEEP-FIX TESTS PASSED")
