"""Optional-module seam (MIT — everything free).

Coderain is fully open source. The engine still resolves its heavier modules
(RPG mechanics, the multi-brain/quad pipeline, vector recall, the agentic
memory-lookup tool) through this seam rather than importing them directly, so
the core keeps running even if `coderain/modules/` is trimmed from a build.
There is NO licensing — every feature is on whenever its module is importable.

`CODERAIN_NO_MODULES=1` simulates the modules being absent (tests use it to
prove the core stands alone).
"""
from __future__ import annotations

import importlib
import os
from types import ModuleType

# Feature flag -> the module that implements it (None = lives in core code).
FEATURES: dict[str, str | None] = {
    "rpg": "rpg",                 # mechanics, sheet, companions side-chat
    "multi_brain": "trinity",     # quad pipeline (Director/Validator/Writer)
    "vector_recall": "vector",    # embeddings + salience retriever
    "memory_tool": None,          # agentic lookup_memory/recall_* tools
}


def _suppressed() -> bool:
    return os.environ.get("CODERAIN_NO_MODULES") == "1"


def module(name: str) -> ModuleType | None:
    """Import an optional module, or None when it's absent/suppressed."""
    if _suppressed():
        return None
    try:
        return importlib.import_module(f"coderain.modules.{name}")
    except ImportError:
        return None


# Back-compat alias (older call sites used pro_module()).
pro_module = module


def enabled(feature: str) -> bool:
    """Free features: always. Module-backed features: on when importable."""
    mod = FEATURES.get(feature)
    if feature in FEATURES and mod is not None and module(mod) is None:
        return False
    return True
