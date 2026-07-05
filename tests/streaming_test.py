"""Streaming-core tests: the push-based ThinkFilter must match the pull-based
filter_think byte-for-byte across arbitrary chunk boundaries.

This locks the equivalence the Phase 6 Pyodide spike relies on: the browser drives
ThinkFilter.feed() per fetch chunk (async/push) and must produce exactly what the
desktop generator produces.
"""
import sys, random
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.streaming import ThinkFilter, filter_think
from coderain import llm as _llm  # re-export still importable for old callers

# filter_think is still reachable from llm (regression_test.py imports it there).
assert _llm.filter_think is filter_think, "llm must re-export the same filter_think"


def push(text_chunks):
    """Run the push-based filter over a chunk list; return the concatenated visible text."""
    f = ThinkFilter()
    out = [f.feed(c) for c in text_chunks]
    out.append(f.flush())
    return "".join(out)


def pull(text_chunks):
    return "".join(filter_think(iter(text_chunks)))


def rechunk(s, rng):
    """Split a string into random-sized pieces (including empty ones)."""
    pieces, i = [], 0
    while i < len(s):
        j = min(len(s), i + rng.randint(0, 4))
        pieces.append(s[i:j])
        i = j
    return pieces


# 1) Both shapes agree, and both strip a simple think block.
src = "<think>secret reasoning</think>Hello, world."
assert push([src]) == "Hello, world.", push([src])
assert pull([src]) == "Hello, world."
print("1) think block stripped; push == pull")

# 2) Tag split across many tiny chunks (the hard case) still strips cleanly.
hard = list("<th") + ["ink>hid", "den"] + list("</thi") + ["nk>Vis", "ible"]
assert push(hard) == "Visible", push(hard)
assert pull(hard) == "Visible", pull(hard)
print("2) split-across-chunks tags stripped identically")

# 3) Fuzz: for many random strings and random re-chunkings, push == pull exactly.
rng = random.Random(1234)
alphabet = ["a", "b", " ", ".", "<", ">", "/", "t", "h", "i", "n", "k",
            "<think>", "</think>", "<thi", "nk>", "</th", "ink>"]
for _ in range(4000):
    s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
    chunks = rechunk(s, rng)
    a, b = push(chunks), pull(chunks)
    assert a == b, ("push != pull", repr(s), repr(a), repr(b))
print("3) 4000 fuzzed inputs (malformed tag soup incl.): push == pull, byte-for-byte")

# 4) A trailing partial *opener* prefix is held back (dropped) by both — it could
#    still become <think>. (Non-opener text like "</" is literal and stays.)
for tail in ["<", "<t", "<thi", "<think"]:
    assert push(["ok" + tail]) == "ok", (tail, push(["ok" + tail]))
    assert pull(["ok" + tail]) == "ok", (tail, pull(["ok" + tail]))
assert push(["ok</"]) == "ok</" and pull(["ok</"]) == "ok</"  # not an opener prefix
print("4) trailing partial <think> prefix held back; non-opener text kept")

print("\nSTREAMING CORE TESTS PASSED")
