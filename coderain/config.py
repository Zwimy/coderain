"""Load config.yaml + .env and resolve the active provider profile."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .models import MIN_CONTEXT_BUDGET_TOKENS, MIN_CONTEXT_TOKENS


def _home_dir() -> Path:
    """Where user data lives (config.yaml, .env, saves/, scenarios/, …).

    - CODERAIN_HOME env var wins (portable installs, tests).
    - Frozen build (PyInstaller desktop app): %LOCALAPPDATA%\\Coderain —
      the exe dir is replaced on update, so data must not live there.
    - Source checkout: the repo root, as always.
    """
    override = os.environ.get("CODERAIN_HOME", "").strip()
    if override:
        p = Path(override)
    elif getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(base) / "Coderain"
    else:
        return Path(__file__).resolve().parent.parent
    p.mkdir(parents=True, exist_ok=True)
    return p


ROOT = _home_dir()

# A fresh install (frozen app first run) has no config.yaml — this is the
# shipped default: local Ollama quad (qwen3 Director / gemma3 Writer). The
# Settings page rewrites it from the UI.
_DEFAULT_CONFIG = """\
active_profile: local
profiles:
  local:
    base_url: http://localhost:11434/v1
    model: qwen3:4b
    api_key_env: OLLAMA_API_KEY
    context_tokens: 16384
generation:
  temperature: 0.9
  top_p: 0.95
  max_tokens: 2500
  think: true
  use_memory_tool: false
  trinity_brain: true
  response_length: medium
  ai_acts_as_player: false
  chapter_outline: true
memory:
  short_term_turns: 12
  medium_fold_after: 12
  medium_fold_size: 5
  long_fold_after: 8
  long_fold_size: 4
  context_budget_tokens: 8000
rpg: {}
retrieval:
  enabled: false
  embed_model: nomic-embed-text
  top_k: 4
trinity:
  director:
    profile: local
    model: qwen3:4b
  lorekeeper:
    profile: local
    model: gemma3:4b
  writer:
    profile: local
    model: gemma3:4b
"""


@dataclass
class Profile:
    name: str
    base_url: str
    model: str
    api_key: str
    context_tokens: int
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    profile: Profile
    generation: dict[str, Any]
    memory: dict[str, Any]
    rpg: dict[str, Any]
    retrieval: dict[str, Any]
    raw: dict[str, Any]


def build_profile(data: dict, name: str, model: str | None = None) -> Profile:
    """Resolve a named profile from a loaded config dict into a Profile, optionally
    overriding just the model. Reused by the Trinity Brain so each stage can point at
    a different endpoint/key/model. Assumes .env is already loaded."""
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise SystemExit(
            f"profile '{name}' not found. Options: {', '.join(profiles)}"
        )
    p = profiles[name]
    base_url = p.get("base_url")
    model = model or p.get("model")
    if not base_url or not model:
        # A hand-edited/partial profile must fail with a readable message, not a
        # bare KeyError at server import (which loads config once at boot).
        raise SystemExit(
            f"profile '{name}' is incomplete — it needs both base_url and model")
    key_env = p.get("api_key_env", "")
    api_key = os.getenv(key_env, "") if key_env else ""
    if not api_key:
        # Ollama and some local servers don't check the key; use a placeholder.
        api_key = "not-needed"
    return Profile(
        name=name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        # Floored, never capped: a too-small window starves the memory system
        # (an 8 GB GPU handles the floor locally), while 131k/200k/1M+ windows
        # pass straight through wherever the model allows them.
        context_tokens=max(MIN_CONTEXT_TOKENS,
                           int(p.get("context_tokens", 8192))),
        extra_headers=p.get("extra_headers", {}) or {},
    )


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if not cfg_path.exists():                    # first run of a fresh install
        cfg_path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    # A malformed config must never be fatal: load_config runs inside request
    # handlers, and SystemExit there would take the whole server down rather
    # than return an error. Fall back to the shipped defaults instead, so the
    # app still boots and the user can fix it from Settings.
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        data = None
    if not isinstance(data, dict):
        data = yaml.safe_load(_DEFAULT_CONFIG)

    active = data.get("active_profile")
    if active is None or active not in (data.get("profiles") or {}):
        fallback = yaml.safe_load(_DEFAULT_CONFIG)
        if not (data.get("profiles") or {}):
            data = fallback                      # nothing usable — start clean
        active = data.get("active_profile") or next(iter(data["profiles"]))
        data["active_profile"] = active
    try:
        profile = build_profile(data, active)
    except SystemExit:
        # build_profile still exits hard on an incomplete/partial profile (a
        # hand-edited config.yaml can produce one). Same reasoning as above: this
        # runs at boot AND inside request handlers, so degrade to the shipped
        # defaults rather than taking the process down.
        fallback = yaml.safe_load(_DEFAULT_CONFIG)
        data = fallback
        active = data["active_profile"]
        profile = build_profile(data, active)
    return Config(
        profile=profile,
        generation=data.get("generation", {}),
        memory=data.get("memory", {}),
        rpg=data.get("rpg", {}) or {},
        retrieval=data.get("retrieval", {}) or {},
        raw=data,
    )


# `auto` fills the profile's window, but past a point that just re-sends the
# whole novel every pass — the compressed scene/arc memory exists precisely so we
# DON'T have to. On a 200k/1M model that was the biggest per-turn token sink. Cap
# the auto-derived budget at a generous ceiling; a user who genuinely wants more
# sets an explicit number (those stay uncapped — the deliberate escape hatch).
AUTO_BUDGET_CAP_TOKENS = 24000


def context_budget(config: Config) -> int:
    """The assembled-memory budget in tokens. An explicit number is used as-is
    (floored, uncapped); `auto`/0 derives it from the active profile's window —
    reply tokens + overhead reserved — then caps it at AUTO_BUDGET_CAP_TOKENS so
    a long-context model doesn't dump its whole window into every pass."""
    raw = config.memory.get("context_budget_tokens", 8000)
    auto = raw in (0, None) or (isinstance(raw, str)
                                and raw.strip().lower() == "auto")
    if auto:
        reply = int(config.generation.get("max_tokens", 700) or 700)
        derived = config.profile.context_tokens - reply - 2048
        derived = min(derived, AUTO_BUDGET_CAP_TOKENS)
        return max(MIN_CONTEXT_BUDGET_TOKENS, derived)
    try:
        return max(MIN_CONTEXT_BUDGET_TOKENS, int(raw))
    except (TypeError, ValueError):
        return 8000


# response_length is the primary length control. It used to only add a soft
# prompt hint (which strong hosted models happily ignore) while max_tokens stayed
# at 2500 for every setting, so "short" had no teeth. It now also caps the OUTPUT
# tokens. The caps stay generous enough that a thinking model isn't starved of
# prose (reasoning + reply share this budget); "medium" honors the user's own
# max_tokens so the advanced sampler still means something.
def reply_tokens(generation: dict | None) -> int:
    g = generation or {}
    length = str(g.get("response_length", "medium")).lower()
    if length == "short":
        return 1200
    if length == "long":
        return 4096
    try:
        return max(256, int(g.get("max_tokens", 2500) or 2500))
    except (TypeError, ValueError):
        return 2500


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a crash or a full disk can never
    leave a half-written config behind (MemoryStore.write does the same). A torn
    config.yaml or .env used to brick startup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save_yaml(data: dict, path: str | Path | None = None) -> None:
    """Persist the whole config dict back to config.yaml (comments are not kept)."""
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    _atomic_write(cfg_path, yaml.safe_dump(data, sort_keys=False,
                                           default_flow_style=False,
                                           allow_unicode=True))


def read_env() -> dict[str, str]:
    path = ROOT / ".env"
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]  # strip surrounding quotes a hand-editor may have added
            out[k.strip()] = v
    return out


def write_env(updates: dict[str, str]) -> None:
    env = read_env()
    env.update({k: v for k, v in updates.items() if k})
    lines = [f"{k}={v}" for k, v in env.items()]
    _atomic_write(ROOT / ".env", "\n".join(lines) + "\n")
