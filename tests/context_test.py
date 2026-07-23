"""Context floors + auto budget + model hints (post-W1 model-setup pass).

Covers: profile context_tokens floored (never capped), context_budget explicit /
auto / floor / garbage handling, long-context (131k+) flow-through, and the
models hint table used by Settings (and later the PWA).
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import models as M
from coderain.config import (AUTO_BUDGET_CAP_TOKENS, Config, Profile,
                             build_profile, context_budget)


def _cfg(ctx_tokens, budget, max_tokens=700):
    prof = Profile(name="t", base_url="http://x", model="m", api_key="k",
                   context_tokens=ctx_tokens)
    return Config(profile=prof,
                  generation={"max_tokens": max_tokens},
                  memory={"context_budget_tokens": budget},
                  rpg={}, retrieval={}, raw={})


# ---- 1) profile floor: clamped UP, never capped ----
data = {"profiles": {"tiny": {"base_url": "http://x", "model": "m",
                              "context_tokens": 2048},
                     "huge": {"base_url": "http://x", "model": "m",
                              "context_tokens": 1_000_000}}}
assert build_profile(data, "tiny").context_tokens == M.MIN_CONTEXT_TOKENS
assert build_profile(data, "huge").context_tokens == 1_000_000
print("1) context_tokens floored to", M.MIN_CONTEXT_TOKENS, "- 1M passes through")

# ---- 2) explicit budget used as-is (floored) ----
assert context_budget(_cfg(32768, 8000)) == 8000
assert context_budget(_cfg(32768, 500)) == M.MIN_CONTEXT_BUDGET_TOKENS
print("2) explicit budget respected; floored at", M.MIN_CONTEXT_BUDGET_TOKENS)

# ---- 3) auto budget fills the window minus reply + overhead, then CAPS ----
# The compressed scene/arc memory exists so we don't re-send the whole novel; auto
# on a big-context model was the biggest per-turn token sink, so it's capped.
# A window whose derived budget lands below the cap derives normally...
mid = 24576
assert mid - 2500 - 2048 < AUTO_BUDGET_CAP_TOKENS      # guard the fixture itself
assert context_budget(_cfg(mid, "auto", max_tokens=2500)) == mid - 2500 - 2048
assert context_budget(_cfg(mid, 0, max_tokens=2500)) == mid - 2500 - 2048
# ...a large window hits the cap rather than dumping ~126k/998k every pass.
assert context_budget(_cfg(131072, "auto", max_tokens=2500)) == AUTO_BUDGET_CAP_TOKENS
assert context_budget(_cfg(1_000_000, "auto")) == AUTO_BUDGET_CAP_TOKENS
# tiny window: auto still meets the floor
assert context_budget(_cfg(8192, "auto", max_tokens=7000)) == M.MIN_CONTEXT_BUDGET_TOKENS
print("3) auto budget: derives below the cap, capped above it; floor holds on tiny")

# ---- 4) garbage budget value falls back safely ----
assert context_budget(_cfg(32768, "lots")) == 8000
print("4) unparseable budget falls back to 8000")

# ---- 5) hints table sane ----
assert M.RECOMMENDED_MIN_CONTEXT == 16000
assert all(isinstance(c, int) and c >= 100_000 for _, _, c in M.CONTEXT_HINTS)
assert M.CONTEXT_HINTS == sorted(M.CONTEXT_HINTS, key=lambda r: -r[2])
lines = M.context_hint_lines()
assert any("Claude" in ln for ln in lines)
assert any("16,000" in ln for ln in lines)
# the two recommended defaults lead the list and are starred in the render
assert [n for n, *_ in M.CONTEXT_HINTS[:2]] == \
    [n for n, *_ in M.RECOMMENDED_DEFAULTS]
assert sum(ln.startswith("* ") for ln in lines) >= 2
assert all(r[3] >= 1_000_000 for r in M.RECOMMENDED_DEFAULTS)
print("5) hints table: sorted, populated, recommended defaults starred on top")

# ---- 6) platform comparison table sane ----
comp = M.platform_comparison_lines()
assert any("AI Dungeon" in ln for ln in comp)
assert any("FictionLab" in ln for ln in comp)
assert any("Llama 3.3 70B" in ln for ln in comp)
assert all(isinstance(c, int) and c >= M.LONG_CONTEXT - 5000
           for _, _, c, _ in M.BYO_ALTERNATIVES)
assert 4 <= len(M.BYO_ALTERNATIVES) <= 6
assert all(len(r) == 4 for r in M.PLATFORM_MODELS)
assert M.LOCAL_SUGGESTIONS and any(kind == "thinking"
                                   for _, kind, _, _ in M.LOCAL_SUGGESTIONS) \
    and any(kind == "non-thinking" for _, kind, _, _ in M.LOCAL_SUGGESTIONS)
print("6) platform comparison + local suggestions populated")

print("\nCONTEXT TESTS PASSED")
