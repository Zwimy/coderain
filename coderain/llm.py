"""Provider-agnostic LLM client.

Everything (local Ollama, OpenRouter, Together, ...) speaks the OpenAI-compatible
chat API, so this one client covers all of them. Only base_url / model / api_key
differ, and those come from the active profile in config.yaml.
"""
from __future__ import annotations

import contextlib
import json
import re
from typing import Iterator

from openai import OpenAI

from .config import Profile
# The pure stream-processing core lives in `streaming` (no network deps) so it can
# also run in-browser under Pyodide. Re-exported here for backwards compatibility.
from . import streaming
from .streaming import THINK_CLOSE, THINK_OPEN, ThinkFilter, filter_think  # noqa: F401


class LLM:
    def __init__(self, profile: Profile, generation: dict):
        self.profile = profile
        self.gen = generation
        self.client = OpenAI(
            base_url=profile.base_url,
            api_key=profile.api_key,
            default_headers=profile.extra_headers or None,
            # The SDK's defaults are read=600s with max_retries=2, so a stalled
            # request could occupy the turn lock for ~30 MINUTES before failing.
            # That is indistinguishable from a hang, and it lands where it hurts
            # most: the fold runs AFTER the prose has streamed, so the reader is
            # left staring at finished text with a dead UI.
            #
            # Generous, not tight: a fold legitimately generates ~4,300 tokens
            # (measured on a real save), which is minutes on a slow local model.
            # The point is a ceiling that exists, not a short one.
            timeout=request_timeout(generation),
            max_retries=1,
        )
        # --- token accounting -------------------------------------------
        # The provider already tells us exactly what each call cost; we used to
        # drop those frames on the floor and estimate from character counts
        # instead. `on_usage` is set by the Engine to persist a record; `stage`
        # says which part of the pipeline is spending (writer, director, fold,
        # plan, lore, tool), so the cost of the optional brains is visible
        # rather than inferred.
        self.last_usage: dict | None = None
        self.on_usage = None
        self.stage = "writer"
        self._ask_usage = True     # cleared if the provider rejects the option

    @contextlib.contextmanager
    def as_stage(self, stage: str):
        """Label every call made inside the block. Restores the previous label,
        so nesting (a fold triggered inside a turn) reports honestly."""
        prev = self.stage
        self.stage = stage
        try:
            yield
        finally:
            self.stage = prev

    def _record(self, usage) -> None:
        if usage is None:
            return
        rec = {
            "stage": self.stage,
            "model": self.profile.model,
            "in": int(getattr(usage, "prompt_tokens", 0) or 0),
            "out": int(getattr(usage, "completion_tokens", 0) or 0),
        }
        # A cached-prompt discount is worth seeing: it is most of the bill on a
        # long story, where the system block barely changes between turns.
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details else None
        if cached:
            rec["cached"] = int(cached)
        self.last_usage = rec
        if self.on_usage:
            try:
                self.on_usage(rec)
            except Exception:  # noqa: BLE001 — accounting must never kill a turn
                pass

    def _create(self, want_usage: bool, **kw):
        if want_usage:
            kw["stream_options"] = {"include_usage": True}
        return self.client.chat.completions.create(**kw)

    def _create_stream(self, **kw):
        """Ask for usage, and stop asking if this provider won't have it.

        `stream_options` is an OpenAI extension; some OpenAI-compatible servers
        reject the unknown field with a 400. That must not break generation, so
        one 400 downgrades this client for the rest of its life and the turn
        proceeds without accounting.
        """
        if not self._ask_usage:
            return self._create(False, **kw)
        try:
            return self._create(True, **kw)
        except Exception as e:  # noqa: BLE001 — inspected, then re-raised
            status = getattr(e, "status_code", None)
            text = str(e).lower()
            rejected = (status in (400, 422) or "stream_options" in text
                        or "unknown" in text or "unsupported" in text)
            if not rejected:
                raise                      # a real failure: auth, network, model
            self._ask_usage = False
            return self._create(False, **kw)

    def _params(self, **overrides) -> dict:
        g = self.gen
        p = {
            "temperature": g.get("temperature", 0.9),
            "top_p": g.get("top_p", 0.95),
            "max_tokens": g.get("max_tokens", 700),
        }
        # ST-24 custom stop sequences (accepts a list or a single string).
        stop = g.get("stop")
        if stop:
            p["stop"] = stop if isinstance(stop, list) else [stop]
        # ST-26 sampler surface — the OpenAI-standard subset, only sent when the
        # user opted in (unset = provider default, no behavior change).
        for k in ("frequency_penalty", "presence_penalty", "seed"):
            if g.get(k) is not None:
                p[k] = g[k]
        p.update(overrides)
        # repetition_penalty is non-standard (llama.cpp/Ollama) → extra_body so it
        # reaches those backends without breaking strict OpenAI schemas. Merged AFTER
        # overrides (and via setdefault) so a caller's own extra_body isn't clobbered
        # and can still win on the same key.
        if g.get("repetition_penalty") is not None:
            eb = dict(p.get("extra_body") or {})
            eb.setdefault("repetition_penalty", g["repetition_penalty"])
            p["extra_body"] = eb
        return p

    def _raw_stream(self, messages: list[dict], params: dict) -> Iterator[str]:
        resp = self._create_stream(
            model=self.profile.model,
            messages=messages,
            stream=True,
            **params,
        )
        for chunk in resp:
            # The usage frame arrives last and carries no choices — this is the
            # exact frame the old code skipped, and it holds the real numbers.
            self._record(getattr(chunk, "usage", None))
            if not getattr(chunk, "choices", None):
                continue   # usage/keep-alive frames arrive with empty choices
            delta = chunk.choices[0].delta
            yield getattr(delta, "content", None) or ""

    def stream(self, messages: list[dict], **overrides) -> Iterator[str]:
        """Yield visible text chunks, suppressing <think>...</think> reasoning."""
        params = self._params(**overrides)
        yield from filter_think(self._raw_stream(messages, params))

    def complete(self, messages: list[dict], **overrides) -> str:
        return "".join(self.stream(messages, **overrides))

    def complete_with_tools(self, messages: list[dict], tools: list[dict],
                            dispatch, max_rounds: int = 3, **overrides) -> str:
        """Run a tool-calling loop: let the model call tools (via `dispatch`) until
        it produces a final answer. Used for the optional memory-lookup tool on
        capable/hosted models. Not streamed."""
        params = self._params(**overrides)
        convo = list(messages)
        for _ in range(max_rounds):
            resp = self.client.chat.completions.create(
                model=self.profile.model, messages=convo,
                tools=tools, tool_choice="auto", **params,
            )
            self._record(getattr(resp, "usage", None))
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None)
            if not calls:
                return _strip_think_text(msg.content or "")
            convo.append({
                "role": "assistant", "content": msg.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name,
                                  "arguments": c.function.arguments}}
                    for c in calls
                ],
            })
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except ValueError:      # see extract_json: a huge int literal
                    args = {}           # raises a bare ValueError, not a decode error
                result = dispatch(c.function.name, args)
                convo.append({"role": "tool", "tool_call_id": c.id,
                              "content": str(result)})
        # ran out of rounds: force a final answer without tools
        resp = self.client.chat.completions.create(
            model=self.profile.model, messages=convo, **params,
        )
        self._record(getattr(resp, "usage", None))
        return _strip_think_text(resp.choices[0].message.content or "")


def stage(llm, name: str):
    """Label an LLM's calls, tolerating a client that isn't a full LLM.

    Trinity, the summarizer and the planner all accept an injected client (a
    pinned per-stage model, or a stub in the tests). Accounting is a nicety, so
    a client without `as_stage` just doesn't get labelled — it must never turn
    into an AttributeError mid-turn.
    """
    fn = getattr(llm, "as_stage", None)
    return fn(name) if callable(fn) else contextlib.nullcontext()


def _strip_think_text(text: str) -> str:
    return "".join(filter_think(iter([text])))


def extract_json(text: str) -> dict | None:
    """Pull a JSON dict out of arbitrary model text. Returns None if there isn't
    one.

    Now genuinely brace-balanced (streaming.json_objects), which is what this
    docstring always claimed. It used to be `re.compile(r"\\{.*\\}", re.DOTALL)`
    — greedy, first brace to LAST brace — so a model that wrote valid JSON and
    then added a closing sentence containing a brace produced no object at all.

    It takes the first candidate that PARSES rather than the first that exists,
    because a reasoning model often narrates a brace before committing to the
    real object ("I'll return {scene_summary: ...} shaped output:"). Stopping at
    the first balanced span would hand back that sketch instead of the answer.
    """
    for raw in streaming.json_objects(text):
        try:
            obj = json.loads(raw)
        except ValueError:
            # ValueError, not JSONDecodeError: json.loads also raises a BARE
            # ValueError for an integer literal past Python's 4300-digit
            # conversion limit ({"day": 9999...}, the degenerate
            # digit-repetition failure mode). That escaped this function and
            # killed the turn with an uncaught exception and an EMPTY health
            # log — invariant 2 both ways at once. JSONDecodeError is a
            # ValueError subclass, so this still covers it.
            continue
        if isinstance(obj, dict):
            return obj
    return None


# JSON stages on reasoning models (qwen3 etc.) need headroom: the server-side
# thinking spends 1-2k tokens BEFORE the JSON — and scales with payload size (a
# live threads-stage run truncated even at 4096) — so a too-small budget cuts the
# object mid-brace (finish=length), which then looks like "the model failed".
JSON_MIN_TOKENS = 8192

# Wall clock for ONE model request, seconds. Overridable per install via
# generation.request_timeout_s for a very slow local model on a big fold.
REQUEST_TIMEOUT_S = 300


def request_timeout(generation: dict | None) -> float:
    """Per-request ceiling. Floored at 30s so a typo cannot make every call fail
    instantly, which would look exactly like the model being unreachable."""
    try:
        return max(30.0, float((generation or {}).get("request_timeout_s",
                                                      REQUEST_TIMEOUT_S)))
    except (TypeError, ValueError):
        return float(REQUEST_TIMEOUT_S)

# 8192 is not always enough either, and chasing the number upward is a losing
# game — reasoning length scales with the payload, and a fold's payload grows
# with the story. The retry has to be able to RECOVER instead.
#
# Measured on qwen3:4b: scene fold 1 failed "JSON truncated (unclosed brace)",
# scene fold 2 failed "model returned empty output" — both at the 8192 floor, and
# both permanent, because a fold is one-way and its pointer advances regardless.
# Isolated, the same call at a 1176-token prompt succeeded while spending ~2861
# tokens on reasoning before 300 characters of JSON; a real fold prompt is
# several times larger.
#
# The old retry could not have helped: it re-sent at the SAME budget with a nudge
# ("That was not valid JSON"), so a truncation failure truncated identically the
# second time. Escalating the ceiling is what makes the retry mean something.
JSON_RETRY_CEILING = 24576

# The prose edition of the same disease lives in config.prose_tokens /
# REASONING_HEADROOM. It used to be a PROSE_MIN_TOKENS constant here, which was
# imported by trinity.py and then never used — the call site hardcoded a 1024
# floor that could not engage — so the bug it was written for stayed live.


def emit_json_ex(llm, system: str, payload: str = "", retry: int = 1,
                 messages: list[dict] | None = None,
                 **overrides) -> tuple[dict | None, str | None]:
    """Structured-emit with error reporting: returns (obj, None) on success or
    (None, reason) on failure — callers decide whether to degrade or surface it.

    The reusable seam shared by the summarizer, the scenario generator, and the
    Trinity Brain. Takes any object exposing `.complete(messages)` (the real LLM or
    a test stub). Pass `messages=` to keep a full conversation (e.g. the Director
    needs the story history); else system+payload builds a 2-message convo. Bumps
    max_tokens to JSON_MIN_TOKENS so reasoning can't starve the JSON output."""
    convo = list(messages) if messages is not None else [
        {"role": "system", "content": system},
        {"role": "user", "content": payload},
    ]
    # Only the real client gets the token bump — test stubs often define a bare
    # complete(messages) and must keep working without kwargs.
    if hasattr(llm, "gen"):
        overrides.setdefault(
            "max_tokens", max(JSON_MIN_TOKENS,
                              int(llm.gen.get("max_tokens", 0) or 0)))
    err = "no attempts made"
    for _ in range(retry + 1):
        try:
            text = llm.complete(convo, **overrides)
        except Exception as e:  # noqa: BLE001 — network/model failure -> no JSON
            return None, f"model call failed: {e}"
        obj = extract_json(text)
        if obj is not None:
            return obj, None
        tail = text.strip()[-80:].replace("\n", " ")
        # Two of these three mean "the model ran out of room", not "the model got
        # it wrong", and they are the two that actually happen on a reasoning
        # model. They need a bigger budget, not a scolding.
        starved = False
        if "{" in text and text.count("{") > text.count("}"):
            err = (f"JSON truncated (unclosed brace — likely max_tokens too small "
                   f"for a reasoning model); tail: …{tail}")
            starved = True
        elif not tail:
            err = "model returned empty output"
            starved = True
        else:
            err = f"no valid JSON in output; tail: …{tail}"
        if starved and overrides.get("max_tokens"):
            # Raise the ceiling for the next attempt. This is a cap, not a target:
            # a model that finishes early still finishes early, so the only cost
            # of headroom is the room to not fail.
            grown = min(JSON_RETRY_CEILING, int(overrides["max_tokens"]) * 2)
            if grown > overrides["max_tokens"]:
                overrides["max_tokens"] = grown
                err += f" [retrying at max_tokens={grown}]"
        convo.append({"role": "user", "content": (
            "Your previous reply ran out of room before the JSON was finished. "
            "Answer again with a SHORT JSON object and nothing else — keep every "
            "string brief." if starved else
            "That was not valid JSON. Return ONLY the JSON object, nothing else.")})
    return None, err


def emit_json(llm, system: str, payload: str, retry: int = 1,
              **overrides) -> dict | None:
    """Back-compat wrapper: emit_json_ex minus the error reason."""
    obj, _ = emit_json_ex(llm, system, payload, retry, **overrides)
    return obj
