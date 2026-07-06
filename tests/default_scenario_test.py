"""The bundled default world ("The Veil"): idempotent seeding, populated lore with
Tier-2 attributes, recommended play-aids flowing into a new save, and a clean
export/import round-trip."""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import default_scenario as ds
from coderain.memory import Library, safe_output_regex

root = os.path.join(tempfile.gettempdir(), "se_default_scn")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)

# ---- ensure_default seeds The Veil, and does so idempotently ----
lib.scenarios.ensure_default()
lib.scenarios.ensure_default()
worlds = lib.scenarios.list()
assert len(worlds) == 1, f"expected exactly one seeded world, got {len(worlds)}"
assert worlds[0]["slug"] == ds.SLUG, worlds[0]
scen_dir = lib.scenarios.dir(ds.SLUG)
assert (scen_dir / "aids.json").exists(), "aids sidecar not written"
print("1) ensure_default seeds 'the-veil' once (idempotent)")

# ---- premise carries the authored ## Opening with the {{user}} macro ----
premise = (scen_dir / "premise.md").read_text(encoding="utf-8")
assert "## Opening" in premise and "{{user}}" in premise, "opening/macro missing"
assert "copper coin" in premise.lower()
print("2) premise has an authored ## Opening using {{user}}")

# ---- populated lore parses, with the Tier-2 attributes wired ----
from coderain.memory import MemoryStore
store = MemoryStore(scen_dir)
chars = {e.slug: e for e in store.entries("characters.md")}
assert {"wren", "the-tall-man", "corin", "the-arbiter"} <= set(chars), chars.keys()
assert chars["wren"].pinned(), "Wren should be pinned"
assert chars["the-tall-man"].chance() == 40, "Tall Man chance attr not parsed"
assert chars["the-tall-man"].group() == "threat", "Tall Man group attr not parsed"
assert chars["corin"].delay() == 4, "Corin delay attr not parsed"
canon = {e.slug: e for e in store.entries("canon-events.md")}
assert canon["wrens-silence"].hidden(), "the twist entry must be hidden"
locs = {e.slug: e for e in store.entries("locations.md")}
assert locs["the-veil"].pinned(), "The Veil setting must be pinned (always-on)"
assert locs["static-quarter"].delay() == 6, "Static Quarter delay not parsed"
print("3) lore populated: pinned/chance/group/delay/hidden attrs all parse")

# ---- every recommended output-regex rule is ReDoS-safe ----
for r in ds.AIDS["regex_rules"]:
    assert safe_output_regex(r["find"]), f"unsafe default regex shipped: {r['find']!r}"
print("4) all recommended output-regex rules pass safe_output_regex")

# ---- a save made from the world copies the lore AND seeds the play aids ----
save_slug = lib.saves.create("My Waking", scenario_slug=ds.SLUG, mode="simple")
ss = lib.store(save_slug)
ws = ss.world_state()
assert ws.get("quick_actions") and "Take the copper coin" in ws["quick_actions"], ws.get("quick_actions")
assert ws.get("regex_rules") and len(ws["regex_rules"]) == 3, ws.get("regex_rules")
an = ws.get("authors_note") or {}
assert an.get("depth") == "tail" and an.get("every") == 3, an
note = ss.custom_instructions()
assert "second-person" in note.lower() and "veil" in note.lower(), note[:120]
# the world content came across too
assert "wren" in {e.slug for e in ss.entries("characters.md")}
print("5) new save from the world seeds quick actions + regex + author's-note + lore")

# ---- assembled context: pinned always-on lore is present; the opening greeting
#      is NOT duplicated into the premise section; the secret is framed as a secret ----
msgs = ss.assemble(history=[], player_input="I look around the diner")
sys_txt = msgs[0]["content"]
assert "The Veil" in sys_txt, "pinned setting lore missing from context"
# 'Vane Street' appears only in the verbatim opening greeting — it must NOT ride
# in the standing premise context (that's turn 1 of the transcript's job).
assert "Vane Street" not in sys_txt, "verbatim opening leaked into premise context"
# hidden secret only ever appears under the Secrets framing, never as open prose
if "wrens-silence" in sys_txt or "offered the coin before" in sys_txt.lower():
    assert "Secrets you know" in sys_txt, "hidden twist surfaced outside the Secrets block"
print("6) assemble: pinned lore in; opening not duplicated; secret stays a secret")

# ---- export -> import round-trip keeps the world intact (aids + lore) ----
zip_path = os.path.join(root, "veil.zip")
lib.scenarios.export(ds.SLUG, zip_path)
new_slug = lib.scenarios.import_(zip_path, title="Veil Copy")
nd = lib.scenarios.dir(new_slug)
assert (nd / "aids.json").read_bytes() == (scen_dir / "aids.json").read_bytes(), "aids lost on round-trip"
assert (nd / "characters.md").read_text(encoding="utf-8") == \
       (scen_dir / "characters.md").read_text(encoding="utf-8"), "lore changed on round-trip"
print("7) export -> import round-trip preserves aids + lore byte-for-byte")

print("\nALL DEFAULT-SCENARIO CHECKS PASSED")
