"""Character motivations and goals (2026-07-26 request: "add motivations and goals
... these should also change and update throughout the story ... so even ongoing
stories get this added when a character is referenced").

Characters carry two live header lines:
  wants:      the goal RIGHT NOW (concrete, one line)
  motivation: why they want it (the driver underneath)

Asserts:
 1) a fold can SET them on a character (new goal recorded);
 2) a later fold REWRITES a goal the story has changed;
 3) a fold that doesn't mention them does NOT wipe them (goals persist);
 4) BACKFILL: a character who appears in the folded turns with no goal is flagged
    to the model, so an ongoing story fills in as it plays (no migration needed);
 5) they reach the model — the rendered entry carries both lines into context.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-motiv-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.memory import Library  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

cfg = load_config()
lib = Library(os.path.join(HOME, "lib"))
store = lib.store(lib.create_story("Motive", "A fixer works a debt in a wet city."))
store.write("characters.md",
            "# Characters\n\n## Mara {#mara}\nimportance: 4\n\nA sly fence who "
            "runs the pawnshop on Kell Street.\n")
summ = Summarizer(cfg, store, llm=None)


def attrs_of(slug):
    return next(e.attrs for e in store.entries("characters.md") if e.slug == slug)


# ---- 1) a fold SETS a goal ------------------------------------------------
summ._apply_promotions({"promotions": [
    {"kind": "character", "slug": "mara", "title": "Mara", "importance": 4,
     "wants": "get the ledger back before the ring notices it is gone",
     "motivation": "the debt on it is her sister's, not hers",
     "detail": "A sly fence who runs the pawnshop on Kell Street."},
]})
a = attrs_of("mara")
assert a.get("wants", "").startswith("get the ledger back"), a
assert "sister" in a.get("motivation", ""), a
print("1) a fold records wants + motivation on a character")

# ---- 2) the story changes what she is after -> REWRITTEN ------------------
summ._apply_promotions({"promotions": [
    {"kind": "character", "slug": "mara", "title": "Mara", "importance": 4,
     "wants": "get out of the city before the ring finds her",
     "detail": "A sly fence. She already recovered the ledger, and it cost her."},
]})
a = attrs_of("mara")
assert a["wants"] == "get out of the city before the ring finds her", a
assert "sister" in a.get("motivation", ""), \
    "motivation should persist when the fold only changes the goal"
print("2) a changed goal is rewritten; the deeper motivation persists")

# ---- 3) a fold that ignores them must NOT wipe them ------------------------
summ._apply_promotions({"promotions": [
    {"kind": "character", "slug": "mara", "title": "Mara", "importance": 4,
     "detail": "A sly fence, now keeping her head down."},
]})
a = attrs_of("mara")
assert a.get("wants") and a.get("motivation"), \
    f"a silent fold wiped the goal/motivation: {a}"
print("3) a fold that doesn't mention them leaves both intact")

# ---- 4) BACKFILL: a goalless character present in the turns is flagged -----
store.write("characters.md", store.read("characters.md")
            + "\n## Shade {#shade}\nimportance: 3\n\nA broker who deals in "
              "data-chips.\n")
turns = [{"role": "player", "text": "I ask Shade about the chip."},
         {"role": "narrator", "text": "Shade turns the chip over, weighing it."}]
ctx = summ._existing_context(turns)
assert "NO GOAL RECORDED YET" in ctx, ctx[:400]
assert "Shade" in ctx.split("NO GOAL RECORDED YET")[1][:120], ctx[-400:]
assert "Mara" not in ctx.split("NO GOAL RECORDED YET")[1][:120], \
    "a character that already HAS a goal must not be flagged for backfill"
print("4) backfill: a goalless character in the turns is flagged, one with a goal is not")

# the flag disappears once the goal exists (so it isn't asked for every fold)
summ._apply_promotions({"promotions": [
    {"kind": "character", "slug": "shade", "title": "Shade", "importance": 3,
     "wants": "trade the chip up for passage off-world",
     "motivation": "he is being hunted and needs to disappear",
     "detail": "A broker who deals in data-chips."},
]})
assert "NO GOAL RECORDED YET" not in summ._existing_context(turns)
print("   once filled in, the character is no longer flagged")

# ---- 5) they actually reach the model -------------------------------------
msgs = store.assemble([{"role": "narrator", "text": "Shade waits."}],
                      "I look at Shade and Mara.", budget_tokens=8000)
sys_txt = msgs[0]["content"]
assert "wants: trade the chip up for passage off-world" in sys_txt, \
    "the goal never reached the prompt"
assert "motivation: he is being hunted" in sys_txt, \
    "the motivation never reached the prompt"
print("5) both lines reach the model in the assembled context")

shutil.rmtree(HOME, ignore_errors=True)
print("\nMOTIVATIONS TESTS PASSED")
