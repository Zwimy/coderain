"""Provider-agnostic LLM client.

Everything (local Ollama, OpenRouter, Together, ...) speaks the OpenAI-compatible
chat API, so this one client covers all of them. Only base_url / model / api_key
differ, and those come from the active profile in config.yaml.
"""
from __future__ import annotations

import json
import re
from typing import Iterator

from openai import OpenAI

from .config import Profile
# The pure stream-processing core lives in `streaming` (no network deps) so it can
# also run in-browser under Pyodide. Re-exported here for backwards compatibility.
from .streaming import THINK_CLOSE, THINK_OPEN, ThinkFilter, filter_think  # noqa: F401


class LLM:
    def __init__(self, profile: Profile, generation: dict):
        self.profile = profile
        self.gen = generation
        self.client = OpenAI(
            base_url=profile.base_url,
            api_key=profile.api_key,
            default_headers=profile.extra_headers or None,
        )

    def _params(self, **overrides) -> dict:
        p = {
            "temperature": self.gen.get("temperature", 0.9),
            "top_p": self.gen.get("top_p", 0.95),
            "max_tokens": self.gen.get("max_tokens", 700),
        }
        p.update(overrides)
        return p

    def _raw_stream(self, messages: list[dict], params: dict) -> Iterator[str]:
        resp = self.client.chat.completions.create(
            model=self.profile.model,
            messages=messages,
            stream=True,
            **params,
        )
        for chunk in resp:
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
                            dispatch, max_rounds: int = 4) -> str:
        """Run a tool-calling loop: let the model call tools (via `dispatch`) until
        it produces a final answer. Used for the optional memory-lookup tool on
        capable/hosted models. Not streamed."""
        params = self._params()
        convo = list(messages)
        for _ in range(max_rounds):
            resp = self.client.chat.completions.create(
                model=self.profile.model, messages=convo,
                tools=tools, tool_choice="auto", **params,
            )
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
                except json.JSONDecodeError:
                    args = {}
                result = dispatch(c.function.name, args)
                convo.append({"role": "tool", "tool_call_id": c.id,
                              "content": str(result)})
        # ran out of rounds: force a final answer without tools
        resp = self.client.chat.completions.create(
            model=self.profile.model, messages=convo, **params,
        )
        return _strip_think_text(resp.choices[0].message.content or "")


def _strip_think_text(text: str) -> str:
    return "".join(filter_think(iter([text])))


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict | None:
    """Pull the first brace-balanced {...} object out of arbitrary model text and
    validate it as a JSON dict. Returns None on no-match or invalid JSON."""
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


# JSON stages on reasoning models (qwen3 etc.) need headroom: the server-side
# thinking spends 1-2k tokens BEFORE the JSON — and scales with payload size (a
# live threads-stage run truncated even at 4096) — so a too-small budget cuts the
# object mid-brace (finish=length), which then looks like "the model failed".
JSON_MIN_TOKENS = 8192

# Same disease, prose edition: the quad Writer's richer prompt (plan + resolved
# mechanics) makes a reasoning model think longer, and at the user's normal
# max_tokens the thinking can consume the WHOLE budget -> zero visible prose
# (caught live: 28s of generation, empty output). Floor the writer stage.
PROSE_MIN_TOKENS = 4096


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
        if "{" in text and text.count("{") > text.count("}"):
            err = (f"JSON truncated (unclosed brace — likely max_tokens too small "
                   f"for a reasoning model); tail: …{tail}")
        elif not tail:
            err = "model returned empty output"
        else:
            err = f"no valid JSON in output; tail: …{tail}"
        convo.append({"role": "user",
                      "content": "That was not valid JSON. Return ONLY the "
                                 "JSON object, nothing else."})
    return None, err


def emit_json(llm, system: str, payload: str, retry: int = 1,
              **overrides) -> dict | None:
    """Back-compat wrapper: emit_json_ex minus the error reason."""
    obj, _ = emit_json_ex(llm, system, payload, retry, **overrides)
    return obj
