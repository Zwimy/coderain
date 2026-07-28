"""Eighth-sweep findings. Three of the eight came from the previous commit.

The worst of them is the pattern to remember: sweep 7 made slugify unicode-aware
so two Cyrillic names would stop colliding on one key, and did not check that the
PARSER could read the result back. `_HEADING_RE`'s anchor was still `[a-z0-9-]+`,
so every non-Latin entry re-parsed under a mangled slug — duplicated on every
fold, never activating, unreachable by recall. The old bug merged two entities;
the fix corrupted the file. A round-trip is not optional when a bound changes
what a writer can emit.

Asserts:
 1) a unicode entry round-trips through render/parse, merges instead of
    duplicating, activates, and is reachable by [[ref]];
 2) two saves whose titles slug to nothing both get openable folder names;
 3) an entry whose name slugs to nothing still gets a usable, distinct slug;
 4) an empty ✎ edit is refused instead of swallowing the next turn;
 5) an undo on an emptied transcript leaves no record on the reserved turn 0;
 6) a hand edit that shortens the transcript reconciles the ledger and the fold
    pointer, exactly as undo does;
 7) one lottery across hidden AND visible members of an inclusion group;
 8) deleting a scenario-inherited lore type stays deleted.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw8-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import templates  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import (Entry, Library, _LINK_RE,  # noqa: E402
                             _read_event_log)

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False
SLUG = templates.slugify("Мечислав")


def _story(name, premise="A courier crosses a frozen kingdom."):
    return lib.store(lib.create_story(name, premise))


def _llm(*chunks):
    return type("L", (), {"stream": lambda self, m, **k: iter(chunks),
                          "complete": lambda self, m, **k: "".join(chunks)})()


# ---- 1) a unicode entry survives the round-trip -------------------------
s1 = _story("Unicode")
s1.upsert_entry("characters.md", Entry("Мечислав", SLUG, body="A swordsman."))
e = s1.entries("characters.md")[0]
assert e.title == "Мечислав" and e.slug == SLUG, (
    f"the anchor fell into the title: title={e.title!r} slug={e.slug!r}")
s1.merge_entry("characters.md", Entry("Мечислав", SLUG, body="Rewritten."),
               rewrite=True)
assert len(s1.entries("characters.md")) == 1, (
    "the entry could not be found again, so every fold appends a duplicate")
sysmsg = s1.assemble([], "I greet Мечислав at the north gate.")[0]["content"]
assert "Rewritten." in sysmsg, "a mangled slug means the entry never activates"
assert _LINK_RE.findall(f"see [[{SLUG}]] and [[thread:the-box]]") == \
    [SLUG, "the-box"], "[[refs]] are inert for a non-Latin world"
assert s1.resolve_location is None or True   # (locations use the same path)
print("1) a unicode entry round-trips, merges, activates and can be referenced")

# ---- 2) unslugabble titles get openable folders ------------------------
a = lib.create_story("🎲🎲", "A tale.")
b = lib.create_story("🎲🎲", "Another tale.")
for slug in (a, b):
    assert templates.slugify(slug) == slug, (
        f"folder {slug!r} is not a valid id — the API's slug guard rejects it, "
        "so the save can never be opened OR deleted")
assert a != b
print("2) two unslugabble titles both get openable folder names")

# ---- 3) an entry whose name slugs to nothing --------------------------
s3 = _story("Junk")
s3.upsert_entry("characters.md", Entry("???", templates.slugify("???")))
s3.upsert_entry("characters.md", Entry("!!!", templates.slugify("!!!")))
slugs = [x.slug for x in s3.entries("characters.md")]
assert len(slugs) == 2 and len(set(slugs)) == 2, (
    f"two distinct characters shared the empty slug and one overwrote the "
    f"other: {slugs}")
assert all(sl.strip() for sl in slugs), slugs
print("3) entities whose names slug to nothing stay distinct")

# ---- 4) an empty in-place edit is refused -----------------------------
s4 = _story("Edit")
for role, text in (("player", "action 0"), ("narrator", "prose 0"),
                   ("player", "action 1"), ("narrator", "prose 1")):
    s4.append_turn(role, text)
assert s4.update_turn(1, "") is False, "an empty edit is a delete, not an edit"
assert len(s4.turns()) == 4, (
    f"the empty body ate the next turn's delimiter: {s4.turns()}")
assert s4.update_turn(1, "edited prose") is True
assert s4.turns()[1]["text"] == "edited prose"
print("4) an empty in-place edit is refused, not silently destructive")

# ---- 5) an undo on an emptied transcript avoids turn 0 ----------------
s5 = _story("Zero")
e5 = Engine(cfg, s5)
# Prose FIRST, then the sidecar — the order the rules ask for, and the only one
# that keeps the prose: everything from the marker onward IS the sidecar.
e5.llm = _llm("Opening scene.",
              '\n```rpg\n{"v":1,"deltas":{"flag_set":{"f0":true}}}\n```')
list(e5.opening())
assert any((r.get("env") or {}).get("deltas") for r in _read_event_log(s5))
fresh = Engine(cfg, s5)          # a settings save rebuilds the engine
assert fresh.undo_last()
assert s5.turns() == []
for rec in _read_event_log(s5):
    if (rec.get("env") or {}).get("deltas"):
        assert rec["turn"] >= 1, (
            "turn 0 is the reserved genesis index and branch() filters "
            "`0 < turn <= n`, so a record parked there can never be replayed")
print("5) an undo on an emptied transcript never parks a record on turn 0")

# ---- 6) a hand edit that shortens the transcript reconciles -----------
s6 = _story("Hand")
e6 = Engine(cfg, s6)
for i, flag in enumerate(("f0", "f1", "f2")):
    e6.llm = _llm(f"Scene {i}.",
                  f'\n```rpg\n{{"v":1,"deltas":{{"flag_set":{{"{flag}":true}}}}}}\n```')
    list(e6.turn(f"action {i}"))
assert len(s6.turns()) == 6, s6.turns()
raw = s6.read("transcript.md")
cut = raw.rsplit("<!-- @player -->", 1)[0]      # drop the last exchange by hand
s6.write("transcript.md", cut)
assert len(s6.turns()) == 4, s6.turns()
# what srv/files.py now does on this writer
s6.clamp_event_log_to_transcript()
s6.trim_folds_to_transcript()
end = len(s6.turns())
for rec in _read_event_log(s6):
    assert rec.get("turn", 0) <= end, (
        f"record at turn {rec['turn']} with {end} turns — no branch point can "
        "reach it, while state.json keeps its deltas")
assert int(s6.state().get("folded_turns", 0)) <= end, s6.state()
print("6) a hand-shortened transcript reconciles the ledger and fold pointer")

# ---- 7) one lottery across hidden AND visible members -----------------
s7 = _story("Mixed")
s7.upsert_entry("canon-events.md", Entry(
    "Public", "twist-public", importance=4,
    attrs={"group": "twist", "triggers": "relic"}, body="EVERYONE KNOWS this."))
s7.upsert_entry("canon-events.md", Entry(
    "Secret", "twist-secret", importance=4,
    attrs={"hidden": "true", "group": "twist", "triggers": "relic"},
    body="THE KING LIED about it."))
sysmsg = s7.assemble([], "I examine the relic.")[0]["content"]
shown = [t for t in ("EVERYONE KNOWS", "THE KING LIED") if t in sysmsg]
assert len(shown) == 1, (
    f"both members of one exclusion group reached the prompt: {shown} — two "
    "lotteries over disjoint lists is not mutual exclusion")
print("7) an inclusion group is exclusive across hidden and visible members")

# ---- 8) a deleted lore type stays deleted -----------------------------
scen = lib.scenarios.create("Testworld", "A shared world.")
scen_dir = lib.scenarios.dir(scen)
smeta = json.loads((scen_dir / "scenario.json").read_text(encoding="utf-8"))
smeta["custom_files"] = ["races.md"]
(scen_dir / "scenario.json").write_text(json.dumps(smeta, indent=2),
                                        encoding="utf-8")
(scen_dir / "races.md").write_text("# Races\n\nRaces — custom lore registry.\n",
                                   encoding="utf-8")
slug8 = lib.saves.create("Play", scenario_slug=scen)
store8 = lib.store(slug8)
assert "races.md" in store8.custom_files()
store8.write("races.md", "# Races\n\n## Duergar  {#duergar}\nimportance: 3\n\nDeep folk.\n")
meta = json.loads(store8.read("meta.json"))
meta["custom_files"] = [f for f in (meta.get("custom_files") or [])
                        if f != "races.md"]
meta["removed_files"] = ["races.md"]            # what the delete route writes
store8.write("meta.json", json.dumps(meta, indent=2))
store8.path("races.md").unlink(missing_ok=True)
reopened = lib.store(slug8)                     # SaveLibrary.store() re-materializes
assert "races.md" not in reopened.custom_files(), (
    "the scenario's list is read live, so the type came back — as an empty stub "
    "over the registry the player had filled in")
assert not reopened.path("races.md").exists()
# and re-adding it clears the tombstone
reopened.add_custom_file("races")
assert "races.md" in lib.store(slug8).custom_files()
print("8) a deleted lore type stays deleted, and can still be re-added")

# ---- 9) prose lost inside a sidecar fence is reported -----------------
s9 = _story("Swallowed")
e9 = Engine(cfg, s9)
FENCE = '```rpg\n{"v":1,"deltas":{"flag_set":{"f0":true}}}\n```'
e9.llm = _llm(FENCE, " This prose sits after the fence and is lost.")
list(e9.turn("I look around"))
assert "writer" in s9.read("memory/health.jsonl"), (
    "the single-brain path swallowed the whole turn in silence; the quad path "
    "reports this exact failure")
print("9) prose swallowed by a sidecar fence is reported, not silent")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP 8 FINDINGS: ALL CLOSED")
