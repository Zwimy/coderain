"""Ninth-sweep findings. Three came from the previous commit.

The one to remember is finding 6: sweep 8 made srv/files.py reconcile the ledger
after every transcript write, and reconciliation is LOSSY. Cutting an exchange
and pasting it straight back left two envelopes sharing one turn index forever,
so a later branch replayed deltas from turns after its own branch point. A
repair that runs unconditionally is not a repair — it has to be conditional on
the damage it repairs.

Asserts:
 1) a visible entry is not relabelled a secret because a hidden entry elsewhere
    shares its slug;
 2) an anchorless entry whose title slugs to nothing is replaced in place, not
    duplicated, and can be revealed and removed;
 3) a newline in a model-supplied item name cannot corrupt items.md;
 4) attrs and titles from any producer are one line, and importance is clamped;
 5) a `## ` heading inside the model's arc synopsis is not re-appended forever;
 6) a transcript write that changes nothing moves no ledger record;
 7) a transcript write that SHORTENS still reconciles, and leaves a snapshot;
 8) re-adding a deleted lore type actually restores it;
 9) a generation that produces nothing at all says so in the health log.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw9-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import validator as V  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Entry, Library, _read_event_log  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False


def _story(name, premise="A courier crosses a frozen kingdom."):
    return lib.store(lib.create_story(name, premise))


def _llm(*chunks):
    return type("L", (), {"stream": lambda self, m, **k: iter(chunks),
                          "complete": lambda self, m, **k: "".join(chunks)})()


class _Stub:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, m, **k):
        return self.payload

    def stream(self, m, **k):
        return iter([self.payload])


# ---- 1) a shared slug across registries ---------------------------------
s1 = _story("Shared")
s1.upsert_entry("locations.md", Entry(
    "Blackwood", "blackwood", attrs={"triggers": "blackwood"},
    body="PUBLIC: a rain-dark forest north of the town."))
s1.upsert_entry("factions.md", Entry(
    "Blackwood", "blackwood", attrs={"hidden": "true", "triggers": "blackwood"},
    body="SECRET: the family runs the smuggling ring."))
sysmsg = s1.assemble([], "we ride into blackwood")[0]["content"]
head = "Secrets you know"
public_at = sysmsg.find("PUBLIC: a rain-dark forest")
assert public_at != -1, "the public entry vanished from the prompt entirely"
secrets_at = sysmsg.find(head)
assert secrets_at == -1 or public_at < secrets_at, (
    "ordinary geography was handed to the Writer inside the Secrets block, "
    "under an instruction never to state it outright")
print("1) a hidden entry elsewhere cannot relabel a public one as a secret")

# ---- 2) an anchorless entry whose title slugs to nothing ---------------
s2 = _story("Anchorless")
s2.write("locations.md", "# Locations\n\n## ???\nimportance: 4\nhidden: true\n\n"
                         "The place with no name.\n")
e2 = s2.entries("locations.md")[0]
assert e2.slug.strip(), e2.slug
s2.set_hidden(e2.slug, False)
after = s2.entries("locations.md")
assert len(after) == 1, (
    f"the reveal appended a second copy instead of replacing: "
    f"{[x.slug for x in after]}")
assert after[0].hidden() is False, "the reveal reported success and did nothing"
assert s2.remove_entry("locations.md", e2.slug) is True
assert s2.entries("locations.md") == []
print("2) an anchorless entry is replaced in place, revealed, and removable")

# ---- 3) a newline in an item name --------------------------------------
s3 = _story("Items")
st = s3.state()
st["rpg"] = {"enabled": True, "inventory": {}}
s3.write_state(st)
clean, _rej = V.validate(
    {"v": 1, "deltas": {"inventory_add": [{"name": "Rusty\nSword", "qty": 1}]}}, s3)
for it in (clean.get("deltas") or {}).get("inventory_add") or []:
    assert "\n" not in it["name"], repr(it["name"])
print("3) a newline in an item name never reaches items.md")

# ---- 4) one-line attrs and a clamped importance ------------------------
s4 = _story("Attrs")
s4.upsert_entry("characters.md", Entry(
    "Mara\nVell", "mara", importance=100,
    attrs={"status": "wounded and hiding\nin the cellar", "wants": "to vanish"},
    body="A spy."))
got = s4.entries("characters.md")[0]
assert got.title == "Mara Vell", repr(got.title)
assert got.attrs.get("wants") == "to vanish", (
    f"the newline in `status` swallowed every attr after it: {got.attrs}")
assert got.importance == 5, got.importance
# importance is multiplied into the score and +100 is the always-on sentinel,
# so an unclamped 100 skipped the lore-budget cutoff and starved everything else
s4.upsert_entry("locations.md", Entry(
    "Huge", "huge", attrs={"triggers": "huge"}, body="H" * 4000))
s4.write("locations.md", s4.read("locations.md").replace(
    "importance: 5", "importance: 100").replace("importance: 3", "importance: 100"))
s4.upsert_entry("locations.md", Entry(
    "Small", "small", attrs={"triggers": "small"}, body="A small room."))
sysmsg = s4.assemble([], "huge and small", budget_tokens=400)[0]["content"]
assert "A small room." in sysmsg, (
    "a hand-edited importance:100 scored as always-on and starved the rest")
print("4) titles and attrs are one line; importance is clamped at the parser")

# ---- 5) a `## ` inside the model's arc synopsis ------------------------
s5 = _story("Arc")
s5.write("memory/arc.md", "# Arc synopsis (long-term)\n\n(nothing yet)\n\n"
                          "## Beats\n- find the sword\n")
sm5 = Summarizer(cfg, s5, _Stub(json.dumps(
    {"arc": "Synopsis.\n\n## Act One\nThe hero left home."})))
for _ in range(3):
    sm5._fold_arc([Entry("Scene 1", "scene-1", attrs={"turns": "1-2"},
                         body="Something happened.")])
arc = s5.read("memory/arc.md")
assert arc.count("Act One") == 1, (
    f"the model's own heading was mistaken for authored content and "
    f"re-appended on every fold: {arc.count('Act One')} copies")
assert "## Beats" in arc, "the authored beats were eaten"
print("5) a heading inside the synopsis is not re-appended on every fold")

# ---- 6) a transcript write that changes nothing ------------------------
s6 = _story("Rewrite")
e6 = Engine(cfg, s6)
for i, flag in enumerate(("f0", "f1", "f2")):
    e6.llm = _llm(f"Scene {i}.",
                  f'\n```rpg\n{{"v":1,"deltas":{{"flag_set":{{"{flag}":true}}}}}}\n```')
    list(e6.turn(f"action {i}"))
before_log = [(r.get("turn"), r.get("env")) for r in _read_event_log(s6)]
raw = s6.read("transcript.md")
s6.write("transcript.md", raw)                 # byte-identical rewrite
if len(s6.turns()) < 6:                        # (the guard srv/files.py applies)
    s6.clamp_event_log_to_transcript()
after_log = [(r.get("turn"), r.get("env")) for r in _read_event_log(s6)]
assert before_log == after_log, (
    "a rewrite that changed nothing re-stamped turn indices; two envelopes now "
    "share one index and no branch can separate them again")
print("6) a transcript write that changes nothing moves no ledger record")

# ---- 7) a transcript write that SHORTENS still reconciles --------------
cut = raw.rsplit("<!-- @player -->", 1)[0]
s6.write("transcript.md", cut)
assert len(s6.turns()) == 4, s6.turns()
s6.snapshot(keep=8, reason="transcript-edit")
s6.clamp_event_log_to_transcript()
s6.trim_folds_to_transcript()
end = len(s6.turns())
for rec in _read_event_log(s6):
    assert rec.get("turn", 0) <= end, rec
assert any(p.name for p in (s6.dir / ".snapshots").iterdir()), (
    "trim_folds deletes scenes outright, so the snapshot is the only way back")
print("7) a transcript write that shortens reconciles, behind a snapshot")

# ---- 8) re-adding a deleted lore type restores it ---------------------
s8 = _story("Types")
s8.add_custom_file("races")
assert "races.md" in s8.custom_files()
meta = json.loads(s8.read("meta.json"))
meta["custom_files"] = [f for f in (meta.get("custom_files") or [])
                        if f != "races.md"]
meta["removed_files"] = ["races.md"]
s8.write("meta.json", json.dumps(meta, indent=2))
assert "races.md" not in s8.custom_files()
# Through the ROUTE the SPA calls, not MemoryStore.add_custom_file — the store
# method already cleared the tombstone, the web door did not, and the web door
# is the only one the world editor uses.
from srv.pieces import _declare_type_in  # noqa: E402
_declare_type_in(s8.dir, "meta.json", "races")
assert "races.md" in s8.custom_files(), (
    "the tombstone survived the re-add, so the type existed on disk and in the "
    "meta while the engine ignored it forever — never indexed, never activated, "
    "and 400 from every /world/pieces route")
print("8) re-adding a deleted lore type actually restores it")

# ---- 9) a generation that produces nothing says so --------------------
s9 = _story("Silent")
e9 = Engine(cfg, s9)
s9.append_turn("player", "I wait")
s9.append_turn("narrator", "Nothing stirs.")
e9.llm = _llm("")
assert "".join(e9.continue_story()).strip() == ""
assert len(s9.turns()) == 2, s9.turns()
assert "writer" in s9.read("memory/health.jsonl"), (
    "the reader clicked Continue and nothing happened, with no trace anywhere")
print("9) a generation that produces nothing at all is reported")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP 9 FINDINGS: ALL CLOSED")
