"""The eight sweep-3 findings that were confirmed but left unfixed at the time.

Sweep 3 reproduced each of these and the commit named them rather than quietly
dropping them; this suite is where they were finally closed. Every assertion was
checked to go RED against the old code — a test that cannot fail is worth nothing
(CLAUDE.md).

Asserts:
 1) the reject LABEL is bounded, so a 200k-char delta name cannot become the
    Director's corrective re-ask payload;
 2) quest_update and inventory_equip honour LIST_CAP like every other list;
 3) an equip citing item #150 of a 200-item add is rejected — _valid_equip reads
    the POST-cap add list, the one rpg.apply actually applies;
 4) a slug built from model text is bounded (slugs become state.json keys);
 5) add_facts bounds both the batch and each fact — facts.md rides every prompt
    forever and nothing prunes it;
 6) a failed arc fold does NOT advance folded_scenes, and says so in the health
    log;
 7) a `kind: "thread"` promotion cannot reopen a resolved thread (the round-2 fix
    closed the new_threads door only);
 8) chapter numbering survives a hole in the outline (no overwrite, no wasted
    top-up calls);
 9) scene numbering survives a hole in scenes.md;
10) a branch that drops the scene covering turns 40-50 at turn 45 does not leave
    40-45 claimed-as-folded by a stale pointer;
11) a quad envelope logged for a narrator turn that never arrived is re-indexed
    onto the last real turn instead of being stranded past the end.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw3open-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import validator as V  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import (Entry, Library, _filter_folds_after,  # noqa: E402
                             _read_event_log, _reconcile_fold_state)
from coderain.planner import ChapterPlanner  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom."))


class _Stub:
    """Fixed payload for every call."""

    def __init__(self, payload):
        self.payload = payload

    def complete(self, messages, **kw):
        return self.payload

    def stream(self, messages, **kw):
        return iter([self.payload])


# ---- 1) the reject label is bounded --------------------------------------
s1 = _story("Labels")
huge = "x" * 200_000
_clean, rejected = V.validate(
    {"v": 1, "deltas": {"quest_update": {huge: "active"}}}, s1)
assert rejected, "a quest update against a nonexistent thread must be rejected"
payload = V.rejection_text(rejected)
assert len(payload) < 2000, (
    f"the corrective re-ask payload is {len(payload)} chars — the raw delta "
    "name was interpolated into it verbatim")
assert all(len(r["delta"]) <= V.STR_CAP for r in rejected), rejected
print("1) reject labels are bounded, so the re-ask payload stays small")

# ---- 2) quest_update / inventory_equip honour LIST_CAP -------------------
s2 = _story("Caps")
over = V.LIST_CAP + 20
for i in range(over):
    s2.upsert_entry("threads.md", Entry(f"Thread {i}", f"th-{i}",
                                        attrs={"status": "open"},
                                        body="unresolved"))
clean, rejected = V.validate(
    {"v": 1, "deltas": {"quest_update": {f"th-{i}": "active"
                                         for i in range(over)}}}, s2)
got = (clean.get("deltas") or {}).get("quest_update") or {}
assert len(got) <= V.LIST_CAP, f"quest_update kept {len(got)} entries"
assert any("at most" in r["reason"] for r in rejected), rejected

st = s2.state()
st["rpg"] = {"enabled": True,
             "inventory": {f"item-{i}": {"qty": 1} for i in range(over)}}
s2.write_state(st)
clean, rejected = V.validate(
    {"v": 1, "deltas": {"inventory_equip": [f"item-{i}" for i in range(over)]}}, s2)
got = (clean.get("deltas") or {}).get("inventory_equip") or []
assert len(got) <= V.LIST_CAP, f"inventory_equip kept {len(got)} items"
print("2) quest_update and inventory_equip are capped like every other list")

# ---- 3) equip legality reads the POST-cap add list -----------------------
s3 = _story("Equip")
st = s3.state()
st["rpg"] = {"enabled": True, "inventory": {}}
s3.write_state(st)
adds = [f"blade-{i}" for i in range(200)]
clean, rejected = V.validate(
    {"v": 1, "deltas": {"inventory_add": adds,
                        "inventory_equip": ["blade-150"]}}, s3)
kept_adds = (clean.get("deltas") or {}).get("inventory_add") or []
assert len(kept_adds) == V.LIST_CAP, len(kept_adds)
assert "blade-150" not in ((clean.get("deltas") or {}).get("inventory_equip") or []), (
    "equipped an item the capped inventory_add never actually added")
assert any("not held" in r["reason"] for r in rejected), rejected
# The sanity half: an item INSIDE the cap must still equip, or this "fix" would
# just be a broken equip delta.
clean, _rej = V.validate(
    {"v": 1, "deltas": {"inventory_add": adds, "inventory_equip": ["blade-3"]}}, s3)
assert (clean.get("deltas") or {}).get("inventory_equip") == ["blade-3"], clean
print("3) equip legality uses the capped add list, not the raw one")

# ---- 4) slugs from model text are bounded -------------------------------
s4 = _story("Slugs")
st = s4.state()
st["rpg"] = {"enabled": True, "inventory": {}}
s4.write_state(st)
clean, _rej = V.validate(
    {"v": 1, "deltas": {"inventory_add": [{"name": "a " * 100_000, "qty": 1}]}}, s4)
for it in (clean.get("deltas") or {}).get("inventory_add") or []:
    assert len(it["slug"]) <= V.STR_CAP, len(it["slug"])
    assert len(it["name"]) <= V.STR_CAP, len(it["name"])
print("4) a slug built from model text cannot exceed STR_CAP")

# ---- 5) facts.md is bounded on both axes --------------------------------
s5 = _story("Facts")
n = s5.add_facts([f"Fact number {i}. " + "y" * 5000 for i in range(200)])
assert n <= 24, f"add_facts wrote {n} facts from a single fold"
assert all(len(f) <= 240 for f in s5.facts()), [len(f) for f in s5.facts()][:5]
print("5) add_facts bounds both the batch size and each fact")

# ---- 6) a failed arc fold holds the pointer and logs ---------------------
s6 = _story("ArcFail")
for i in range(1, 41):
    s6.append_turn("player" if i % 2 else "narrator", f"turn {i}")
for k in range(1, 9):
    s6.upsert_entry("memory/scenes.md", Entry(
        f"Scene {k}", f"scene-{k}", attrs={"turns": f"{k * 2 - 1}-{k * 2}"},
        body=f"Something happened in scene {k}."))
st = s6.state()
st["folded_turns"], st["folded_scenes"] = 40, 0
s6.write_state(st)
e6 = Engine(cfg, s6)
e6.summarizer.llm = _Stub("not json at all")     # the arc call fails
e6.summarizer.long_after = 2
e6.summarizer.long_size = 4
e6.summarizer.medium_after = 10_000              # keep the scene loop out of it
before = int(s6.state().get("folded_scenes", 0))
e6.summarizer.maybe_fold()
assert int(s6.state().get("folded_scenes", 0)) == before, (
    "a failed arc fold advanced folded_scenes; those scenes are now marked "
    "absorbed by a synopsis that never mentions them")
health = s6.read("memory/health.jsonl")
assert "arc-fold" in health, f"the failure was silent: {health!r}"
print("6) a failed arc fold holds its pointer and logs the degradation")

# ---- 7) a thread promotion cannot reopen a resolved thread ---------------
s7 = _story("Reopen")
s7.upsert_entry("threads.md", Entry("The Debt", "the-debt",
                                    attrs={"status": "resolved"},
                                    body="Paid in full."))
sm7 = Summarizer(cfg, s7, _Stub(""))
sm7._apply_promotions({"promotions": [
    {"kind": "thread", "slug": "the-debt", "title": "The Debt",
     "status": "open", "detail": "Mentioned again in passing."}]})
th = {e.slug: e for e in s7.entries("threads.md")}["the-debt"]
assert th.attrs.get("status") == "resolved", (
    f"a promotion reopened a resolved thread: {th.attrs}")
# The other way in: a promotion that simply OMITS status. rewrite=True treats a
# missing managed key as a deliberate clear, which is just as bad — an entry with
# no status reads as open to assemble().
sm7._apply_promotions({"promotions": [
    {"kind": "thread", "slug": "the-debt", "title": "The Debt",
     "detail": "Mentioned a third time."}]})
th = {e.slug: e for e in s7.entries("threads.md")}["the-debt"]
assert th.attrs.get("status") == "resolved", (
    f"a promotion with no status cleared the resolved marker: {th.attrs}")
print("7) neither door lets a fold reopen a resolved thread")

# ---- 8) chapter numbering survives a hole -------------------------------
s8 = _story("Outline")
s8.write("premise.md", "A courier crosses a frozen kingdom carrying a sealed box.")
cfg8 = load_config()
cfg8.generation["chapter_plan"] = True
cfg8.generation["chapter_horizon"] = 3
# ONE chapter per call. Seeding no longer asks for a batch, so a stub replying
# with the same {"chapters": [...]} object every time now yields nothing at all.
# Same coverage (numbering survives a hole), current protocol.
class _SeqStub:
    def __init__(self, items):
        self.items = list(items)

    def complete(self, messages, **k):
        nxt = self.items.pop(0) if self.items else {"title": "Extra", "goal": "x"}
        return json.dumps(nxt)


p8 = ChapterPlanner(cfg8, s8, _SeqStub([
    {"title": "One", "goal": "a"}, {"title": "Two", "goal": "b"},
    {"title": "Three", "goal": "c"}]))
assert p8.enabled(), "precondition: the planner must be on for this check"
p8.seed()
assert [c.slug for c in p8.chapters()] == ["ch-1", "ch-2", "ch-3"], p8.chapters()
s8.remove_entry("memory/outline.md", "ch-2")            # a hand-deleted chapter
p8.llm = _Stub(json.dumps({"title": "Four", "goal": "d"}))
made = p8._generate_next()
assert made.slug == "ch-4", (
    f"numbered from the COUNT, not the highest: wrote {made.slug}, overwriting "
    "a real chapter and leaving the outline the same size")
assert len(p8.chapters()) == 3, [c.slug for c in p8.chapters()]
print("8) chapter numbering skips past a hole instead of overwriting")

# ---- 9) scene numbering survives a hole ---------------------------------
s9 = _story("SceneNo")
for k in (1, 2, 3):
    s9.upsert_entry("memory/scenes.md", Entry(
        f"Scene {k}", f"scene-{k}", attrs={"turns": f"{k}-{k}"}, body="x"))
s9.remove_entry("memory/scenes.md", "scene-2")
sm9 = Summarizer(cfg, s9, _Stub(""))
assert sm9._next_scene_no() == 4, sm9._next_scene_no()
print("9) scene numbering skips past a hole instead of overwriting")

# ---- 10) a branch tells the pointer which turns it uncovered ------------
s10 = _story("Uncovered")
for i in range(1, 51):
    s10.append_turn("player" if i % 2 else "narrator", f"turn {i}")
s10.upsert_entry("memory/scenes.md", Entry(
    "Scene 1", "scene-1", attrs={"turns": "1-39"}, body="early"))
s10.upsert_entry("memory/scenes.md", Entry(
    "Scene 2", "scene-2", attrs={"turns": "40-50"}, body="late"))
s10.upsert_entry("memory/scenes.md", Entry(       # forces the `unreadable` path
    "Scene 3", "scene-3", body="no range at all"))
st = s10.state()
st["folded_turns"] = 50
s10.write_state(st)
uncovered = _filter_folds_after(s10, 45)
assert uncovered == 40, uncovered
_reconcile_fold_state(s10, uncovered)
assert s10.state()["folded_turns"] == 39, (
    f"pointer is {s10.state()['folded_turns']}; turns 40-45 lost the scene that "
    "summarized them and would never be folded by anyone")
print("10) a branch does not leave uncovered turns claimed as folded")

# ---- 11) a quad envelope for a turn that never arrived ------------------
s11 = _story("Ledger")
e11 = Engine(cfg, s11)
s11.append_turn("player", "I open the box")
# Exactly what trinity does: apply + log against the turn the Writer is about to
# produce...
e11._pre_turn_rpg = e11._snapshot_rpg()
e11.apply_envelope({"v": 1, "deltas": {"gold_delta": 7}}, False,
                   log_turn=len(s11.turns()) + 1)
rec = _read_event_log(s11)[-1]
assert rec["turn"] > len(s11.turns()), "precondition: the record is past the end"
# ...and the Writer returns nothing, so that turn never lands.
assert s11.clamp_event_log_to_transcript() is True
rec = _read_event_log(s11)[-1]
assert rec["turn"] == len(s11.turns()), rec
assert s11.world_state()["player"]["gold"] >= 7, s11.world_state()
assert s11.clamp_event_log_to_transcript() is False, "second call must be a no-op"
print("11) an envelope whose narrator turn never arrived stays in the ledger")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP-3 OPEN FINDINGS: ALL CLOSED")
