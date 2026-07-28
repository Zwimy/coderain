"""Fold-pipeline defects found in the 2026-07-28 bug sweep.

A fold rewrites N turns into one paragraph and advances a pointer; after that
the paragraph IS the memory. Every bug here is silent, permanent story damage
discovered dozens of turns later, with the original turns long gone.

Asserts:
 1) repeated undo cannot strand the fold pointer past the transcript, and folds
    describing retracted turns do not survive as canon;
 2) the arc fold preserves the authored `## Beats` list it shares a file with;
 3) the arc loop advances by the ACTUAL chunk, so no scene is skipped;
 4) a newline in a promoted attr cannot swallow the attrs after it;
 5) a non-list `aliases` cannot abort a fold mid-write;
 6) refold refuses a partially-missing range;
 7) refold snapshots do not evict the pre-fold restore points a branch needs.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-swf-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Entry, Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom "
                                            "carrying a sealed box."))


class _Stub:
    """Fold LLM that answers with fixed JSON."""

    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def complete(self, messages, **kw):
        self.calls += 1
        return self.payload

    def stream(self, messages, **kw):
        return iter([self.complete(messages, **kw)])


cfg = load_config()
cfg.memory.update({"medium_fold_after": 4, "medium_fold_size": 2})

# ---- 1) repeated undo cannot strand the fold pointer -------------------
s1 = _story("Undo")
e1 = Engine(cfg, s1)
e1.llm = _Stub('{"scene_summary": "The courier walked on.", "timeline": "walked"}')
e1.summarizer.llm = e1.llm
for i in range(1, 11):
    s1.append_turn("player" if i % 2 else "narrator", f"ORIGINAL-{i}")
e1.maybe_fold()
folded_before = s1.state()["folded_turns"]
assert folded_before >= 6, s1.state()
for _ in range(3):
    e1.undo_last()
st = s1.state()
assert st["folded_turns"] <= len(s1.turns()), (
    f"fold pointer {st['folded_turns']} is past the {len(s1.turns())}-turn "
    "transcript; the turns that replace the undone ones would never fold")
bodies = " ".join(e.body + e.attrs.get("turns", "")
                  for e in s1.entries("memory/scenes.md"))
for sc in s1.entries("memory/scenes.md"):
    end = int(sc.attrs["turns"].split("-")[1])
    assert end <= len(s1.turns()), (
        f"{sc.slug} still summarizes turns {sc.attrs['turns']} — the retracted "
        f"branch stays in memory as canon")
print(f"1) undo x3: pointer {folded_before} -> {st['folded_turns']} for "
      f"{len(s1.turns())} turns, no scene describes dropped turns")

# ---- 2) the arc fold keeps the authored beats --------------------------
s2 = _story("Beats")
e2 = Engine(cfg, s2)
s2.write("memory/arc.md", "# Arc synopsis (long-term)\n\nEarly days.\n\n"
                          "## Beats\n- Find the box\n- Open the box\n- Pay for it\n")
assert len(s2.beats()) == 3, s2.beats()
e2.llm = _Stub('{"arc": "The courier reached the pass."}')
e2.summarizer.llm = e2.llm
e2.summarizer._fold_arc([Entry("Scene 1", "scene-1", attrs={"turns": "1-2"},
                               body="Something happened.")])
assert len(s2.beats()) == 3, (
    f"the arc fold deleted the authored beats: {s2.beats()}\n"
    f"{s2.read('memory/arc.md')}")
assert "reached the pass" in s2.read("memory/arc.md"), s2.read("memory/arc.md")
print("2) the arc fold rewrites the synopsis and keeps the ## Beats list")

# ---- 3) the arc loop advances by the real chunk ------------------------
s3 = _story("Arc")
cfg3 = load_config()
cfg3.memory.update({"medium_fold_after": 4, "medium_fold_size": 2,
                    "long_fold_after": 1, "long_fold_size": 100})
e3 = Engine(cfg3, s3)
e3.llm = _Stub('{"arc": "Summarised."}')
e3.summarizer.llm = e3.llm
for n in range(1, 6):
    s3.upsert_entry("memory/scenes.md", Entry(
        f"Scene {n}", f"scene-{n}", attrs={"turns": f"{n * 2 - 1}-{n * 2}"},
        body=f"Scene {n} body."))
s3.append_turn("player", "x")
e3.summarizer.maybe_fold()
folded_sc = s3.state()["folded_scenes"]
assert folded_sc == 5, (
    f"folded_scenes={folded_sc} but only 5 scenes exist — the counter advanced "
    "by the configured size, so later scenes land in the arc's blind spot")
print(f"3) arc fold advanced by the real chunk ({folded_sc} scenes, not 100)")

# ---- 4) a newline in an attr cannot eat the attrs after it -------------
s4 = _story("Attrs")
e4 = Engine(cfg, s4)
e4.llm = _Stub('{"scene_summary": "She hid.", "timeline": "hid", "promotions": ['
               '{"kind": "character", "slug": "keeper", "title": "Keeper",'
               ' "status": "wounded\\nhiding in the cellar",'
               ' "wants": "to reach the bridge", "motivation": "she owes a debt",'
               ' "detail": "The keeper of the toll bridge."}]}')
e4.summarizer.llm = e4.llm
e4.summarizer._apply_promotions(e4.summarizer._emit_json("x", "y"))
keeper = next(e for e in s4.entries("characters.md") if e.slug == "keeper")
assert keeper.attrs.get("wants") == "to reach the bridge", keeper.attrs
assert keeper.attrs.get("motivation") == "she owes a debt", keeper.attrs
assert "\n" not in keeper.attrs.get("status", ""), keeper.attrs
print(f"4) a multiline status keeps wants/motivation intact ({keeper.attrs['status']!r})")

# ---- 5) a non-list aliases cannot abort the fold ----------------------
s5 = _story("Aliases")
e5 = Engine(cfg, s5)
e5.llm = _Stub('{"scene_summary": "It happened.", "timeline": "t", "promotions": ['
               '{"kind": "character", "slug": "ghost", "title": "Ghost",'
               ' "aliases": 3, "detail": "A pale figure."}]}')
e5.summarizer.llm = e5.llm
for i in range(1, 11):
    s5.append_turn("player" if i % 2 else "narrator", f"turn {i}")
events = e5.summarizer.maybe_fold()          # must not raise
assert s5.state()["folded_turns"] > 0, "the fold aborted; nothing advanced"
assert any(e.slug == "ghost" for e in s5.entries("characters.md"))
print(f"5) a scalar `aliases` no longer aborts the fold ({len(events)} events)")

# ---- 6) refold refuses a partial range --------------------------------
s6 = _story("Refold")
e6 = Engine(cfg, s6)
for i in range(1, 7):
    s6.append_turn("player" if i % 2 else "narrator", f"turn {i}")
s6.upsert_entry("memory/scenes.md", Entry(
    "Scene 3", "scene-3", attrs={"turns": "5-6"}, body="The good full summary."))
s6.drop_last_turns(1)                        # turn 6 is gone; 5 remains
e6.llm = _Stub('{"scene_summary": "A partial rewrite.", "timeline": "part"}')
e6.summarizer.llm = e6.llm
res = e6.summarizer.refold_scene("scene-3")
assert not res["ok"], res
assert next(e for e in s6.entries("memory/scenes.md")
            if e.slug == "scene-3").body == "The good full summary.", \
    "a partial range overwrote a correct summary"
print("6) refold refuses a range the transcript only partly has")

# ---- 7) refold snapshots don't evict branch restore points -------------
s7 = _story("Snaps")
e7 = Engine(cfg, s7)
for i in range(1, 5):
    s7.append_turn("player" if i % 2 else "narrator", f"turn {i}")
s7.upsert_entry("memory/scenes.md", Entry(
    "Scene 1", "scene-1", attrs={"turns": "1-2"}, body="Body."))
for _ in range(5):
    s7.snapshot(keep=5)                      # pre-fold restore points
pre = sorted(p.name for p in (Path(s7.dir) / ".snapshots").iterdir() if p.is_dir())
e7.llm = _Stub('{"scene_summary": "Rewritten.", "timeline": "rw"}')
e7.summarizer.llm = e7.llm
for _ in range(4):
    e7.summarizer.refold_scene("scene-1")
post = sorted(p.name for p in (Path(s7.dir) / ".snapshots").iterdir() if p.is_dir())
assert set(pre) <= set(post), (
    f"refold evicted pre-fold restore points: {sorted(set(pre) - set(post))}")
print(f"7) {len(pre)} pre-fold restore points survive 4 refolds")

shutil.rmtree(HOME, ignore_errors=True)
print("\nFOLD SWEEP TESTS PASSED")
