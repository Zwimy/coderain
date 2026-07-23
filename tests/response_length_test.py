"""response_length must actually cap output (2026-07-22 play-test: 'short' had
no effect, most replies were long). It used to only add a soft prompt hint while
max_tokens stayed at 2500 for every setting — and the quad writer floored it to
4096 regardless. Now it caps the real output-token budget on every path."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from coderain.config import load_config, reply_tokens   # noqa: E402
from coderain.engine import Engine                       # noqa: E402
from coderain.memory import Library                       # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="cr-len-"))
lib = Library(WORK)


def test_reply_tokens_mapping():
    assert reply_tokens({"response_length": "short"}) == 1200
    assert reply_tokens({"response_length": "long"}) == 4096
    # medium honors the user's own max_tokens (the advanced sampler)
    assert reply_tokens({"response_length": "medium", "max_tokens": 3000}) == 3000
    assert reply_tokens({}) == 2500                       # default
    print("reply_tokens: short<medium<long, medium honors max_tokens")


def test_length_reaches_the_model_as_max_tokens():
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["use_memory_tool"] = False
    cfg.generation["think"] = False
    cfg.generation["max_tokens"] = 2500
    store = lib.store(lib.create_story("Len", "A frontier town."))
    eng = Engine(cfg, store)

    class Capture:
        def __init__(self): self.max_tokens = None
        def stream(self, messages, **o):
            self.max_tokens = o.get("max_tokens")
            yield "A reply."
    cap = Capture()
    eng.llm = cap

    seen = {}
    for length in ("short", "medium", "long"):
        cfg.generation["response_length"] = length
        list(eng.turn(f"do {length}"))
        seen[length] = cap.max_tokens
    print("max_tokens seen:", seen)
    assert seen["short"] == 1200, seen
    assert seen["medium"] == 2500, seen
    assert seen["long"] == 4096, seen
    assert seen["short"] < seen["medium"] < seen["long"]
    print("response_length caps the real output budget on the prose path")


def test_length_directive_in_prompt():
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["use_memory_tool"] = False
    cfg.generation["response_length"] = "short"
    store = lib.store(lib.create_story("Dir", "A town."))
    eng = Engine(cfg, store)

    class Peek:
        def __init__(self): self.sys = ""
        def stream(self, messages, **o):
            self.sys = messages[0]["content"]
            yield "ok"
    peek = Peek()
    eng.llm = peek
    list(eng.turn("look"))
    assert "LENGTH: keep it short" in peek.sys, "short directive missing from prompt"
    print("short response also carries a firm length directive")


for fn in (test_reply_tokens_mapping,
           test_length_reaches_the_model_as_max_tokens,
           test_length_directive_in_prompt):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nRESPONSE LENGTH TESTS PASSED")
