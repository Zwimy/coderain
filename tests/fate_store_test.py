"""Fate's cache file and per-save setting (D-045).

The sentence a turn was steered by lives in memory/fate.jsonl, keyed by (turn, action, the narration before it). It is
NOT state, so it stays out of memory/events.jsonl (which describes state and has a long history of count-based
rollback bugs). The setting lives in meta.json, like `mode`, because a branch copies meta.json whole while it
reverts state.json to the snapshot's version.

 1) put replaces a record with the same key, get returns the newest, and the file keeps only the newest KEEP
 2) garbage lines and records of the wrong shape are skipped, never raised
 3) prune drops the exchanges past the transcript's end and nothing else
 4) recent_directions: before a turn, oldest first, only real directions, at most k
 5) the setting: off by default, garbage is off, a round trip, a bad mode refused, other meta keys kept
 6) a branch carries the setting (with and without a snapshot) and keeps only the cache records up to the fork
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="cr-fate-store-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import fate                                   # noqa: E402
from coderain.config import load_config                    # noqa: E402
from coderain.memory import Library                        # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
_n = [0]


def story(turns=0):
    _n[0] += 1
    slug = lib.create_story(f"Fate store {_n[0]}", "A courier crosses a frozen kingdom.")
    store = lib.store(slug)
    for k in range(turns):
        store.append_turn("player", f"I act {k}.")
        store.append_turn("narrator", f"Something happens {k}.")
    return slug, store


def rec(n, text="A bell rings.", key=None, tier="natural"):
    return {"n": n, "key": key or f"{n}:aaaaaaaaaaaa:bbbbbbbb", "nonce": 0, "roll": 5, "tier": tier,
            "stakes": "some", "text": text, "model": "stub"}


def test_put_get_and_cap():
    _slug, s = story()
    fate.put(s, rec(2, "first"))
    fate.put(s, rec(2, "second"))                                    # same key: replaced, not added
    assert [r["text"] for r in fate.read(s)] == ["second"], fate.read(s)
    assert fate.get(s, "2:aaaaaaaaaaaa:bbbbbbbb")["text"] == "second"
    assert fate.get(s, "9:zzz:zzz") is None
    for k in range(3, 3 + fate.KEEP + 20):
        fate.put(s, rec(k, f"line {k}"))
    got = fate.read(s)
    assert len(got) == fate.KEEP and got[-1]["n"] == 3 + fate.KEEP + 19 and got[0]["n"] == 3 + 20, (len(got), got[0]["n"])
    assert all(r["n"] != 2 for r in got), "the oldest record was kept past the cap"
    print("1. put replaces a record with the same key, get finds it, and the file keeps only the newest %d" % fate.KEEP)


def test_garbage_is_skipped():
    _slug, s = story()
    p = s.dir / "memory" / "fate.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json\n" + json.dumps(rec(2)) + "\n" + json.dumps({"n": "x", "key": "k"}) + "\n"
                 + json.dumps([1, 2]) + "\n" + json.dumps({"n": 3}) + "\n\n" + json.dumps(rec(4)) + "\n",
                 encoding="utf-8")
    assert [r["n"] for r in fate.read(s)] == [2, 4], fate.read(s)
    assert fate.read(story()[1]) == []                                 # no file at all
    print("2. garbage lines, wrong shapes and a missing file are skipped, never raised")


def test_prune():
    _slug, s = story()
    for n in (2, 4, 6, 8):
        fate.put(s, rec(n))
    assert fate.prune(s, 8) == 0
    assert fate.prune(s, 5) == 2 and [r["n"] for r in fate.read(s)] == [2, 4]
    assert fate.prune(s, 0) == 2 and fate.read(s) == []
    assert fate.prune(s, 0) == 0
    print("3. prune drops only the exchanges past the end")


def test_recent_directions():
    _slug, s = story()
    for n, text in ((2, "one"), (4, ""), (6, "three"), (8, "four"), (10, "five"), (12, "six")):
        fate.put(s, rec(n, text))
    assert fate.recent_directions(s, 10) == ["one", "three", "four"], fate.recent_directions(s, 10)
    assert fate.recent_directions(s, 100, k=2) == ["five", "six"]
    assert fate.recent_directions(s, 2) == []
    print("4. the recent directions are the last k real ones before the turn, oldest first")


def test_settings():
    slug, s = story()
    assert fate.settings(s) == {"mode": "off", "show_die": False}
    meta = json.loads(s.read("meta.json"))
    meta["fate"] = "nonsense"
    s.write("meta.json", json.dumps(meta))
    assert fate.settings(s) == {"mode": "off", "show_die": False}
    meta["fate"] = {"mode": "LOUD", "show_die": "yes"}
    s.write("meta.json", json.dumps(meta))
    assert fate.settings(s) == {"mode": "off", "show_die": False}, "an unknown mode or a non-boolean must mean off"
    title = json.loads(s.read("meta.json"))["title"]
    assert fate.set_settings(s, "preview") == {"mode": "preview", "show_die": False}
    assert fate.set_settings(s, show_die=True) == {"mode": "preview", "show_die": True}
    assert fate.set_settings(s, "ON", False) == {"mode": "on", "show_die": False}
    assert fate.settings(s) == {"mode": "on", "show_die": False}
    assert json.loads(s.read("meta.json"))["title"] == title, "another meta key was lost"
    try:
        fate.set_settings(s, "sometimes")
    except ValueError:
        pass
    else:
        raise AssertionError("a bad mode was accepted")
    assert fate.settings(s)["mode"] == "on", "a refused change altered the setting"
    print("5. off by default; garbage is off; a round trip; a bad mode is refused; other meta keys are kept")


def test_branch():
    slug, s = story(turns=3)                                  # 6 turns
    fate.set_settings(s, "preview", True)
    for n in (2, 4, 6):
        fate.put(s, rec(n, f"line {n}"))
    cfg = load_config()
    new, _warn = lib.saves.branch(slug, 4, cfg.rpg)           # no snapshot yet
    b = lib.store(new)
    assert fate.settings(b) == {"mode": "preview", "show_die": True}, fate.settings(b)
    assert [r["n"] for r in fate.read(b)] == [2, 4], fate.read(b)
    assert [r["n"] for r in fate.read(s)] == [2, 4, 6], "the source's cache was touched"
    s.snapshot(keep=8, reason="test")                         # a snapshot is what reverts state.json on a branch
    fate.set_settings(s, "on", False)
    new2, _warn = lib.saves.branch(slug, 6, cfg.rpg)
    b2 = lib.store(new2)
    assert fate.settings(b2) == {"mode": "on", "show_die": False}, "the setting did not survive a branch with a snapshot"
    assert [r["n"] for r in fate.read(b2)] == [2, 4, 6]
    print("6. a branch carries the setting, with or without a snapshot, and trims the cache to the fork")


for fn in (test_put_get_and_cap, test_garbage_is_skipped, test_prune, test_recent_directions, test_settings,
           test_branch):
    fn()
shutil.rmtree(HOME, ignore_errors=True)
print("\nFATE STORE TESTS PASSED")
