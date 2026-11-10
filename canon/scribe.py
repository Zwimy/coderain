"""The Scribe: reads finished prose and proposes claims. It never writes anything.

Separating the model that writes the story from the model that records it is the
point. A writer asked to emit a state block as well as prose did so reliably on
only some turns in this repo's own measurements, and one writing prose is not
reading it as a checklist. Extraction from finished text is the easier job.

Nothing here raises into a turn. A model that is down, slow, refuses, or returns
nonsense produces an Extraction whose `status` says so, so the failure is visible
and the story continues. (Invariant 2: a turn never dies from bad model output,
and never degrades invisibly.)

The Ollama client uses only urllib. It pins the context window on EVERY request:
the server's default can be very large (this machine's is 65536), and a tiny
extraction prompt would otherwise allocate a cache for it, which on a small GPU
means spilling to the CPU and a long stall.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from canon.claims import SLOT_HELP, Claim, Parsed, parse, schema

CHUNK_CHARS = 5000        # a passage longer than this is read in pieces
MAX_CTX = 16384           # refuse a larger window: nobody needs it for this job


class ScribeError(RuntimeError):
    """The model could not be reached or kept rejecting the request."""


SYSTEM = """\
You are a continuity scribe for an interactive story. Read the passage and list \
the physical facts it STATES about the characters, so a later passage can be \
checked against them.

Record only what the passage plainly says or shows. Do not guess, infer or tidy up.
Do NOT record: wishes, plans, hypotheticals, dreams, comparisons ("eyes like green \
glass", "cold as winter"), things said about someone's past that is not shown now, or \
anything about "you", the reader. A passage that only does these gets no claims.

Slots (use these and no others):
{slots}

Each claim has:
- entity: the character's name as written in the passage or the character list. \
Never a pronoun. If you cannot tell whose it is, skip it.
- slot and op. Ops: set (replace a single value), add (appears, is put on, picked \
up, hurt, a new mark), remove (taken off, put down, healed, gone), clear (nothing \
left in that slot).
- value: the trait itself, a short phrase taken from the passage, such as "raven", \
"green" or "grey wool coat". Name the colour or kind, not what the thing is doing.
- evidence: the exact words from the passage that state it, copied and not rewritten. \
The value must appear inside the evidence.
- confidence: high if stated outright, medium if slightly implied, low if unsure.

Answer with JSON only: {{"claims": [ ... ]}}. If the passage states nothing in these \
slots, answer {{"claims": []}}.

Example. Passage: "Jarrow shrugged off his rain-soaked cloak. His cropped grey hair \
glistened."
Answer: {{"claims":[{{"entity":"Jarrow","slot":"state.outfit","op":"remove",\
"value":"rain-soaked cloak","evidence":"shrugged off his rain-soaked cloak",\
"confidence":"high"}},{{"entity":"Jarrow","slot":"identity.hair","op":"set",\
"value":"cropped grey","evidence":"His cropped grey hair","confidence":"high"}}]}}

Example. Passage: "Her laugh was as cold as winter. In the dream, Jarrow's cloak \
was red."
Answer: {{"claims":[]}}
"""


def build_prompt(prose: str, roster: list[dict]) -> tuple[str, str]:
    """(system, user). Pure, so it can be tested and its size reasoned about."""
    slots = "\n".join(f"- {k}: {v}" for k, v in SLOT_HELP.items())
    if roster:
        names = "; ".join(
            r["name"] + (f" (also called {', '.join(r['aliases'])})"
                         if r.get("aliases") else "") for r in roster)
        known = f"Characters in this story: {names}."
    else:
        known = "No characters are known yet; name anyone the passage describes."
    return SYSTEM.format(slots=slots), f'{known}\n\nPassage:\n"""\n{prose}\n"""'


def chunks(prose: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split at paragraph breaks into pieces of at most `limit` characters. A
    single paragraph longer than the limit is split at sentence ends."""
    parts: list[str] = []
    cur = ""
    for para in re.split(r"\n\s*\n|\n", prose):
        if not para.strip():
            continue
        pieces = re.split(r"(?<=[.!?])\s+", para) if len(para) > limit else [para]
        for piece in (q for p in pieces for q in _split_long(p, limit)):
            if cur and len(cur) + len(piece) + 1 > limit:
                parts.append(cur)
                cur = ""
            cur = f"{cur}\n{piece}".strip()
    if cur:
        parts.append(cur)
    return parts or [prose]


def _split_long(piece: str, limit: int) -> list[str]:
    """Cut a piece that is still over the limit, at a space when one is close.
    Text with no sentence breaks (garbled output, a pasted table) would otherwise
    become one chunk larger than the context the request is pinned to."""
    out = []
    while len(piece) > limit:
        cut = piece.rfind(" ", 0, limit)
        cut = cut if cut > limit // 2 else limit
        out.append(piece[:cut].strip())
        piece = piece[cut:].strip()
    if piece:
        out.append(piece)
    return out


@dataclass
class Extraction:
    claims: list[Claim] = field(default_factory=list)
    rejects: list[dict] = field(default_factory=list)
    status: str = "ok"          # ok | empty_output | refusal | no_json | bad_shape | error
    raw: str = ""
    seconds: float = 0.0
    error: str = ""


class Scribe:
    """`llm` is anything with complete(system, user, schema) -> str."""

    def __init__(self, llm):
        self.llm = llm

    def extract(self, prose: str, roster: list[dict]) -> Extraction:
        started = time.time()
        out = Extraction()
        raws: list[str] = []
        for piece in chunks(prose):
            system, user = build_prompt(piece, roster)
            try:
                raw = self.llm.complete(system, user, schema())
            except ScribeError as exc:
                out.status, out.error = "error", str(exc)
                break
            except Exception as exc:  # noqa: BLE001 - a turn must never die here
                out.status, out.error = "error", f"{type(exc).__name__}: {exc}"
                break
            raws.append(raw)
            p: Parsed = parse(raw)
            out.claims += p.claims
            out.rejects += p.rejects
            # Report the worst status seen: one refused chunk must not hide
            # behind four that parsed.
            if p.status != "ok" and out.status == "ok":
                out.status = p.status
        out.raw = "\n---\n".join(raws)
        out.seconds = time.time() - started
        return out


class _Rejected(Exception):
    """HTTP 400: the server did not accept the request, usually a field it does
    not know. The body says which."""

    def __init__(self, body: str):
        self.body = body


class _Limited(Exception):
    """HTTP 429: a rate limit or an exhausted quota. The body says which."""

    def __init__(self, body: str, retry_after: str | None):
        self.body, self.retry_after = body, retry_after


def _http(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    """POST JSON, return JSON. The one place that talks to a server.

    Messages name the HOST and never the request headers, so a bearer token cannot
    end up in an exception, a log or a report.
    """
    host = urllib.parse.urlparse(url).netloc
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 400:
            raise _Rejected(body) from None
        if exc.code == 429:
            raise _Limited(body, (exc.headers or {}).get("retry-after")) from None
        if exc.code in (401, 403):
            raise ScribeError(f"HTTP {exc.code} from {host}: not authorised "
                              "(check the key and its permissions)") from None
        raise ScribeError(f"HTTP {exc.code} from {host}: {body[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ScribeError(f"cannot reach {host}: {exc}") from None
    except ValueError as exc:
        raise ScribeError(f"unreadable reply from {host}: {exc}") from None


class OllamaChat:
    """A minimal Ollama /api/chat client. No dependencies, no streaming."""

    def __init__(self, model: str, host: str = "http://localhost:11434", *,
                 num_ctx: int = 4096, num_predict: int = 1200, timeout: float = 240,
                 think: bool | None = None, keep_alive: str = "2m", seed: int = 7):
        if not 1024 <= num_ctx <= MAX_CTX:
            raise ValueError(f"num_ctx must be 1024..{MAX_CTX}, got {num_ctx}")
        self.model, self.host = model, host.rstrip("/")
        self.num_ctx, self.num_predict = num_ctx, num_predict
        self.timeout, self.think = timeout, think
        self.keep_alive, self.seed = keep_alive, seed
        self.dropped: set[str] = set()      # optional fields this server refused

    def _payload(self, system: str, user: str, schema_: dict | None) -> dict:
        p = {"model": self.model, "stream": False,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}],
             # temperature 0 and a fixed seed: the same passage gives the same
             # claims, which is what makes a measurement repeatable.
             "options": {"temperature": 0, "seed": self.seed,
                         "num_ctx": self.num_ctx, "num_predict": self.num_predict},
             "keep_alive": self.keep_alive}
        if schema_ is not None and "format" not in self.dropped:
            p["format"] = schema_
        if self.think is not None and "think" not in self.dropped:
            p["think"] = self.think
        return p

    def _post(self, path: str, payload: dict) -> dict:
        try:
            return _http(self.host + path, payload, {}, self.timeout)
        except _Limited as exc:
            raise ScribeError(f"rate limited by {self.host}: {exc.body[:200]}") from None

    def complete(self, system: str, user: str, schema_: dict | None = None) -> str:
        for _ in range(3):
            payload = self._payload(system, user, schema_)
            try:
                data = self._post("/api/chat", payload)
            except _Rejected as exc:
                # An older server may not know `format` or `think`. Drop the
                # optional field it names and try again, and remember, so the
                # next call does not pay for the same failure.
                bad = [k for k in ("format", "think")
                       if k in payload and k in exc.body.lower()]
                if not bad:
                    raise ScribeError(f"request refused: {exc.body[:200]}") from None
                self.dropped.update(bad)
                continue
            return (data.get("message") or {}).get("content", "") or ""
        raise ScribeError("the server kept rejecting optional request fields")

    def unload(self) -> None:
        """Ask the server to free the model now instead of after keep_alive."""
        try:
            self._post("/api/generate", {"model": self.model, "keep_alive": 0,
                                         "stream": False})
        except (ScribeError, _Rejected):
            pass


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class NotLocal(RuntimeError):
    """The model is not on this machine, so a real story must not be sent to it."""


def require_local(llm) -> None:
    """Refuse a model that is not demonstrably local. A fake used in tests can say
    `stays_local = True`; a hosted client cannot, because it has no such flag.

    Used wherever a person's real story is read by a model without their asking for
    each call: the replay gate and the engine's shadow mode."""
    if getattr(llm, "stays_local", False) is True:
        return
    if isinstance(llm, OllamaChat):
        host = urllib.parse.urlparse(llm.host).hostname or ""
        if host in _LOCAL_HOSTS:
            return
        raise NotLocal(f"the Ollama host is {host!r}, which is not this machine")
    raise NotLocal(f"{type(llm).__name__} is not a local model; a real story is "
                   "only ever sent to a server on this machine")


def strict_schema() -> dict:
    """The claim schema in the form OpenAI's structured outputs accept.

    Strict mode wants additionalProperties false on every object and does not take
    maxItems, so those are adjusted on a copy; the cap is enforced by the parser
    (MAX_CLAIMS) either way.
    """
    s = copy.deepcopy(schema())
    s["additionalProperties"] = False
    arr = s["properties"]["claims"]
    arr.pop("maxItems", None)
    arr["items"]["additionalProperties"] = False
    return {"name": "claims", "strict": True, "schema": s}


class OpenAIChat:
    """A minimal client for any OpenAI-compatible /chat/completions endpoint.

    OpenAI, OpenRouter and others speak this. No dependencies, no streaming.

    Money and secrets, because this one can cost something and carries a key:

      * The key is read from an environment variable named by `key_env`, at call
        time. It is never stored on the object, never printed, and never part of
        an error message (see _http). The person running an evaluation sets the
        variable in their own terminal, so the key does not pass through anyone
        or anything that is only reading the results.
      * `token_budget` is a hard stop. Once input plus output tokens reach it the
        next call raises instead of spending more. A run that was supposed to be
        free cannot quietly become a paid one.
      * A 429 that says the quota is exhausted, or the DAILY request cap is hit, is
        not retried, and neither is anything after it: retrying a bill is not a
        rate limit, and a free tier's daily cap does not lift until tomorrow.
        `exhausted` holds the reason so a runner can stop instead of recording a
        wall of errors as if they were the model's answers.

    Free tiers (OpenRouter's `:free` models allow 20 requests a minute) are met
    with `min_interval`, which spaces requests so the per-minute cap is not hit
    and slept through.

    A reasoning model can spend the whole `max_tokens` thinking and return an
    empty reply with finish_reason "length". That is counted in `truncated`, so
    an empty answer is not read as a model that had nothing to say.
    """

    def __init__(self, model: str, *, base_url: str = "https://api.openai.com/v1",
                 key_env: str = "OPENAI_API_KEY", max_tokens: int = 2000,
                 timeout: float = 120, reasoning_effort: str | None = None,
                 token_budget: int = 250_000, seed: int = 7,
                 min_interval: float = 0.0, attempts: int = 5):
        self.model, self.base_url = model, base_url.rstrip("/")
        self.key_env, self.max_tokens, self.timeout = key_env, max_tokens, timeout
        self.reasoning_effort, self.token_budget, self.seed = (
            reasoning_effort, token_budget, seed)
        self.min_interval = max(0.0, float(min_interval))
        self.attempts = max(1, int(attempts))   # a free pool can stay busy for a minute
        self.tokens_in = self.tokens_out = 0
        self.truncated = 0                  # replies cut off by max_tokens
        self.exhausted = ""                 # why no further request will be sent
        self._last_sent = 0.0
        self.dropped: set[str] = set()      # optional fields this server refused

    def __repr__(self) -> str:                 # never show anything sensitive
        return f"OpenAIChat(model={self.model!r}, base_url={self.base_url!r})"

    @property
    def tokens_used(self) -> int:
        return self.tokens_in + self.tokens_out

    def _key(self) -> str:
        key = os.environ.get(self.key_env, "").strip()
        if not key:
            raise ScribeError(f"the environment variable {self.key_env} is not set")
        return key

    def _payload(self, system: str, user: str, schema_: dict | None) -> dict:
        p = {"model": self.model,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}],
             "max_completion_tokens": self.max_tokens,
             "temperature": 0, "seed": self.seed}
        if schema_ is not None:
            p["response_format"] = {"type": "json_schema",
                                    "json_schema": strict_schema()}
        if self.reasoning_effort:
            p["reasoning_effort"] = self.reasoning_effort
        for name in self.dropped:
            p.pop(name, None)
        return p

    def _pace(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_sent)
        if wait > 0:
            time.sleep(wait)
        self._last_sent = time.monotonic()

    @staticmethod
    def _error_in_body(data: dict) -> tuple[str, bool] | None:
        """OpenRouter can deliver an upstream failure as HTTP 200 with an `error`
        object and no choices. Without this it would read as an empty answer.
        Returns (message, is_rate_limit), or None when the reply is a real one."""
        err = data.get("error")
        if not err or data.get("choices"):
            return None
        if isinstance(err, dict):
            return str(err.get("message") or err)[:200], err.get("code") == 429
        return str(err)[:200], False

    def complete(self, system: str, user: str, schema_: dict | None = None) -> str:
        if self.exhausted:
            raise ScribeError(self.exhausted)
        if self.tokens_used >= self.token_budget:
            raise ScribeError(f"token budget of {self.token_budget} reached "
                              f"({self.tokens_used} used); stopping")
        headers = {"Authorization": f"Bearer {self._key()}"}
        url = self.base_url + "/chat/completions"
        host = urllib.parse.urlparse(url).netloc
        last = ""                           # why the most recent attempt failed
        for attempt in range(self.attempts):
            payload = self._payload(system, user, schema_)
            self._pace()
            try:
                data = _http(url, payload, headers, self.timeout)
                bad_body = self._error_in_body(data)
                if bad_body:
                    message, limited = bad_body
                    if limited:
                        raise _Limited(message, None)
                    raise ScribeError(f"{host} returned an error: {message}")
            except ScribeError as exc:
                # A wrong key, or no endpoint allowed by the account's data policy
                # (OpenRouter's free models need a privacy setting turned on), will
                # fail every request the same way. Say so once and stop.
                text = str(exc)
                if "not authorised" in text or "no endpoints found" in text.lower():
                    self.exhausted = text
                raise
            except _Rejected as exc:
                # Models differ on temperature, seed, reasoning_effort and
                # structured outputs. Drop the one the server names and retry.
                low = exc.body.lower()
                # Some servers say "reasoning" ("reasoning is mandatory for this
                # model") without ever writing the parameter's name.
                bad = [k for k, needle in (("temperature", "temperature"),
                                           ("seed", "seed"),
                                           ("reasoning_effort", "reasoning"),
                                           ("response_format", "response_format"))
                       if k in payload and needle in low]
                if not bad:
                    raise ScribeError(f"request refused: {exc.body[:200]}") from None
                self.dropped.update(bad)
                last = f"dropped {bad} after: {exc.body[:100]}"
                continue
            except _Limited as exc:
                low = exc.body.lower()
                last = f"rate limited: {exc.body[:140]}"
                if "insufficient_quota" in low or "billing" in low or "quota" in low:
                    self.exhausted = ("quota exhausted or no balance; not retrying: "
                                      + exc.body[:160])
                    raise ScribeError(self.exhausted) from None
                if "per-day" in low or "per day" in low or "daily" in low:
                    self.exhausted = ("daily request limit reached; no further "
                                      "requests will be sent: " + exc.body[:160])
                    raise ScribeError(self.exhausted) from None
                try:
                    wait = min(float(exc.retry_after or 0) or 2 ** attempt, 20.0)
                except ValueError:
                    wait = 2 ** attempt
                time.sleep(wait)
                continue
            usage = data.get("usage") or {}
            self.tokens_in += int(usage.get("prompt_tokens") or 0)
            self.tokens_out += int(usage.get("completion_tokens") or 0)
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            if choice.get("finish_reason") == "length":
                self.truncated += 1
            return content
        raise ScribeError(f"the server kept rejecting or rate limiting the request "
                          f"({self.attempts} attempts); last: {last}")

    def unload(self) -> None:
        """Nothing to free on a hosted server; present so callers need not care."""
