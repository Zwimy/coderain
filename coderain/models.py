"""Popular-model context-size hints + the app's context floors.

Informational data for the Settings UI (desktop now, PWA later — this module is
the single source of truth for both): what context window popular hosted models
ship with, so a user picking a cloud profile knows what `context_tokens` to
enter. Numbers move fast — they are HINTS, not truth; the provider's model page
wins. The engine itself has no upper limit: any `context_tokens` the model
allows (131k, 200k, 1M+) flows straight through to the context budget.
"""
from __future__ import annotations

# Floors (tokens). A profile's context_tokens is clamped UP to MIN_CONTEXT_TOKENS
# (an 8 GB GPU handles this fine locally; below it the memory system starves).
# The assembled-memory budget never drops below MIN_CONTEXT_BUDGET_TOKENS
# (~6-8k characters — premise + sheet + recent turns barely fit under that).
MIN_CONTEXT_TOKENS = 8192
MIN_CONTEXT_BUDGET_TOKENS = 2000

# What to RECOMMEND when a user configures any profile by hand.
RECOMMENDED_MIN_CONTEXT = 16000
# At/above this a model is "long-context": memory can stay almost entirely
# unfolded in the window (set context_budget_tokens to `auto` to use it all).
LONG_CONTEXT = 131072

# The two DEFAULT suggestions shown first at the empty key/model field (web app
# + desktop): both 1M context, dual thinking/non-thinking per request (one model
# can serve Director AND Writer), OpenAI-compatible APIs, open weights.
# (display name, model id, provider, context, why)
RECOMMENDED_DEFAULTS: list[tuple[str, str, str, int, str]] = [
    ("DeepSeek V4 Pro", "deepseek-v4-pro", "DeepSeek", 1_048_576,
     "1.6T MoE; strongest prose+reasoning per dollar; 384k max output"),
    ("GLM 5.2", "glm-5.2", "Zhipu (z.ai)", 1_000_000,
     "750B MoE; sparse attention keeps 1M-context calls cheap; MIT weights"),
]

# (display name, provider, context window in tokens) — mid-2026 snapshot of
# popular hosted models, largest first. Kept deliberately short: a visual aid,
# not a catalog. The RECOMMENDED_DEFAULTS pair leads the list.
CONTEXT_HINTS: list[tuple[str, str, int]] = [
    ("DeepSeek V4 Pro",     "DeepSeek",   1_048_576),
    ("GLM 5.2",             "Zhipu",      1_000_000),
    ("Claude Sonnet 5",     "Anthropic",  1_000_000),
    ("Gemini 3 Pro",        "Google",     1_000_000),
    ("Llama 4 Maverick",    "Meta",       1_000_000),
    ("GPT-5.2",             "OpenAI",       400_000),
    ("Grok 4",              "xAI",          256_000),
    ("Kimi K2",             "Moonshot",     256_000),
    ("Claude Opus 4.8",     "Anthropic",    200_000),
    ("DeepSeek V3.2",       "DeepSeek",     128_000),
]


# --- story-platform comparison ("what runs under the brand name") ------------
# What the big AI-fiction platforms run, per their own docs (mid-2026 snapshot),
# with the context window GATED BY SUBSCRIPTION TIER. Kept straight: most
# platform models are FINETUNES — running the base model with your own key gets
# you the same architecture and the full native window, but NOT their house
# tuning. Only rows marked "same model" are the identical thing.
# (platform model, platform, what it is per their docs, platform context)
PLATFORM_MODELS: list[tuple[str, str, str, str]] = [
    ("Nova",           "AI Dungeon", "Llama 3.3 70B finetune",          "4k-64k by tier"),
    ("Harbinger",      "AI Dungeon", "Mistral Small 3.1 24B finetune",  "2k-32k by tier"),
    ("Wayfarer Small", "AI Dungeon", "Mistral NeMo 12B finetune",       "4k-32k by tier"),
    ("DeepSeek V3.2",  "AI Dungeon", "DeepSeek V3.2 (671B MoE)",        "4k-128k by tier"),
    ("Hermes 3 405B",  "AI Dungeon", "Llama 3.1 405B finetune",         "credit-gated to 32k"),
    ("Oracle V3",      "FictionLab", "base undisclosed (badge: 685B)",  "32k free / 128k paid"),
    ("Glendora V4",    "FictionLab", "blend of models, undisclosed",    "128k paid"),
    ("Ophelia",        "FictionLab", "'novelist' model, undisclosed",   "128k paid"),
]
# (BYO model, comparable to, context with your own key, honest note)
BYO_ALTERNATIVES: list[tuple[str, str, int, str]] = [
    ("Llama 3.3 70B",          "Nova (its base model)",       131_072,
     "same base, full window — not their finetune"),
    ("Mistral Small 3.2 24B",  "Harbinger/Hearthfire base",   128_000,
     "the family they finetune — base flavor, not house style"),
    ("DeepSeek V3.2",          "AI Dungeon DeepSeek / Atlas", 128_000,
     "same model they build on; 128k is its hard ceiling"),
    ("DeepSeek V4 Pro",        "AI Dungeon DeepSeek V4 Pro",  1_048_576,
     "same model; theirs starts at 0k context + paid credits"),
    ("GLM 5.2",                "Raven / GLM 5.1 (same family)", 1_000_000,
     "successor of the family AI Dungeon serves tier-gated"),
    ("Claude Sonnet 5",        "(no platform equivalent)",  1_000_000,
     "frontier prose; 1M window"),
]

# --- hosted presets (web app "Hosted" toggle) ---------------------------------
# Prefills for the hosted-model dropdown: pick one and the base URL + context
# land in the form (all OpenAI-compatible endpoints). The key is yours; the
# starred RECOMMENDED_DEFAULTS pair leads. "custom" keeps every field editable.
HOSTED_PRESETS: list[dict] = [
    {"label": "DeepSeek V4 Pro (recommended)", "model": "deepseek-v4-pro",
     "base_url": "https://api.deepseek.com/v1", "context": 1_048_576,
     "note": "1M ctx, dual think modes — one model covers Director AND Writer"},
    {"label": "GLM 5.2 (recommended)", "model": "glm-5.2",
     "base_url": "https://api.z.ai/api/paas/v4", "context": 1_000_000,
     "note": "1M ctx, sparse attention keeps long calls cheap"},
    {"label": "DeepSeek V3.2 (budget)", "model": "deepseek-chat",
     "base_url": "https://api.deepseek.com/v1", "context": 128_000,
     "note": "the AI Dungeon flagship's base model, full 128k window"},
    {"label": "Claude Sonnet 5", "model": "claude-sonnet-5",
     "base_url": "https://api.anthropic.com/v1/", "context": 1_000_000,
     "note": "frontier prose (OpenAI-compatible endpoint)"},
    {"label": "OpenRouter (any model)", "model": "deepseek/deepseek-v4-pro",
     "base_url": "https://openrouter.ai/api/v1", "context": 1_048_576,
     "note": "one key, hundreds of models — edit the model id freely"},
]

# Plain-language walkthrough for the Settings "Hosted" panel — written for
# someone who has never used an API key. Rendered by the web app (and reusable
# by the desktop app later).
HOSTED_HOWTO: list[str] = [
    "An API key is like a prepaid phone card for an AI model: you buy a little "
    "credit at the model's website, they give you a secret code (the key), and "
    "this app uses that code to talk to the model directly. No subscription, "
    "no middleman — you pay only for what you actually play.",
    "1. Go to platform.deepseek.com (our recommended provider) and sign up "
    "with an email — like any other website account.",
    "2. Add a small credit, ~$5 is plenty to start (Billing → Top up).",
    "3. Create an API key (API Keys → Create) and copy it. It looks like a "
    "long random password. Treat it like one — don't share it.",
    "4. Back here: flip to Hosted, pick the 'DeepSeek V4 Pro' preset, paste "
    "your key, and hit Save & apply. That's it — your stories now run on a "
    "top-tier model.",
    "What it costs: roughly $0.01-0.02 per story turn. Playing 20 turns a day, "
    "every day, is about $6/month — and nothing at all in months you don't "
    "play.",
    "Privacy: the key is stored only on this PC (in the app's .env file) and "
    "every call goes straight from your machine to the provider.",
]

# Plain-language walkthrough for the Settings "Local" panel — written for someone
# who has never installed a local model. Rendered by the web app (reusable by the
# desktop app later). Keep every model tag here in sync with LOCAL_SUGGESTIONS.
LOCAL_HOWTO: list[str] = [
    "Local models run entirely on your own PC — no key, no cost, completely "
    "private. You install one free program (Ollama), download a couple of "
    "models once, and you're offline forever. A GPU with 8 GB+ is ideal; it "
    "runs on CPU too, just slower.",
    "1. Install Ollama: go to ollama.com/download, get the installer for your "
    "system (Windows / macOS / Linux) and run it. It starts on its own and "
    "sits quietly in the background — nothing to configure.",
    "2. Download two models. Open a terminal (Windows: PowerShell) and run "
    "'ollama pull qwen3:4b' (the planner) then 'ollama pull gemma3:4b' (the "
    "writer). Each is a few GB and downloads once. Optional, for smarter "
    "memory recall: 'ollama pull nomic-embed-text'.",
    "3. IMPORTANT — give the models room to think. Out of the box Ollama only "
    "remembers about 4,000 words, which starves longer stories. Set an "
    "environment variable OLLAMA_CONTEXT_LENGTH to 16384, then restart Ollama. "
    "(Windows: search 'Edit environment variables' → New user variable. "
    "macOS/Linux: add 'export OLLAMA_CONTEXT_LENGTH=16384' to your shell "
    "profile.)",
    "4. Come back here, keep the toggle on Local, and pick your models in the "
    "dropdowns below — qwen3:4b for the Director, gemma3:4b for the Writer. Hit "
    "Save & apply. Your stories now run 100% on your machine.",
    "Hardware note: on an 8 GB GPU, qwen3:4b + gemma3:4b is the sweet spot "
    "(~5 GB, quick). Bigger models (qwen3:8b, llama3.1:8b) sharpen the prose "
    "but need more VRAM or spill onto the slower CPU. The list below shows "
    "what you already have installed and suggested upgrades.",
]

# --- local suggestions for an 8 GB GPU (alongside qwen3:4b + gemma3:4b) ------
# (ollama tag, thinking?, download size, why)
LOCAL_SUGGESTIONS: list[tuple[str, str, str, str]] = [
    ("qwen3:8b",       "thinking",     "5.2 GB",
     "sharper Director; keep context <=8k or expect stage swaps"),
    ("deepseek-r1:8b", "thinking",     "5.2 GB",
     "different reasoning flavor (Llama distill) for the Director"),
    ("llama3.1:8b",    "non-thinking", "4.9 GB",
     "classic roleplay prose; Writer alternative to gemma3"),
]


def platform_comparison_lines() -> list[str]:
    """The platform-vs-BYO table as aligned text (Settings dialog / PWA)."""
    lines = ["WHAT THE BIG PLATFORMS RUN (their own docs):", ""]
    lines.append(f"{'Their name':<16}{'Platform':<12}{'Actually is':<32}{'Context'}")
    lines.append("-" * 78)
    for name, platform, base, ctx in PLATFORM_MODELS:
        lines.append(f"{name:<16}{platform:<12}{base:<32}{ctx}")
    lines += ["", "COMPARABLE MODELS WITH YOUR OWN KEY (full native window, no tier):", ""]
    lines.append(f"{'Model':<24}{'Comparable to':<30}{'Context'}")
    lines.append("-" * 78)
    for name, stand_in, ctx, _note in BYO_ALTERNATIVES:
        lines.append(f"{name:<24}{stand_in:<30}{ctx:>10,}")
    lines += ["", "Platform models are mostly finetunes: a base model gives you the",
              "same architecture and full context, NOT their house tuning."]
    return lines


def context_hint_lines() -> list[str]:
    """The hints table as aligned text lines (Settings dialog / CLI / PWA)."""
    starred = {name for name, *_ in RECOMMENDED_DEFAULTS}
    lines = [f"  {'Model':<20}{'Provider':<12}{'Context':>10}"]
    lines.append("-" * 44)
    for name, provider, ctx in CONTEXT_HINTS:
        star = "* " if name in starred else "  "
        lines.append(f"{star}{name:<20}{provider:<12}{ctx:>10,}")
    lines.append("")
    lines.append("* recommended defaults: 1M context + per-request thinking")
    lines.append("  toggle (one model covers Director AND Writer)")
    lines.append("")
    lines.append(f"Recommended: at least {RECOMMENDED_MIN_CONTEXT:,} tokens.")
    lines.append(f"{LONG_CONTEXT:,}+ = long-context; set the memory budget to")
    lines.append("'auto' to fill the whole window. Numbers are a snapshot —")
    lines.append("your provider's model page has the final say.")
    return lines
