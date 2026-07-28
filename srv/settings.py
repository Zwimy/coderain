"""Settings, connection profiles, model lists, and the readiness and
semantic-recall checks."""
from __future__ import annotations

import copy
import httpx
from fastapi import APIRouter
from fastapi import HTTPException
from coderain import __version__
from coderain import features
from coderain import models as models_mod
from coderain.config import ROOT as DATA_ROOT
from coderain.config import read_env
from coderain.config import save_yaml
from coderain.config import write_env
from coderain.llm import LLM

from . import core
from .core import HOSTED_KEY_ENV
from .core import OLLAMA_TAGS
from .core import _clean_quick_actions
from .core import _reload_config

router = APIRouter()


@router.get("/api/retrieval/check")
def retrieval_check():
    """Does semantic recall ACTUALLY work? Settings only reported the checkbox, so
    a provider without an embeddings endpoint (DeepSeek answers 404) read as
    'enabled' while the retriever silently degraded to a no-op — losing recall
    with nothing to show for it. This spends one tiny embedding call to find out."""
    if not bool(core._cfg.retrieval.get("enabled")):
        return {"ok": False, "state": "off",
                "detail": "Semantic recall is switched off."}
    if not features.enabled("vector"):
        return {"ok": False, "state": "unavailable",
                "detail": "The vector recall module is not in this build."}
    vector_mod = features.module("vector")
    probe = getattr(vector_mod, "probe_embedder", None)
    if probe is None:
        return {"ok": True, "state": "unknown", "detail": ""}
    who = str(core._cfg.retrieval.get("profile", "") or "").strip() or "the chat model"
    try:
        err = probe(LLM(core._cfg.profile, core._cfg.generation).client,
                    core._cfg.retrieval, core._cfg)
    except Exception as e:  # noqa: BLE001 — a broken profile must not 500 here
        err = f"{type(e).__name__}: {str(e)[:160]}"
    if err:
        return {"ok": False, "state": "failing", "embedder": who, "error": err,
                "detail": f"Embeddings are not working on {who}, so semantic "
                          "recall is doing nothing. Point 'Embed with' at a "
                          "provider that serves embeddings (local Ollama with "
                          "nomic-embed-text is free)."}
    # It works — so re-arm any live retriever whose breaker had tripped. Without
    # this the check reported "live" while every loaded story kept returning
    # nothing, because the breaker latched and only a restart cleared it.
    revived = 0
    for eng in core._engines.values():
        r = getattr(eng, "retriever", None)
        if r is not None and getattr(r, "_failed", False):
            try:
                r.reset()
                revived += 1
            except Exception:  # noqa: BLE001 — a check must not 500
                pass
    return {"ok": True, "state": "working", "embedder": who,
            "detail": f"Semantic recall is live (embedding on {who})."
                      + (f" Re-enabled it on {revived} open "
                         f"{'story' if revived == 1 else 'stories'}."
                         if revived else "")}


@router.get("/api/ready")
def ready():
    """Is there a model this install can actually talk to?

    The app used to boot straight into the library with no check at all, so a
    new user with no Ollama and no API key clicked New story -> Begin and got a
    blank page with an unreadable error. Nothing told them a model was needed.
    This is the gate the first-run chooser hangs off.

    Cheap and honest: for local we ask Ollama what it has installed (a model
    must actually be pulled, not just the daemon running); for hosted we check a
    key and a model are configured. No tokens are spent.
    """
    mode = "hosted" if core._cfg.raw.get("active_profile") == "hosted" else "local"
    if mode == "hosted":
        prof = (core._cfg.raw.get("profiles") or {}).get("hosted") or {}
        has_key = bool(read_env().get(HOSTED_KEY_ENV, "").strip())
        model = str(prof.get("model", "")).strip()
        base = str(prof.get("base_url", "")).strip()
        if not has_key:
            return {"ok": False, "mode": mode, "reason": "no_key",
                    "detail": "No API key saved yet."}
        if not model or not base:
            return {"ok": False, "mode": mode, "reason": "no_model",
                    "detail": "No hosted model chosen yet."}
        return {"ok": True, "mode": mode, "model": model}

    try:
        r = httpx.get(OLLAMA_TAGS, timeout=3)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:                                   # noqa: BLE001
        return {"ok": False, "mode": mode, "reason": "no_ollama",
                "detail": "Ollama isn't running (or isn't installed)."}
    if not names:
        return {"ok": False, "mode": mode, "reason": "no_models",
                "detail": "Ollama is running but has no models pulled yet."}
    want = str((core._cfg.raw.get("profiles") or {}).get("local", {})
               .get("model", "")).strip()
    # Ollama reports "qwen3:4b"; a config may say "qwen3" — match on the stem.
    if want and not any(n == want or n.split(":")[0] == want.split(":")[0]
                        for n in names):
        return {"ok": False, "mode": mode, "reason": "model_missing",
                "detail": f"The selected model ({want}) isn't installed.",
                "installed": names}
    return {"ok": True, "mode": mode, "model": want or names[0],
            "installed": names}


@router.get("/api/models/local")
def local_models():
    """Installed Ollama models for the local dropdowns (live from the daemon;
    static suggestions as a fallback when it's not running)."""
    installed: list[dict] = []
    error = ""
    try:
        r = httpx.get(OLLAMA_TAGS, timeout=3)
        r.raise_for_status()
        for m in r.json().get("models", []):
            size_gb = round((m.get("size", 0) or 0) / 1e9, 1)
            installed.append({"name": m.get("name", ""),
                              "size": f"{size_gb} GB"})
    except Exception as e:  # noqa: BLE001
        error = f"Ollama not reachable ({e.__class__.__name__})"
    return {"installed": installed, "error": error,
            "howto": models_mod.LOCAL_HOWTO,
            "suggestions": [{"name": n, "kind": kind, "size": size,
                             "note": note}
                            for n, kind, size, note
                            in models_mod.LOCAL_SUGGESTIONS]}


@router.get("/api/models/hosted")
def hosted_models():
    return {"presets": models_mod.HOSTED_PRESETS,
            "hints": models_mod.context_hint_lines(),
            "platforms": models_mod.platform_comparison_lines(),
            "howto": models_mod.HOSTED_HOWTO,
            "recommended_min": models_mod.RECOMMENDED_MIN_CONTEXT}


@router.get("/api/settings")
def get_settings():
    raw = core._cfg.raw
    trinity = raw.get("trinity") or {}
    local = raw.get("profiles", {}).get("local", {})
    hosted = raw.get("profiles", {}).get("hosted", {})
    return {
        "mode": "hosted" if raw.get("active_profile") == "hosted" else "local",
        "local": {
            "director": (trinity.get("director") or {}).get("model")
            or local.get("model", ""),
            # No base-model fallback: the lore-keeper is OPT-IN, so an unset
            # stage must read back as "" (the dropdown's "(none)") — otherwise
            # the UI would imply a continuity pass that isn't actually running.
            "lorekeeper": (trinity.get("lorekeeper") or {}).get("model", ""),
            "writer": (trinity.get("writer") or {}).get("model")
            or local.get("model", ""),
            "context_tokens": local.get("context_tokens", 16384),
        },
        "hosted": {
            "model": hosted.get("model", ""),
            "base_url": hosted.get("base_url", ""),
            "context_tokens": hosted.get("context_tokens", 131072),
            "key_set": bool(read_env().get(HOSTED_KEY_ENV, "")),
        },
        # Which data folder this instance reads and writes. The desktop build and a
        # source run use DIFFERENT homes (%LOCALAPPDATA%\Coderain vs the repo), so a
        # key saved in one looks "not saved" in the other. Showing it makes that
        # visible instead of feeling like settings failed to persist.
        "home": str(DATA_ROOT),
        "version": __version__,
        "generation": {
            "response_length":
                core._cfg.generation.get("response_length", "medium"),
            "trinity_brain": bool(core._cfg.generation.get("trinity_brain", True)),
            "use_memory_tool": bool(core._cfg.generation.get("use_memory_tool", False)),
            "ai_acts_as_player":
                bool(core._cfg.generation.get("ai_acts_as_player", False)),
            "chapter_outline":
                bool(core._cfg.generation.get("chapter_outline", True)),
            "chapter_horizon": int(core._cfg.generation.get("chapter_horizon", 4)),
            "lore_check": bool(core._cfg.generation.get("lore_check", False)),
            "lore_check_every": int(core._cfg.generation.get("lore_check_every", 1)),
            "start_reply_with": core._cfg.generation.get("start_reply_with", ""),
            "stop": core._cfg.generation.get("stop", []),
            "temperature": core._cfg.generation.get("temperature", 0.9),
            "top_p": core._cfg.generation.get("top_p", 0.95),
            "max_tokens": core._cfg.generation.get("max_tokens", 2500),
            "frequency_penalty": core._cfg.generation.get("frequency_penalty"),
            "presence_penalty": core._cfg.generation.get("presence_penalty"),
            "repetition_penalty": core._cfg.generation.get("repetition_penalty"),
            "seed": core._cfg.generation.get("seed"),
        },
        "quick_actions": _clean_quick_actions(core._cfg.raw.get("quick_actions")),
        # Your model's price per MILLION tokens. Left at 0 the app reports tokens
        # only — deliberately not a bundled price list, because those go stale and
        # a wrong number is worse than no number.
        "price_in": float(core._cfg.raw.get("price_in", 0) or 0),
        "price_out": float(core._cfg.raw.get("price_out", 0) or 0),
        # Previously web-invisible: these existed in config.yaml and the legacy
        # Tk app but had no endpoint, so semantic recall was permanently OFF and
        # the memory depth/budget could not be tuned from the main UI at all.
        "memory": {
            "short_term_turns": core._cfg.memory.get("short_term_turns", 12),
            "medium_fold_after": core._cfg.memory.get("medium_fold_after", 12),
            "medium_fold_size": core._cfg.memory.get("medium_fold_size", 5),
            "long_fold_after": core._cfg.memory.get("long_fold_after", 8),
            "long_fold_size": core._cfg.memory.get("long_fold_size", 4),
            "context_budget_tokens":
                core._cfg.memory.get("context_budget_tokens", "auto"),
        },
        "retrieval": {
            "enabled": bool(core._cfg.retrieval.get("enabled", False)),
            "embed_model": core._cfg.retrieval.get("embed_model", "nomic-embed-text"),
            "top_k": core._cfg.retrieval.get("top_k", 4),
            "half_life_turns": core._cfg.retrieval.get("half_life_turns", 40),
            "min_similarity": core._cfg.retrieval.get("min_similarity", 0.25),
            "available": features.enabled("vector"),
            "profile": core._cfg.retrieval.get("profile", ""),
            "profiles": sorted((core._cfg.raw.get("profiles") or {}).keys()),
        },
    }


@router.put("/api/settings")
def put_settings(body: dict):
    # Build against a COPY: a later validation failure (e.g. hosted mode with no
    # model) used to abort with 400 after already mutating the live config, so
    # the running process reported a temperature/sampler that was never written
    # to disk and silently reverted on restart.
    raw = copy.deepcopy(core._cfg.raw)
    mode = body.get("mode") if body.get("mode") in ("local", "hosted") \
        else "local"
    if "quick_actions" in body:                 # ST-30 global quick actions
        raw["quick_actions"] = _clean_quick_actions(body.get("quick_actions"))
    gen = body.get("generation") or {}
    raw.setdefault("generation", {})
    if gen.get("response_length") in ("short", "medium", "long"):
        raw["generation"]["response_length"] = gen["response_length"]
    if "trinity_brain" in gen:
        raw["generation"]["trinity_brain"] = bool(gen["trinity_brain"])
    if "use_memory_tool" in gen:
        raw["generation"]["use_memory_tool"] = bool(gen["use_memory_tool"])
    if "ai_acts_as_player" in gen:
        raw["generation"]["ai_acts_as_player"] = bool(gen["ai_acts_as_player"])
    if "chapter_outline" in gen:
        raw["generation"]["chapter_outline"] = bool(gen["chapter_outline"])
    if "lore_check" in gen:
        raw["generation"]["lore_check"] = bool(gen["lore_check"])
    if "lore_check_every" in gen and gen["lore_check_every"] not in (None, ""):
        try:
            raw["generation"]["lore_check_every"] = max(
                1, min(10, int(gen["lore_check_every"])))
        except (TypeError, ValueError):
            pass
    if "chapter_horizon" in gen and gen["chapter_horizon"] not in (None, ""):
        try:
            raw["generation"]["chapter_horizon"] = max(2, min(8, int(gen["chapter_horizon"])))
        except (TypeError, ValueError):
            pass

    # Memory depth / budget — was config-file-only, so a web user could not trade
    # history depth against context budget.
    mem = body.get("memory") or {}
    if mem:
        raw.setdefault("memory", {})
        for key, lo, hi in (("short_term_turns", 2, 200),
                            ("medium_fold_after", 2, 200),
                            ("medium_fold_size", 1, 100),
                            ("long_fold_after", 1, 200),
                            ("long_fold_size", 1, 100)):
            if key in mem and mem[key] not in (None, ""):
                try:
                    raw["memory"][key] = max(lo, min(hi, int(mem[key])))
                except (TypeError, ValueError):
                    pass
        if "context_budget_tokens" in mem:
            v = mem["context_budget_tokens"]
            if isinstance(v, str) and v.strip().lower() == "auto":
                raw["memory"]["context_budget_tokens"] = "auto"
            else:
                try:
                    raw["memory"]["context_budget_tokens"] = max(1000, int(v))
                except (TypeError, ValueError):
                    pass

    # Model price per million tokens (0 = report tokens only, no cost).
    for key in ("price_in", "price_out"):
        if key in body:
            try:
                raw[key] = max(0.0, round(float(body[key] or 0), 4))
            except (TypeError, ValueError):
                pass

    # Semantic recall (vector retrieval) — a headline memory feature that was
    # permanently off for anyone who never hand-edited config.yaml.
    ret = body.get("retrieval") or {}
    if ret:
        raw.setdefault("retrieval", {})
        if "enabled" in ret:
            raw["retrieval"]["enabled"] = bool(ret["enabled"])
        if str(ret.get("embed_model", "")).strip():
            raw["retrieval"]["embed_model"] = str(ret["embed_model"]).strip()
        if "profile" in ret:
            # Which profile does the EMBEDDING (may differ from the chat model:
            # a hosted story model often has no embeddings endpoint at all).
            name = str(ret.get("profile", "") or "").strip()
            if name and name not in (raw.get("profiles") or {}):
                raise HTTPException(400, f"no such profile: {name}")
            raw["retrieval"]["profile"] = name
        for key, lo, hi, cast in (("top_k", 1, 20, int),
                                  ("half_life_turns", 1, 500, int),
                                  ("min_similarity", 0.0, 1.0, float)):
            if key in ret and ret[key] not in (None, ""):
                try:
                    raw["retrieval"][key] = max(lo, min(hi, cast(ret[key])))
                except (TypeError, ValueError):
                    pass
    # ST-22 persistent reply prefix (literal; every generated turn starts with it)
    if "start_reply_with" in gen:
        raw["generation"]["start_reply_with"] = str(gen["start_reply_with"] or "")[:300]
    # ST-24 custom stop sequences (accepts a list or newline-separated string)
    if "stop" in gen:
        stop = gen["stop"]
        if isinstance(stop, str):
            stop = stop.split("\n")
        raw["generation"]["stop"] = ([s.strip() for s in stop
                                      if isinstance(s, str) and s.strip()][:8]
                                     if isinstance(stop, list) else [])
    # ST-26 core samplers (always set; clamped to sane ranges)
    for key, lo, hi, cast in (("temperature", 0.0, 2.0, float),
                              ("top_p", 0.0, 1.0, float),
                              ("max_tokens", 1, 100000, int)):
        if key in gen and gen[key] not in (None, ""):
            try:
                raw["generation"][key] = max(lo, min(hi, cast(gen[key])))
            except (TypeError, ValueError):
                pass
    # ST-26 opt-in samplers: set within range, or clear (None/"") -> provider default
    for key, lo, hi, cast in (("frequency_penalty", -2.0, 2.0, float),
                              ("presence_penalty", -2.0, 2.0, float),
                              ("repetition_penalty", 0.0, 2.0, float),
                              ("seed", 0, 2**31 - 1, int)):
        if key in gen:
            if gen[key] in (None, ""):
                raw["generation"].pop(key, None)
            else:
                try:
                    raw["generation"][key] = max(lo, min(hi, cast(gen[key])))
                except (TypeError, ValueError):
                    pass

    if mode == "local":
        loc = body.get("local") or {}
        profile = raw.setdefault("profiles", {}).setdefault("local", {})
        profile.setdefault("base_url", "http://localhost:11434/v1")
        profile.setdefault("api_key_env", "OLLAMA_API_KEY")
        try:
            profile["context_tokens"] = max(
                models_mod.MIN_CONTEXT_TOKENS,
                int(loc.get("context_tokens",
                            profile.get("context_tokens", 16384))))
        except (TypeError, ValueError):
            pass
        director = str(loc.get("director", "")).strip()
        writer = str(loc.get("writer", "")).strip()
        keeper = str(loc.get("lorekeeper", "")).strip()
        if director:
            profile["model"] = director
        trinity = {}
        for stage, model in (("director", director), ("lorekeeper", keeper),
                             ("writer", writer)):
            if model:
                trinity[stage] = {"profile": "local", "model": model}
        # Choosing a lore-keeper model is what TURNS THE PASS ON — "(none)"
        # leaves the stage absent, so trinity.lore_llm_pass stays False.
        if keeper:
            trinity["lorekeeper"]["llm_pass"] = True
        if trinity:
            raw["trinity"] = trinity
        else:
            raw.pop("trinity", None)
        raw["active_profile"] = "local"
    else:
        ho = body.get("hosted") or {}
        model = str(ho.get("model", "")).strip()
        base_url = str(ho.get("base_url", "")).strip()
        if not model or not base_url:
            raise HTTPException(400, "hosted mode needs a model and base URL")
        try:
            ctx = max(models_mod.MIN_CONTEXT_TOKENS,
                      int(ho.get("context_tokens", 131072)))
        except (TypeError, ValueError):
            ctx = 131072
        raw.setdefault("profiles", {})["hosted"] = {
            "base_url": base_url, "model": model,
            "api_key_env": HOSTED_KEY_ENV, "context_tokens": ctx,
        }
        key = str(ho.get("api_key", "")).strip()
        if key:
            write_env({HOSTED_KEY_ENV: key})
        # One big dual-mode model serves every stage, so drop the LOCAL per-stage
        # model pins — but keep any other trinity settings. This used to pop the
        # whole block, which silently deleted a hand-configured lore-keeper every
        # time the user pressed Save in hosted mode.
        tri = raw.get("trinity")
        if isinstance(tri, dict):
            kept = {k: {kk: vv for kk, vv in v.items()
                        if kk not in ("profile", "model")}
                    for k, v in tri.items() if isinstance(v, dict)}
            kept = {k: v for k, v in kept.items() if v}
            if kept:
                raw["trinity"] = kept
            else:
                raw.pop("trinity", None)
        raw["active_profile"] = "hosted"

    save_yaml(raw)
    _reload_config()
    return get_settings()


# ---------- ST-25 connection profiles (named connection bundles) ----------
def _profiles_saved() -> dict:
    p = core._cfg.raw.get("connection_profiles")
    return p if isinstance(p, dict) else {}


@router.get("/api/profiles")
def list_profiles():
    saved = _profiles_saved()
    active = core._cfg.raw.get("active_profile_name", "")
    return {"profiles": sorted(saved.keys()),
            "active": active if active in saved else ""}   # never a dangling pointer


@router.post("/api/profiles")
def save_profile(body: dict):
    """Snapshot the CURRENT active connection under a name."""
    name = str(body.get("name", "")).strip()
    if not name or "/" in name or "\\" in name or len(name) > 60:
        raise HTTPException(400, "profile name must be 1-60 chars with no slashes")
    raw = core._cfg.raw
    kind = raw.get("active_profile", "local")
    src = (raw.get("profiles") or {}).get(kind, {})
    # Never snapshot an empty connection: a profile without base_url/model would
    # persist a config that crashes load_config on the next boot.
    if not (src.get("base_url") and src.get("model")):
        raise HTTPException(400, "the active connection has no model/URL to save yet")
    saved = raw.setdefault("connection_profiles", {})
    saved[name] = {"kind": kind, **{k: src[k] for k in
                   ("base_url", "model", "api_key_env", "context_tokens")
                   if k in src}}
    raw["active_profile_name"] = name
    save_yaml(raw)
    _reload_config()
    return list_profiles()


@router.post("/api/profiles/activate")
def activate_profile(body: dict):
    name = str(body.get("name", "")).strip()
    saved = _profiles_saved().get(name)
    if not isinstance(saved, dict):
        raise HTTPException(404, f"no such profile: {name}")
    raw = core._cfg.raw
    kind = saved.get("kind", "local")
    raw.setdefault("profiles", {})[kind] = {k: v for k, v in saved.items()
                                            if k != "kind"}
    raw["active_profile"] = kind
    raw["active_profile_name"] = name
    save_yaml(raw)
    _reload_config()
    return get_settings()


@router.delete("/api/profiles/{name}")
def delete_profile(name: str):
    raw = core._cfg.raw
    if isinstance(raw.get("connection_profiles"), dict):
        raw["connection_profiles"].pop(name, None)
        if raw.get("active_profile_name") == name:
            raw["active_profile_name"] = ""
        save_yaml(raw)
        _reload_config()
    return list_profiles()
