"""Final-sweep regressions (2026-07-06): ST-31 ReDoS guard, branch carry-forward,
regex/prefix order, emptied-turn, config robustness, $1 backrefs."""
import os, sys, shutil, tempfile, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library, safe_output_regex

root = os.path.join(tempfile.gettempdir(), "se_sweep5")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)


def _eng(rules, chunk, prefix=""):
    store = lib.store(lib.saves.create("Rx", mode="simple", premise="."))
    ws = store.world_state(); ws["regex_rules"] = rules; store.set_world_state(ws)
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["start_reply_with"] = prefix
    eng = Engine(cfg, store)
    eng.llm = type("L", (), {"stream": lambda self, m, **k: iter([chunk])})()
    return store, eng


# ---- ST-31 ReDoS guard: pathological patterns rejected, benign ones pass ----
for good in (r"\bword\b", "colou?r", "wry smile", r"\s{2,}"):
    assert safe_output_regex(good) is True, f"benign pattern rejected: {good}"
for bad in ("(a+)+$", r"(\w+\s*)+$", "(.*a){25}", "[", "x" * 201, ""):
    assert safe_output_regex(bad) is False, f"dangerous/invalid pattern passed: {bad}"
print("1) safe_output_regex: nested-quantifier / over-long / invalid rejected")

# ---- ST-31: a ReDoS rule is SKIPPED at execution (would hang if run) ----
store, eng = _eng([{"find": "(a+)+$", "replace": "X"}], "a" * 40 + "b")
t0 = time.time()
out = eng._apply_output_regex("a" * 40 + "b")
assert time.time() - t0 < 0.5, "dangerous rule must be skipped, not executed"
assert out == "a" * 40 + "b", "skipped rule leaves text unchanged"
print("2) ST-31: catastrophic rule skipped at exec (no hang), text untouched")

# ---- ST-31 order: rule scrubs MODEL output; the ST-22 prefix survives ----
store, eng = _eng([{"find": r"\*", "replace": ""}], "*waves*", prefix="* ")
"".join(eng.turn("go"))
assert store.turns()[-1]["text"] == "* waves", \
    f"prefix must survive the scrub; got {store.turns()[-1]['text']!r}"
print("3) ST-31: regex scrubs model output; the reply prefix is preserved")

# ---- ST-31: a rule that empties the turn stores nothing (no blank turn) ----
store, eng = _eng([{"find": ".+", "replace": "", "flags": "s"}], "some prose")
"".join(eng.turn("go"))
assert not [t for t in store.turns() if t["role"] == "narrator"], \
    "an emptied turn must not be stored"
print("4) ST-31: a rule that empties output stores no blank turn")

# ---- ST-31: SillyTavern/JS-style $1 backreference works ($1 -> \1) ----
store, eng = _eng([{"find": "(hello)", "replace": "$1!"}], "hello world")
"".join(eng.turn("go"))
assert store.turns()[-1]["text"] == "hello! world", store.turns()[-1]["text"]
print("5) ST-31: $1 backreference translated to Python \\1")

# ---- branch preserves quick_actions + regex_rules (genesis-log rebuild) ----
cfgb = load_config(); cfgb.generation["trinity_brain"] = False
slug = lib.saves.create("Br", mode="simple", premise="A tale.")
bs = lib.store(slug)
ws = bs.world_state()
ws["quick_actions"] = ["Wait", "Look"]
ws["regex_rules"] = [{"find": "foo", "replace": "bar", "flags": "i"}]
ws["authors_note"] = {"depth": "tail", "every": 2}
bs.set_world_state(ws)
eb = Engine(cfgb, bs)
eb.llm = type("L", (), {"stream": lambda self, m, **k: iter(["A scene."])})()
"".join(eb.opening()); "".join(eb.turn("look"))
new_slug, _w = lib.saves.branch(slug, len(bs.turns()), cfgb.rpg)
bws = lib.store(new_slug).world_state()
assert bws.get("quick_actions") == ["Wait", "Look"], "branch dropped quick_actions"
assert bws.get("regex_rules") == [{"find": "foo", "replace": "bar", "flags": "i"}], \
    "branch dropped regex_rules"
assert bws.get("authors_note") == {"depth": "tail", "every": 2}, "branch dropped authors_note"
print("6) branch preserves quick_actions + regex_rules + authors_note")

# ---- load_config degrades to the shipped defaults on a malformed config ----
# Contract CHANGED in the 2026-07-21 sweep (D8): this used to raise SystemExit,
# but load_config also runs inside web request handlers, where SystemExit takes
# the whole server down instead of returning an error. A broken config must now
# fall back to a usable profile so the app still boots and can be fixed from
# Settings. See tests/sweep7_server_test.py.
bad = os.path.join(root, "bad.yaml")
for content in ("just: a mapping\nwith: no active_profile\n", "", "- a\n- b\n",
                "]]] not : valid : yaml [[["):
    with open(bad, "w", encoding="utf-8") as f:
        f.write(content)
    cfg_bad = load_config(bad)
    assert cfg_bad.profile.model, f"no usable fallback for config: {content!r}"
print("7) load_config: malformed/empty config -> usable fallback (never fatal)")

print("\nALL SWEEP5 CHECKS PASSED")
