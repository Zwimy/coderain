"""Tier 3 — prompt & generation control.

Covers so far:
  ST-24 custom stop sequences + ST-26 sampler surface -> LLM._params passthrough
  ST-22 persistent 'Start reply with' prefix -> every generated narrator turn
(macros ST-20 and author's note ST-21 append here as they land.)
"""
import os, sys, shutil, tempfile, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import Profile, load_config
from coderain.engine import Engine
from coderain.llm import LLM
from coderain.macros import expand_macros
from coderain.memory import Entry, Library

# ---- ST-24 + ST-26: generation params reach LLM._params ----
prof = Profile("local", "http://localhost:11434/v1", "m", "k", 8192)
llm = LLM(prof, {"temperature": 0.5, "top_p": 0.8, "max_tokens": 300,
                 "stop": ["\nUser:", "###"], "frequency_penalty": 0.4,
                 "presence_penalty": 0.2, "seed": 7, "repetition_penalty": 1.15})
p = llm._params()
assert p["temperature"] == 0.5 and p["top_p"] == 0.8 and p["max_tokens"] == 300
assert p["stop"] == ["\nUser:", "###"], "ST-24 stop list must pass through"
assert p["frequency_penalty"] == 0.4 and p["presence_penalty"] == 0.2, "penalties"
assert p["seed"] == 7, "seed passthrough"
assert p["extra_body"]["repetition_penalty"] == 1.15, "repetition_penalty via extra_body"
# a single-string stop is wrapped in a list
assert LLM(prof, {"stop": "END"})._params()["stop"] == ["END"]
# unset opt-in samplers must NOT be sent (provider default preserved)
p2 = LLM(prof, {"temperature": 0.9})._params()
for k in ("stop", "frequency_penalty", "presence_penalty", "seed", "extra_body"):
    assert k not in p2, f"{k} must be absent when unset"
print("1) ST-24 stop + ST-26 samplers pass through _params; unset stays absent")

# ---- ST-22: persistent reply prefix on every generated turn ----
root = os.path.join(tempfile.gettempdir(), "se_tier3")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.saves.create("Inn", mode="simple", premise="A roadside inn."))
cfg = load_config()
cfg.generation["trinity_brain"] = False          # single-brain path
cfg.generation["start_reply_with"] = '"'         # persistent dialogue-quote prefix
eng = Engine(cfg, store)


class ProseLLM:
    def stream(self, messages, **k):
        yield "Hello there, weary traveler."


eng.llm = ProseLLM()
out = "".join(eng.turn("I step inside."))
assert out == '"Hello there, weary traveler.', f"streamed = prefix+prose, got {out!r}"
assert store.turns()[-1]["role"] == "narrator"
assert store.turns()[-1]["text"] == '"Hello there, weary traveler.', \
    "stored narrator turn must begin with the prefix (display == storage)"

# empty prefix = unchanged behavior
cfg.generation["start_reply_with"] = ""
out2 = "".join(eng.turn("I sit by the fire."))
assert out2 == "Hello there, weary traveler.", "no prefix -> untouched"
print("2) ST-22 persistent prefix: every generated turn starts with it (stream==store)")

# ---- ST-20: macro expansion (unit) ----
assert expand_macros("Hi {{user}}!", player="Aria") == "Hi Aria!"
assert expand_macros("Hi {{player}}!", player="Aria") == "Hi Aria!"
assert expand_macros("Day {{day}} at {{clock}}", day="3", clock="dusk") == "Day 3 at dusk"
r = expand_macros("{{roll::2d6}}", seed=5, turn=1)
assert 2 <= int(r) <= 12 and expand_macros("{{roll::2d6}}", seed=5, turn=1) == r, \
    "roll is in range AND replay-stable"
assert 1 <= int(expand_macros("{{roll::20}}", seed=5, turn=1)) <= 20, "{{roll::N}} = 1..N"
c = expand_macros("{{random::sword::shield::bow}}", seed=9, turn=2)
assert c in ("sword", "shield", "bow")
assert expand_macros("{{random::sword::shield::bow}}", seed=9, turn=2) == c, "random stable"
two = "{{roll::1d100}}-{{roll::1d100}}"
assert expand_macros(two, seed=1, turn=0) == expand_macros(two, seed=1, turn=0), \
    "two rolls in one string are jointly reproducible"
assert expand_macros("{{unknown}} {{char}}") == "{{unknown}} {{char}}", "unknown untouched"
assert expand_macros("plain") == "plain"
print("3) ST-20 macros: user/day/clock, seeded roll+random, unknown left as-is")

# ---- ST-20: macros expand inside the assembled context ----
store2 = lib.store(lib.saves.create(
    "MacroWorld", mode="simple", premise="Welcome, {{user}}. You rolled {{roll::1d1}}."))
persona = store2.entries("player.md")[0].title      # the player persona name
sysm = store2.assemble([], "look around")[0]["content"]
assert f"Welcome, {persona}." in sysm, "premise {{user}} -> player persona name"
assert "You rolled 1." in sysm, "{{roll::1d1}} -> 1"
assert "{{user}}" not in sysm and "{{roll" not in sysm, "no raw macros leak to the model"
print("4) ST-20 macros expand in the assembled context block")

# ---- ST-20: macros expand in the authored opening (first message) ----
store3 = lib.store(lib.saves.create(
    "Greet", mode="simple",
    premise="A tale.\n## Opening\n\nHello, {{user}}! Fate rolls {{roll::1d1}}.\n"))
persona3 = store3.entries("player.md")[0].title
cfg3 = load_config()
cfg3.generation["trinity_brain"] = False
eng3 = Engine(cfg3, store3)
op = "".join(eng3.opening())
assert f"Hello, {persona3}!" in op and "Fate rolls 1." in op, "opening macros must expand"
assert store3.turns()[-1]["text"] == op, "stored opening == expanded text"
print("5) ST-20 macros expand in the authored opening greeting")

# ---- ST-21: author's note depth (system vs tail) + frequency ----
store4 = lib.store(lib.saves.create("Note", mode="simple", premise="A quiet case."))
store4.write("custom-instructions.md", "header\n---\nKeep it noir.")
cfg4 = load_config()
cfg4.generation["trinity_brain"] = False
eng4 = Engine(cfg4, store4)
msgs = [{"role": "system", "content": "BASE"}, {"role": "user", "content": "do X"}]

# default (system depth, every 1): note rides the system prompt
out = eng4._augment_style(msgs)
assert "Keep it noir." in out[0]["content"], "default author's note -> system prompt"

# tail depth: note leaves the system prompt, lands just before the player's action
ws = store4.world_state(); ws["authors_note"] = {"depth": "tail", "every": 1}
store4.set_world_state(ws)
out = eng4._augment_style(msgs)
assert "Keep it noir." not in out[0]["content"], "tail depth -> not in system"
assert out[-1]["content"] == "do X", "player's action stays last"
assert out[-2]["content"].startswith("# AUTHOR'S NOTE") and "Keep it noir." in out[-2]["content"], \
    "tail author's note sits right before the player's action"

# frequency: every 3 -> injects on exchange 3, 6, ... (exchange = narrator turns + 1)
ws["authors_note"] = {"depth": "system", "every": 3}; store4.set_world_state(ws)
assert "Keep it noir." not in eng4._augment_style(msgs)[0]["content"], "exchange 1 (every 3) -> skip"
store4.append_turn("narrator", "n1"); store4.append_turn("narrator", "n2")  # exchange 3 next
assert "Keep it noir." in eng4._augment_style(msgs)[0]["content"], "exchange 3 (every 3) -> inject"
print("6) ST-21 author's note: system/tail depth + every-N frequency")

# ================= bugsweep regression fixes (2026-07-06) =================

# FIX F1: unclosed `{{name::` fragments must not cause an O(n^2) hang.
t0 = time.time()
_ = expand_macros("{{roll::" * 20000, seed=1, turn=1)
assert time.time() - t0 < 2.0, "unclosed macros hung (ReDoS regression)"
assert expand_macros("{{roll::1d1}}", seed=1, turn=1) == "1", "normal macros still work"
assert expand_macros("{{random::a::b::c}}", seed=1, turn=1) in ("a", "b", "c")
print("7) FIX F1 macro ReDoS: unclosed fragments are linear, normal macros intact")

# FIX E: a caller's own extra_body must not clobber repetition_penalty.
p3 = LLM(prof, {"repetition_penalty": 1.15})._params(extra_body={"min_p": 0.05})
assert p3["extra_body"]["repetition_penalty"] == 1.15 and p3["extra_body"]["min_p"] == 0.05, \
    "extra_body must deep-merge, not overwrite"
print("8) FIX E: extra_body deep-merges (repetition_penalty survives an override)")

# FIX A: on an empty-prose turn the prefix must NOT be streamed or stored.
cfgE = load_config()
cfgE.generation["trinity_brain"] = False
cfgE.generation["start_reply_with"] = '"'
storeE = lib.store(lib.saves.create("Void", mode="simple", premise="Nothing here."))
engE = Engine(cfgE, storeE)
engE.llm = type("EmptyLLM", (), {"stream": lambda self, m, **k: iter(())})()
before = len(storeE.turns())
outE = "".join(engE.turn("do nothing"))
assert outE == "", f"empty prose must stream nothing, not an orphan prefix; got {outE!r}"
assert not [t for t in storeE.turns() if t["role"] == "narrator" and t["text"] == '"'], \
    "must never store a bare prefix as a narrator turn"
# FIX F4: a non-string start_reply_with is ignored (no garbage prefix)
engE.cfg.generation["start_reply_with"] = ["oops"]
assert engE._reply_prefix() == "", "non-string prefix must be ignored"
print("9) FIX A: prefix never orphaned on an empty turn; FIX F4 non-string ignored")

# FIX B: 'every N' counts exchanges (narrator turns), 1-based — no parity bug.
cfgB = load_config()
cfgB.generation["trinity_brain"] = False
storeB = lib.store(lib.saves.create("Cadence", mode="simple", premise="A case."))
storeB.write("custom-instructions.md", "keep\n---\nNoir tone.")
engB = Engine(cfgB, storeB)
wsB = storeB.world_state(); wsB["authors_note"] = {"depth": "system", "every": 2}
storeB.set_world_state(wsB)
msgsB = [{"role": "system", "content": "BASE"}, {"role": "user", "content": "act"}]
assert "Noir tone." not in engB._augment_style(msgsB)[0]["content"], "exchange 1 (every 2) -> skip"
storeB.append_turn("player", "a"); storeB.append_turn("narrator", "b")
assert "Noir tone." in engB._augment_style(msgsB)[0]["content"], "exchange 2 (every 2) -> inject"
storeB.append_turn("player", "c"); storeB.append_turn("narrator", "d")
assert "Noir tone." not in engB._augment_style(msgsB)[0]["content"], "exchange 3 (every 2) -> skip"
print("10) FIX B: author's-note every-N cadence counts exchanges (no parity bug)")

# FIX F2: macros inside the author's note expand (like the opening/context do).
storeB.write("custom-instructions.md", "keep\n---\nAddress {{user}} by name.")
wsB["authors_note"] = {"depth": "system", "every": 1}; storeB.set_world_state(wsB)
persB = storeB.entries("player.md")[0].title
outB = engB._augment_style(msgsB)[0]["content"]
assert f"Address {persB} by name." in outB and "{{user}}" not in outB, "note macros must expand"
print("11) FIX F2: author's-note macros expand (no raw {{...}} to the model)")

print("\nALL TIER-3 CHECKS PASSED")
