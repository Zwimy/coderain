"""Verbatim history was a fixed COUNT with no token ceiling, and the author's
note was invisible in the one panel built to explain the prompt.

short_term_turns sent the last N turns whatever they cost, entirely outside the
context budget: 12 terse turns and 12 enormous ones produced wildly different
prompts and neither was measured. Most chat front ends budget history by tokens
instead. This keeps the count as the cap a user reasons about and adds a token
ceiling underneath it.

Separately, the author's note rides the system prompt under "# STYLE
DIRECTIVES", a single-# heading, so the ## section split in the context report
never saw it: a user asking "why does my style note do nothing" could not see
its size, or whether this turn even included it.

 1) short turns are untouched: the count cap still decides
 2) long turns are trimmed from the OLDEST end by the token ceiling
 3) trimming never goes below HISTORY_FLOOR_TURNS
 4) an explicit short_term_max_tokens overrides auto
 5) the context report shows the note's size, placement and whether it applies
 6) `every: N` makes the report say the note is NOT included on off turns
 7) the report's history count matches what is actually sent
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-histbud-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import (HISTORY_FLOOR_TURNS, history_budget,   # noqa: E402
                             load_config)
from coderain.engine import Engine                                   # noqa: E402
from coderain.inspect import context_report                          # noqa: E402
from coderain.memory import Library                                  # noqa: E402

lib = Library(WORK / "lib")


def _story(name, text, n=12):
    slug = lib.create_story(name, "A courier crosses a frozen kingdom.")
    store = lib.store(slug)
    for _ in range(n // 2):
        store.append_turn("player", "go")
        store.append_turn("narrator", text)
    return store


def _cfg(max_tokens=None, budget=8000):
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.memory["short_term_turns"] = 12
    cfg.memory["context_budget_tokens"] = budget
    if max_tokens is not None:
        cfg.memory["short_term_max_tokens"] = max_tokens
    else:
        cfg.memory.pop("short_term_max_tokens", None)
    return cfg


def test_short_turns_use_the_count_cap():
    store = _story("short", "Rain on the cobbles.")
    eng = Engine(_cfg(), store)
    assert len(eng.history_window()) == 12, len(eng.history_window())
    print("1. short turns: all 12 sent, count cap decides")


def test_long_turns_are_trimmed_oldest_first():
    store = _story("long", "X" * 6000)
    eng = Engine(_cfg(), store)
    win = eng.history_window()
    assert len(win) < 12, len(win)
    # the NEWEST turns are the ones kept
    # == not `is`: turns() builds a FRESH dict per turn on every call, so two
    # calls never return the same object and `is` could only ever be False.
    assert win[-1] == store.turns()[-1], "trimmed from the wrong end"
    total = sum(len(t["text"]) for t in win)
    assert total <= eng.history_tokens * 4 or len(win) == HISTORY_FLOOR_TURNS
    print(f"2. long turns trimmed to {len(win)}, newest kept")


def test_floor_is_respected():
    """§3 one runaway turn must not leave the model with no conversation.

    20k chars per turn, not 400k: the point is that every turn individually
    exceeds the ceiling, which 20k already does at any sane budget. The first
    draft wrote 2.4 MB to disk on every run of the suite for no extra coverage.
    """
    store = _story("huge", "X" * 20_000)
    eng = Engine(_cfg(), store)
    win = eng.history_window()
    assert len(win) == HISTORY_FLOOR_TURNS, len(win)
    print(f"3. floor holds at {HISTORY_FLOOR_TURNS} turns even for absurd turns")


def test_explicit_setting_overrides_auto():
    cfg_auto = _cfg(budget=8000)
    assert history_budget(cfg_auto) == 4000, history_budget(cfg_auto)
    cfg_set = _cfg(max_tokens=1500)
    assert history_budget(cfg_set) == 1500
    cfg_junk = _cfg(max_tokens="nonsense")
    assert history_budget(cfg_junk) == 4000, history_budget(cfg_junk)
    print("4. auto = half the memory budget; explicit wins; junk falls back")


def test_report_surfaces_the_note():
    store = _story("note", "Rain.")
    store.set_custom_instructions("Gritty. Hostile characters. Present tense.")
    ws = store.world_state()
    ws["authors_note"] = {"depth": "tail", "every": 1}
    store.set_world_state(ws)
    cfg = _cfg()
    d = context_report(Engine(cfg, store), cfg)
    an = d["authors_note"]
    assert an["chars"] == len("Gritty. Hostile characters. Present tense."), an
    assert an["depth"] == "tail" and an["every"] == 1, an
    assert an["included_next_turn"] is True, an
    print("5. report shows note size, placement and inclusion:", an)


def test_report_flags_a_skipped_note():
    """§6 the exact confusion: with every=3 the note is absent from most turns,
    and nothing in the prose says so."""
    store = _story("skip", "Rain.", n=2)          # 1 narrator turn -> exchange 2
    store.set_custom_instructions("Gritty.")
    ws = store.world_state()
    ws["authors_note"] = {"depth": "tail", "every": 3}
    store.set_world_state(ws)
    cfg = _cfg()
    d = context_report(Engine(cfg, store), cfg)
    assert d["authors_note"]["included_next_turn"] is False, d["authors_note"]
    print("6. report says the note is NOT included on an off turn")


def test_report_history_matches_what_is_sent():
    store = _story("match", "X" * 6000)
    cfg = _cfg()
    eng = Engine(cfg, store)
    d = context_report(eng, cfg)
    assert d["history_msgs"] == len(eng.history_window()) + 1, d["history_msgs"]
    assert d["history_trimmed"] > 0, d
    assert d["history_cap_turns"] == 12 and d["history_budget_tokens"] > 0
    print(f"7. report agrees with the prompt; trimmed={d['history_trimmed']}")


try:
    for fn in (test_short_turns_use_the_count_cap,
               test_long_turns_are_trimmed_oldest_first,
               test_floor_is_respected,
               test_explicit_setting_overrides_auto,
               test_report_surfaces_the_note,
               test_report_flags_a_skipped_note,
               test_report_history_matches_what_is_sent):
        fn()
finally:
    # try/finally: a failing assertion used to abort the module before the
    # cleanup line, leaking the temp dir into %TEMP% on every red run.
    shutil.rmtree(WORK, ignore_errors=True)
print("\nHISTORY BUDGET TESTS PASSED")
