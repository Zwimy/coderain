"""Context assembly priorities (2026-07-26 audit of what actually reaches the API).

Auditing a real 234-turn save showed the budget being spent on the WRONG things at
tighter settings: 21 open threads (an unbounded, ever-growing block) crowded out the
recent scene summaries, the timeline, and the characters actually on stage. Since the
folded scenes ARE the short-term memory that replaces the raw turns, losing them
breaks continuity far worse than trimming lore does.

Asserts:
 1) 'Open threads' is bounded and cannot monopolize the budget; the overflow is still
    named in a one-line index so nothing silently disappears.
 2) 'Recent scenes' survives a tight budget (it is priority 1, above bulk lore).
 3) the timeline is bounded (it is append-only and grows forever).
 4) section inclusion is monotonic for the sections that matter: a bigger budget
    never drops a scene/thread/timeline section that a smaller budget kept.
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-ctxprio-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.memory import Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
store = lib.store(lib.create_story("Prio", "A long-running heist across a wet city."))

# A save that looks like a real long game: many open threads, many scenes.
store.write("threads.md", "# Threads\n\n" + "\n\n".join(
    f"## Thread {i} {{#thread-{i}}}\nstatus: open\nimportance: {1 + i % 5}\n\n"
    f"An unresolved obligation number {i}. " + ("detail " * 40)
    for i in range(1, 22)))
store.write("memory/scenes.md", "# Scenes\n\n" + "\n\n".join(
    f"## Scene {i} {{#scene-{i}}}\nturns: {i}-{i+4}\n\n"
    f"In scene {i} the crew moved on the vault. " + ("prose " * 40)
    for i in range(1, 46)))
store.write("memory/timeline.md", "# Timeline (turn index)\n" + "\n".join(
    f"- [T{i}-{i+4}] Day {i}: the crew did a thing worth remembering here."
    for i in range(1, 120)))
hist = [{"role": "player", "text": "we move"},
        {"role": "narrator", "text": "The rain keeps falling."}]


def sections_at(budget):
    s = store.assemble(hist, "I check the map.", scenes_tail=4,
                       budget_tokens=budget)[0]["content"]
    return re.findall(r"^## (.+)$", s, re.M), s


# ---- 1) open threads are bounded, overflow still indexed -------------------
# NB: entries render as '## Title {#slug}' too, so the section runs until the next
# NON-entry heading, not the next '## ' line.
heads, sys_txt = sections_at(8000)
block = re.search(r"^## Open threads$(.*?)(?=^## (?![^\n]*\{#)|\Z)",
                  sys_txt, re.M | re.S).group(1)
kept_n = len(re.findall(r"^## Thread \d+\s+\{#", block, re.M))
assert len(block) < 8000 * 4 * 0.30, \
    f"open threads still monopolize the budget: {len(block)} chars"
assert kept_n < 21, f"nothing was trimmed: {kept_n} of 21 threads in full"
assert "Also open" in block, "overflow threads vanished instead of being indexed"
assert "[[thread:" in block, "overflow index lost its slugs"
print(f"1) open threads bounded to {len(block):,} chars "
      f"({kept_n} of 21 in full, rest indexed by slug)")

# ---- 2) recent scenes survive a tight budget -------------------------------
for b in (6000, 8000, 12000):
    heads, _ = sections_at(b)
    assert any(h.startswith("Recent scenes") for h in heads), \
        f"Recent scenes dropped at budget {b} (continuity backbone lost)"
print("2) 'Recent scenes' survives tight budgets (6k/8k/12k)")

# ---- 3) the timeline is bounded --------------------------------------------
_h, sys_txt = sections_at(8000)
tl = re.search(r"^## Timeline.*?$(.*?)(?=^## |\Z)", sys_txt, re.M | re.S).group(1)
lines = [ln for ln in tl.splitlines() if ln.strip().startswith("- [T")]
assert 0 < len(lines) < 119, f"timeline not bounded: {len(lines)} lines"
assert "earlier turns folded" in tl, "no note that earlier timeline lines were cut"
print(f"3) timeline bounded to {len(lines)} newest lines (of 119) with a note")

# ---- 4) monotonic for the sections that matter -----------------------------
WATCH = ("Open threads", "Recent scenes", "Timeline", "Story so far",
         "Established facts", "Premise", "You")
prev = None
for b in (4000, 6000, 8000, 12000, 16000, 24000, 32000):
    heads, _ = sections_at(b)
    got = {w for w in WATCH if any(h.startswith(w) for h in heads)}
    if prev is not None:
        lost = prev - got
        assert not lost, f"budget {b} DROPPED sections a smaller budget kept: {lost}"
    prev = got
print("4) inclusion is monotonic for the sections that matter")

shutil.rmtree(HOME, ignore_errors=True)
print("\nCONTEXT-PRIORITY TESTS PASSED")
