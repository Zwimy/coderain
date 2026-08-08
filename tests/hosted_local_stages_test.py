"""Hosted mode could not use a local supporting model, and history was a fixed 12.

TWO CHANGES.

1. Saving in hosted mode used to STRIP every per-stage model pin ("one big
   dual-mode model serves every stage"), so a hosted Writer with a free local
   Director was impossible to configure from the UI — even though the engine has
   always honoured such a pin. §1-§5.

2. short_term_turns was a fixed 12 messages, roughly 6 exchanges, sitting outside
   the context budget. No comparable app does this: AI Dungeon gives history ~50%
   of the remaining tokens, SillyTavern fits as many recent messages as the
   allowance holds. It is now "auto" — the token ceiling governs. §6-§8.

 1) a local pin round-trips through GET /api/settings
 2) a stage pinned to a NON-local profile does not read back as local
 3) saving hosted mode WRITES the local pins instead of stripping them
 4) a blank pin means "follow the hosted model" and removes the pin
 5) saving hosted mode still preserves unrelated trinity settings
 6) short_term_turns 'auto' yields the sanity cap, not 12
 7) an explicit number still wins
 8) 0 does NOT mean "the whole transcript" (recent_turns(0) is turns()[0:])
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-hoststage-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import (HISTORY_COUNT_CAP, load_config,        # noqa: E402
                             short_term_turns)
from srv.settings import _local_pin                                  # noqa: E402


def test_local_pin_round_trips():
    tri = {"director": {"profile": "local", "model": "qwen3:4b"}}
    assert _local_pin(tri, "director") == "qwen3:4b"
    print("1. a local pin reads back as the model name")


def test_non_local_pin_is_not_local():
    """§2 a stage pointed at another HOSTED model is not a local supporting
    model, and must not show up in the local dropdown as if it were."""
    assert _local_pin({"director": {"profile": "hosted", "model": "x"}},
                      "director") == ""
    assert _local_pin({"director": {"model": "qwen3:4b"}}, "director") == ""
    assert _local_pin({}, "director") == ""
    assert _local_pin({"director": "malformed"}, "director") == ""
    print("2. non-local, unset and malformed pins all read back empty")


def _save(body_hosted, existing_trinity=None):
    """Drive the hosted branch of put_settings against a temp config."""
    import srv.core as core
    from srv.settings import put_settings
    raw = core._cfg.raw
    raw["profiles"] = {"local": {"base_url": "http://localhost:11434/v1",
                                 "model": "qwen3:4b",
                                 "api_key_env": "OLLAMA_API_KEY",
                                 "context_tokens": 16384},
                       "hosted": {"base_url": "https://api.example.com/v1",
                                  "model": "big-model",
                                  "api_key_env": "HOSTED_API_KEY",
                                  "context_tokens": 131072}}
    if existing_trinity is not None:
        raw["trinity"] = existing_trinity
    else:
        raw.pop("trinity", None)
    body = {"mode": "hosted",
            "hosted": {"model": "big-model",
                       "base_url": "https://api.example.com/v1",
                       "context_tokens": 131072, "api_key": "",
                       **body_hosted}}
    put_settings(body)
    return load_config().raw.get("trinity") or {}


def test_saving_hosted_writes_the_pins():
    tri = _save({"director_local": "qwen3:4b", "lorekeeper_local": "gemma3:4b"})
    assert tri.get("director") == {"profile": "local", "model": "qwen3:4b"}, tri
    assert tri.get("lorekeeper") == {"profile": "local", "model": "gemma3:4b"}, tri
    print("3. hosted save writes local stage pins:", tri)


def test_blank_pin_follows_hosted():
    tri = _save({"director_local": "", "lorekeeper_local": ""},
                existing_trinity={"director": {"profile": "local",
                                               "model": "qwen3:4b"}})
    assert "profile" not in (tri.get("director") or {}), tri
    assert "model" not in (tri.get("director") or {}), tri
    print("4. a blank pin removes the pin (stage follows the hosted model)")


def test_unrelated_trinity_settings_survive():
    """§5 the regression the old code was written to avoid — do not undo it."""
    tri = _save({"director_local": "qwen3:4b"},
                existing_trinity={"lorekeeper": {"profile": "local",
                                                 "model": "gemma3:4b",
                                                 "enabled": True}})
    assert (tri.get("lorekeeper") or {}).get("enabled") is True, tri
    print("5. unrelated per-stage settings survive a hosted save")


# ---- history sizing --------------------------------------------------

class _Cfg:
    def __init__(self, val):
        self.memory = {} if val is None else {"short_term_turns": val}


def test_auto_uses_the_cap():
    assert short_term_turns(_Cfg("auto")) == HISTORY_COUNT_CAP
    assert short_term_turns(_Cfg(None)) == HISTORY_COUNT_CAP     # absent = auto
    assert short_term_turns(_Cfg("")) == HISTORY_COUNT_CAP
    assert load_config().memory.get("short_term_turns") == "auto"
    print(f"6. auto -> {HISTORY_COUNT_CAP}; shipped default is 'auto'")


def test_explicit_number_wins():
    assert short_term_turns(_Cfg(12)) == 12
    assert short_term_turns(_Cfg("24")) == 24
    assert short_term_turns(_Cfg("nonsense")) == HISTORY_COUNT_CAP
    print("7. an explicit number still wins; junk falls back to auto")


def test_zero_is_not_the_whole_transcript():
    """§8 recent_turns(n) is turns()[-n:], and [-0:] is [0:] — the ENTIRE
    transcript. Someone setting 0 to mean 'no verbatim history' would have got
    the whole novel in every prompt."""
    assert short_term_turns(_Cfg(0)) == HISTORY_COUNT_CAP
    assert short_term_turns(_Cfg(-5)) == HISTORY_COUNT_CAP
    print("8. 0 and negatives are treated as auto, never as 'everything'")


try:
    for fn in (test_local_pin_round_trips,
               test_non_local_pin_is_not_local,
               test_saving_hosted_writes_the_pins,
               test_blank_pin_follows_hosted,
               test_unrelated_trinity_settings_survive,
               test_auto_uses_the_cap,
               test_explicit_number_wins,
               test_zero_is_not_the_whole_transcript):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nHOSTED LOCAL-STAGE + HISTORY SIZING TESTS PASSED")
