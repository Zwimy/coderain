"""Final-sweep regressions (2026-07-06, pre-default-scenario):
quantified-alternation ReDoS, atomic-write temp uniqueness, and the server's
malformed-payload / lost-update hardening."""
import os, sys, tempfile, shutil, glob, threading, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

root = os.path.join(tempfile.gettempdir(), "se_sweep6")
if os.path.exists(root):
    shutil.rmtree(root)
os.makedirs(root, exist_ok=True)
# Point the whole app at a throwaway home BEFORE importing anything that reads it.
os.environ["CODERAIN_HOME"] = root

from coderain.memory import Library, safe_output_regex  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.config import load_config  # noqa: E402

# ---- safe_output_regex: quantified-alternation bombs now rejected ----
for bomb in ("(a|a)+$", "(a|ab)+$", "(a|a)*", "(x|xy|xyz)+", "(.|.)+"):
    assert safe_output_regex(bomb) is False, f"quantified-alternation not blocked: {bomb}"
# ...while an UN-quantified alternation and ordinary patterns still pass.
for ok in ("(cat|dog)", "colou?r", r"\bword\b", "grey|gray"):
    assert safe_output_regex(ok) is True, f"benign pattern wrongly blocked: {ok}"
print("1) safe_output_regex: quantified alternation blocked; plain alternation allowed")

# ---- exec-time: a quantified-alternation rule is skipped, never hangs ----
lib = Library(root)
store = lib.store(lib.saves.create("Rx", mode="simple", premise="."))
ws = store.world_state(); ws["regex_rules"] = [{"find": "(a|a)+$", "replace": "X"}]
store.set_world_state(ws)
cfg = load_config(); cfg.generation["trinity_brain"] = False
eng = Engine(cfg, store)
t0 = time.time()
out = eng._apply_output_regex("a" * 40 + "b")
assert time.time() - t0 < 0.5, "quantified-alternation rule must be skipped, not run"
assert out == "a" * 40 + "b", "skipped rule leaves text unchanged"
print("2) engine: quantified-alternation rule skipped at exec (no hang)")

# ---- atomic write uses a per-write unique temp and leaves no .tmp behind ----
s2 = lib.store(lib.saves.create("Wr", mode="simple", premise="."))
for i in range(30):
    s2.write("world-bible.md", f"# World bible\n\nrev {i}\n")
assert s2.read("world-bible.md").strip().endswith("rev 29"), "last write must win"
leftovers = glob.glob(os.path.join(s2.dir, "*.tmp"))
assert not leftovers, f"atomic write left temp files behind: {leftovers}"
print("3) MemoryStore.write: unique temp, no leftover .tmp, last write wins")

# ---- concurrent writers to the same file: no corruption, one clean winner ----
s3 = lib.store(lib.saves.create("Cc", mode="simple", premise="."))
vals = [f"# World bible\n\nwriter {n}\n" for n in range(8)]
def _w(v):
    for _ in range(20):
        s3.write("world-bible.md", v)
ts = [threading.Thread(target=_w, args=(v,)) for v in vals]
[t.start() for t in ts]; [t.join() for t in ts]
final = s3.read("world-bible.md")
assert final in vals, f"concurrent writes corrupted the file: {final!r}"
assert not glob.glob(os.path.join(s3.dir, "*.tmp")), "leftover tmp after race"
print("4) MemoryStore.write: concurrent writers -> one intact winner, no torn file")

# ---- server _entry_from_dict tolerates malformed attrs/aliases (400 not 500) ----
import server  # noqa: E402  (imports cleanly against the temp home)
for bad in ({"title": "X", "attrs": [1, 2]},
            {"title": "X", "attrs": "nope"},
            {"title": "X", "aliases": 5},
            {"title": "X", "aliases": {"a": 1}}):
    e = server._entry_from_dict(bad)
    assert e.attrs == {} or isinstance(e.attrs, dict), f"attrs not coerced: {bad}"
    assert isinstance(e.aliases, list), f"aliases not coerced: {bad}"
# a genuinely empty piece still 400s
try:
    server._entry_from_dict({})
    assert False, "empty piece must raise"
except server.HTTPException as ex:
    assert ex.status_code == 400
print("5) server._entry_from_dict: malformed attrs/aliases coerced, not a 500")

# ---- server _clean_regex_rules drops the quantified-alternation bomb on save ----
kept = server._clean_regex_rules([
    {"find": "(a|a)+$", "replace": "boom"},      # dropped
    {"find": "wry smile", "replace": "grin"},    # kept
])
assert kept == [{"find": "wry smile", "replace": "grin", "flags": ""}], kept
print("6) server._clean_regex_rules: quantified-alternation rule dropped on save")

print("\nALL SWEEP6 CHECKS PASSED")
