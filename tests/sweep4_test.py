"""Pre-Tier-4 bugsweep regressions (2026-07-06): security + cross-tier fixes.

Covers: path-traversal / zip-slip guards; reply prefix never orphaned on a
whitespace-only (sidecar) turn; branch preserves the author's note; build_profile
degrades on a partial profile.
"""
import os, sys, shutil, tempfile
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import build_profile, load_config
from coderain.engine import Engine
from coderain.memory import Library, _safe_child, _safe_zip_member

root = os.path.join(tempfile.gettempdir(), "se_sweep4")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)

# ---- security: _safe_child blocks anything but a direct child dir ----
r = Path(root)
assert _safe_child(r, "my-story") is True
for bad in ("", ".", "..", "../evil", "..\\..\\Windows", "/etc", "a/b"):
    assert _safe_child(r, bad) is False, f"_safe_child must reject {bad!r}"
print("1) _safe_child: only a direct child slug passes (no traversal rmtree)")

# ---- security: _safe_zip_member blocks traversal AND absolute/drive/UNC ----
assert _safe_zip_member(r, "meta.json") is True
assert _safe_zip_member(r, "sub/dir/file.md") is True
for bad in ("../escape.txt", "..\\x", "C:/abs.txt", "/abs.txt", "//srv/s/x",
            "dir/", ""):
    assert _safe_zip_member(r, bad) is False, f"_safe_zip_member must reject {bad!r}"
print("2) _safe_zip_member: traversal + absolute/drive/UNC entries rejected")

# ---- ST-22 prefix must NOT be orphaned on a whitespace-only (no-prose) turn ----
cfg = load_config()
cfg.generation["trinity_brain"] = False
cfg.generation["start_reply_with"] = ">>"
store = lib.store(lib.saves.create("WS", mode="simple", premise="Quiet."))
eng = Engine(cfg, store)
eng.llm = type("WsLLM", (), {"stream": lambda self, m, **k: iter([" ", "\n"])})()
assert "".join(eng.turn("x")) == "", "whitespace-only prose must stream nothing"
assert not [t for t in store.turns() if t["role"] == "narrator"], "nothing stored"
# but a real turn with LEADING whitespace still gets the prefix, blanks trimmed
eng.llm = type("WsLLM2", (), {"stream": lambda self, m, **k: iter(["  ", "Hello world"])})()
out = "".join(eng.turn("y"))
assert out == ">>Hello world", f"leading blank swallowed, prefix before prose; got {out!r}"
assert store.turns()[-1]["text"] == ">>Hello world", "stored == streamed"
print("3) ST-22 prefix: not orphaned on empty turn; leading blank trimmed on real turn")

# ---- branch must preserve the author's note (genesis-log, no-snapshot path) ----
cfg2 = load_config()
cfg2.generation["trinity_brain"] = False
slug = lib.saves.create("Br", mode="simple", premise="A tale.")
bs = lib.store(slug)
ws = bs.world_state(); ws["authors_note"] = {"depth": "tail", "every": 4}
bs.set_world_state(ws)
eng2 = Engine(cfg2, bs)
eng2.llm = type("L", (), {"stream": lambda self, m, **k: iter(["A scene unfolds."])})()
"".join(eng2.opening())
"".join(eng2.turn("look around"))
turn_n = len(bs.turns())
new_slug, _warn = lib.saves.branch(slug, turn_n, cfg2.rpg)
branched = lib.store(new_slug).world_state().get("authors_note")
assert branched == {"depth": "tail", "every": 4}, \
    f"branch dropped the author's note: {branched!r}"
print("4) branch preserves the author's note across a genesis-log rebuild")

# ---- build_profile: a partial profile fails readably, not with a bare KeyError ----
try:
    build_profile({"profiles": {"p": {"model": "m"}}}, "p")   # no base_url
    assert False, "expected SystemExit on an incomplete profile"
except SystemExit:
    pass
try:
    build_profile({"profiles": {"p": {"base_url": "u"}}}, "p")  # no model
    assert False, "expected SystemExit on an incomplete profile"
except SystemExit:
    pass
print("5) build_profile: incomplete profile -> readable SystemExit (no boot KeyError)")

print("\nALL SWEEP4 CHECKS PASSED")
