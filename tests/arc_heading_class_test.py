"""The arc fold's `## ` demotion, pinned for the whole CLASS of line separators.

Round 11 (2026-07-29). Commit `a7deec7` found that `(?m)^` breaks only on \\n
while `str.splitlines()` breaks on nine separators, fixed it in `Entry.render`,
and left the identical mismatch in `summarizer._fold_arc` — even though the
comment on that very line says "Entry.render demotes body headings for exactly
this reason; the arc writer is the other place it matters." The two sites written
to stay in sync had diverged, and a verification sweep found it four commits
later.

It survived because the existing test pinned ONE separator. `sweep9_findings_test`
§5 uses \\n; `verify_sweep_test` §3 uses \\x0c. Neither generalises. This one
sweeps the class, which is the only reason to trust either site again.

Why it matters beyond tidiness: `## Beats` in memory/arc.md is documented as
AUTHORED-only. `store.beats()` reads it, it drives the per-turn "Beat n/m" block,
and `validator._beats` validates the `beat_advance` delta against it — so a
forged heading lets the model invent a beat list and then advance through it.
Separately, `_arc_tail` treats everything from the second top-level heading on as
the author's and re-appends it, so a forged one grows the file on every fold, for
ever, in a section assembled at priority 1 on every turn. A fold is one-way.

Asserts, for each of LF / CR / U+2028 / NEL / FF:
 1) the model cannot forge a live `## Beats` — store.beats() sees only the real one;
 2) arc.md does not grow across repeated folds.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-archead-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.memory import Entry, Library  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()

SEED_ARC = ("# Arc synopsis (long-term)\n\n(nothing yet)\n\n"
            "## Beats\n- real beat\n")

# Every separator str.splitlines() honours that `(?m)^` does not. \r\n is covered
# by \n; \x0b/\x1c/\x1d/\x1e behave as \x0c does and are left out to keep the
# runtime down.
SEPARATORS = [
    ("\n", "LF"),
    ("\r", "CR"),
    (" ", "U+2028"),
    ("\x85", "NEL"),
    ("\x0c", "FF"),
]


class _Fold:
    """A summarizer LLM that always returns the same fold payload."""

    def __init__(self, payload):
        self.payload = payload

    def complete(self, messages, **kw):
        return self.payload

    def stream(self, messages, **kw):
        return iter([self.payload])


for sep, label in SEPARATORS:
    store = lib.store(lib.create_story("Arc " + label, "A courier travels."))
    store.write("memory/arc.md", SEED_ARC)
    payload = json.dumps({"arc": "Synopsis." + sep + "## Beats\n- FORGED BEAT"})
    summarizer = Summarizer(cfg, store, _Fold(payload))

    sizes = []
    for _ in range(4):
        summarizer._fold_arc([Entry("Scene 1", "scene-1",
                                    attrs={"turns": "1-2"}, body="Something.")])
        sizes.append(len(store.read("memory/arc.md")))

    assert store.beats() == ["real beat"], (
        "[%s] the model forged a live `## Beats` no author wrote: %r. "
        "store.beats() drives the per-turn 'Beat n/m' block and beat_advance "
        "validates against it, so the Logic Agent can advance an invented list."
        % (label, store.beats()))
    assert len(set(sizes)) == 1, (
        "[%s] arc.md grew on every fold (%s). _arc_tail treats the model's own "
        "heading as authored content and re-appends it, unbounded, into a "
        "section that rides every prompt at priority 1." % (label, sizes))
    print("  %-7s forged heading demoted, arc.md stable at %d bytes"
          % (label, sizes[0]))

shutil.rmtree(HOME, ignore_errors=True)
print("\nARC HEADING CLASS: ALL SEPARATORS HELD")
