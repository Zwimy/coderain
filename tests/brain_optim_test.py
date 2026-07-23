"""Brain token-optimization (2026-07-23 'optimize the brain, keep functionality,
reduce tokens').

Asserts, with zero functionality loss:
 1) the Director gets a SLIM planning context — the writer-rules prose is dropped,
    the story/memory context is kept, and the raw history is trimmed to
    trinity.director.history_turns (older turns already live in the memory context).
 2) the Director is told '/no_think' when the profile runs think-on for prose (a
    JSON planner needs no chain-of-thought); the Writer's own payload is untouched.
 3) an IMPORTANT canon-event (importance>=4) folds its causal chain (Why / So what)
    into the entry; an ordinary event does NOT (verbose memory is re-sent forever).
 4) 'auto' context budget is capped so a huge-context model stops dumping its whole
    window into every pass; an explicit number stays uncapped (the escape hatch).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-brainopt-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import (AUTO_BUDGET_CAP_TOKENS, Config, context_budget,  # noqa: E402
                             load_config)
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Library  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


# ---- 1 & 2) Director diet + /no_think --------------------------------------
cfg = load_config()
cfg.generation["trinity_brain"] = True
cfg.generation["think"] = True                       # prose think on...
cfg.raw["trinity"] = {"director": {"history_turns": 2}}   # ...but slim the planner
store = lib.store(lib.create_story("Diet", "A long march down a mountain road."))
st = store.rpg_state(); st["enabled"] = True; st["seed"] = 3   # rpg on -> Director runs
store.set_rpg_state(st)

# Seed several prior turns so history-trimming actually has something to cut.
for i in range(4):
    store.append_turn("player", f"player line {i}")
    store.append_turn("narrator", f"narrator line {i}")

engine = Engine(cfg, store)
assert engine.trinity is not None


class DietStub:
    def __init__(self):
        self.director_sys = None
        self.director_history = None
        self.writer_sys = None

    def complete(self, messages, **k):               # Director
        self.director_sys = messages[0]["content"]
        self.director_history = messages[1:]
        return json.dumps({"beat_plan": "You press on.",
                           "must_stay_consistent": [],
                           "envelope": {"v": 1, "deltas": {}}})

    def stream(self, messages, **k):                 # Writer
        self.writer_sys = messages[0]["content"]
        yield "You press on down the road."


stub = DietStub()
engine.llm = stub
engine.trinity.director_llm = stub
engine.trinity.writer_llm = stub

out = "".join(engine.turn("keep walking"))
assert out == "You press on down the road.", repr(out)

# Director planning context: story state kept, writer-rules prose dropped.
assert "LOGIC AGENT" in stub.director_sys, "director missing its own role prompt"
assert "# STORY & MEMORY CONTEXT" in stub.director_sys, "director lost story state"
assert "Writer rules & tone" not in stub.director_sys, \
    "director still carries the prose-writing rules (not slimmed)"
# History trimmed to history_turns; the LAST message is always the live action.
assert len(stub.director_history) == 2, \
    f"director history not trimmed: {len(stub.director_history)}"
assert stub.director_history[-1]["content"] == "keep walking", \
    "trimming dropped the player's current action"
print("1) Director gets a slim planning context (no writer-rules, history trimmed to 2)")

# /no_think on the Director only; the Writer keeps the full novel-writing payload.
assert "/no_think" in stub.director_sys, "Director not told to skip thinking"
assert "Writer rules & tone" in stub.writer_sys, "Writer lost its prose rules"
assert "/no_think" not in stub.writer_sys, "Writer wrongly told to skip thinking"
print("2) Director told /no_think; Writer's payload untouched")


# ---- 3) causal capture: important events only -------------------------------
store2 = lib.store(lib.create_story("Causal", "A city on the edge of a war."))
summ = Summarizer(cfg, store2, engine.llm)

events = summ._apply_promotions({"promotions": [
    {"kind": "canon-event", "slug": "the-betrayal", "title": "The Betrayal",
     "importance": 5, "when": "Day 3, dusk",
     "cause": "the duke's gold ran out and the guard went unpaid",
     "consequence": "the gates now stand open to the northern army",
     "detail": "The captain of the watch opened the eastern gate at dusk."},
    {"kind": "canon-event", "slug": "a-spilled-cup", "title": "A Spilled Cup",
     "importance": 2,
     "cause": "someone bumped the table",
     "consequence": "wine on the floor",
     "detail": "A cup of wine was knocked over in the tavern."},
]})
assert any("the-betrayal" in e for e in events), events

body = next(e.body for e in store2.entries("canon-events.md")
           if e.slug == "the-betrayal")
assert "Why: the duke's gold ran out" in body, body
assert "So what: the gates now stand open" in body, body

trivial = next(e.body for e in store2.entries("canon-events.md")
               if e.slug == "a-spilled-cup")
assert "Why:" not in trivial and "So what:" not in trivial, \
    "an ordinary event should NOT carry the causal chain (bloats memory)"
print("3) important event records Why/So-what; ordinary event stays terse")


# ---- 4) auto budget cap + explicit escape hatch -----------------------------
def _cfg_with(context_tokens: int, budget) -> Config:
    c = load_config()
    c.profile.context_tokens = context_tokens
    c.memory["context_budget_tokens"] = budget
    c.generation["max_tokens"] = 2000
    return c


big_auto = context_budget(_cfg_with(1_000_000, "auto"))
assert big_auto <= AUTO_BUDGET_CAP_TOKENS, big_auto
assert big_auto == AUTO_BUDGET_CAP_TOKENS, big_auto      # a 1M window hits the cap
print(f"4a) auto budget on a 1M model capped at {big_auto} tokens (was ~998000)")

small_auto = context_budget(_cfg_with(16384, "auto"))
assert small_auto < AUTO_BUDGET_CAP_TOKENS, small_auto   # small window: derived, uncapped
print(f"4b) auto budget on a 16k model derives {small_auto} (below the cap)")

explicit = context_budget(_cfg_with(1_000_000, 60000))
assert explicit == 60000, explicit                       # explicit number: uncapped
print("4c) an explicit budget stays uncapped (the deliberate escape hatch)")


shutil.rmtree(HOME, ignore_errors=True)
print("\nBRAIN-OPTIMIZATION TESTS PASSED")
