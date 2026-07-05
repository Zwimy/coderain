"""Optional-module seam: the core engine must run fully even if the heavier
modules (rpg/trinity/vector) are trimmed from a build. CODERAIN_NO_MODULES=1
simulates their absence — everything is free, so there's no licensing to test.
"""
import ast
import inspect
import os
import shutil
import sys
import tempfile

sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain import features                          # noqa: E402
from coderain import sidecar as sidecar_mod            # noqa: E402
from coderain.config import load_config                # noqa: E402
from coderain.engine import Engine                     # noqa: E402
from coderain.memory import Library                    # noqa: E402

root = os.path.join(tempfile.gettempdir(), "cr_modules")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)

# ---- 1) modules resolve when present; hidden under CODERAIN_NO_MODULES ----
assert features.module("rpg") is not None                # normal tree ships them
assert features.enabled("rpg") is True
os.environ["CODERAIN_NO_MODULES"] = "1"
try:
    assert features.module("rpg") is None
    assert features.enabled("rpg") is False
    assert features.enabled("multi_brain") is False
    assert features.enabled("vector_recall") is False
    assert features.enabled("anything-not-a-module") is True   # core is free
finally:
    del os.environ["CODERAIN_NO_MODULES"]
print("1) seam resolves modules; NO_MODULES hides them, core stays on")

# ---- 2) the CORE engine runs a full simple turn with modules absent ----
os.environ["CODERAIN_NO_MODULES"] = "1"
try:
    cfg = load_config()
    cfg.generation["trinity_brain"] = True    # asks for quad — degrades (module)
    slug = lib.saves.create("Core", premise="A lighthouse at world's end.")
    eng = Engine(cfg, lib.saves.store(slug))
    # trinity/rpg/vector are modules → absent; the memory tool is core → stays.
    assert eng.trinity is None and eng.rpg_mod is None
    assert eng.retriever is None

    class _Stub:
        def stream(self, *a, **k):
            for w in ("The lamp turns.", " ```rpg\n", '{"deltas":{}}', "\n```"):
                yield w
        def complete(self, *a, **k):
            return "The lamp turns."
    eng.llm = _Stub()
    out = "".join(eng.turn("I climb the stairs."))
    assert "```rpg" not in out and "deltas" not in out, out
    assert eng.store.turns()[-1]["role"] == "narrator"
    assert "rpg" in eng.store.world_state()   # state shape stays stable
finally:
    del os.environ["CODERAIN_NO_MODULES"]
print("2) core engine: full turn, sidecar stripped, quad/tool/rpg degraded")

# ---- 3) sidecar filtering is core (never imports a module) ----
tree = ast.parse(inspect.getsource(sidecar_mod))
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom):
        assert "modules" not in (node.module or ""), ast.dump(node)
prose, sc = sidecar_mod.strip_sidecar('Hi ```rpg {"check":{}} ```')
assert prose == "Hi" and sc == {"check": {}}
print("3) sidecar filtering is core and standalone")

print("\nMODULES SEAM TESTS PASSED")
