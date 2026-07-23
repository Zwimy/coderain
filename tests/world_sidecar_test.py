"""World sidecar for narrative + location linking (2026-07-23 'do we have location
in the sidecar / improve the simple sidecar').

The engine applies world deltas (time / location / reveal / flags) in EVERY mode,
but the schema that teaches the model to emit them lived only in rpg-rules.md,
injected only with RPG on — so a pure-narrative single-brain story never learned
the sidecar existed. This ungates a small world sidecar for narrative and links the
`location` delta to locations.md.

Asserts:
 1) single-brain + RPG off: the writer IS taught the world sidecar, and an emitted
    location/time/reveal applies (location normalizes to its canonical title; a
    hidden entry is revealed).
 2) the location the player is IN force-activates into the NEXT turn's context even
    when nothing mentions it — its details stay in play.
 3) single-brain + RPG on does NOT get the world sidecar (rpg-rules already covers
    the full envelope — no double injection).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-worldsc-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))

WORLD_SC_HEADING = "## Keeping the world consistent"
TAVERN_BODY = "A smoke-filled den where quiet deals are struck."


def _seed(store):
    store.write("locations.md",
                "# Locations\n\n## Blackwood Tavern {#blackwood-tavern}\n"
                f"importance: 3\n\n{TAVERN_BODY}\n")
    # A hidden entry the story can `reveal` (validator rejects non-hidden slugs).
    store.write("characters.md",
                "# Characters\n\n## Thorne {#thornes-secret}\nhidden: true\n"
                "importance: 3\n\nA fixer with a buried past.\n")


# ---- 1) narrative single-brain: taught the sidecar; deltas apply -------------
cfg = load_config()
cfg.generation["trinity_brain"] = False          # single-brain
store = lib.store(lib.create_story("Tavern", "A rain-soaked errand in a river town."))
assert not store.rpg_enabled()                    # RPG off (default)
_seed(store)
engine = Engine(cfg, store)


class SidecarStub:
    """Single-brain writer: prose + a fenced world sidecar."""
    def __init__(self):
        self.last_sys = None

    def stream(self, messages, **k):
        self.last_sys = messages[0]["content"]
        yield "You duck in out of the rain as night comes on.\n\n"
        yield "```rpg\n"
        yield ('{"deltas": {"time_advance": {"phase": "night"}, '
               '"location": "blackwood tavern", '     # lowercase -> normalizes
               '"reveal": ["thornes-secret"]}}\n')
        yield "```"


stub = SidecarStub()
engine.llm = stub
visible = "".join(engine.turn("step inside"))
engine.maybe_fold()

assert WORLD_SC_HEADING in stub.last_sys, "narrative writer was NOT taught the world sidecar"
assert "```rpg" not in visible, "sidecar leaked into the prose"

ws = store.world_state()
assert ws.get("time", {}).get("phase") == "night", ws.get("time")
# location normalized to the canonical title, not the lowercase input
assert ws.get("player", {}).get("location") == "Blackwood Tavern", ws.get("player")
# the hidden entry was revealed
thorne = next(e for e in store.entries("characters.md") if e.slug == "thornes-secret")
assert not thorne.hidden(), "reveal delta did not make the entry public"
print("1) narrative single-brain: taught the sidecar; time/location/reveal applied")

# resolve_location matches by slug, title, and alias
assert store.resolve_location("BLACKWOOD TAVERN").slug == "blackwood-tavern"
assert store.resolve_location("nowhere-real") is None
print("   resolve_location matches known places, None otherwise")


# ---- 2) current location force-activates next turn --------------------------
class CaptureStub:
    def __init__(self):
        self.sys = None

    def stream(self, messages, **k):
        self.sys = messages[0]["content"]
        yield "You wait, watching the door."


cap = CaptureStub()
engine.llm = cap
# The action mentions nothing about the tavern — the only reason its entry can be
# in context is the force-activation of the place the player is IN.
"".join(engine.turn("keep still and think"))
assert TAVERN_BODY in cap.sys, \
    "the current location's entry was not force-activated into context"
print("2) the place you're in stays in context (force-activated) even unmentioned")


# ---- 3) RPG on -> no world sidecar (full envelope already injected) ----------
store2 = lib.store(lib.create_story("Dungeon", "A torch-lit crawl beneath the keep."))
st = store2.rpg_state(); st["enabled"] = True
store2.set_rpg_state(st)
eng2 = Engine(cfg, store2)
assert eng2.trinity is None                       # still single-brain


class RpgStub:
    def __init__(self):
        self.sys = None

    def stream(self, messages, **k):
        self.sys = messages[0]["content"]
        yield "The corridor forks ahead."


rs = RpgStub()
eng2.llm = rs
"".join(eng2.turn("go left"))
assert WORLD_SC_HEADING not in rs.sys, \
    "world sidecar double-injected on an RPG story (rpg-rules already covers it)"
assert "The sidecar (envelope v1)" in rs.sys, "RPG story lost the full envelope"
print("3) RPG on: full envelope only, no world-sidecar double injection")

shutil.rmtree(HOME, ignore_errors=True)
print("\nWORLD-SIDECAR TESTS PASSED")
