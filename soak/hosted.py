"""A hosted Writer for the play soak, on free OpenRouter models only (D-068).

The play soak used to talk to a local Ollama only. What a story does on a larger Writer is an open question (D-055 asks whether a larger
model is immune to what a 4B one does), so `python -m soak play --provider openrouter` lets it use a hosted `:free` model, under
limits the code enforces rather than promises:

- the model must end in `:free`, so a key given for a free test cannot spend (`--allow-paid` is the explicit way round it);
- the key is read from the environment by NAME. It is never an argument and never written to the run's config, which holds only the
  variable's name, and no message in this module can contain it;
- requests are spaced (a `:free` model allows about 20 a minute), a refused or busy request is retried after a wait, and every attempt
  counts against a request budget, because a free model also has a daily cap;
- the budget is checked before each turn, so a run stops cleanly between turns with what it has instead of dying inside one;
- a request that fails for good (the retries are spent, or the error is not worth retrying, such as a daily cap) stops the run at once, and
  that turn is not recorded: a shared free pool can stay saturated for many minutes, and error text written into the story as if it were
  narration would corrupt every row after it.

The pacing and the retry sit on the OpenAI SDK's own `chat.completions.create`, the one place every chat request of the engine goes
through (the Writer, the folds, the canon reader and the direct calls), so nothing in the engine changes.
"""
from __future__ import annotations

import os
import time

OPENROUTER_URL = "https://openrouter.ai/api/v1"
KEY_ENV = "OPENROUTER_API_KEY"
# The same spacing the corpus harness uses: 18.75 a minute, under the 20 a minute cap of a ':free' model, with a little room.
FREE_INTERVAL = 3.2
# A turn is the Writer's call, sometimes a fold (several calls) and the canon reader's pass. Below this many requests left the run stops
# before starting another turn.
MIN_TURN_REQUESTS = 12
# Seconds to wait after a refused or busy request, one entry per retry (so eight attempts). A free model's pool is shared and is often
# busy for a minute at a time.
RETRY_WAITS = (5, 10, 20, 40, 60, 60, 60)
_CONNECTION_ERRORS = ("APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout", "ConnectTimeout")


def check_model(model: str | None, allow_paid: bool = False) -> None:
    """Refuse a model that may cost money. OpenRouter marks the free variants with the `:free` suffix."""
    if not model:
        raise SystemExit("refused: --provider openrouter needs --model")
    if not str(model).endswith(":free") and not allow_paid:
        raise SystemExit(f"refused: {model!r} is not a ':free' model; pass --allow-paid to use one that may cost money")


def require_key(env: str = KEY_ENV) -> None:
    """The key must be in the environment. Only the variable's NAME is ever named in a message."""
    if not os.environ.get(env, "").strip():
        raise SystemExit(f"refused: the key is read from the environment variable {env}, and it is not set")


class Pacer:
    """Spaces requests, counts every attempt, and says how many are left. The clock and the sleep are parameters so a test can fake time."""

    def __init__(self, interval: float = FREE_INTERVAL, max_requests: int = 900, clock=time.monotonic, sleep=time.sleep):
        self.interval = interval
        self.max_requests = max_requests
        self.clock = clock
        self.sleep = sleep
        self.count = 0
        self._last: float | None = None
        self.failed = False                 # a request failed for good: the run stops, and that turn is not recorded
        self.last_error: str | None = None

    def left(self) -> int:
        return self.max_requests - self.count

    def before_request(self) -> None:
        if self._last is not None:
            wait = self.interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()
        self.count += 1


def retryable(exc: BaseException) -> bool:
    """A busy pool (429), a provider fault (5xx) or a dropped connection is worth another try; a bad request, a bad key or a missing
    model (400 to 404) is not, and trying again would only spend the budget."""
    # A daily cap does not lift in a few minutes: waiting and trying again would only spend the rest of the budget.
    text = str(getattr(exc, "body", None) or exc).lower()
    if "per-day" in text or "per day" in text:
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return type(exc).__name__ in _CONNECTION_ERRORS


def describe(exc: BaseException) -> str:
    """What stopped the run, in a few words: the status or the exception's name, never the provider's body."""
    status = getattr(exc, "status_code", None)
    return f"status {status}" if isinstance(status, int) else type(exc).__name__


def install(pacer: Pacer, waits: tuple = RETRY_WAITS, sleep=time.sleep):
    """Pace and retry every chat request of this process. Returns a function that puts the SDK back."""
    from openai.resources.chat.completions import Completions
    original = Completions.create

    def paced(self, *a, **kw):
        for attempt in range(len(waits) + 1):
            pacer.before_request()
            try:
                return original(self, *a, **kw)
            except Exception as e:  # noqa: BLE001 - classified by retryable(); anything else is re-raised untouched
                if attempt >= len(waits) or not retryable(e):
                    pacer.failed = True
                    pacer.last_error = describe(e)
                    raise
                sleep(waits[attempt])

    Completions.create = paced

    def undo() -> None:
        Completions.create = original
    return undo


def profile_lines(model: str) -> str:
    """The `profiles:` entry of the run's config. It names the environment variable; the key itself is never written."""
    return f"""active_profile: hosted
profiles:
  hosted:
    base_url: {OPENROUTER_URL}
    model: {model}
    api_key_env: {KEY_ENV}
    context_tokens: 32768
"""
